"""Agent runtime shared by every pipeline stage.

An agent never calls another agent. It claims one item in its input status
with a lease, does its job, and writes the result plus a PROCESSED_BY edge in
one guarded query that only succeeds while it still holds the lease. If the
agent dies, the lease runs out and another copy reclaims the item."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from .. import events, orgs
from ..config import get_settings
from ..db import now_ms, org_graph_name, query, redis

log = logging.getLogger(__name__)

AGENTS_KEY = "rn:agents"


def cmd_key(name: str) -> str:
    return f"rn:agent:cmd:{name}"


class AgentKilled(Exception):
    pass


class LeaseLost(Exception):
    pass


class Agent:
    kind = "agent"
    label = "Request"
    in_status = "NEW"
    order = "r.created_at ASC"

    def __init__(self, name: str):
        self.name = name
        self.s = get_settings()
        self.processed = 0
        self.job: str | None = None
        self.job_org: str | None = None
        self.state = "idle"
        self._last_beat = 0.0

    # ---- heartbeat & control -------------------------------------------------
    async def beat(self, force: bool = False) -> None:
        if not force and time.monotonic() - self._last_beat < 1.0:
            return
        self._last_beat = time.monotonic()
        await redis().hset(
            AGENTS_KEY,
            self.name,
            json.dumps(
                {
                    "name": self.name,
                    "kind": self.kind,
                    "state": self.state,
                    "job": self.job,
                    "org": self.job_org,
                    "processed": self.processed,
                    "last_seen": now_ms(),
                }
            ),
        )

    async def killed(self) -> bool:
        return (await redis().get(cmd_key(self.name))) == "kill"

    # ---- claim / renew / finish ---------------------------------------------
    async def claim(self, org: str) -> dict | None:
        now = now_ms()
        rows = await query(
            org_graph_name(org),
            f"MATCH (r:{self.label} {{status:$status}})"
            " WHERE (r.claimed_by IS NULL OR r.lease_until < $now) AND coalesce(r.not_before, 0) <= $now"
            f" WITH r ORDER BY {self.order} LIMIT 1"
            " WITH r, r.claimed_by AS prev"
            " SET r.claimed_by = $me, r.lease_until = $now + $lease, r.attempts = coalesce(r.attempts, 0) + 1"
            " RETURN properties(r) AS item, prev",
            {"status": self.in_status, "now": now, "me": self.name, "lease": self.s.lease_ms},
        )
        if not rows:
            return None
        item, prev = rows[0]["item"], rows[0]["prev"]
        item.pop("embedding", None)
        if prev and prev != self.name:
            await events.incr(org, "reclaimed")
            await query(
                org_graph_name(org),
                f"MATCH (r:{self.label} {{id:$id}}) MERGE (a:Agent {{name:$me}}) ON CREATE SET a.kind=$kind"
                " CREATE (r)-[:PROCESSED_BY {at:$now, action:'reclaimed', reason:$reason}]->(a)",
                {"id": item["id"], "me": self.name, "kind": self.kind, "now": now,
                 "reason": f"lease held by {prev} expired"},
            )
            await events.publish(
                org, "reclaimed", f"{self.name} reclaimed {item['id']} after {prev}'s lease expired",
                id=item["id"], agent=self.name, previous=prev,
            )
        return item

    async def renew(self, org: str, item_id: str) -> bool:
        rows = await query(
            org_graph_name(org),
            f"MATCH (r:{self.label} {{id:$id}}) WHERE r.claimed_by = $me SET r.lease_until = $until RETURN count(r) AS n",
            {"id": item_id, "me": self.name, "until": now_ms() + self.s.lease_ms},
        )
        return bool(rows and rows[0]["n"])

    async def finish(
        self,
        org: str,
        item_id: str,
        next_status: str,
        props: dict[str, Any],
        reason: str,
        extra_cypher: str = "",
        extra_params: dict | None = None,
    ) -> bool:
        """Write the result only if this agent still holds the lease."""
        params = {
            "id": item_id,
            "me": self.name,
            "kind": self.kind,
            "props": props,
            "next": next_status,
            "now": now_ms(),
            "reason": reason,
            "from": self.in_status,
            **(extra_params or {}),
        }
        rows = await query(
            org_graph_name(org),
            f"MATCH (r:{self.label} {{id:$id}}) WHERE r.claimed_by = $me"
            " SET r += $props, r.status = $next, r.claimed_by = NULL, r.lease_until = NULL, r.updated_at = $now"
            " WITH r MERGE (a:Agent {name:$me}) ON CREATE SET a.kind = $kind"
            " CREATE (r)-[:PROCESSED_BY {at:$now, action:$kind, from:$from, to:$next, reason:$reason}]->(a)"
            f" {extra_cypher}"
            " RETURN r.id AS id",
            params,
        )
        if not rows:
            log.warning("%s lost the lease on %s; result discarded", self.name, item_id)
            return False
        self.processed += 1
        return True

    async def release(self, org: str, item_id: str, delay_ms: int = 0, props: dict | None = None) -> None:
        await query(
            org_graph_name(org),
            f"MATCH (r:{self.label} {{id:$id}}) WHERE r.claimed_by = $me"
            " SET r += $props, r.claimed_by = NULL, r.lease_until = NULL, r.not_before = $nb",
            {"id": item_id, "me": self.name, "nb": now_ms() + delay_ms, "props": props or {}},
        )

    # ---- main loop ----------------------------------------------------------
    async def process(self, org: str, item: dict) -> None:
        raise NotImplementedError

    async def _work(self, org: str, item: dict) -> None:
        self.job, self.job_org, self.state = item["id"], org, "working"
        await self.beat(force=True)
        task = asyncio.create_task(self.process(org, item))
        renew_every = self.s.lease_ms / 3000
        last_renew = time.monotonic()
        try:
            while not task.done():
                # Poll often so a kill lands mid-job, like a real crash.
                done, _ = await asyncio.wait({task}, timeout=0.25)
                if done:
                    break
                if await self.killed():
                    task.cancel()
                    raise AgentKilled()
                if time.monotonic() - last_renew >= renew_every:
                    if not await self.renew(org, item["id"]):
                        task.cancel()
                        raise LeaseLost()
                    last_renew = time.monotonic()
                await self.beat()
            task.result()
        except (AgentKilled, LeaseLost):
            raise
        except Exception:
            log.exception("%s failed on %s", self.name, item.get("id"))
            # Back off and let any copy retry; the item is not lost.
            await self.release(org, item["id"], delay_ms=5000)
        finally:
            self.job, self.job_org, self.state = None, None, "idle"
            if not (await self.killed()):
                await self.beat(force=True)

    async def run(self) -> None:
        log.info("%s started", self.name)
        await redis().delete(cmd_key(self.name))
        await self.beat(force=True)
        try:
            while True:
                if await self.killed():
                    raise AgentKilled()
                worked = False
                for org in await orgs.all_orgs():
                    item = await self.claim(org["slug"])
                    if item:
                        worked = True
                        try:
                            await self._work(org["slug"], item)
                        except LeaseLost:
                            log.warning("%s lost lease on %s", self.name, item["id"])
                await self.beat()
                if not worked:
                    await asyncio.sleep(self.s.poll_interval_s)
        except AgentKilled:
            # Simulated crash: stop without releasing the lease.
            self.state = "dead"
            await self.beat(force=True)
            for org in await orgs.all_orgs():
                await events.publish(org["slug"], "agent_down", f"{self.name} crashed", agent=self.name)
            log.warning("%s killed", self.name)


class PeriodicAgent:
    """Runs a job per org on a timer. A Redis lock keeps one copy per org at a time."""

    kind = "periodic"
    interval_s = 30.0

    def __init__(self, name: str):
        self.name = name
        self.s = get_settings()
        self.processed = 0

    async def beat(self, state: str = "idle", org: str | None = None) -> None:
        await redis().hset(
            AGENTS_KEY,
            self.name,
            json.dumps({"name": self.name, "kind": self.kind, "state": state, "job": None, "org": org,
                        "processed": self.processed, "last_seen": now_ms()}),
        )

    async def tick(self, org: str) -> None:
        raise NotImplementedError

    async def run(self) -> None:
        log.info("%s started", self.name)
        while True:
            for org in await orgs.all_orgs():
                slug = org["slug"]
                lock = f"rn:lock:{self.kind}:{slug}"
                if await redis().set(lock, self.name, nx=True, px=int(self.interval_s * 1000 * 0.9)):
                    await self.beat("working", slug)
                    try:
                        await self.tick(slug)
                        self.processed += 1
                    except Exception:
                        log.exception("%s tick failed for %s", self.name, slug)
            for _ in range(int(self.interval_s)):
                await self.beat()
                await asyncio.sleep(1)
