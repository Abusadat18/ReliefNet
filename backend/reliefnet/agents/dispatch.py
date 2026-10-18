"""Agent 4 - Dispatch. TRIAGED -> ASSIGNED: pick a team and a safe route."""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .. import events, geo, memory, routing
from ..domain import SPEED_M_PER_MIN, coverage
from ..models import Lesson, Request, Team
from .base import Agent

# Extra route cost (metres) for a road a lesson says is risky right now.
RISK_COST_M = 4000.0


def local_hour(tz_offset_minutes: int) -> int:
    return (datetime.now(timezone.utc) + timedelta(minutes=tz_offset_minutes)).hour


@dataclass
class Option:
    team: Team
    route: dict
    eta: float
    coverage: float
    score: float
    skills: list[Lesson]


class DispatchAgent(Agent):
    kind = "dispatch"
    label = "Request"
    in_status = "TRIAGED"
    order = "r.priority DESC, r.created_at ASC"

    async def process(self, org: str, req: Request) -> None:
        # Simulated planning time, so the lease demo can kill an agent mid-job.
        await asyncio.sleep(self.s.dispatch_work_ms / 1000)
        teams = await memory.teams_with_load(org)
        lessons = await memory.active_lessons(org, ["road_risk", "team_skill"])
        penalties, road_lessons = self.road_penalties(lessons)
        dest = await geo.nearest_junction(req.lat, req.lon)

        options = [o for t in teams if (o := await self.consider(t, req, dest, penalties, lessons))]
        if not options:
            if not teams:
                why = "no team is on duty"
            elif any(coverage(req.needs, t.supplies) > 0 for t in teams):
                why = "every route from a team that can help is flooded"
            else:
                why = f"no team carries {', '.join(req.needs) or 'what this household needs'}"
            await self.release(org, req.id, delay_ms=15_000, props={"blocked_reason": why})
            await events.publish(org, "unreachable", f"{req.id}: {why}; retrying in 15 s", id=req.id)
            return

        best = max(options, key=lambda o: o.score)
        route = best.route
        # A lesson counts as used when its road was on any candidate path: it
        # either added cost to the chosen route or pushed the route away.
        relevant = [n for n in road_lessons if n in route.get("considered", [])]
        used = list(dict.fromkeys([road_lessons[n] for n in relevant] + [s.key for s in best.skills]))
        avoided = [n for n in relevant if n not in route["roads"]]
        reason = self.explain(best, avoided)

        ok = await memory.assign_team(org, self.me, req.id, best.team.name, best.eta, route,
                                      json.dumps(route["coords"]), used, reason)
        if not self.done(ok, req.id):
            return
        await events.incr(org, "assigned")
        await events.publish(
            org, "assigned", f"{req.id} -> {best.team.name} (ETA {best.eta} min). {reason}",
            id=req.id, team=best.team.name, eta=best.eta, roads=route["roads"], coords=route["coords"],
            agent=self.name, lessons=used,
        )

    def road_penalties(self, lessons: list[Lesson]) -> tuple[dict[str, float], dict[str, str]]:
        """Extra cost per risky road right now, and which lesson said so."""
        hour = local_hour(self.s.tz_offset_minutes)
        penalties: dict[str, float] = {}
        sources: dict[str, str] = {}
        for lesson in lessons:
            starts = lesson.after_hour
            if lesson.kind == "road_risk" and (starts is None or starts < 0 or hour >= starts):
                penalties[lesson.target] = RISK_COST_M * lesson.confidence
                sources[lesson.target] = lesson.key
        return penalties, sources

    async def consider(self, team: Team, req: Request, dest: str, penalties: dict[str, float],
                       lessons: list[Lesson]) -> Option | None:
        """Score one team for this request, or None if it cannot help."""
        cov = coverage(req.needs, team.supplies)
        if cov == 0:
            return None
        route = await routing.route(team.base, dest, penalties)
        if route is None:
            return None
        eta = round(route["length_m"] / SPEED_M_PER_MIN + 4, 1)
        skills = [l for l in lessons if l.kind == "team_skill" and l.target == team.name and l.need in req.needs]
        over_capacity = max(0, team.load + 1 - team.capacity)
        score = (cov * 100 - eta * 1.2 - team.load * 6 - over_capacity * 25
                 + sum(12 * l.confidence for l in skills))
        return Option(team, route, eta, cov, score, skills)

    @staticmethod
    def explain(best: Option, avoided: list[str]) -> str:
        roads = best.route["roads"]
        parts = [
            f"{best.team.name} covers {int(best.coverage * 100)}% of needs",
            f"ETA {best.eta} min",
            f"route via {', '.join(roads[:4])}" if roads else "team base is next to the household",
        ]
        if avoided:
            parts.append("avoids " + ", ".join(avoided) + " (lesson)")
        if best.skills:
            parts.append(best.skills[0].text)
        return "; ".join(parts)
