"""Agent 6 - Shift Coordinator: handover briefings and "why" answers."""
from __future__ import annotations

import ast
import re
from datetime import datetime, timedelta, timezone

from rapidfuzz import fuzz, process

from .. import areas, events, llm, memory
from ..config import get_settings
from ..db import now_ms, redis
from ..domain import LESSON_KINDS
from ..models import Family
from ..routing import snapshot
from .base import PeriodicAgent

BRIEF_SYSTEM = """You are the Shift Coordinator of ReliefNet, a flood relief operation in {area}.
Write the handover briefing for the incoming shift from the data provided. Be concrete: name households,
wards, teams, roads and numbers. Structure: a 2-sentence situation summary, then sections
"Top priorities", "Roads", "Teams", "Lessons in effect", "Watch out for". Use short bullet points.
Use only the data given; do not invent facts. Keep it under 300 words. Plain text with simple markdown."""

WHY_SYSTEM = """You are the Shift Coordinator of ReliefNet. A coordinator asks why something happened to
a household. Answer from the timeline only, which is read from the shared memory graph. Explain step by
step in plain language: which agent or team did what, when, and why (quote the recorded reasons). End with
the current state and what happens next. Under 150 words. Do not invent anything not in the timeline."""


def _clock(ms: int | None) -> str:
    if not ms:
        return "--:--"
    tz = get_settings().tz_offset_minutes
    return (datetime.fromtimestamp(ms / 1000, timezone.utc) + timedelta(minutes=tz)).strftime("%H:%M")


# ------------------------------------------------------------------ briefings

async def briefing_data(org: str) -> dict:
    lessons = sorted(await memory.active_lessons(org, LESSON_KINDS), key=lambda l: -l.confidence)[:6]
    return {
        "requests": await memory.status_counts(org, "Request"),
        "families": await memory.status_counts(org, "Family"),
        "top": await memory.top_waiting(org, 8),
        "teams": await memory.team_activity(org),
        "lessons": [{"text": l.text, "confidence": l.confidence} for l in lessons],
        "roads": {r["name"]: r["status"] for r in await snapshot() if r["status"] != "open"},
    }


def render_briefing_rules(org_name: str, shift: str, d: dict) -> str:
    req, fam = d["requests"], d["families"]
    waiting = req.get("NEW", 0) + req.get("RESOLVED", 0) + req.get("TRIAGED", 0)
    lines = [
        f"## {shift} handover — {org_name}",
        "",
        f"{fam.get('SERVED', 0)} households served so far, {fam.get('ASSIGNED', 0)} with a team on the way, "
        f"{fam.get('UNSERVED', 0)} still waiting. {waiting} requests are in the queue and "
        f"{req.get('MERGED', 0)} duplicate messages were merged.",
        "",
        "**Top priorities**",
    ]
    for t in d["top"][:6]:
        who = t["name"] or t["family"]
        extra = f" — BLOCKED: {t['blocked']}" if t.get("blocked") else ""
        lines.append(f"- {who} ({t['family']}), ward {t['ward']} {t['landmark'] or ''}: P{t['priority'] or '?'}, "
                     f"needs {', '.join(t['needs'] or [])}, waiting since {_clock(t['since'])}{extra}")
    if not d["top"]:
        lines.append("- Queue is clear.")
    lines += ["", "**Roads**"]
    lines += [f"- {n}: {s.upper()}" for n, s in d["roads"].items()] or ["- All roads open."]
    lines += ["", "**Teams**"]
    lines += [f"- {t['team']}: {t['active']} active, {t['delivered']} delivered" for t in d["teams"]]
    lines += ["", "**Lessons in effect**"]
    lines += [f"- {l['text']} ({int(l['confidence'] * 100)}%)" for l in d["lessons"]] or ["- None yet."]
    return "\n".join(lines)


async def make_briefing(org: str, org_name: str, shift: str | None = None) -> dict:
    d = await briefing_data(org)
    shift = shift or ("Night shift" if not 8 <= int(_clock(now_ms())[:2]) < 20 else "Day shift")
    text, how = None, "rules"
    if llm.is_live():
        prompt = f"Org: {org_name}\nShift starting: {shift} at {_clock(now_ms())}\nData:\n{d}"
        text = await llm.text_call(get_settings().model_smart, BRIEF_SYSTEM.format(area=areas.region().title), prompt, effort="medium")
        how = llm.name_of(get_settings().model_smart) if text else "rules"
    text = text or render_briefing_rules(org_name, shift, d)
    bid = f"B-{await redis().incr(f'rn:seq:{org}:B')}"
    await memory.save_briefing(org, bid, shift, text, how)
    await events.publish(org, "briefing", f"{shift} briefing ready ({bid})", id=bid)
    return {"id": bid, "shift": shift, "text": text, "by": how, "at": now_ms()}


