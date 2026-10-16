"""Agent 6 - Shift Coordinator: handover briefings and "why" answers."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from rapidfuzz import fuzz, process

from .. import events, llm
from ..config import get_settings
from ..db import now_ms, org_graph_name, query, redis
from ..routing import snapshot
from .base import PeriodicAgent

BRIEF_SYSTEM = """You are the Shift Coordinator of ReliefNet, a flood relief operation in Ganga Nagar.
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


async def briefing_data(org: str) -> dict:
    g = org_graph_name(org)
    counts = await query(
        g, "MATCH (r:Request) RETURN r.status AS status, count(r) AS n", readonly=True
    )
    fam = await query(
        g, "MATCH (f:Family) RETURN f.status AS status, count(f) AS n", readonly=True
    )
    top = await query(
        g,
        "MATCH (r:Request) WHERE r.status IN ['TRIAGED', 'RESOLVED', 'NEW'] MATCH (r)-[:FOR]->(f:Family)"
        " RETURN r.id AS id, f.id AS family, f.name AS name, r.priority AS priority, r.ward AS ward,"
        " r.landmark AS landmark, r.needs AS needs, r.reason AS reason, r.blocked_reason AS blocked,"
        " r.created_at AS since ORDER BY r.priority DESC LIMIT 8",
        readonly=True,
    )
    teams = await query(
        g,
        "MATCH (t:Team) OPTIONAL MATCH (r:Request {status:'ASSIGNED'})-[:ASSIGNED_TO {active:true}]->(t)"
        " OPTIONAL MATCH (t)-[:MADE]->(d:Delivery)"
        " RETURN t.name AS team, count(DISTINCT r) AS active, count(DISTINCT d) AS delivered",
        readonly=True,
    )
    lessons = await query(
        g,
        "MATCH (l:Lesson) WHERE l.confidence >= 0.5 RETURN l.text AS text, l.confidence AS confidence"
        " ORDER BY l.confidence DESC LIMIT 6",
        readonly=True,
    )
    roads = [r for r in await snapshot() if r["status"] != "open"]
    road_status: dict[str, str] = {}
    for r in roads:
        road_status[r["name"]] = r["status"]
    return {"requests": counts, "families": fam, "top": top, "teams": teams, "lessons": lessons,
            "roads": road_status}


def render_briefing_rules(org_name: str, shift: str, d: dict) -> str:
    req = {r["status"]: r["n"] for r in d["requests"]}
    fam = {r["status"]: r["n"] for r in d["families"]}
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
    text = None
    how = "rules"
    if llm.is_live():
        prompt = f"Org: {org_name}\nShift starting: {shift} at {_clock(now_ms())}\nData:\n{d}"
        text = await llm.text_call(get_settings().model_smart, BRIEF_SYSTEM, prompt, effort="medium")
        how = "claude" if text else "rules"
    text = text or render_briefing_rules(org_name, shift, d)
    seq = await redis().incr(f"rn:seq:{org}:B")
    bid = f"B-{seq}"
    await query(
        org_graph_name(org),
        "CREATE (:Briefing {id:$id, at:$now, shift:$shift, text:$text, by:$how})",
        {"id": bid, "now": now_ms(), "shift": shift, "text": text, "how": how},
    )
    await events.publish(org, "briefing", f"{shift} briefing ready ({bid})", id=bid)
    return {"id": bid, "shift": shift, "text": text, "by": how, "at": now_ms()}


