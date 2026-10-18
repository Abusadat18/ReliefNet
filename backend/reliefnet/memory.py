"""The shared memory: every graph query the agents use, with a name.

Agents call these functions and never write Cypher themselves, so each agent
reads as a short recipe and every query can be reviewed in one place.

Writes that end a pipeline step are *guarded*: they match the item only while
`claimed_by` is still this agent, so a worker whose lease expired cannot
overwrite the work of the copy that reclaimed the item."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from redis.exceptions import ResponseError

from .db import now_ms, org_graph_name, query
from .models import Candidate, Family, Lesson, Request, Team


@dataclass(frozen=True)
class Worker:
    """Who is writing: the agent's name, its kind, and the items it claims."""

    name: str
    kind: str
    label: str  # node label it claims, e.g. "Request"
    status: str  # status it claims from, e.g. "TRIAGED"


# ============================================================ leases (every agent)

async def claim_next(org: str, me: Worker, order: str, lease_ms: int) -> tuple[dict | None, str | None]:
    """Atomically claim the next free item in `me.status`.

    An item is free when nobody holds it, or the holder's lease has expired.
    Returns the item's properties and the previous holder (if it was reclaimed)."""
    rows = await query(
        org_graph_name(org),
        f"MATCH (r:{me.label} {{status:$status}})"
        " WHERE (r.claimed_by IS NULL OR r.lease_until < $now) AND coalesce(r.not_before, 0) <= $now"
        f" WITH r ORDER BY {order} LIMIT 1"
        " WITH r, r.claimed_by AS prev"
        " SET r.claimed_by = $me, r.lease_until = $now + $lease, r.attempts = coalesce(r.attempts, 0) + 1"
        " RETURN properties(r) AS item, prev",
        {"status": me.status, "now": now_ms(), "me": me.name, "lease": lease_ms},
    )
    if not rows:
        return None, None
    item = rows[0]["item"]
    item.pop("embedding", None)
    return item, rows[0]["prev"]


async def note_reclaim(org: str, me: Worker, item_id: str, previous: str) -> None:
    """Record on the item that `me` took it over from a crashed holder."""
    await query(
        org_graph_name(org),
        f"MATCH (r:{me.label} {{id:$id}}) MERGE (a:Agent {{name:$me}}) ON CREATE SET a.kind = $kind"
        " CREATE (r)-[:PROCESSED_BY {at:$now, action:'reclaimed', reason:$reason}]->(a)",
        {"id": item_id, "me": me.name, "kind": me.kind, "now": now_ms(),
         "reason": f"lease held by {previous} expired"},
    )


async def renew_lease(org: str, me: Worker, item_id: str, lease_ms: int) -> bool:
    """Extend the lease. False means another agent has taken the item."""
    rows = await query(
        org_graph_name(org),
        f"MATCH (r:{me.label} {{id:$id}}) WHERE r.claimed_by = $me SET r.lease_until = $until RETURN count(r) AS n",
        {"id": item_id, "me": me.name, "until": now_ms() + lease_ms},
    )
    return bool(rows and rows[0]["n"])


async def release(org: str, me: Worker, item_id: str, delay_ms: int = 0, props: dict | None = None) -> None:
    """Give the item back unfinished; no agent may take it for `delay_ms`."""
    await query(
        org_graph_name(org),
        f"MATCH (r:{me.label} {{id:$id}}) WHERE r.claimed_by = $me"
        " SET r += $props, r.claimed_by = NULL, r.lease_until = NULL, r.not_before = $nb",
        {"id": item_id, "me": me.name, "nb": now_ms() + delay_ms, "props": props or {}},
    )