# ------------------------------------------------------------------ "why" answers

async def find_family(org: str, question: str) -> Family | None:
    """Find the household a question is about: by id (F-, R- or M-) or by name."""
    m = re.search(r"\b([FfRrMm])-?(\d{2,5})\b", question)
    if m:
        kind, num = m.group(1).upper(), m.group(2)
        key = {"F": "family_id", "R": "request_id", "M": "message_id"}[kind]
        found = await memory.family_by(org, **{key: f"{kind}-{num}"})
        if found:
            return found
    names = await memory.named_families(org)
    if not names:
        return None
    q = re.sub(r"\b(why|hasn'?t|has|not|been|the|family|served|what|happened|to|is|was|where|household)\b", " ",
               question.lower())
    best = process.extractOne(q, {fid: n.lower() for fid, n in names.items()}, scorer=fuzz.partial_token_set_ratio,
                              score_cutoff=70)
    return await memory.family_by(org, family_id=best[2]) if best else None


def evidence_text(ev) -> str:
    """Short text for the evidence on a DUPLICATE_OF edge. Older edges keep it as the text of a dict."""
    if isinstance(ev, str):
        try:
            ev = ast.literal_eval(ev)
        except (ValueError, SyntaxError):
            return ev
    if not isinstance(ev, dict):
        return str(ev or "")
    parts = []
    if ev.get("similarity") is not None:
        parts.append(f"similarity {ev['similarity']}")
    if ev.get("distance_m") is not None:
        parts.append(f"{ev['distance_m']} m")
    if ev.get("same_landmark"):
        parts.append("same landmark")
    elif ev.get("same_ward"):
        parts.append("same ward")
    if ev.get("people"):
        parts.append(f"{ev['people']} people")
    if ev.get("name") in ("match", "different"):
        parts.append(f"name {ev['name']}")
    parts += [f"conflict: {c}" for c in ev.get("conflicts") or []]
    return " · ".join(parts)


async def family_trace(org: str, fid: str) -> dict:
    """Everything the graph remembers about one household, as a timeline and a subgraph."""
    steps: list[dict] = []
    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    def node(nid: str, label: str, title: str, **extra):
        nodes.setdefault(nid, {"id": nid, "label": label, "title": title, **extra})

    def edge(src: str, dst: str, kind: str, at=None, reason: str = "", props: str = ""):
        edges.append({"from": src, "to": dst, "type": kind, "at": at, "reason": reason or "", "props": props or ""})

    def step(at, who: str, kind: str, what: str):
        steps.append({"at": at, "who": who, "kind": kind, "what": what})

    family = await memory.family_by(org, family_id=fid)
    fam = family.model_dump() if family else {"id": fid}
    node(fid, "Family", fam.get("name") or fid, status=fam.get("status"))
    h = await memory.household_history(org, fid)

    for r in h["requests"]:
        node(r["id"], "Request", r["id"], status=r["status"], priority=r["priority"])
        edge(r["id"], fid, "FOR", r["at"], props=f"status:{r['status']}")
        if r["mid"]:
            node(r["mid"], "Message", r["mid"], text=r["text"])
            edge(r["mid"], r["id"], "BECAME", r["at"], f"{r['channel']} message: \"{r['text']}\"")
            step(r["at"], f"{r['channel']} message", "message", f"{r['mid']}: \"{r['text']}\"")
    for p in h["processed"]:
        node(p["agent"], "Agent", p["agent"])
        edge(p["rid"], p["agent"], "PROCESSED_BY", p["at"], p["reason"], f"action:{p['action']}")
        step(p["at"], p["agent"], p["action"], f"{p['rid']} -> {p['to'] or p['action']}: {p['reason']}")
    for d in h["duplicates"]:
        ev = evidence_text(d["ev"])
        edge(d["rid"], d["cid"], "DUPLICATE_OF", d["at"], ev or d["reason"], f"score:{d['score']}")
        step(d["at"], "Dedupe", "merge",
             f"{d['rid']} is the same household as {d['cid']} (score {d['score']}, {d['by']}): {ev}")
    for a in h["assignments"]:
        node(a["team"], "Team", a["team"])
        roads = a["roads"] or []
        why = f"route over {len(roads)} roads" + ("" if a["active"] else ", ended") if roads else ""
        edge(a["rid"], a["team"], "ASSIGNED_TO", a["at"], why, f"eta_min:{a['eta']}" if a["eta"] is not None else "")
    for x in h["handoffs"]:
        node(x["src"], "Agent", x["src"])
        node(x["dst"], "Agent", x["dst"])
        edge(x["src"], x["dst"], "HANDED_OFF", x["at"], x["reason"], f"request:{x['rid']}")
        step(x["at"], x["src"], "handoff", f"handed {x['rid']} to {x['dst']}: {x['reason']}")
    for x in h["reroutes"]:
        if x["road"]:
            step(x["at"], "Road network", "reroute",
                 f"{x['road']} flooded on {x['team']}'s route, so {x['rid']} went back to Dispatch")
        else:
            step(x["at"], x["team"], "reroute",
                 f"{x['reason'] or x['team'] + ' off duty'}, so {x['rid']} went back to Dispatch")
    for l in h["lessons"]:
        node(l["key"], "Lesson", l["text"])
        edge(l["rid"], l["key"], "USED_LESSON", l["at"], l["text"], f"by:{l['by']}")
        step(l["at"], l["by"], "lesson", f"used lesson: {l['text']}")
    for l in h["cited_by"]:
        node(l["key"], "Lesson", l["text"])
        edge(l["key"], fid, "DERIVED_FROM", l["at"], l["text"], f"confidence:{l['confidence']}")
    for d in h["deliveries"]:
        node(d["id"], "Delivery", d["id"])
        node(d["team"], "Team", d["team"])
        edge(d["team"], d["id"], "MADE", d["at"])
        edge(d["id"], fid, "SERVED", d["at"], ", ".join(d["items"] or []))
        step(d["at"], d["team"], "delivery", f"delivered {', '.join(d['items'] or [])}. {d['notes'] or ''}".strip())

    steps.sort(key=lambda s: s["at"] or 0)
    edges.sort(key=lambda e: e["at"] or 0)
    for s in steps:
        s["time"] = _clock(s["at"])
    reqs = h["requests"]
    current = next((r for r in reqs if r["status"] != "MERGED"), reqs[0] if reqs else None)
    return {"family": fam, "requests": reqs, "current": current, "timeline": steps,
            "graph": {"nodes": list(nodes.values()), "edges": edges}}