async def find_family(org: str, question: str) -> dict | None:
    g = org_graph_name(org)
    m = re.search(r"\b([FfRrMm])-?(\d{2,5})\b", question)
    if m:
        kind, num = m.group(1).upper(), m.group(2)
        if kind == "F":
            rows = await query(g, "MATCH (f:Family {id:$id}) RETURN properties(f) AS f", {"id": f"F-{num}"}, readonly=True)
        elif kind == "R":
            rows = await query(g, "MATCH (:Request {id:$id})-[:FOR]->(f:Family) RETURN properties(f) AS f",
                               {"id": f"R-{num}"}, readonly=True)
        else:
            rows = await query(g, "MATCH (:Message {id:$id})-[:BECAME]->()-[:FOR]->(f:Family) RETURN properties(f) AS f",
                               {"id": f"M-{num}"}, readonly=True)
        if rows:
            return rows[0]["f"]
    fams = await query(
        g, "MATCH (f:Family) WHERE f.name <> '' RETURN f.id AS id, f.name AS name", readonly=True
    )
    if not fams:
        return None
    q = re.sub(r"\b(why|hasn'?t|has|not|been|the|family|served|what|happened|to|is|was|where|household)\b", " ",
               question.lower())
    best = process.extractOne(q, {f["id"]: f["name"].lower() for f in fams}, scorer=fuzz.partial_token_set_ratio,
                              score_cutoff=70)
    if not best:
        return None
    rows = await query(g, "MATCH (f:Family {id:$id}) RETURN properties(f) AS f", {"id": best[2]}, readonly=True)
    return rows[0]["f"] if rows else None