async def _finish(
    org: str,
    me: Worker,
    item_id: str,
    next_status: str,
    props: dict[str, Any],
    reason: str,
    then: str = "",
    params: dict | None = None,
    guard: str = "",
) -> bool:
    """Guarded end of a step: set the new status, release the lease, add a
    PROCESSED_BY edge with the reason, then run `then` (more Cypher that can
    use `r` for the item and `a` for this agent). False if the lease was lost.

    `guard` is an extra MATCH before any write: when it finds nothing, nothing is written."""
    rows = await query(
        org_graph_name(org),
        f"MATCH (r:{me.label} {{id:$id}}) WHERE r.claimed_by = $me"
        f" {guard}"
        " SET r += $props, r.status = $next, r.claimed_by = NULL, r.lease_until = NULL, r.updated_at = $now"
        " WITH r MERGE (a:Agent {name:$me}) ON CREATE SET a.kind = $kind"
        " CREATE (r)-[:PROCESSED_BY {at:$now, action:$kind, from:$from, to:$next, reason:$reason}]->(a)"
        f" {then}"
        " RETURN r.id AS id",
        {"id": item_id, "me": me.name, "kind": me.kind, "props": props, "next": next_status, "now": now_ms(),
         "reason": reason, "from": me.status, **(params or {})},
    )
    return bool(rows)


async def finish_step(org: str, me: Worker, item_id: str, next_status: str, props: dict, reason: str) -> bool:
    """End a step that writes nothing besides the item's own properties."""
    return await _finish(org, me, item_id, next_status, props, reason)


# ============================================================ Intake

async def create_request(org: str, me: Worker, message_id: str, request: Request, vector: list[float],
                         parsed_by: str) -> bool:
    """Mark the message PARSED and create the Request it BECAME, with its embedding."""
    return await _finish(
        org, me, message_id, "PARSED", {"kind": "help_request", "parsed_by": parsed_by},
        f"extracted request {request.id} ({parsed_by})",
        then=(
            " CREATE (r)-[:BECAME {at:$now}]->(req:Request)"
            " SET req = $req, req.loc = point({latitude:$req.lat, longitude:$req.lon}),"
            " req.embedding = vecf32($vec)"
            " CREATE (req)-[:PROCESSED_BY {at:$now, action:'intake', from:'', to:'NEW', reason:$why}]->(a)"
        ),
        params={"req": request.props(), "vec": vector, "why": f"created from {message_id} via {parsed_by}"},
    )


# ============================================================ Dedupe

async def similar_requests(org: str, request_id: str, k: int = 12) -> list[Candidate]:
    """Nearest earlier requests by meaning (vector index), each with its household."""
    rows = await query(
        org_graph_name(org),
        "MATCH (me:Request {id:$id})"
        " CALL db.idx.vector.queryNodes('Request', 'embedding', $k, me.embedding) YIELD node, score"
        " WITH node, score WHERE node.id <> $id"
        " MATCH (node)-[:FOR]->(f:Family)"
        " RETURN node.id AS id, node.name AS name, node.people AS people, node.elderly AS elderly,"
        " node.children AS children, node.ward AS ward, node.landmark AS landmark, node.lat AS lat,"
        " node.lon AS lon, node.summary AS summary, node.status AS status, f.id AS family,"
        " 1.0 - score AS similarity",  # the index returns cosine distance
        {"id": request_id, "k": k},
        readonly=True,
    )
    return [Candidate.model_validate(r) for r in rows]


async def create_household(org: str, me: Worker, request_id: str, family_id: str, reason: str,
                           near_radius_m: float) -> bool:
    """Resolve the request as a new Family, with NEEDS edges and NEAR edges to neighbours."""
    return await _finish(
        org, me, request_id, "RESOLVED", {"family": family_id}, f"new household {family_id} ({reason})",
        then=(
            " CREATE (r)-[:FOR]->(f:Family {id:$fid, name:r.name, people:r.people, elderly:r.elderly,"
            "   children:r.children, needs:r.needs, lat:r.lat, lon:r.lon, ward:r.ward, landmark:r.landmark,"
            "   status:'UNSERVED', first_seen:r.created_at, last_seen:r.created_at, requests:1})"
            " SET f.loc = point({latitude:r.lat, longitude:r.lon})"
            " FOREACH (need IN r.needs |"
            "   MERGE (n:Need {name:need}) MERGE (f)-[:NEEDS {open:true, since:$now}]->(n))"
            " WITH r, f"
            " OPTIONAL MATCH (o:Family) WHERE o.id <> f.id AND distance(o.loc, f.loc) < $rad"
            " FOREACH (_ IN CASE WHEN o IS NULL THEN [] ELSE [1] END |"
            "   MERGE (f)-[:NEAR]->(o) MERGE (o)-[:NEAR]->(f))"
            " WITH DISTINCT r"
        ),
        params={"fid": family_id, "rad": near_radius_m},
    )


