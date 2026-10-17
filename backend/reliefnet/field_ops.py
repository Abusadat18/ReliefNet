"""Graph writes shared by the API, the Field agent, Telegram and the simulator."""
from __future__ import annotations

import logging

from . import events, orgs, routing
from .db import REGION_GRAPH, now_ms, org_graph_name, query, redis

log = logging.getLogger(__name__)

# A road becomes "flooded" (impassable) after this many independent teams
# report it, or after one verified coordinator report.
FLOOD_CONFIRMATIONS = 2
REPORT_WINDOW_MS = 6 * 3600 * 1000


async def ingest_message(
    org: str,
    text: str,
    channel: str,
    *,
    sender: str = "",
    received_at: int | None = None,
    sim_household: str = "",
    extra: dict | None = None,
) -> str:
    seq = await redis().incr(f"rn:seq:{org}:M")
    mid = f"M-{1000 + seq}"
    await query(
        org_graph_name(org),
        "CREATE (:Message {id:$id, text:$text, channel:$channel, sender:$sender, received_at:$at,"
        " status:'RAW', sim_household:$sim})",
        {"id": mid, "text": text[:2000], "channel": channel, "sender": sender,
         "at": received_at or now_ms(), "sim": sim_household},
    )
    if extra:  # the bot's structured fields; empty values are left off the node
        props = {k: v for k, v in extra.items() if v not in (None, "")}
        if props:
            await query(org_graph_name(org), "MATCH (m:Message {id:$id}) SET m += $props", {"id": mid, "props": props})
    await events.incr(org, "messages_in")
    await events.publish(org, "message", f"{mid} ({channel}): {text[:160]}", id=mid, channel=channel)
    return mid


async def reroute_affected(org: str, road: str) -> list[str]:
    rows = await query(
        org_graph_name(org),
        "MATCH (r:Request {status:'ASSIGNED'})-[a:ASSIGNED_TO {active:true}]->(t:Team)"
        " WHERE $road IN r.route_roads"
        " SET a.active = false, a.ended = 'rerouted', r.status = 'TRIAGED', r.claimed_by = NULL,"
        "   r.lease_until = NULL, r.rerouted = coalesce(r.rerouted, 0) + 1, r.reroute_reason = $why,"
        "   r.priority = r.priority + 5"
        " CREATE (r)-[:REROUTED {at:$now, road:$road, team:t.name}]->(t)"
        " WITH r MATCH (r)-[:FOR]->(f:Family) SET f.status = 'UNSERVED'"
        " RETURN r.id AS id",
        {"road": road, "now": now_ms(), "why": f"{road} flooded on the assigned route"},
    )
    ids = [r["id"] for r in rows]
    if ids:
        await events.incr(org, "rerouted", len(ids))
        await events.publish(
            org, "rerouted", f"{road} flooded: {len(ids)} assignment(s) sent back to Dispatch for a new route",
            road=road, ids=ids,
        )
    return ids


async def report_road(
    org: str,
    road_text: str,
    status: str,
    *,
    reporter: str,
    team: str | None = None,
    verified: bool = False,
    source_text: str = "",
) -> dict:
    road = await routing.match_road(road_text)
    if not road:
        return {"ok": False, "error": f"Unknown road '{road_text}'. Known roads: {', '.join(await routing.road_names())}"}
    now = now_ms()
    seq = await redis().incr("rn:seq:report")
    rid = f"RP-{seq}"
    reporter_key = f"{org}:{team}" if team else reporter
    report = {"id": rid, "road": road, "status": status, "org": org, "by": reporter, "team": team or "",
              "key": reporter_key, "at": now, "verified": verified, "text": source_text[:300]}
    await query(REGION_GRAPH, "CREATE (rep:Report) SET rep = $p", {"p": report})
    await query(
        org_graph_name(org),
        "CREATE (rep:Report) SET rep = $p"
        " WITH rep OPTIONAL MATCH (v:Volunteer {id:$by}) FOREACH (_ IN CASE WHEN v IS NULL THEN [] ELSE [1] END |"
        "   CREATE (v)-[:REPORTED {at:$at}]->(rep))",
        {"p": report, "by": reporter, "at": now},
    )
    before = await routing.road_state(road)
    if status == "open":
        new_status = "open" if verified or team else before
    else:
        rows = await query(
            REGION_GRAPH,
            "MATCH (p:Report {road:$road, status:'flooded'}) WHERE p.at > $since"
            " RETURN count(DISTINCT p.key) AS teams, max(CASE WHEN p.verified THEN 1 ELSE 0 END) AS verified",
            {"road": road, "since": now - REPORT_WINDOW_MS},
        )
        teams = rows[0]["teams"] if rows else 0
        confirmed = verified or (rows and rows[0]["verified"]) or teams >= FLOOD_CONFIRMATIONS
        new_status = "flooded" if confirmed else ("reported" if before != "flooded" else "flooded")
    rerouted: dict[str, list[str]] = {}
    if new_status != before:
        await routing.set_road_status(road, new_status)
        for o in await orgs.all_orgs():
            slug = o["slug"]
            await events.publish(
                slug, "road",
                f"{rid}: {road} is now {new_status.upper()} (reported by {reporter if slug == org else 'another org'})",
                road=road, status=new_status, previous=before, report=rid,
            )
            if new_status == "flooded":
                rerouted[slug] = await reroute_affected(slug, road)
    else:
        await events.publish(org, "road_report", f"{rid}: report on {road}: {status} (still {before})", road=road,
                             status=before, report=rid)
    return {"ok": True, "road": road, "status": new_status, "previous": before, "report": rid,
            "rerouted": rerouted.get(org, [])}


