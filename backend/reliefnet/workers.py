"""Run the agent fleet.

    python -m reliefnet.workers                       # default fleet
    python -m reliefnet.workers --dispatch 5 --intake 4

Each agent copy is an asyncio task. Copies can also run in separate
processes or machines: they share nothing except the graph."""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import socket

from . import db, embed
from .agents import AGENT_TYPES
from .agents.base import AGENTS_KEY, cmd_key
from .seed import seed_all

log = logging.getLogger("reliefnet.workers")

DEFAULT_FLEET = {"intake": 2, "dedupe": 1, "triage": 1, "dispatch": 4, "learner": 1, "coordinator": 1}


async def supervise(fleet: dict[str, int], prefix: str = "") -> None:
    tasks: dict[str, asyncio.Task] = {}
    specs: dict[str, tuple] = {}
    for kind, n in fleet.items():
        cls, label = AGENT_TYPES[kind]
        for i in range(1, n + 1):
            name = f"{prefix}{label}-{i}" if n > 1 or kind == "dispatch" else f"{prefix}{label}"
            specs[name] = (cls, name)

    def start(name: str) -> None:
        cls, nm = specs[name]
        tasks[name] = asyncio.create_task(cls(nm).run(), name=nm)

    for name in specs:
        start(name)
    log.info("fleet started: %s", ", ".join(specs))
    try:
        while True:
            await asyncio.sleep(1)
            for name in specs:
                cmd = await db.redis().get(cmd_key(name))
                task = tasks.get(name)
                if cmd == "revive" and (task is None or task.done()):
                    await db.redis().delete(cmd_key(name))
                    log.info("reviving %s", name)
                    start(name)
                elif task is not None and task.done() and cmd != "kill":
                    exc = task.exception()
                    log.error("%s exited (%s); restarting", name, exc)
                    start(name)
    finally:
        for t in tasks.values():
            t.cancel()
        await db.redis().hdel(AGENTS_KEY, *specs.keys())


async def main() -> None:
    ap = argparse.ArgumentParser()
    for kind, n in DEFAULT_FLEET.items():
        ap.add_argument(f"--{kind}", type=int, default=n)
    ap.add_argument("--prefix", default=os.environ.get("AGENT_PREFIX", ""),
                    help="name prefix when running several worker processes")
    ap.add_argument("--no-seed", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if not args.no_seed:
        await seed_all()
    fleet = {k: getattr(args, k) for k in DEFAULT_FLEET if getattr(args, k) > 0}
    log.info("worker host %s, embeddings: %s", socket.gethostname(), await embed.warmup())
    try:
        await supervise(fleet, args.prefix)
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