async def live_request_of(org: str, family_id: str, exclude_id: str) -> str | None:
    """The household's request that is still in progress, if there is one."""
    rows = await query(
        org_graph_name(org),
        "MATCH (f:Family {id:$fid})<-[:FOR]-(p:Request)"
        " WHERE p.id <> $id AND p.status IN ['NEW', 'RESOLVED', 'TRIAGED', 'ASSIGNED']"
        " RETURN p.id AS id ORDER BY p.created_at LIMIT 1",
        {"fid": family_id, "id": exclude_id},
        readonly=True,
    )
    return rows[0]["id"] if rows else None


async def link_to_household(
    org: str,
    me: Worker,
    request_id: str,
    next_status: str,
    family_id: str,
    match_id: str,
    merged_into: str | None,
    score: float,
    evidence: dict,
    reason: str,
    decided_by: str,
) -> bool:
    """Attach a duplicate request to an existing Family, with a DUPLICATE_OF edge
    that keeps the evidence, and fold its details into the household."""
    return await _finish(
        org, me, request_id, next_status, {"family": family_id, "merged_into": merged_into or ""},
        f"same household as {match_id} ({family_id}): {reason}",
        then=(
            " WITH r MATCH (f:Family {id:$fid}), (c:Request {id:$cid})"
            " CREATE (r)-[:FOR]->(f)"
            " CREATE (r)-[:DUPLICATE_OF {at:$now, score:$score, evidence:$ev, reason:$why, decided_by:$by}]->(c)"
            " SET f.people = CASE WHEN r.people > f.people THEN r.people ELSE f.people END,"
            "     f.elderly = CASE WHEN r.elderly > f.elderly THEN r.elderly ELSE f.elderly END,"
            "     f.children = CASE WHEN r.children > f.children THEN r.children ELSE f.children END,"
            "     f.name = CASE WHEN f.name = '' THEN r.name ELSE f.name END,"
            "     f.last_seen = $now, f.requests = f.requests + 1,"
            "     f.needs = f.needs + [n IN r.needs WHERE NOT n IN f.needs],"
            "     f.status = CASE WHEN f.status = 'SERVED' THEN 'UNSERVED' ELSE f.status END"
            " FOREACH (need IN r.needs |"
            "   MERGE (n:Need {name:need}) MERGE (f)-[e:NEEDS]->(n) SET e.open = true)"
            " WITH r"
        ),
        params={"fid": family_id, "cid": match_id, "score": score, "ev": str(evidence), "why": reason,
                "by": decided_by},
    )


async def fold_duplicate(org: str, primary_id: str, duplicate_id: str) -> None:
    """Copy a duplicate's new details into the live request, and send the live
    request back to Triage if it is still waiting for a team."""
    await query(
        org_graph_name(org),
        "MATCH (p:Request {id:$pid}), (r:Request {id:$rid})"
        " SET p.needs = p.needs + [n IN r.needs WHERE NOT n IN p.needs],"
        "     p.people = CASE WHEN r.people > p.people THEN r.people ELSE p.people END,"
        "     p.elderly = CASE WHEN r.elderly > p.elderly THEN r.elderly ELSE p.elderly END,"
        "     p.children = CASE WHEN r.children > p.children THEN r.children ELSE p.children END,"
        "     p.water_entering = p.water_entering OR r.water_entering,"
        "     p.trapped = p.trapped OR r.trapped, p.merged_count = coalesce(p.merged_count, 0) + 1,"
        "     p.name = CASE WHEN p.name = '' THEN r.name ELSE p.name END"
        " WITH p WHERE p.status = 'TRIAGED' AND (p.claimed_by IS NULL OR p.lease_until < $now)"
        " SET p.status = 'RESOLVED'",
        {"pid": primary_id, "rid": duplicate_id, "now": now_ms()},
    )


# ============================================================ Triage

async def household_of(org: str, request_id: str) -> Family | None:
    rows = await query(
        org_graph_name(org),
        "MATCH (r:Request {id:$id})-[:FOR]->(f:Family) RETURN properties(f) AS f LIMIT 1",
        {"id": request_id},
        readonly=True,
    )
    return Family.model_validate(rows[0]["f"]) if rows else None


