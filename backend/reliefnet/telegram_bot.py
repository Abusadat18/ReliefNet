"""Telegram bot for field volunteers and the public.

    TELEGRAM_BOT_TOKEN=... python -m reliefnet.telegram_bot

Long polling, so it works on a laptop with no public URL.
- A volunteer links their account once: the web app shows a code, they send
  `/link 123456` (or tap the deep link). After that their messages go to the
  Field agent, and new assignments for their team are pushed to them.
- Anyone else who writes is treated as a public help request for the
  default org (`/org <slug>` switches it)."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path

import httpx

from . import db, events, field_ops, orgs
from .agents.field import FieldSession
from .config import get_settings
from .db import org_graph_name, query

log = logging.getLogger("reliefnet.telegram")

HELP = (
    "ReliefNet flood help line.\n\n"
    "Need help? Describe who is stuck, how many people, what you need, and the nearest landmark and ward.\n\n"
    "Volunteers: open the ReliefNet field app, tap 'Link Telegram', then send /link CODE here.\n"
    "Commands: /tasks (your assignments), /help"
)


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
                "'done R-123 gave water' when you deliver, or 'NH-12 bridge flooded' to report a road.")

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
        if text in ("/start", "/help"):
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

        found = await self.volunteer_for(chat_id)
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
                await field_ops.add_observation(org, text or "photo from the field", by=vol["id"],
                                                channel="telegram", photo=photo_url)
                await events.publish(org, "photo", f"{vol['name']} sent a photo via Telegram", photo=photo_url)
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
        org = await db.redis().get(f"rn:tg:pub:{chat_id}")
        if not org:
            all_orgs = await orgs.all_orgs()
            org = all_orgs[0]["slug"] if all_orgs else None
        if not org:
            await self.send(chat_id, "The help line is not set up yet.")
            return
        mid = await field_ops.ingest_message(org, text, "telegram", sender=f"tg:{chat_id}")
        await self.send(chat_id, f"Received. Your reference is {mid}. Relief teams are being coordinated. "
                                 "If the situation changes, send another message.")

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
                                       allowed_updates=["message", "edited_message"])
            except httpx.HTTPError as e:
                log.warning("poll error: %s", e)
                await asyncio.sleep(3)
                continue
            for upd in data.get("result", []):
                offset = upd["update_id"] + 1
                await db.redis().set("rn:tg:offset", offset)
                msg = upd.get("message") or upd.get("edited_message")
                if msg:
                    try:
                        await self.handle(msg)
                    except Exception:
                        log.exception("handler failed")
                        await self.send(msg["chat"]["id"], "Sorry, something went wrong. Please try again.")


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    token = get_settings().telegram_bot_token
    if not token:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN (create a bot with @BotFather).")
    bot = Bot(token)
    try:
        await asyncio.gather(bot.poll(), bot.push_assignments())
    finally:
        await bot.http.aclose()
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
