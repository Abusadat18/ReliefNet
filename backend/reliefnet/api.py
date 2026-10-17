"""HTTP API.

    uvicorn reliefnet.api:app --reload
"""
from __future__ import annotations

import asyncio
import json
import logging
import secrets
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import auth, db, events, field_ops, geo, llm, orgs, routing, sim
from .agents.base import AGENTS_KEY, cmd_key
from .agents.coordinator import answer_why, family_trace, make_briefing
from .agents.field import FieldSession, history
from .agents.learner import LearnerAgent
from .auth import User, current_user, require
from .config import get_settings
from .db import REGION_GRAPH, now_ms, org_graph_name, query
from .embed import mode as embed_mode
from .seed import seed_all

log = logging.getLogger("reliefnet.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    await seed_all()
    yield
    for o in await orgs.all_orgs():
        await sim.stop(o["slug"])
    await db.close()


s = get_settings()
app = FastAPI(title="ReliefNet", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in s.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
Path(s.uploads_dir).mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=s.uploads_dir), name="uploads")


# ---------------------------------------------------------------- meta / auth
@app.get("/api/health")
async def health():
    await db.redis().ping()
    return {"ok": True, "graphs": len(await db.list_graphs())}


@app.get("/api/config")
async def config():
    return {
        "auth_mode": s.auth_mode,
        "llm": "live" if llm.is_live() else "rules",
        "models": {"fast": s.model_fast, "smart": s.model_smart} if llm.is_live() else None,
        "embed": embed_mode(),
        "telegram_bot": s.telegram_bot_username,
        "orgs": [{"slug": o["slug"], "name": o["name"]} for o in await orgs.all_orgs()],
    }


@app.get("/api/dev/users")
async def dev_users():
    if s.auth_mode != "dev":
        raise HTTPException(404)
    return await auth.dev_users()


@app.get("/api/me")
async def me(user: User = Depends(current_user)):
    o = await orgs.get(user.org)
    return {**user.__dict__, "org_name": o["name"] if o else user.org}


# ---------------------------------------------------------------- public intake
class HelpIn(BaseModel):
    text: str = Field(min_length=5, max_length=2000)
    name: str = ""
    phone: str = ""


@app.get("/api/public/orgs")
async def public_orgs():
    return [{"slug": o["slug"], "name": o["name"]} for o in await orgs.all_orgs()]


@app.post("/api/public/{org}/help")
async def public_help(org: str, body: HelpIn, request: Request):
    if not await orgs.get(org):
        raise HTTPException(404, "unknown organisation")
    ip = request.client.host if request.client else "unknown"
    key = f"rn:rl:help:{ip}"
    n = await db.redis().incr(key)
    if n == 1:
        await db.redis().expire(key, 60)
    if n > 6:
        raise HTTPException(429, "too many requests; please wait a minute")
    text = body.text.strip()
    if body.name:
        text = f"{body.name}: {text}"
    if body.phone:
        text += f" (phone {body.phone})"
    mid = await field_ops.ingest_message(org, text, "web_form", sender=body.phone or ip)
    return {"ok": True, "reference": mid}


# ---------------------------------------------------------------- ops dashboard
@app.get("/api/ops/region")
async def region(user: User = Depends(current_user)):
    river = await query(REGION_GRAPH, "MATCH (m:Meta {key:'river'}) RETURN m.polygon AS p", readonly=True)
    shelters = await query(
        REGION_GRAPH,
        "MATCH (s:Shelter) RETURN s.id AS id, s.name AS name, s.ward AS ward, s.capacity AS capacity,"
        " s.occupancy AS occupancy, s.open AS open, s.lat AS lat, s.lon AS lon",
        readonly=True,
    )
    return {
        "roads": await routing.snapshot(),
        "wards": await geo.wards(),
        "landmarks": await geo.landmarks(),
        "shelters": shelters,
        "river": json.loads(river[0]["p"]) if river else [],
    }


@app.get("/api/ops/roads")
async def roads(user: User = Depends(current_user)):
    return await routing.snapshot()


