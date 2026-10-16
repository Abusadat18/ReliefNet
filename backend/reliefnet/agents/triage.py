"""Agent 3 - Triage. RESOLVED -> TRIAGED with an explainable priority score."""
from __future__ import annotations

import json
import time

from redis.exceptions import ResponseError

from .. import events
from ..db import now_ms, org_graph_name, query
from .base import Agent

_clusters: dict[str, tuple[float, dict]] = {}


async def clusters(org: str, max_age_s: float = 8.0) -> dict:
    """Community detection over households that live near each other.

    Returns family id -> {cid, unserved, oldest_wait_h}."""
    hit = _clusters.get(org)
    if hit and time.monotonic() - hit[0] < max_age_s:
        return hit[1]
    try:
        rows = await query(
            org_graph_name(org),
            "CALL algo.labelPropagation({nodeLabels:['Family'], relationshipTypes:['NEAR']})"
            " YIELD node, communityId"
            " RETURN node.id AS id, node.status AS status, node.first_seen AS first_seen, node.ward AS ward,"
            " communityId AS cid",
            readonly=True,
        )
    except ResponseError as e:
        # Before the first NEAR edge exists the relationship type is unknown.
        if "unknown relationship-type" not in str(e):
            raise
        rows = []
    now = now_ms()
    groups: dict[int, list[dict]] = {}
    for r in rows:
        groups.setdefault(r["cid"], []).append(r)
    out: dict[str, dict] = {}
    for cid, members in groups.items():
        unserved = [m for m in members if m["status"] != "SERVED"]
        oldest = max(((now - (m["first_seen"] or now)) / 3_600_000 for m in unserved), default=0.0)
        info = {"cid": cid, "size": len(members), "unserved": len(unserved), "oldest_wait_h": round(oldest, 1),
                "members": [m["id"] for m in members]}
        for m in members:
            out[m["id"]] = info
    _clusters[org] = (time.monotonic(), out)
    return out


def cluster_bonus(info: dict | None) -> int:
    if not info or info["unserved"] < 3:
        return 0
    return min(17, 3 + info["unserved"] + int(info["oldest_wait_h"] * 1.5))


def score(req: dict, family: dict, cluster: dict | None, area_lessons: list[dict]) -> tuple[int, list[str], int]:
    parts: list[tuple[int, str]] = []
    if req.get("medical") or "medicine" in req.get("needs", []):
        parts.append((30, f"medical need ({req.get('medical') or 'medicine'})"))
    if req.get("elderly"):
        parts.append((20, f"{req['elderly']} elderly"))
    if req.get("pregnant_or_disabled"):
        parts.append((20, "pregnant or disabled person"))
    if req.get("children"):
        parts.append((min(15, 8 + 3 * req["children"]), f"{req['children']} children"))
    if req.get("water_entering"):
        parts.append((20, "water entering house"))
    elif req.get("trapped"):
        parts.append((15, "trapped"))
    if req.get("urgency") == "critical":
        parts.append((25, "critical urgency"))
    people = req.get("people") or 1
    if people >= 4:
        parts.append((min(8, people), f"{people} people"))
    wait_h = (now_ms() - (family.get("first_seen") or now_ms())) / 3_600_000
    if wait_h >= 1:
        parts.append((min(20, int(wait_h * 3)), f"waiting {wait_h:.1f} h"))
    bonus = cluster_bonus(cluster)
    if bonus:
        parts.append((bonus, f"unserved cluster ({cluster['unserved']} households, oldest {cluster['oldest_wait_h']} h)"))
    for l in area_lessons:
        if l.get("target") == f"ward {req.get('ward')}":
            pts = int(round(10 * l["confidence"]))
            parts.append((pts, f"lesson: {l['text']}"))
    if req.get("geo_confidence") in ("low", "none"):
        parts.append((3, "location unclear, needs a call back"))
    total = min(100, sum(p for p, _ in parts))
    return total, [f"+{p} {why}" for p, why in parts], bonus


class TriageAgent(Agent):
    kind = "triage"
    label = "Request"
    in_status = "RESOLVED"
    order = "r.created_at ASC"

    async def process(self, org: str, req: dict) -> None:
        g = org_graph_name(org)
        fam = await query(
            g, "MATCH (r:Request {id:$id})-[:FOR]->(f:Family) RETURN properties(f) AS f LIMIT 1", {"id": req["id"]},
            readonly=True,
        )
        family = fam[0]["f"] if fam else {}
        cl = (await clusters(org)).get(family.get("id", ""))
        lessons = await query(
            g,
            "MATCH (l:Lesson {kind:'area_risk'}) WHERE l.confidence >= 0.5"
            " RETURN l.key AS key, l.text AS text, l.target AS target, l.confidence AS confidence",
            readonly=True,
        )
        total, reasons, bonus = score(req, family, cl, lessons)
        used = [l["key"] for l in lessons if l.get("target") == f"ward {req.get('ward')}"]
        ok = await self.finish(
            org, req["id"], "TRIAGED",
            {"priority": total, "reason": "; ".join(reasons), "cluster_bonus": bonus,
             "cluster_id": cl["cid"] if cl else -1},
            f"priority {total}: " + "; ".join(reasons),
            extra_cypher=(
                " WITH r, a OPTIONAL MATCH (l:Lesson) WHERE l.key IN $used"
                " FOREACH (_ IN CASE WHEN l IS NULL THEN [] ELSE [1] END |"
                "   CREATE (r)-[:USED_LESSON {at:$now, by:$me}]->(l))"
                " WITH DISTINCT r"
            ),
            extra_params={"used": used},
        )
        if not ok:
            return
        if cl and bonus:
            # The whole cluster moves up the queue, not just this request.
            await query(
                g,
                "MATCH (r:Request {status:'TRIAGED'})-[:FOR]->(f:Family) WHERE f.id IN $members AND r.id <> $id"
                "   AND coalesce(r.cluster_bonus, 0) < $bonus"
                " SET r.priority = CASE WHEN r.priority - coalesce(r.cluster_bonus, 0) + $bonus > 100 THEN 100"
                "   ELSE r.priority - coalesce(r.cluster_bonus, 0) + $bonus END, r.cluster_bonus = $bonus",
                {"members": cl["members"], "id": req["id"], "bonus": bonus},
            )
        await events.incr(org, "triaged")
        await events.publish(
            org, "triaged", f"{req['id']} priority {total}" + (f" (cluster +{bonus})" if bonus else ""),
            id=req["id"], priority=total, reasons=reasons, breakdown=json.dumps(reasons),
        )