def render_why_rules(trace: dict) -> str:
    fam = trace["family"]
    who = fam.get("name") or fam["id"]
    lines = [f"{who} ({fam['id']}) is {fam.get('status', 'UNKNOWN').lower()}."]
    for s in trace["timeline"]:
        lines.append(f"{s['time']} — {s['who']}: {s['what']}")
    cur = trace.get("current")
    if cur:
        if cur["status"] == "TRIAGED":
            lines.append(f"Now: {cur['id']} waits in the Dispatch queue at priority {cur['priority']}"
                         + (f" ({cur['blocked']})" if cur.get("blocked") else "") + ".")
        elif cur["status"] == "ASSIGNED":
            lines.append(f"Now: {cur['team']} is on the way.")
        elif cur["status"] == "DELIVERED":
            lines.append("Now: help has been delivered.")
    return "\n".join(lines)


async def answer_why(org: str, question: str) -> dict:
    fam = await find_family(org, question)
    if not fam:
        return {"answer": "I could not find that household in this organisation's memory. Try a family name or an "
                          "id such as F-212 or R-188.", "trace": None, "by": "rules"}
    trace = await family_trace(org, fam.id)
    answer, how = None, "rules"
    if llm.is_live():
        tl = "\n".join(f"{s['time']} | {s['who']} | {s['what']}" for s in trace["timeline"])
        prompt = (f"Question: {question}\nHousehold: {fam.name or fam.id} ({fam.id}), status {fam.status}\n"
                  f"Current request: {trace.get('current') or {}}\nTimeline:\n{tl}")
        answer = await llm.text_call(get_settings().model_smart, WHY_SYSTEM, prompt, effort="medium")
        how = llm.name_of(get_settings().model_smart) if answer else "rules"
    return {"answer": answer or render_why_rules(trace), "trace": trace, "by": how}


class ShiftScheduler(PeriodicAgent):
    """Writes a briefing automatically at each configured shift change."""

    kind = "coordinator"
    interval_s = 30.0

    async def tick(self, org: str) -> None:
        from .. import orgs

        hhmm = _clock(now_ms())
        for t in get_settings().shift_times.split(","):
            t = t.strip()
            if t and hhmm[:2] == t[:2] and abs(int(hhmm[3:]) - int(t[3:])) < 1:
                key = f"rn:shift:{org}:{datetime.now(timezone.utc).date()}:{t}"
                if await redis().set(key, "1", nx=True, ex=7200):
                    o = await orgs.get(org)
                    shift = "Night shift" if t >= "20:00" or t < "08:00" else "Day shift"
                    await make_briefing(org, o["name"] if o else org, shift)