async def household_communities(org: str) -> list[dict]:
    """Community detection (label propagation) over households linked by NEAR.

    Returns one row per household: id, status, first_seen and community id `cid`."""
    try:
        return await query(
            org_graph_name(org),
            "CALL algo.labelPropagation({nodeLabels:['Family'], relationshipTypes:['NEAR']})"
            " YIELD node, communityId"
            " RETURN node.id AS id, node.status AS status, node.first_seen AS first_seen, communityId AS cid",
            readonly=True,
        )
    except ResponseError as e:
        # Before the first NEAR edge exists, the relationship type is unknown.
        if "unknown relationship-type" not in str(e):
            raise
        return []


# A coordinator's override wins over confidence: 'on' applies a lesson, 'off' never applies it.
LESSON_IN_USE = "coalesce(l.override, '') <> 'off' AND (l.override = 'on' OR l.confidence >= $min)"


async def active_lessons(org: str, kinds: list[str], min_confidence: float = 0.5) -> list[Lesson]:
    """Lessons of these kinds that are confident enough to act on, or that a coordinator applied."""
    rows = await query(
        org_graph_name(org),
        f"MATCH (l:Lesson) WHERE l.kind IN $kinds AND {LESSON_IN_USE} RETURN properties(l) AS l",
        {"kinds": kinds, "min": min_confidence},
        readonly=True,
    )
    return [Lesson.model_validate(r["l"]) for r in rows]


async def set_lesson_override(org: str, key: str, override: str | None, by: str) -> dict | None:
    """Apply ('on') or dismiss ('off') a lesson, or give the decision back to its confidence (None).
    The Learner keeps updating the confidence; the override stays until a coordinator clears it."""
    rows = await query(
        org_graph_name(org),
        "MATCH (l:Lesson {key:$key}) SET l.override = $o, l.override_by = $by, l.override_at = $now"
        " RETURN l.key AS key, l.text AS text, l.override AS override",
        {"key": key, "o": override, "by": by, "now": now_ms()},
    )
    return rows[0] if rows else None


async def save_priority(org: str, me: Worker, request_id: str, priority: int, reasons: list[str], bonus: int,
                        cluster_id: int, used_lessons: list[str]) -> bool:
    """Mark the request TRIAGED with its score and reasons; link the lessons it used."""
    return await _finish(
        org, me, request_id, "TRIAGED",
        {"priority": priority, "reason": "; ".join(reasons), "cluster_bonus": bonus, "cluster_id": cluster_id},
        f"priority {priority}: " + "; ".join(reasons),
        then=_USED_LESSONS,
        params={"used": used_lessons},
    )


async def lift_cluster(org: str, family_ids: list[str], except_request: str, bonus: int) -> None:
    """Raise every waiting request in a hot cluster to the new cluster bonus."""
    await query(
        org_graph_name(org),
        "MATCH (r:Request {status:'TRIAGED'})-[:FOR]->(f:Family) WHERE f.id IN $members AND r.id <> $id"
        "   AND coalesce(r.cluster_bonus, 0) < $bonus"
        " SET r.priority = CASE WHEN r.priority - coalesce(r.cluster_bonus, 0) + $bonus > 100 THEN 100"
        "   ELSE r.priority - coalesce(r.cluster_bonus, 0) + $bonus END, r.cluster_bonus = $bonus",
        {"members": family_ids, "id": except_request, "bonus": bonus},
    )


# Links the item `r` to lessons in $used. Appended to guarded step writes.
_USED_LESSONS = (
    " WITH r OPTIONAL MATCH (l:Lesson) WHERE l.key IN $used"
    " FOREACH (_ IN CASE WHEN l IS NULL THEN [] ELSE [1] END |"
    "   CREATE (r)-[:USED_LESSON {at:$now, by:$me}]->(l))"
    " WITH DISTINCT r"
)


# ============================================================ Dispatch

async def teams_with_load(org: str) -> list[Team]:
    """Active teams, each with its number of open assignments."""
    rows = await query(
        org_graph_name(org),
        "MATCH (t:Team {status:'active'})"
        " OPTIONAL MATCH (x:Request {status:'ASSIGNED'})-[a:ASSIGNED_TO {active:true}]->(t)"
        " RETURN t.name AS name, t.supplies AS supplies, t.base_junction AS base, t.capacity AS capacity,"
        " count(x) AS load",
        readonly=True,
    )
    return [Team.model_validate(r) for r in rows]


