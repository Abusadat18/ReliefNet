"""Live events and counters. Events go to a capped Redis stream (so a new
dashboard can replay recent history) and to a pub/sub channel (for live push)."""
from __future__ import annotations

import json
import uuid
from typing import Any

from .db import now_ms, redis

STREAM_MAXLEN = 800
GLOBAL_ORG = "_all"


def stream_key(org: str) -> str:
    return f"rn:events:{org}"


def channel(org: str) -> str:
    return f"rn:live:{org}"


async def publish(org: str, kind: str, text: str, **data: Any) -> None:
    evt = {"org": org, "kind": kind, "text": text, "at": now_ms(), "data": data}
    payload = json.dumps(evt, default=str)
    r = redis()
    pipe = r.pipeline(transaction=False)
    pipe.xadd(stream_key(org), {"e": payload}, maxlen=STREAM_MAXLEN, approximate=True)
    pipe.publish(channel(org), payload)
    await pipe.execute()


async def recent(org: str, count: int = 120) -> list[dict]:
    rows = await redis().xrevrange(stream_key(org), count=count)
    return [json.loads(fields["e"]) for _, fields in rows]


def metrics_key(org: str) -> str:
    return f"rn:metrics:{org}"


async def incr(org: str, name: str, by: int = 1) -> None:
    r = redis()
    pipe = r.pipeline(transaction=False)
    pipe.hincrby(metrics_key(org), name, by)
    # A sorted set of timestamps gives a cheap "per minute" rate.
    ts = now_ms()
    pipe.zadd(f"rn:rate:{org}:{name}", {f"{ts}:{uuid.uuid4().hex[:8]}:{by}": ts})
    pipe.zremrangebyscore(f"rn:rate:{org}:{name}", 0, ts - 120_000)
    await pipe.execute()


async def metrics(org: str) -> dict[str, int]:
    raw = await redis().hgetall(metrics_key(org))
    return {k: int(v) for k, v in raw.items()}


async def rate_per_min(org: str, name: str, window_ms: int = 60_000) -> float:
    ts = now_ms()
    members = await redis().zrangebyscore(f"rn:rate:{org}:{name}", ts - window_ms, ts)
    total = sum(int(m.rsplit(":", 1)[1]) for m in members)
    return total * 60_000 / window_ms


async def reset_metrics(org: str) -> None:
    r = redis()
    keys = [metrics_key(org), stream_key(org)]
    async for k in r.scan_iter(match=f"rn:rate:{org}:*"):
        keys.append(k)
    if keys:
        await r.delete(*keys)