@app.get("/api/ops/snapshot")
async def snapshot(user: User = Depends(require("coordinator"))):
    g = org_graph_name(user.org)
    families = await query(
        g,
        "MATCH (f:Family)"
        " OPTIONAL MATCH (f)<-[:FOR]-(r:Request) WHERE r.status IN ['NEW','RESOLVED','TRIAGED','ASSIGNED','DELIVERED']"
        " WITH f, r ORDER BY r.created_at DESC"
        " WITH f, collect(r)[0] AS r"
        " RETURN f.id AS id, f.name AS name, f.lat AS lat, f.lon AS lon, f.status AS status, f.people AS people,"
        " f.elderly AS elderly, f.children AS children, f.needs AS needs, f.ward AS ward, f.landmark AS landmark,"
        " f.requests AS requests, f.first_seen AS first_seen, r.id AS request, r.status AS request_status,"
        " r.priority AS priority, r.team AS team, r.blocked_reason AS blocked",
        readonly=True,
    )
    routes = await query(
        g,
        "MATCH (r:Request {status:'ASSIGNED'})-[a:ASSIGNED_TO {active:true}]->(t:Team)"
        " RETURN r.id AS id, t.name AS team, r.route AS route, a.eta_min AS eta, r.route_roads AS roads,"
        " r.priority AS priority",
        readonly=True,
    )
    for r in routes:
        r["route"] = json.loads(r["route"]) if r["route"] else []
    teams = await query(
        g,
        "MATCH (t:Team) OPTIONAL MATCH (x:Request {status:'ASSIGNED'})-[:ASSIGNED_TO {active:true}]->(t)"
        " OPTIONAL MATCH (t)-[:MADE]->(d:Delivery)"
        " RETURN t.name AS name, t.lat AS lat, t.lon AS lon, t.supplies AS supplies, t.capacity AS capacity,"
        " t.status AS status, count(DISTINCT x) AS load, count(DISTINCT d) AS delivered",
        readonly=True,
    )
    pending = await query(
        g,
        "MATCH (r:Request) WHERE r.status IN ['NEW','RESOLVED'] AND NOT (r)-[:FOR]->()"
        " RETURN r.id AS id, r.lat AS lat, r.lon AS lon, r.status AS status",
        readonly=True,
    )
    return {"families": families, "routes": routes, "teams": teams, "pending": pending, "at": now_ms()}


@app.get("/api/ops/queue")
async def queue(user: User = Depends(require("coordinator"))):
    rows = await query(
        org_graph_name(user.org),
        "MATCH (r:Request) WHERE r.status IN ['NEW','RESOLVED','TRIAGED','ASSIGNED']"
        " OPTIONAL MATCH (r)-[:FOR]->(f:Family)"
        " RETURN r.id AS id, r.status AS status, r.priority AS priority, r.summary AS summary, r.ward AS ward,"
        " r.landmark AS landmark, r.needs AS needs, r.team AS team, r.eta_min AS eta, r.claimed_by AS claimed_by,"
        " r.lease_until AS lease_until, r.reason AS reason, r.blocked_reason AS blocked, r.created_at AS created_at,"
        " r.merged_count AS merged, f.id AS family, f.name AS name, r.channel AS channel"
        " ORDER BY coalesce(r.priority, 0) DESC, r.created_at ASC LIMIT 200",
        readonly=True,
    )
    return {"items": rows, "now": now_ms()}


