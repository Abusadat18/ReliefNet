"""Graph writes shared by the API, the Field agent, Telegram and the simulator."""
from __future__ import annotations

import logging
import re

from . import areas, events, orgs, routing
from .db import REGION_GRAPH, now_ms, org_graph_name, query, redis
from .domain import SUPPLIES, TEAM_CAPACITY_MAX, TEAM_NAME_MAX

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


async def _send_back(org: str, match: str, params: dict, why: str, edge: str) -> list[str]:
    """Give active assignments back to Dispatch: the request returns to TRIAGED with a higher
    priority and a REROUTED edge. `match` binds `r`, `a` (ASSIGNED_TO) and `t` (the team)."""
    rows = await query(
        org_graph_name(org),
        f"{match}"
        " SET a.active = false, a.ended = 'rerouted', r.status = 'TRIAGED', r.claimed_by = NULL,"
        "   r.lease_until = NULL, r.rerouted = coalesce(r.rerouted, 0) + 1, r.reroute_reason = $why,"
        "   r.priority = r.priority + 5"
        f" CREATE (r)-[:REROUTED {{{edge}}}]->(t)"
        " WITH r MATCH (r)-[:FOR]->(f:Family) SET f.status = 'UNSERVED'"
        " RETURN r.id AS id",
        {**params, "now": now_ms(), "why": why},
    )
    ids = [r["id"] for r in rows]
    if ids:
        await events.incr(org, "rerouted", len(ids))
    return ids


async def reroute_affected(org: str, road: str) -> list[str]:
    ids = await _send_back(
        org,
        "MATCH (r:Request {status:'ASSIGNED'})-[a:ASSIGNED_TO {active:true}]->(t:Team) WHERE $road IN r.route_roads",
        {"road": road}, f"{road} flooded on the assigned route", "at:$now, road:$road, team:t.name",
    )
    if ids:
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


async def call_numbers(org: str, request_ids: list[str]) -> dict[str, str]:
    """The number a team calls for each request: the contact number first, then the household's own."""
    rows = await query(
        org_graph_name(org),
        "MATCH (r:Request) WHERE r.id IN $ids"
        " RETURN r.id AS id, CASE WHEN coalesce(r.alt_phone, '') <> '' THEN r.alt_phone ELSE r.phone END AS number",
        {"ids": request_ids},
        readonly=True,
    )
    return {r["id"]: r["number"] for r in rows if r["number"]}


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


# ---------------------------------------------------------------- teams
# Every query finds a team by its name (assignments, field agents, lessons, Telegram),
# so a name never changes after creation, and a team is never deleted: it goes off duty.