async def assign_team(
    org: str,
    me: Worker,
    request_id: str,
    team: str,
    eta_min: float,
    route: dict,
    route_json: str,
    used_lessons: list[str],
    reason: str,
) -> bool:
    """Mark the request ASSIGNED, create ASSIGNED_TO and the HANDED_OFF edge to the
    team's field agent. Refuses if the request already has an active assignment,
    or if the team went off duty after Dispatch read the team list."""
    return await _finish(
        org, me, request_id, "ASSIGNED",
        {"team": team, "assigned_at": now_ms(), "eta_min": eta_min, "route_roads": route["roads"],
         "route": route_json, "route_length_m": route["length_m"], "blocked_reason": ""},
        reason,
        then=(
            " WITH r, a MATCH (t:Team {name:$team}) MATCH (r)-[:FOR]->(f:Family)"
            " CREATE (r)-[:ASSIGNED_TO {active:true, at:$now, eta_min:$eta, roads:$roads, by:$me}]->(t)"
            " SET f.status = 'ASSIGNED'"
            " MERGE (fa:Agent {name:'Field-' + $team}) ON CREATE SET fa.kind = 'field'"
            " CREATE (a)-[:HANDED_OFF {request:r.id, at:$now, reason:$reason}]->(fa)"
            + _USED_LESSONS
        ),
        params={"team": team, "eta": eta_min, "roads": route["roads"], "used": used_lessons},
        # Both checks run before any write, so a refused assignment changes nothing.
        guard="AND NOT (r)-[:ASSIGNED_TO {active:true}]->() MATCH (:Team {name:$team, status:'active'})",
    )


# ============================================================ Learner

async def learner_evidence(org: str, since: int) -> dict[str, list[dict]]:
    """Field evidence since `since`: flood reports, deliveries, unserved wards, observations."""
    g = org_graph_name(org)
    reports = await query(
        g,
        "MATCH (p:Report) WHERE p.at > $since AND p.status = 'flooded'"
        " RETURN p.id AS id, p.road AS road, p.at AS at, p.team AS team, p.verified AS verified",
        {"since": since}, readonly=True,
    )
    deliveries = await query(
        g,
        "MATCH (t:Team)-[:MADE]->(d:Delivery) WHERE d.at > $since"
        " RETURN d.id AS id, t.name AS team, d.duration_min AS mins, d.needs AS needs",
        {"since": since}, readonly=True,
    )
    wards = await query(
        g,
        "MATCH (f:Family) WHERE f.status <> 'SERVED' AND f.ward > 0"
        " RETURN f.ward AS ward, count(f) AS unserved, min(f.first_seen) AS oldest, collect(f.id)[0..6] AS ids",
        readonly=True,
    )
    observations = await query(
        g,
        "MATCH (o:Observation) WHERE o.at > $since AND size(o.text) > 12"
        " RETURN o.id AS id, o.text AS text, o.at AS at ORDER BY o.at DESC LIMIT 25",
        {"since": since}, readonly=True,
    )
    return {"reports": reports, "deliveries": deliveries, "wards": wards, "observations": observations}


async def team_names(org: str) -> list[str]:
    rows = await query(org_graph_name(org), "MATCH (t:Team) RETURN t.name AS n", readonly=True)
    return [r["n"] for r in rows]


