"""Agent 3 - Triage. RESOLVED -> TRIAGED with an explainable priority score."""
from __future__ import annotations

import json
import time

from .. import events, memory
from ..db import now_ms
from ..models import Family, Lesson, Request
from .base import Agent

_clusters: dict[str, tuple[float, dict]] = {}


async def clusters(org: str, max_age_s: float = 8.0) -> dict[str, dict]:
    """Group households that live near each other (community detection).

    Returns family id -> {cid, size, unserved, oldest_wait_h, members}."""
    hit = _clusters.get(org)
    if hit and time.monotonic() - hit[0] < max_age_s:
        return hit[1]
    now = now_ms()
    groups: dict[int, list[dict]] = {}
    for r in await memory.household_communities(org):
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


def score(req: Request, family: Family | None, cluster: dict | None,
          area_lessons: list[Lesson]) -> tuple[int, list[str], int]:
    """Priority 0-100, the reasons behind it, and the cluster bonus part."""
    parts: list[tuple[int, str]] = []
    if req.medical or "medicine" in req.needs:
        parts.append((30, f"medical need ({req.medical or 'medicine'})"))
    if req.elderly:
        parts.append((20, f"{req.elderly} elderly"))
    if req.pregnant_or_disabled:
        parts.append((20, "pregnant or disabled person"))
    if req.children:
        parts.append((min(15, 8 + 3 * req.children), f"{req.children} children"))
    if req.water_entering:
        parts.append((20, "water entering house"))
    elif req.trapped:
        parts.append((15, "trapped"))
    if req.urgency == "critical":
        parts.append((25, "critical urgency"))
    if req.people >= 4:
        parts.append((min(8, req.people), f"{req.people} people"))
    first_seen = (family.first_seen if family else None) or now_ms()
    wait_h = (now_ms() - first_seen) / 3_600_000
    if wait_h >= 1:
        parts.append((min(20, int(wait_h * 3)), f"waiting {wait_h:.1f} h"))
    bonus = cluster_bonus(cluster)
    if bonus:
        parts.append((bonus, f"unserved cluster ({cluster['unserved']} households, oldest {cluster['oldest_wait_h']} h)"))
    for lesson in area_lessons:
        if lesson.target == f"ward {req.ward}":
            parts.append((int(round(10 * lesson.confidence)), f"lesson: {lesson.text}"))
    if req.geo_confidence in ("low", "none"):
        parts.append((3, "location unclear, needs a call back"))
    total = min(100, sum(p for p, _ in parts))
    return total, [f"+{p} {why}" for p, why in parts], bonus


class TriageAgent(Agent):
    kind = "triage"
    label = "Request"
    in_status = "RESOLVED"
    order = "r.created_at ASC"

    async def process(self, org: str, req: Request) -> None:
        family = await memory.household_of(org, req.id)
        cluster = (await clusters(org)).get(family.id) if family else None
        lessons = await memory.active_lessons(org, ["area_risk"])

        total, reasons, bonus = score(req, family, cluster, lessons)
        used = [lesson.key for lesson in lessons if lesson.target == f"ward {req.ward}"]
        ok = await memory.save_priority(org, self.me, req.id, total, reasons, bonus,
                                        cluster["cid"] if cluster else -1, used)
        if not self.done(ok, req.id):
            return
        if cluster and bonus:
            # The whole cluster moves up the queue, not just this request.
            await memory.lift_cluster(org, cluster["members"], req.id, bonus)
        await events.incr(org, "triaged")
        await events.publish(
            org, "triaged", f"{req.id} priority {total}" + (f" (cluster +{bonus})" if bonus else ""),
            id=req.id, priority=total, reasons=reasons, breakdown=json.dumps(reasons),
        )