class TeamError(ValueError):
    """A team change that the server refuses. `status` is the HTTP status for the API."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


# No "/": the name is part of the team's URL in the API.
_TEAM_NAME = re.compile(r"^\w[\w .'&()-]*$")


def clean_team_name(name: str) -> str:
    name = " ".join((name or "").split())
    if not name:
        raise TeamError("Enter a team name.")
    if len(name) > TEAM_NAME_MAX:
        raise TeamError(f"Use a team name of {TEAM_NAME_MAX} characters or fewer.")
    if not _TEAM_NAME.match(name):
        raise TeamError("Use only letters, digits, spaces and . ' & ( ) - in a team name.")
    return name


def clean_supplies(supplies: list[str] | None) -> list[str]:
    chosen = {s.strip().lower() for s in supplies or [] if s and s.strip()}
    unknown = sorted(chosen - set(SUPPLIES))
    if unknown:
        raise TeamError(f"Unknown supply: {', '.join(unknown)}. Choose from {', '.join(SUPPLIES)}.")
    if not chosen:
        raise TeamError("Select one or more supplies.")
    return [s for s in SUPPLIES if s in chosen]


def clean_capacity(capacity: int) -> int:
    if isinstance(capacity, bool) or not isinstance(capacity, int) or not 1 <= capacity <= TEAM_CAPACITY_MAX:
        raise TeamError(f"Set a capacity from 1 to {TEAM_CAPACITY_MAX}.")
    return capacity


def team_base(lat: float, lon: float) -> areas.Junction:
    """The road junction nearest to the chosen point. Routes start at a junction."""
    reg = areas.region()
    if not areas.ward_at(reg, lat, lon):
        raise TeamError("Put the team base inside the operation area.")
    return areas.nearest_junction(reg, lat, lon)


async def list_teams(org: str) -> list[dict]:
    return await query(
        org_graph_name(org),
        "MATCH (t:Team)"
        " OPTIONAL MATCH (x:Request {status:'ASSIGNED'})-[:ASSIGNED_TO {active:true}]->(t)"
        " WITH t, count(DISTINCT x) AS load"
        " OPTIONAL MATCH (v:Volunteer)-[:MEMBER_OF]->(t)"
        " RETURN t.name AS name, t.supplies AS supplies, t.capacity AS capacity, t.status AS status,"
        " t.base_junction AS base, t.lat AS lat, t.lon AS lon, load, collect(v.name) AS members"
        " ORDER BY name",
        readonly=True,
    )


async def create_team(org: str, name: str, supplies: list[str], capacity: int, lat: float, lon: float,
                      *, by: str) -> dict:
    name = clean_team_name(name)
    supplies = clean_supplies(supplies)
    capacity = clean_capacity(capacity)
    base = team_base(lat, lon)
    # The check and the write are one query, so two admins cannot add the same name at once.
    rows = await query(
        org_graph_name(org),
        "OPTIONAL MATCH (x:Team) WHERE toLower(x.name) = $key"
        " WITH count(x) AS taken WHERE taken = 0"
        " CREATE (t:Team {name:$name, supplies:$supplies, base_junction:$base, capacity:$capacity,"
        "   lat:$lat, lon:$lon, status:'active', created_at:$now, created_by:$by})"
        " MERGE (a:Agent {name:'Field-' + $name}) SET a.kind = 'field'"
        " MERGE (a)-[:WORKS_FOR]->(t)"
        " RETURN t.name AS name",
        {"key": name.lower(), "name": name, "supplies": supplies, "base": base.id, "capacity": capacity,
         "lat": base.lat, "lon": base.lon, "now": now_ms(), "by": by},
    )
    if not rows:
        raise TeamError(f"A team with the name {name} exists. Use a different name.", 409)
    await events.publish(org, "team", f"{name} added ({', '.join(supplies)}; capacity {capacity})",
                         team=name, change="added")
    return {"name": name, "supplies": supplies, "capacity": capacity, "status": "active", "base": base.id,
            "lat": base.lat, "lon": base.lon}


async def update_team(org: str, name: str, *, supplies: list[str] | None = None, capacity: int | None = None,
                      lat: float | None = None, lon: float | None = None, by: str) -> dict:
    """Change the supplies, the capacity or the base. Active assignments keep their routes."""
    props: dict = {}
    if supplies is not None:
        props["supplies"] = clean_supplies(supplies)
    if capacity is not None:
        props["capacity"] = clean_capacity(capacity)
    if (lat is None) != (lon is None):
        raise TeamError("Send the latitude and the longitude of the base together.")
    if lat is not None and lon is not None:
        base = team_base(lat, lon)
        props |= {"base_junction": base.id, "lat": base.lat, "lon": base.lon}
    if not props:
        raise TeamError("Change the supplies, the capacity or the base.")
    rows = await query(
        org_graph_name(org),
        "MATCH (t:Team {name:$name}) SET t += $props, t.updated_at = $now, t.updated_by = $by"
        " RETURN t.name AS name, t.supplies AS supplies, t.capacity AS capacity, t.status AS status,"
        " t.base_junction AS base, t.lat AS lat, t.lon AS lon",
        {"name": name, "props": props, "now": now_ms(), "by": by},
    )
    if not rows:
        raise TeamError(f"Team {name} does not exist.", 404)
    changed = ", ".join("base" if k == "base_junction" else k for k in props if k not in ("lat", "lon"))
    await events.publish(org, "team", f"{name} changed: {changed}", team=name, change="updated")
    return rows[0]


async def set_team_duty(org: str, name: str, on_duty: bool, *, by: str) -> dict:
    """Put a team on duty or off duty. Off duty sends its active assignments back to Dispatch.

    The status changes first. Dispatch's assignment write needs an active team
    (see `memory.assign_team`), so no new assignment can arrive after this point."""
    status = "active" if on_duty else "off_duty"
    rows = await query(
        org_graph_name(org),
        "MATCH (t:Team {name:$name}) WITH t, t.status AS before"
        " SET t.status = $status, t.duty_at = $now, t.duty_by = $by RETURN before",
        {"name": name, "status": status, "now": now_ms(), "by": by},
    )
    if not rows:
        raise TeamError(f"Team {name} does not exist.", 404)
    ids: list[str] = []
    if not on_duty:
        ids = await _send_back(
            org,
            "MATCH (r:Request {status:'ASSIGNED'})-[a:ASSIGNED_TO {active:true}]->(t:Team {name:$team})",
            {"team": name}, f"{name} off duty", "at:$now, reason:$why, team:t.name",
        )
    if rows[0]["before"] != status or ids:
        text = f"{name} is on duty" if on_duty else f"{name} is off duty"
        if ids:
            text += f": {len(ids)} assignment(s) sent back to Dispatch"
        await events.publish(org, "team", text, team=name, change="duty", status=status, ids=ids)
    return {"name": name, "status": status, "rerouted": ids}