async def save_lesson(org: str, lesson: Lesson, evidence_ids: list[str], vector: list[float]) -> dict:
    """Create or reinforce a lesson and link it to its evidence (DERIVED_FROM).

    Confidence rises when the evidence count grows. Returns `before` (evidence
    count before this call), `seen` and `confidence`."""
    rows = await query(
        org_graph_name(org),
        "MERGE (l:Lesson {key:$key})"
        " ON CREATE SET l.kind=$kind, l.target=$target, l.need=$need, l.created_at=$now, l.seen=0,"
        "   l.confidence=$conf, l.by=$by"
        " WITH l, l.seen AS before"
        " SET l.text=$text, l.after_hour=$after, l.updated_at=$now, l.seen = size($ev),"
        "   l.confidence = CASE WHEN size($ev) > before"
        "     THEN (CASE WHEN l.confidence + 0.1 > $conf THEN l.confidence + 0.1 ELSE $conf END)"
        "     ELSE l.confidence END,"
        "   l.embedding = vecf32($vec)"
        " SET l.confidence = CASE WHEN l.confidence > 0.97 THEN 0.97 ELSE l.confidence END"
        " WITH l, before"
        " OPTIONAL MATCH (e) WHERE e.id IN $ev AND (e:Report OR e:Delivery OR e:Observation OR e:Family)"
        " FOREACH (_ IN CASE WHEN e IS NULL THEN [] ELSE [1] END | MERGE (l)-[:DERIVED_FROM]->(e))"
        " RETURN DISTINCT before, l.seen AS seen, l.confidence AS confidence",
        {"key": lesson.key, "kind": lesson.kind, "target": lesson.target, "need": lesson.need,
         "after": lesson.after_hour if lesson.after_hour is not None else -1, "text": lesson.text,
         "ev": evidence_ids, "conf": lesson.confidence, "now": now_ms(), "by": lesson.by, "vec": vector},
    )
    return rows[0] if rows else {"before": 0, "seen": 0, "confidence": lesson.confidence}


async def decay_lessons(org: str, keep_keys: list[str], factor: float, floor: float = 0.1) -> None:
    """Lower the confidence of every lesson that got no new evidence this round."""
    await query(
        org_graph_name(org),
        "MATCH (l:Lesson) WHERE NOT l.key IN $keep"
        " SET l.confidence = CASE WHEN l.confidence * $f < $floor THEN $floor ELSE l.confidence * $f END",
        {"keep": keep_keys, "f": factor, "floor": floor},
    )


# ============================================================ Shift Coordinator

async def status_counts(org: str, label: str) -> dict[str, int]:
    """How many nodes of `label` are in each status."""
    rows = await query(
        org_graph_name(org), f"MATCH (n:{label}) RETURN n.status AS status, count(n) AS n", readonly=True
    )
    return {r["status"]: r["n"] for r in rows}


async def top_waiting(org: str, limit: int = 8) -> list[dict]:
    """Requests not yet assigned, highest priority first, with their household."""
    return await query(
        org_graph_name(org),
        "MATCH (r:Request) WHERE r.status IN ['TRIAGED', 'RESOLVED', 'NEW'] MATCH (r)-[:FOR]->(f:Family)"
        " RETURN r.id AS id, f.id AS family, f.name AS name, r.priority AS priority, r.ward AS ward,"
        " r.landmark AS landmark, r.needs AS needs, r.reason AS reason, r.blocked_reason AS blocked,"
        " r.created_at AS since ORDER BY r.priority DESC LIMIT $n",
        {"n": limit},
        readonly=True,
    )


async def team_activity(org: str) -> list[dict]:
    """Each team's open assignments and deliveries so far."""
    return await query(
        org_graph_name(org),
        "MATCH (t:Team) OPTIONAL MATCH (r:Request {status:'ASSIGNED'})-[:ASSIGNED_TO {active:true}]->(t)"
        " OPTIONAL MATCH (t)-[:MADE]->(d:Delivery)"
        " RETURN t.name AS team, count(DISTINCT r) AS active, count(DISTINCT d) AS delivered",
        readonly=True,
    )


async def save_briefing(org: str, briefing_id: str, shift: str, text: str, by: str) -> None:
    await query(
        org_graph_name(org),
        "CREATE (:Briefing {id:$id, at:$now, shift:$shift, text:$text, by:$by})",
        {"id": briefing_id, "now": now_ms(), "shift": shift, "text": text, "by": by},
    )


async def family_by(org: str, *, family_id: str | None = None, request_id: str | None = None,
                    message_id: str | None = None) -> Family | None:
    """Find a household by its own id, or by one of its requests or messages."""
    g = org_graph_name(org)
    if family_id:
        rows = await query(g, "MATCH (f:Family {id:$id}) RETURN properties(f) AS f", {"id": family_id}, readonly=True)
    elif request_id:
        rows = await query(g, "MATCH (:Request {id:$id})-[:FOR]->(f:Family) RETURN properties(f) AS f",
                           {"id": request_id}, readonly=True)
    else:
        rows = await query(g, "MATCH (:Message {id:$id})-[:BECAME]->()-[:FOR]->(f:Family) RETURN properties(f) AS f",
                           {"id": message_id}, readonly=True)
    return Family.model_validate(rows[0]["f"]) if rows else None


