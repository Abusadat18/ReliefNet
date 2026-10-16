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

from pydantic import BaseModel

from .. import events, memory, orgs
from ..config import get_settings
from ..db import now_ms, redis
from ..models import Request

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
    model: type[BaseModel] = Request
    in_status = "NEW"
    order = "r.created_at ASC"

    def __init__(self, name: str):
        self.name = name
        self.s = get_settings()
        self.me = memory.Worker(name=name, kind=self.kind, label=self.label, status=self.in_status)
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

    # ---- claim / renew / release --------------------------------------------
    async def claim(self, org: str) -> Any | None:
        props, previous = await memory.claim_next(org, self.me, self.order, self.s.lease_ms)
        if props is None:
            return None
        item = self.model.model_validate(props)
        if previous and previous != self.name:
            await events.incr(org, "reclaimed")
            await memory.note_reclaim(org, self.me, item.id, previous)
            await events.publish(
                org, "reclaimed", f"{self.name} reclaimed {item.id} after {previous}'s lease expired",
                id=item.id, agent=self.name, previous=previous,
            )
        return item

    async def release(self, org: str, item_id: str, delay_ms: int = 0, props: dict | None = None) -> None:
        await memory.release(org, self.me, item_id, delay_ms, props)

    def done(self, ok: bool, item_id: str) -> bool:
        """Count a finished step, or log that the lease was lost before writing."""
        if ok:
            self.processed += 1
        else:
            log.warning("%s lost the lease on %s; result discarded", self.name, item_id)
        return ok

    # ---- main loop ----------------------------------------------------------
    async def process(self, org: str, item: Any) -> None:
        raise NotImplementedError

    async def _work(self, org: str, item: Any) -> None:
        self.job, self.job_org, self.state = item.id, org, "working"
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
                    if not await memory.renew_lease(org, self.me, item.id, self.s.lease_ms):
                        task.cancel()
                        raise LeaseLost()
                    last_renew = time.monotonic()
                await self.beat()
            task.result()
        except (AgentKilled, LeaseLost):
            raise
        except Exception:
            log.exception("%s failed on %s", self.name, item.id)
            # Back off and let any copy retry; the item is not lost.
            await self.release(org, item.id, delay_ms=5000)
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
                            log.warning("%s lost lease on %s", self.name, item.id)
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