async def mark_delivered(
    org: str, request_id: str, items: list[str], notes: str, *, by: str, team: str | None = None
) -> dict:
    now = now_ms()
    seq = await redis().incr(f"rn:seq:{org}:D")
    did = f"D-{seq}"
    rows = await query(
        org_graph_name(org),
        "MATCH (r:Request {id:$rid}) WHERE r.status = 'ASSIGNED'"
        " MATCH (r)-[a:ASSIGNED_TO {active:true}]->(t:Team)"
        " MATCH (r)-[:FOR]->(f:Family)"
        " SET r.status = 'DELIVERED', r.delivered_at = $now, a.active = false, a.ended = 'delivered',"
        "   f.status = 'SERVED', f.served_at = $now"
        " CREATE (t)-[:MADE]->(d:Delivery {id:$did, at:$now, items:$items, notes:$notes, by:$by,"
        "   duration_min: toFloat($now - r.assigned_at) / 60000.0, needs:r.needs})-[:SERVED]->(f)"
        " CREATE (d)-[:FOR_REQUEST]->(r)"
        " MERGE (ag:Agent {name:'Field-' + t.name})"
        " CREATE (r)-[:PROCESSED_BY {at:$now, action:'field', from:'ASSIGNED', to:'DELIVERED', reason:$why}]->(ag)"
        " WITH r, f, t, d OPTIONAL MATCH (f)-[n:NEEDS]->() SET n.open = false"
        " RETURN DISTINCT r.id AS id, f.id AS family, f.name AS name, t.name AS team, d.duration_min AS mins",
        {"rid": request_id, "now": now, "did": did, "items": items, "notes": notes[:500], "by": by,
         "why": f"delivered: {', '.join(items) or 'help given'}"},
    )
    if not rows:
        return {"ok": False, "error": f"{request_id} is not an active assignment"}
    row = rows[0]
    await events.incr(org, "delivered")
    await events.publish(
        org, "delivered",
        f"{did}: {row['team']} delivered to {row['name'] or row['family']} ({request_id}): "
        f"{', '.join(items) or 'help given'}",
        id=request_id, delivery=did, family=row["family"], team=row["team"],
    )
    return {"ok": True, "delivery": did, **row}


async def add_observation(org: str, text: str, *, by: str, channel: str, lat: float | None = None,
                          lon: float | None = None, photo: str | None = None) -> str:
    seq = await redis().incr(f"rn:seq:{org}:O")
    oid = f"O-{seq}"
    await query(
        org_graph_name(org),
        "CREATE (o:Observation {id:$id, text:$text, at:$now, channel:$channel, by:$by, lat:$lat, lon:$lon,"
        " photo:$photo})"
        " WITH o OPTIONAL MATCH (v:Volunteer {id:$by})"
        " FOREACH (_ IN CASE WHEN v IS NULL THEN [] ELSE [1] END | CREATE (v)-[:SAID {at:$now}]->(o))",
        {"id": oid, "text": text[:1000], "now": now_ms(), "channel": channel, "by": by, "lat": lat, "lon": lon,
         "photo": photo},
    )
    return oid


async def team_assignments(org: str, team: str) -> list[dict]:
    return await query(
        org_graph_name(org),
        "MATCH (r:Request {status:'ASSIGNED'})-[a:ASSIGNED_TO {active:true}]->(t:Team {name:$team})"
        " MATCH (r)-[:FOR]->(f:Family)"
        " RETURN r.id AS id, f.id AS family, f.name AS name, r.people AS people, r.needs AS needs,"
        " r.landmark AS landmark, r.ward AS ward, r.priority AS priority, a.eta_min AS eta_min,"
        " r.route_roads AS roads, r.summary AS summary, r.lat AS lat, r.lon AS lon"
        " ORDER BY r.priority DESC",
        {"team": team},
        readonly=True,
    )


async def nearest_shelters(lat: float, lon: float, limit: int = 3) -> list[dict]:
    return await query(
        REGION_GRAPH,
        "MATCH (s:Shelter {open:true})"
        " RETURN s.id AS id, s.name AS name, s.ward AS ward, s.capacity - s.occupancy AS free,"
        " distance(point({latitude:s.lat, longitude:s.lon}), point({latitude:$lat, longitude:$lon})) AS meters"
        " ORDER BY meters LIMIT $n",
        {"lat": lat, "lon": lon, "n": limit},
        readonly=True,
    )