async def named_families(org: str) -> dict[str, str]:
    """Household id -> name, for households that have a name."""
    rows = await query(org_graph_name(org), "MATCH (f:Family) WHERE f.name <> '' RETURN f.id AS id, f.name AS name",
                       readonly=True)
    return {r["id"]: r["name"] for r in rows}


async def household_history(org: str, family_id: str) -> dict[str, list[dict]]:
    """Every recorded step for one household: its requests and messages, the
    agents that processed them, duplicate links, assignments, handoffs,
    reroutes, lessons used, lessons that cite it and deliveries."""
    g = org_graph_name(org)
    requests = await query(
        g,
        "MATCH (r:Request)-[:FOR]->(:Family {id:$id}) OPTIONAL MATCH (m:Message)-[:BECAME]->(r)"
        " RETURN r.id AS id, r.status AS status, r.created_at AS at, r.channel AS channel, r.summary AS summary,"
        " r.priority AS priority, r.team AS team, r.blocked_reason AS blocked, m.id AS mid, m.text AS text",
        {"id": family_id}, readonly=True,
    )
    ids = {"ids": [r["id"] for r in requests]}
    out = {"requests": requests}
    out["processed"] = await query(
        g,
        "MATCH (r:Request)-[p:PROCESSED_BY]->(a:Agent) WHERE r.id IN $ids"
        " RETURN r.id AS rid, a.name AS agent, p.at AS at, p.action AS action, p.to AS to, p.reason AS reason",
        ids, readonly=True,
    )
    out["duplicates"] = await query(
        g,
        "MATCH (r:Request)-[d:DUPLICATE_OF]->(c:Request) WHERE r.id IN $ids"
        " RETURN r.id AS rid, c.id AS cid, d.at AS at, d.score AS score, d.reason AS reason, d.evidence AS ev,"
        " d.decided_by AS by",
        ids, readonly=True,
    )
    out["assignments"] = await query(
        g,
        "MATCH (r:Request)-[a:ASSIGNED_TO]->(t:Team) WHERE r.id IN $ids"
        " RETURN r.id AS rid, t.name AS team, a.at AS at, a.eta_min AS eta, a.roads AS roads, a.active AS active,"
        " a.ended AS ended",
        ids, readonly=True,
    )
    out["handoffs"] = await query(
        g,
        "MATCH (a:Agent)-[h:HANDED_OFF]->(f:Agent) WHERE h.request IN $ids"
        " RETURN a.name AS src, f.name AS dst, h.at AS at, h.request AS rid, h.reason AS reason",
        ids, readonly=True,
    )
    out["reroutes"] = await query(
        g,
        "MATCH (r:Request)-[x:REROUTED]->(t:Team) WHERE r.id IN $ids"
        " RETURN r.id AS rid, x.at AS at, x.road AS road, x.reason AS reason, t.name AS team",
        ids, readonly=True,
    )
    out["lessons"] = await query(
        g,
        "MATCH (r:Request)-[u:USED_LESSON]->(l:Lesson) WHERE r.id IN $ids"
        " RETURN r.id AS rid, u.at AS at, u.by AS by, l.key AS key, l.text AS text",
        ids, readonly=True,
    )
    out["cited_by"] = await query(
        g,
        "MATCH (l:Lesson)-[:DERIVED_FROM]->(:Family {id:$id})"
        " RETURN l.key AS key, l.text AS text, l.created_at AS at, l.confidence AS confidence",
        {"id": family_id}, readonly=True,
    )
    out["deliveries"] = await query(
        g,
        "MATCH (t:Team)-[:MADE]->(d:Delivery)-[:SERVED]->(:Family {id:$id})"
        " RETURN d.id AS id, d.at AS at, d.items AS items, d.notes AS notes, t.name AS team",
        {"id": family_id}, readonly=True,
    )
    return out


# ============================================================ Field

async def request_location(org: str, request_id: str) -> tuple[float, float] | None:
    rows = await query(
        org_graph_name(org), "MATCH (r:Request {id:$id}) RETURN r.lat AS lat, r.lon AS lon",
        {"id": request_id}, readonly=True,
    )
    return (rows[0]["lat"], rows[0]["lon"]) if rows else None
