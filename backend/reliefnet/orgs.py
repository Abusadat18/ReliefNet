"""Org registry. Each relief organisation gets its own FalkorDB graph
(`org_<slug>`); this registry only stores display metadata."""
from __future__ import annotations

import json
import re
import time

from .db import org_graph_name, redis

REGISTRY = "rn:orgs"
_cache: tuple[float, list[dict]] | None = None


def valid_slug(slug: str) -> bool:
    return bool(re.fullmatch(r"[a-z0-9_]{2,40}", slug))


def normalize_slug(raw: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", raw.lower()).strip("_")[:40]


async def register(slug: str, name: str) -> dict:
    global _cache
    if not valid_slug(slug):
        raise ValueError(f"invalid org slug: {slug!r}")
    org = {"slug": slug, "name": name, "graph": org_graph_name(slug)}
    await redis().hset(REGISTRY, slug, json.dumps(org))
    _cache = None
    return org


async def all_orgs() -> list[dict]:
    global _cache
    if _cache and time.monotonic() - _cache[0] < 5:
        return _cache[1]
    raw = await redis().hgetall(REGISTRY)
    orgs = sorted((json.loads(v) for v in raw.values()), key=lambda o: o["slug"])
    _cache = (time.monotonic(), orgs)
    return orgs


async def get(slug: str) -> dict | None:
    raw = await redis().hget(REGISTRY, slug)
    return json.loads(raw) if raw else None