async def family_trace(org: str, fid: str) -> dict:
    """Everything the graph remembers about one household, as a timeline and a subgraph."""
    g = org_graph_name(org)
    steps: list[dict] = []
    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    def node(nid: str, label: str, title: str, **extra):
        nodes.setdefault(nid, {"id": nid, "label": label, "title": title, **extra})

    fam = (await query(g, "MATCH (f:Family {id:$id}) RETURN properties(f) AS f", {"id": fid}, readonly=True))[0]["f"]
    fam.pop("loc", None)
    node(fid, "Family", fam.get("name") or fid, status=fam.get("status"))
    reqs = await query(
        g,
        "MATCH (r:Request)-[:FOR]->(:Family {id:$id}) OPTIONAL MATCH (m:Message)-[:BECAME]->(r)"
        " RETURN r.id AS id, r.status AS status, r.created_at AS at, r.channel AS channel, r.summary AS summary,"
        " r.priority AS priority, r.team AS team, r.blocked_reason AS blocked, m.id AS mid, m.text AS text",
        {"id": fid}, readonly=True,
    )
    rids = [r["id"] for r in reqs]
    for r in reqs:
        node(r["id"], "Request", r["id"], status=r["status"], priority=r["priority"])
        edges.append({"from": r["id"], "to": fid, "type": "FOR"})
        if r["mid"]:
            node(r["mid"], "Message", r["mid"], text=r["text"])
            edges.append({"from": r["mid"], "to": r["id"], "type": "BECAME"})
            steps.append({"at": r["at"], "who": f"{r['channel']} message", "what": f"{r['mid']}: \"{r['text']}\"",
                          "kind": "message"})
    proc = await query(
        g,
        "MATCH (r:Request)-[p:PROCESSED_BY]->(a:Agent) WHERE r.id IN $ids"
        " RETURN r.id AS rid, a.name AS agent, p.at AS at, p.action AS action, p.to AS to, p.reason AS reason",
        {"ids": rids}, readonly=True,
    )
    for p in proc:
        node(p["agent"], "Agent", p["agent"])
        edges.append({"from": p["rid"], "to": p["agent"], "type": "PROCESSED_BY"})
        steps.append({"at": p["at"], "who": p["agent"], "what": f"{p['rid']} -> {p['to'] or p['action']}: {p['reason']}",
                      "kind": p["action"]})
    dups = await query(
        g,
        "MATCH (r:Request)-[d:DUPLICATE_OF]->(c:Request) WHERE r.id IN $ids"
        " RETURN r.id AS rid, c.id AS cid, d.at AS at, d.score AS score, d.reason AS reason, d.evidence AS ev,"
        " d.decided_by AS by",
        {"ids": rids}, readonly=True,
    )
    for d in dups:
        edges.append({"from": d["rid"], "to": d["cid"], "type": "DUPLICATE_OF"})
        steps.append({"at": d["at"], "who": "Dedupe", "kind": "merge",
                      "what": f"{d['rid']} is the same household as {d['cid']} (score {d['score']}, {d['by']}): {d['ev']}"})
    assigns = await query(
        g,
        "MATCH (r:Request)-[a:ASSIGNED_TO]->(t:Team) WHERE r.id IN $ids"
        " RETURN r.id AS rid, t.name AS team, a.at AS at, a.eta_min AS eta, a.roads AS roads, a.active AS active,"
        " a.ended AS ended",
        {"ids": rids}, readonly=True,
    )
    for a in assigns:
        node(a["team"], "Team", a["team"])
        edges.append({"from": a["rid"], "to": a["team"], "type": "ASSIGNED_TO"})
    handoffs = await query(
        g,
        "MATCH (a:Agent)-[h:HANDED_OFF]->(f:Agent) WHERE h.request IN $ids"
        " RETURN a.name AS src, f.name AS dst, h.at AS at, h.request AS rid, h.reason AS reason",
        {"ids": rids}, readonly=True,
    )
    for h in handoffs:
        node(h["src"], "Agent", h["src"])
        node(h["dst"], "Agent", h["dst"])
        edges.append({"from": h["src"], "to": h["dst"], "type": "HANDED_OFF"})
        steps.append({"at": h["at"], "who": h["src"], "kind": "handoff",
                      "what": f"handed {h['rid']} to {h['dst']}: {h['reason']}"})
    reroutes = await query(
        g,
        "MATCH (r:Request)-[x:REROUTED]->(t:Team) WHERE r.id IN $ids"
        " RETURN r.id AS rid, x.at AS at, x.road AS road, t.name AS team",
        {"ids": rids}, readonly=True,
    )
    for x in reroutes:
        steps.append({"at": x["at"], "who": "Road network", "kind": "reroute",
                      "what": f"{x['road']} flooded on {x['team']}'s route, so {x['rid']} went back to Dispatch"})
    lessons = await query(
        g,
        "MATCH (r:Request)-[u:USED_LESSON]->(l:Lesson) WHERE r.id IN $ids"
        " RETURN r.id AS rid, u.at AS at, u.by AS by, l.key AS key, l.text AS text",
        {"ids": rids}, readonly=True,
    )
    for l in lessons:
        node(l["key"], "Lesson", l["text"])
        edges.append({"from": l["rid"], "to": l["key"], "type": "USED_LESSON"})
        steps.append({"at": l["at"], "who": l["by"], "kind": "lesson", "what": f"used lesson: {l['text']}"})
    deliveries = await query(
        g,
        "MATCH (t:Team)-[:MADE]->(d:Delivery)-[:SERVED]->(:Family {id:$id})"
        " RETURN d.id AS id, d.at AS at, d.items AS items, d.notes AS notes, t.name AS team",
        {"id": fid}, readonly=True,
    )
    for d in deliveries:
        node(d["id"], "Delivery", d["id"])
        node(d["team"], "Team", d["team"])
        edges.append({"from": d["team"], "to": d["id"], "type": "MADE"})
        edges.append({"from": d["id"], "to": fid, "type": "SERVED"})
        steps.append({"at": d["at"], "who": d["team"], "kind": "delivery",
                      "what": f"delivered {', '.join(d['items'] or [])}. {d['notes'] or ''}".strip()})
    steps.sort(key=lambda s: s["at"] or 0)
    for s in steps:
        s["time"] = _clock(s["at"])
    current = next((r for r in reqs if r["status"] not in ("MERGED",)), reqs[0] if reqs else None)
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
    trace = await family_trace(org, fam["id"])
    answer, how = None, "rules"
    if llm.is_live():
        tl = "\n".join(f"{s['time']} | {s['who']} | {s['what']}" for s in trace["timeline"])
        cur = trace.get("current") or {}
        prompt = (f"Question: {question}\nHousehold: {trace['family'].get('name') or fam['id']} ({fam['id']}), "
                  f"status {trace['family'].get('status')}\nCurrent request: {cur}\nTimeline:\n{tl}")
        answer = await llm.text_call(get_settings().model_smart, WHY_SYSTEM, prompt, effort="medium", max_tokens=4000)
        how = "claude" if answer else "rules"
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
