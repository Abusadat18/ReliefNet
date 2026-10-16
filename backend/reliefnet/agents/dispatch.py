"""Agent 4 - Dispatch. TRIAGED -> ASSIGNED: pick a team and a safe route."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

from .. import events, geo, routing
from ..db import now_ms, org_graph_name, query
from ..domain import SPEED_M_PER_MIN, coverage
from .base import Agent


# Extra route cost (metres) for a road a lesson says is risky right now.
RISK_COST_M = 4000.0


def local_hour(tz_offset_minutes: int) -> int:
    return (datetime.now(timezone.utc) + timedelta(minutes=tz_offset_minutes)).hour


class DispatchAgent(Agent):
    kind = "dispatch"
    label = "Request"
    in_status = "TRIAGED"
    order = "r.priority DESC, r.created_at ASC"

    async def lessons(self, org: str) -> list[dict]:
        return await query(
            org_graph_name(org),
            "MATCH (l:Lesson) WHERE l.kind IN ['road_risk', 'team_skill'] AND l.confidence >= 0.5"
            " RETURN l.key AS key, l.kind AS kind, l.text AS text, l.target AS target, l.need AS need,"
            " l.after_hour AS after_hour, l.confidence AS confidence",
            readonly=True,
        )

    async def process(self, org: str, req: dict) -> None:
        g = org_graph_name(org)
        # Simulated planning time, so the lease demo can kill an agent mid-job.
        await asyncio.sleep(self.s.dispatch_work_ms / 1000)
        teams = await query(
            g,
            "MATCH (t:Team {status:'active'})"
            " OPTIONAL MATCH (x:Request {status:'ASSIGNED'})-[a:ASSIGNED_TO {active:true}]->(t)"
            " RETURN t.name AS name, t.supplies AS supplies, t.base_junction AS base, t.capacity AS capacity,"
            " count(x) AS load",
            readonly=True,
        )
        lessons = await self.lessons(org)
        hour = local_hour(self.s.tz_offset_minutes)
        penalties: dict[str, float] = {}
        road_lessons: dict[str, str] = {}
        for l in lessons:
            if l["kind"] == "road_risk" and (l.get("after_hour") is None or l["after_hour"] < 0 or hour >= l["after_hour"]):
                penalties[l["target"]] = RISK_COST_M * l["confidence"]
                road_lessons[l["target"]] = l["key"]
        dest = await geo.nearest_junction(req["lat"], req["lon"])

        options = []
        for t in teams:
            cov = coverage(req.get("needs", []), t["supplies"])
            if cov == 0:
                continue
            r = await routing.route(t["base"], dest, penalties)
            if r is None:
                continue
            eta = round(r["length_m"] / SPEED_M_PER_MIN + 4, 1)
            skill = [
                l for l in lessons
                if l["kind"] == "team_skill" and l["target"] == t["name"] and l.get("need") in req.get("needs", [])
            ]
            over = max(0, t["load"] + 1 - t["capacity"])
            s = cov * 100 - eta * 1.2 - t["load"] * 6 - over * 25 + sum(12 * l["confidence"] for l in skill)
            options.append({"team": t, "route": r, "eta": eta, "coverage": cov, "score": s, "skill": skill})

        if not options:
            await self.release(
                org, req["id"], delay_ms=15_000,
                props={"blocked_reason": "no team can reach this household; all routes flooded or no supplies"},
            )
            await events.publish(
                org, "unreachable", f"{req['id']}: no reachable team right now, retrying in 15 s", id=req["id"]
            )
            return

        best = max(options, key=lambda o: o["score"])
        team, r = best["team"], best["route"]
        # A lesson counts as used when its road was on any candidate path: it
        # either added cost to the chosen route or pushed the route away.
        relevant = [n for n in road_lessons if n in r.get("considered", [])]
        used = list(dict.fromkeys([road_lessons[n] for n in relevant] + [l["key"] for l in best["skill"]]))
        avoided = [n for n in relevant if n not in r["roads"]]
        why_parts = [
            f"{team['name']} covers {int(best['coverage'] * 100)}% of needs",
            f"ETA {best['eta']} min",
            f"route via {', '.join(r['roads'][:4])}" if r["roads"] else "team base is next to the household",
        ]
        if avoided:
            why_parts.append("avoids " + ", ".join(avoided) + " (lesson)")
        if best["skill"]:
            why_parts.append(best["skill"][0]["text"])
        why = "; ".join(why_parts)
        ok = await self.finish(
            org, req["id"], "ASSIGNED",
            {"team": team["name"], "assigned_at": now_ms(), "eta_min": best["eta"], "route_roads": r["roads"],
             "route": json.dumps(r["coords"]), "route_length_m": r["length_m"], "blocked_reason": ""},
            why,
            extra_cypher=(
                " WITH r, a"
                " OPTIONAL MATCH (r)-[old:ASSIGNED_TO {active:true}]->()"
                " WITH r, a, count(old) AS existing WHERE existing = 0"
                " MATCH (t:Team {name:$team}) MATCH (r)-[:FOR]->(f:Family)"
                " CREATE (r)-[:ASSIGNED_TO {active:true, at:$now, eta_min:$eta, roads:$roads, by:$me}]->(t)"
                " SET f.status = 'ASSIGNED'"
                " MERGE (fa:Agent {name:'Field-' + $team}) ON CREATE SET fa.kind = 'field'"
                " CREATE (a)-[:HANDED_OFF {request:r.id, at:$now, reason:$why}]->(fa)"
                " WITH r OPTIONAL MATCH (l:Lesson) WHERE l.key IN $used"
                " FOREACH (_ IN CASE WHEN l IS NULL THEN [] ELSE [1] END |"
                "   CREATE (r)-[:USED_LESSON {at:$now, by:$me}]->(l))"
                " WITH DISTINCT r"
            ),
            extra_params={"team": team["name"], "eta": best["eta"], "roads": r["roads"], "used": used, "why": why},
        )
        if not ok:
            return
        await events.incr(org, "assigned")
        await events.publish(
            org, "assigned", f"{req['id']} -> {team['name']} (ETA {best['eta']} min). {why}",
            id=req["id"], team=team["name"], eta=best["eta"], roads=r["roads"], coords=r["coords"], agent=self.name,
            lessons=used,
        )