@app.get("/api/ops/stats")
async def stats(user: User = Depends(require("coordinator"))):
    g = org_graph_name(user.org)
    req = {r["s"]: r["n"] for r in await query(g, "MATCH (r:Request) RETURN r.status AS s, count(r) AS n", readonly=True)}
    msg = {r["s"]: r["n"] for r in await query(g, "MATCH (m:Message) RETURN m.status AS s, count(m) AS n", readonly=True)}
    fam = {r["s"]: r["n"] for r in await query(g, "MATCH (f:Family) RETURN f.status AS s, count(f) AS n", readonly=True)}
    double = await db.scalar(
        g,
        "MATCH (f:Family)<-[:FOR]-(:Request)-[a:ASSIGNED_TO {active:true}]->() WITH f, count(a) AS c WHERE c > 1"
        " RETURN count(f)",
        default=0,
    )
    truth = await query(
        g,
        "MATCH (r:Request)-[:FOR]->(f:Family) WHERE r.sim_household <> ''"
        " RETURN r.sim_household AS h, f.id AS f",
        readonly=True,
    )
    pairs_same_h = pairs_same_f = pairs_both = 0
    if truth:
        from collections import Counter

        ch = Counter(t["h"] for t in truth)
        cf = Counter(t["f"] for t in truth)
        cb = Counter((t["h"], t["f"]) for t in truth)
        pairs = lambda c: sum(n * (n - 1) // 2 for n in c.values())  # noqa: E731
        pairs_same_h, pairs_same_f, pairs_both = pairs(ch), pairs(cf), pairs(cb)
    m = await events.metrics(user.org)
    lessons = await db.scalar(g, "MATCH (l:Lesson) WHERE l.confidence >= 0.5 RETURN count(l)", default=0)
    return {
        "requests": req,
        "messages": msg,
        "families": fam,
        "metrics": m,
        "rates": {
            "messages_per_min": await events.rate_per_min(user.org, "messages_in"),
            "assigned_per_min": await events.rate_per_min(user.org, "assigned"),
            "delivered_per_min": await events.rate_per_min(user.org, "delivered"),
        },
        "duplicate_dispatches": double,
        "dedupe": {
            "precision": round(pairs_both / pairs_same_f, 3) if pairs_same_f else None,
            "recall": round(pairs_both / pairs_same_h, 3) if pairs_same_h else None,
            "true_pairs": pairs_same_h,
            "merged_pairs": pairs_same_f,
        },
        "lessons_active": lessons,
        "llm": "live" if llm.is_live() else "rules",
    }


@app.get("/api/ops/events")
async def recent_events(count: int = 120, user: User = Depends(require("coordinator"))):
    return await events.recent(user.org, min(count, 500))


@app.get("/api/ops/family/{fid}")
async def family(fid: str, user: User = Depends(require("coordinator"))):
    exists = await db.scalar(org_graph_name(user.org), "MATCH (f:Family {id:$id}) RETURN count(f)", {"id": fid}, 0)
    if not exists:
        raise HTTPException(404, "unknown household")
    return await family_trace(user.org, fid)


class WhyIn(BaseModel):
    question: str = Field(min_length=2, max_length=500)


@app.post("/api/ops/why")
async def why(body: WhyIn, user: User = Depends(require("coordinator"))):
    return await answer_why(user.org, body.question)


@app.post("/api/ops/briefing")
async def briefing(user: User = Depends(require("coordinator"))):
    o = await orgs.get(user.org)
    return await make_briefing(user.org, o["name"] if o else user.org)


@app.get("/api/ops/briefings")
async def briefings(user: User = Depends(require("coordinator"))):
    return await query(
        org_graph_name(user.org),
        "MATCH (b:Briefing) RETURN b.id AS id, b.at AS at, b.shift AS shift, b.text AS text, b.by AS by"
        " ORDER BY b.at DESC LIMIT 10",
        readonly=True,
    )


@app.get("/api/ops/lessons")
async def lessons(user: User = Depends(require("coordinator"))):
    return await query(
        org_graph_name(user.org),
        "MATCH (l:Lesson) OPTIONAL MATCH (l)-[:DERIVED_FROM]->(e) OPTIONAL MATCH (r:Request)-[:USED_LESSON]->(l)"
        " RETURN l.key AS key, l.kind AS kind, l.text AS text, l.target AS target, l.need AS need,"
        " l.confidence AS confidence, l.seen AS seen, l.created_at AS created_at, l.updated_at AS updated_at,"
        " l.by AS by, collect(DISTINCT e.id) AS evidence, count(DISTINCT r) AS used"
        " ORDER BY l.confidence DESC",
        readonly=True,
    )


@app.post("/api/ops/learn")
async def learn_now(user: User = Depends(require("coordinator"))):
    await LearnerAgent("Learner-manual").tick(user.org)
    return await lessons(user)


@app.get("/api/ops/agents")
async def agents(user: User = Depends(require("coordinator"))):
    raw = await db.redis().hgetall(AGENTS_KEY)
    now = now_ms()
    out = []
    for name, v in sorted(raw.items()):
        a = json.loads(v)
        cmd = await db.redis().get(cmd_key(name))
        if a["state"] != "dead" and now - a["last_seen"] > 6000:
            a["state"] = "stale"
        a["killed"] = cmd == "kill"
        if a.get("org") and a["org"] != user.org:
            a["job"] = None  # never leak another org's request ids
        out.append(a)
    return out


@app.post("/api/ops/agents/{name}/kill")
async def kill_agent(name: str, user: User = Depends(require("coordinator"))):
    if not await db.redis().hexists(AGENTS_KEY, name):
        raise HTTPException(404, "unknown agent")
    await db.redis().set(cmd_key(name), "kill", ex=3600)
    await events.publish(user.org, "agent_kill", f"{user.name} killed {name} (simulated crash)", agent=name)
    return {"ok": True}


@app.post("/api/ops/agents/{name}/revive")
async def revive_agent(name: str, user: User = Depends(require("coordinator"))):
    await db.redis().set(cmd_key(name), "revive", ex=3600)
    await events.publish(user.org, "agent_revive", f"{user.name} restarted {name}", agent=name)
    return {"ok": True}


class RoadIn(BaseModel):
    road: str
    status: str = Field(pattern="^(flooded|open)$")


@app.post("/api/ops/roads")
async def set_road(body: RoadIn, user: User = Depends(require("coordinator"))):
    res = await field_ops.report_road(
        user.org, body.road, body.status, reporter=user.id, verified=True, source_text=f"coordinator: {body.road}"
    )
    if not res["ok"]:
        raise HTTPException(400, res["error"])
    return res


class MessageIn(BaseModel):
    text: str = Field(min_length=3, max_length=2000)
    channel: str = "helpline"


@app.post("/api/ops/messages")
async def add_message(body: MessageIn, user: User = Depends(require("coordinator"))):
    return {"id": await field_ops.ingest_message(user.org, body.text, body.channel, sender=user.id)}


@app.get("/api/ops/teams")
async def teams(user: User = Depends(current_user)):
    return await query(
        org_graph_name(user.org),
        "MATCH (t:Team) OPTIONAL MATCH (v:Volunteer)-[:MEMBER_OF]->(t)"
        " RETURN t.name AS name, t.supplies AS supplies, t.capacity AS capacity, t.status AS status,"
        " collect(v.name) AS members ORDER BY t.name",
        readonly=True,
    )


@app.get("/api/ops/tenancy")
async def tenancy(user: User = Depends(require("coordinator"))):
    g = org_graph_name(user.org)
    counts = await query(
        g, "MATCH (n) RETURN labels(n)[0] AS label, count(n) AS n ORDER BY n DESC", readonly=True
    )
    all_graphs = await db.list_graphs()
    return {
        "graph": g,
        "counts": counts,
        "shared": REGION_GRAPH,
        "graphs_in_instance": len(all_graphs),
        "org_graphs": sum(1 for x in all_graphs if x.startswith("org_")),
    }


# ---------------------------------------------------------------- simulator
class SimIn(BaseModel):
    rate_per_min: float = Field(default=20, ge=1, le=600)
    auto_field: bool = True
    scenario: str = Field(default="demo", pattern="^(demo|flood)$")
    households: int = Field(default=60, ge=5, le=400)


@app.post("/api/sim/start")
async def sim_start(body: SimIn, user: User = Depends(require("coordinator"))):
    await sim.start(user.org, rate_per_min=body.rate_per_min, auto_field=body.auto_field, scenario=body.scenario,
                    households=body.households)
    return sim.status(user.org)


@app.post("/api/sim/stop")
async def sim_stop(user: User = Depends(require("coordinator"))):
    await sim.stop(user.org)
    return sim.status(user.org)


@app.get("/api/sim/status")
async def sim_status(user: User = Depends(require("coordinator"))):
    return sim.status(user.org)


class BurstIn(BaseModel):
    count: int = Field(default=200, ge=1, le=5000)


@app.post("/api/sim/burst")
async def sim_burst(body: BurstIn, user: User = Depends(require("coordinator"))):
    return await sim.burst(user.org, body.count)


@app.post("/api/sim/reset")
async def sim_reset(user: User = Depends(require("admin"))):
    from .seed import seed_org

    await sim.stop(user.org)
    o = await orgs.get(user.org)
    await seed_org(user.org, o["name"] if o else user.org, reset=True)
    for k in await db.redis().keys(f"rn:seq:{user.org}:*"):
        await db.redis().delete(k)
    auth.forget(user.org, user.id)
    await events.publish(user.org, "reset", "Org memory reset for a fresh demo")
    return {"ok": True}


@app.post("/api/sim/reset-roads")
async def reset_roads(user: User = Depends(require("admin"))):
    rows = await query(REGION_GRAPH, "MATCH ()-[r:ROAD]->() WHERE r.status <> 'open' RETURN DISTINCT r.name AS n")
    for r in rows:
        await routing.set_road_status(r["n"], "open")
    await query(REGION_GRAPH, "MATCH (p:Report) DELETE p")
    for o in await orgs.all_orgs():
        await events.publish(o["slug"], "road", "All roads reset to OPEN")
    return {"reopened": [r["n"] for r in rows]}


# ---------------------------------------------------------------- field app
class ChatIn(BaseModel):
    text: str = Field(min_length=1, max_length=1500)


@app.get("/api/field/me")
async def field_me(user: User = Depends(current_user)):
    assignments = await field_ops.team_assignments(user.org, user.team) if user.team else []
    linked = await db.scalar(
        org_graph_name(user.org), "MATCH (v:Volunteer {id:$id}) RETURN v.telegram_chat_id", {"id": user.id}
    )
    return {"user": user.__dict__, "assignments": assignments, "telegram_linked": bool(linked)}


@app.get("/api/field/history")
async def field_history(user: User = Depends(current_user)):
    return await history(user.org, user.id, limit=60)


@app.post("/api/field/chat")
async def field_chat(body: ChatIn, user: User = Depends(current_user)):
    session = FieldSession(user.org, user.__dict__, "web")
    return await session.reply(body.text)


class TeamIn(BaseModel):
    team: str


@app.post("/api/field/team")
async def field_team(body: TeamIn, user: User = Depends(current_user)):
    rows = await query(
        org_graph_name(user.org),
        "MATCH (v:Volunteer {id:$id}), (t:Team {name:$team})"
        " OPTIONAL MATCH (v)-[old:MEMBER_OF]->() DELETE old"
        " WITH DISTINCT v, t CREATE (v)-[:MEMBER_OF]->(t) RETURN t.name AS team",
        {"id": user.id, "team": body.team},
    )
    if not rows:
        raise HTTPException(404, "unknown team")
    auth.forget(user.org, user.id)
    return {"team": rows[0]["team"]}


@app.post("/api/field/telegram-link")
async def telegram_link(user: User = Depends(current_user)):
    code = f"{secrets.randbelow(900000) + 100000}"
    await db.redis().set(f"rn:tglink:{code}", json.dumps({"org": user.org, "id": user.id}), ex=900)
    bot = s.telegram_bot_username
    return {"code": code, "bot": bot, "deep_link": f"https://t.me/{bot}?start={code}" if bot else None,
            "expires_in": 900}


@app.post("/api/field/photo")
async def field_photo(file: UploadFile = File(...), note: str = "", user: User = Depends(current_user)):
    if file.content_type not in ("image/jpeg", "image/png", "image/webp"):
        raise HTTPException(400, "only jpeg, png or webp photos")
    data = await file.read()
    if len(data) > 8 * 1024 * 1024:
        raise HTTPException(400, "photo too large (8 MB max)")
    ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}[file.content_type]
    name = f"{uuid.uuid4().hex}.{ext}"
    (Path(s.uploads_dir) / name).write_bytes(data)
    oid = await field_ops.add_observation(user.org, note or "photo from the field", by=user.id, channel="web",
                                          photo=f"/uploads/{name}")
    await events.publish(user.org, "photo", f"{user.name} sent a photo: {note or ''}".strip(), photo=f"/uploads/{name}")
    return {"observation": oid, "url": f"/uploads/{name}"}


# ---------------------------------------------------------------- live stream
@app.get("/api/stream")
async def stream(request: Request, user: User = Depends(current_user)):
    async def gen():
        pubsub = db.redis().pubsub()
        await pubsub.subscribe(events.channel(user.org))
        try:
            yield f"event: hello\ndata: {json.dumps({'org': user.org})}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=15.0)
                if msg is None:
                    yield ": keep-alive\n\n"
                    continue
                yield f"data: {msg['data']}\n\n"
        finally:
            await pubsub.unsubscribe()
            await pubsub.aclose()

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
