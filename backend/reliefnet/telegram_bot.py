"""Telegram bot for field volunteers and the public.

    TELEGRAM_BOT_TOKEN=... python -m reliefnet.telegram_bot

Long polling, so it works on a laptop with no public URL.
- A volunteer links their account once: the web app shows a code, they send
  `/link 123456` (or tap the deep link). After that their messages go to the
  Field agent, and new assignments for their team are pushed to them.
- `/start` opens a short guided form for anyone (see intake_flow.py): location,
  the family's phone number, how many people, what they need. A linked volunteer
  uses `/report` to fill it in for a family. Plain text without `/start` is still
  accepted as a help request, so nobody is turned away.
- Requests go to `TELEGRAM_DEFAULT_ORG` (`/org <slug>` switches it per chat)."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from pathlib import Path

import httpx

from . import areas, db, events, field_ops, geo, intake_flow as iflow, orgs
from .agents.field import FieldSession
from .config import get_settings
from .db import org_graph_name, query

log = logging.getLogger("reliefnet.telegram")

HELP = (
    "ReliefNet flood help line.\n\n"
    "Need help? Send /start. I will ask a few quick questions: where you are, a phone number, how many people "
    "and what you need. You can also just write your message and I will pass it on.\n\n"
    "Volunteers: open the ReliefNet field app, tap 'Link Telegram', then send /link CODE here. "
    "Then /report fills in a request for a family.\n"
    "Commands: /start (ask for help), /report (volunteers), /tasks (your assignments), /cancel, /help"
)
FLOW_TTL_S = 86400
SWEEP_EVERY_S = 30


class Bot:
    def __init__(self, token: str):
        self.base = f"https://api.telegram.org/bot{token}"
        self.file_base = f"https://api.telegram.org/file/bot{token}"
        self.http = httpx.AsyncClient(timeout=40)

    async def call(self, method: str, **params) -> dict:
        r = await self.http.post(f"{self.base}/{method}", json=params)
        data = r.json()
        if not data.get("ok"):
            log.warning("telegram %s failed: %s", method, data)
        return data

    async def send(self, chat_id: int | str, text: str) -> None:
        for i in range(0, len(text), 3900):
            await self.call("sendMessage", chat_id=chat_id, text=text[i : i + 3900])

    # ------------------------------------------------------------ guided form
    async def send_text(self, chat_id: int | str, text: str, markup: dict | None = None) -> None:
        params: dict = {"chat_id": chat_id, "text": text[:3900]}
        if markup:
            params["reply_markup"] = markup
        await self.call("sendMessage", **params)

    async def target_org(self, chat_id: int) -> str | None:
        chosen = await db.redis().get(f"rn:tg:pub:{chat_id}")
        if chosen:
            return chosen
        default = get_settings().telegram_default_org
        if default and await orgs.get(default):
            return default
        all_orgs = await orgs.all_orgs()
        return all_orgs[0]["slug"] if all_orgs else None

    async def flow_ctx(self, reporter_id: str = "") -> iflow.Ctx:
        names: dict[int, list[str]] = {w["num"]: [] for w in await geo.wards()}
        for l in await geo.landmarks():
            names.setdefault(l["ward"], []).append(l["name"])
        return iflow.Ctx(landmarks=names, reporter_id=reporter_id, now=time.time())

    async def load_flow(self, chat_id: int) -> dict | None:
        raw = await db.redis().get(f"rn:tg:flow:{chat_id}")
        return json.loads(raw) if raw else None

    async def save_flow(self, chat_id: int, draft: iflow.Draft, org: str, reporter_id: str) -> None:
        await db.redis().set(
            f"rn:tg:flow:{chat_id}",
            json.dumps({"draft": draft.to_dict(), "org": org, "reporter_id": reporter_id}),
            ex=FLOW_TTL_S,
        )

    async def clear_flow(self, chat_id: int) -> None:
        await db.redis().delete(f"rn:tg:flow:{chat_id}")

    @staticmethod
    def _rows(buttons: list[iflow.Button], multi: bool) -> list[list[dict]]:
        """Short labels share a row (ward numbers, 1-5), long ones and toggles get their own."""
        rows: list[list[dict]] = []
        short: list[dict] = []
        for b in buttons:
            cell = {"text": ("✅ " if b.selected else "") + b.label, "callback_data": b.id}
            if not multi and len(b.label) <= 8:
                short.append(cell)
                if len(short) == 4:
                    rows.append(short)
                    short = []
                continue
            if short:
                rows.append(short)
                short = []
            rows.append([cell])
        if short:
            rows.append(short)
        return rows

    async def send_reply(self, chat_id: int, reply: iflow.Reply, lang: str) -> None:
        """Show one Reply. Location and contact need Telegram's own keyboard; everything else is inline."""
        r = db.redis()
        if reply.ask_location or reply.ask_contact:
            ask = ({"text": iflow.t("share_location", lang), "request_location": True} if reply.ask_location
                   else {"text": iflow.t("share_contact", lang), "request_contact": True})
            markup = {"keyboard": [[ask]] + [[{"text": b.label}] for b in reply.buttons],
                      "resize_keyboard": True, "one_time_keyboard": True}
            # Those buttons send their label as plain text; remember which tap each one means.
            await r.set(f"rn:tg:labels:{chat_id}", json.dumps({b.label: b.id for b in reply.buttons}), ex=FLOW_TTL_S)
            await r.set(f"rn:tg:kb:{chat_id}", "1", ex=FLOW_TTL_S)
        elif reply.buttons:
            markup = {"inline_keyboard": self._rows(reply.buttons, reply.multi)}
        else:
            markup = None
        await self.send_text(chat_id, reply.text, markup)

    async def show(self, chat_id: int, res: iflow.Result, before_step: str, message_id: int | None) -> None:
        """Send the next question, or just refresh the ticks when a toggle was tapped."""
        r = db.redis()
        lang = res.draft.lang or "en"
        first = res.replies[0] if res.replies else None
        if message_id and first and first.multi and res.draft.step == before_step:
            await self.call("editMessageReplyMarkup", chat_id=chat_id, message_id=message_id,
                            reply_markup={"inline_keyboard": self._rows(first.buttons, True)})
            return
        if message_id:  # the old buttons must not be tappable any more
            await self.call("editMessageReplyMarkup", chat_id=chat_id, message_id=message_id,
                            reply_markup={"inline_keyboard": []})
        if await r.get(f"rn:tg:kb:{chat_id}") and not any(x.ask_location or x.ask_contact for x in res.replies):
            await self.send_text(chat_id, "✓", {"remove_keyboard": True})
            await r.delete(f"rn:tg:kb:{chat_id}", f"rn:tg:labels:{chat_id}")
        for reply in res.replies:
            await self.send_reply(chat_id, reply, lang)

    async def begin_flow(self, chat_id: int, found: tuple[str, dict] | None) -> None:
        org = found[0] if found else await self.target_org(chat_id)
        if not org:
            await self.send(chat_id, "The help line is not set up yet.")
            return
        reporter_id = found[1]["id"] if found else ""
        lang = await db.redis().get(f"rn:tg:lang:{chat_id}") or ""
        res = iflow.start(await self.flow_ctx(reporter_id), lang)
        await self.save_flow(chat_id, res.draft, org, reporter_id)
        await self.show(chat_id, res, "", None)

    async def submit(self, chat_id: int | str, org: str, sub: iflow.Submission) -> str:
        """Save a finished or abandoned form as a message; Intake takes it from there."""
        form = {**sub.form, "partial": sub.partial}
        return await field_ops.ingest_message(
            org, sub.text, "telegram", sender=f"tg:{chat_id}",
            extra={"phone": sub.phone, "phone_kind": sub.phone_kind, "alt_phone": sub.alt_phone,
                   "lat": sub.lat, "lon": sub.lon, "loc_source": sub.loc_source, "ward": sub.ward or None,
                   "landmark": sub.landmark, "reporter_kind": sub.reporter_kind,
                   "reporter_id": sub.reporter_id, "lang": sub.lang, "form": json.dumps(form)},
        )

    async def advance(self, chat_id: int, flow: dict, ev: iflow.Event, message_id: int | None = None) -> None:
        draft = iflow.Draft.from_dict(flow["draft"])
        before = draft.step
        res = iflow.step(draft, ev, await self.flow_ctx(flow["reporter_id"]))
        if res.submission:
            ref = await self.submit(chat_id, flow["org"], res.submission)
            await self.clear_flow(chat_id)
            await db.redis().set(f"rn:tg:lang:{chat_id}", res.draft.lang or "en")
            done = iflow.Result(res.draft, [iflow.done_reply(res.draft.lang, ref)])
            await self.show(chat_id, done, before, message_id)
            return
        if res.draft.step == "cancelled":
            await self.clear_flow(chat_id)
        else:
            await self.save_flow(chat_id, res.draft, flow["org"], flow["reporter_id"])
        await self.show(chat_id, res, before, message_id)

    async def handle_callback(self, cb: dict) -> None:
        await self.call("answerCallbackQuery", callback_query_id=cb["id"])
        msg = cb.get("message") or {}
        if not msg:
            return
        chat_id = msg["chat"]["id"]
        flow = await self.load_flow(chat_id)
        if not flow:
            await self.send(chat_id, "This form has expired. Send /start to begin again.")
            return
        await self.advance(chat_id, flow, iflow.Event(button=cb.get("data", "")), msg.get("message_id"))

    async def sweep_once(self, ttl: float = iflow.STALE_AFTER_S) -> int:
        """Send the forms people stopped filling in (battery died, signal dropped)."""
        sent = 0
        async for key in db.redis().scan_iter(match="rn:tg:flow:*"):
            raw = await db.redis().get(key)
            if not raw:
                continue
            flow = json.loads(raw)
            draft = iflow.Draft.from_dict(flow["draft"])
            if not iflow.is_stale(draft, time.time(), ttl):
                continue
            chat_id = key.rsplit(":", 1)[1]
            await db.redis().delete(key)
            ctx = iflow.Ctx(landmarks={}, reporter_id=flow["reporter_id"], now=time.time())
            ref = await self.submit(chat_id, flow["org"], iflow.build(draft, ctx, partial=True))
            await self.send(chat_id, iflow.t("auto_sent", draft.lang or "en", ref=ref))
            sent += 1
        return sent

    async def sweep(self) -> None:
        while True:
            await asyncio.sleep(SWEEP_EVERY_S)
            try:
                await self.sweep_once()
            except Exception:
                log.exception("sweep failed")

    # ------------------------------------------------------------ identity
    async def volunteer_for(self, chat_id: int) -> tuple[str, dict] | None:
        raw = await db.redis().get(f"rn:tg:chat:{chat_id}")
        if not raw:
            return None
        link = json.loads(raw)
        rows = await query(
            org_graph_name(link["org"]),
            "MATCH (v:Volunteer {id:$id}) OPTIONAL MATCH (v)-[:MEMBER_OF]->(t:Team)"
            " RETURN v.id AS id, v.name AS name, v.role AS role, t.name AS team",
            {"id": link["id"]},
            readonly=True,
        )
        return (link["org"], rows[0]) if rows else None

    async def link(self, chat_id: int, code: str, tg_name: str) -> str:
        raw = await db.redis().getdel(f"rn:tglink:{code.strip()}")
        if not raw:
            return "That code is invalid or expired. Open the field app and tap 'Link Telegram' for a new one."
        link = json.loads(raw)
        await query(
            org_graph_name(link["org"]),
            "MATCH (v:Volunteer {id:$id}) SET v.telegram_chat_id = $chat, v.telegram_name = $name",
            {"id": link["id"], "chat": str(chat_id), "name": tg_name},
        )
        await db.redis().set(f"rn:tg:chat:{chat_id}", json.dumps(link))
        found = await self.volunteer_for(chat_id)
        team = found[1]["team"] if found else None
        return (f"Linked. You are {found[1]['name'] if found else 'a volunteer'}"
                f"{' in ' + team if team else ''}. Send 'tasks' to see your assignments, "
                "'done R-123 gave water' when you deliver, or"
                f" '{areas.drill().flood_road} flooded' to report a road.")

    # ------------------------------------------------------------ handlers
    async def download_photo(self, file_id: str) -> str | None:
        info = await self.call("getFile", file_id=file_id)
        path = (info.get("result") or {}).get("file_path")
        if not path:
            return None
        r = await self.http.get(f"{self.file_base}/{path}")
        name = f"tg_{file_id[-16:]}{Path(path).suffix or '.jpg'}"
        out = Path(get_settings().uploads_dir) / name
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(r.content)
        return f"/uploads/{name}"

    async def handle(self, msg: dict) -> None:
        chat_id = msg["chat"]["id"]
        text = (msg.get("text") or msg.get("caption") or "").strip()
        sender = msg.get("from", {})
        tg_name = " ".join(x for x in [sender.get("first_name"), sender.get("last_name")] if x) or "unknown"

        m = re.match(r"^/(start|link)\s+(\d{6})$", text)
        if m:
            await self.send(chat_id, await self.link(chat_id, m.group(2), tg_name))
            return
        found = await self.volunteer_for(chat_id)
        if text == "/help" or (text == "/start" and found):
            await self.send(chat_id, HELP)
            return
        m = re.match(r"^/org\s+([a-z0-9_]+)$", text)
        if m:
            if await orgs.get(m.group(1)):
                await db.redis().set(f"rn:tg:pub:{chat_id}", m.group(1))
                await self.send(chat_id, f"Your help requests now go to {m.group(1)}.")
            else:
                await self.send(chat_id, "Unknown organisation.")
            return

        flow = await self.load_flow(chat_id)
        if text in ("/start", "/report"):
            if flow and iflow.has_progress(iflow.Draft.from_dict(flow["draft"])):
                await self.advance(chat_id, flow, iflow.Event(text=text))  # asks: continue or start new
            else:
                await self.begin_flow(chat_id, found)
            return
        if flow and text != "/tasks":
            ev = iflow.Event()
            if msg.get("location"):
                ev.lat, ev.lon = msg["location"]["latitude"], msg["location"]["longitude"]
            elif msg.get("contact"):
                ev.contact_phone = msg["contact"].get("phone_number", "")
            else:
                labels = json.loads(await db.redis().get(f"rn:tg:labels:{chat_id}") or "{}")
                if text in labels:
                    ev.button = labels[text]
                else:
                    ev.text = text
            await self.advance(chat_id, flow, ev)
            return

        if found:
            org, vol = found
            if text == "/tasks":
                text = "what are my tasks"
            photo_url = None
            if msg.get("photo"):
                photo_url = await self.download_photo(msg["photo"][-1]["file_id"])
            if msg.get("location"):
                loc = msg["location"]
                await field_ops.add_observation(org, text or "shared location", by=vol["id"], channel="telegram",
                                                lat=loc["latitude"], lon=loc["longitude"])
                await self.send(chat_id, "Location saved for the coordinators.")
                return
            if photo_url:
                oid = await field_ops.add_observation(org, text or "photo from the field", by=vol["id"],
                                                      channel="telegram", photo=photo_url)
                await events.publish(org, "photo", f"{oid}: {vol['name']} sent a photo via Telegram",
                                     observation=oid, photo=photo_url)
                if not text:
                    await self.send(chat_id, "Photo saved for the coordinators.")
                    return
            if not text:
                return
            await self.call("sendChatAction", chat_id=chat_id, action="typing")
            out = await FieldSession(org, vol, "telegram").reply(text)
            await self.send(chat_id, out["reply"])
            return

        if not text:
            await self.send(chat_id, HELP)
            return
        org = await self.target_org(chat_id)
        if not org:
            await self.send(chat_id, "The help line is not set up yet.")
            return
        mid = await field_ops.ingest_message(org, text, "telegram", sender=f"tg:{chat_id}")
        await self.send(chat_id, f"Received. Your reference is {mid}. Relief teams are being coordinated. "
                                 "To help us find you faster, send /start to share your location and phone number.")

    # ------------------------------------------------------------ push
    async def push_assignments(self) -> None:
        """Tell linked volunteers when Dispatch assigns their team."""
        pubsub = db.redis().pubsub()
        await pubsub.psubscribe("rn:live:*")
        async for msg in pubsub.listen():
            if msg.get("type") != "pmessage":
                continue
            try:
                evt = json.loads(msg["data"])
                if evt["kind"] != "assigned":
                    continue
                org, d = evt["org"], evt["data"]
                rows = await query(
                    org_graph_name(org),
                    "MATCH (v:Volunteer)-[:MEMBER_OF]->(:Team {name:$team}) WHERE v.telegram_chat_id IS NOT NULL"
                    " RETURN v.telegram_chat_id AS chat",
                    {"team": d["team"]},
                    readonly=True,
                )
                req = await query(
                    org_graph_name(org),
                    "MATCH (r:Request {id:$id})-[:FOR]->(f:Family) RETURN f.name AS name, f.id AS fid,"
                    " r.people AS people, r.needs AS needs, r.ward AS ward, r.landmark AS landmark",
                    {"id": d["id"]},
                    readonly=True,
                )
                if not rows or not req:
                    continue
                q = req[0]
                text = (f"New assignment {d['id']}: {q['name'] or q['fid']}, ward {q['ward']} {q['landmark'] or ''}. "
                        f"{q['people']} people, needs {', '.join(q['needs'] or [])}. ETA {d['eta']} min via "
                        f"{', '.join(d['roads'][:4])}.")
                for r in rows:
                    await self.send(r["chat"], text)
            except Exception:
                log.exception("push failed")

    async def poll(self) -> None:
        offset = int(await db.redis().get("rn:tg:offset") or 0)
        me = await self.call("getMe")
        log.info("telegram bot @%s polling", (me.get("result") or {}).get("username"))
        while True:
            try:
                data = await self.call("getUpdates", offset=offset, timeout=30,
                                       allowed_updates=["message", "edited_message", "callback_query"])
            except httpx.HTTPError as e:
                log.warning("poll error: %s", e)
                await asyncio.sleep(3)
                continue
            for upd in data.get("result", []):
                offset = upd["update_id"] + 1
                await db.redis().set("rn:tg:offset", offset)
                msg = upd.get("message") or upd.get("edited_message")
                cb = upd.get("callback_query")
                chat = (msg or (cb or {}).get("message") or {}).get("chat", {}).get("id")
                if msg or cb:
                    try:
                        await (self.handle(msg) if msg else self.handle_callback(cb))
                    except Exception:
                        log.exception("handler failed")
                        if chat:
                            await self.send(chat, "Sorry, something went wrong. Please try again.")


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    token = get_settings().telegram_bot_token
    if not token:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN (create a bot with @BotFather).")
    bot = Bot(token)
    try:
        await asyncio.gather(bot.poll(), bot.push_assignments(), bot.sweep())
    finally:
        await bot.http.aclose()
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
