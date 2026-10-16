"""FalkorDB access. One FalkorDB instance holds every org graph, the shared
region graph, and the plain Redis keys (streams, pub/sub, counters)."""
from __future__ import annotations

import time
from typing import Any

from falkordb.asyncio import FalkorDB
from falkordb.edge import Edge
from falkordb.node import Node
from falkordb.path import Path
from redis.asyncio import BlockingConnectionPool, Redis

from .config import get_settings

REGION_GRAPH = "region"
ORG_PREFIX = "org_"

_pool: BlockingConnectionPool | None = None
_db: FalkorDB | None = None
_redis: Redis | None = None


def _make_pool() -> BlockingConnectionPool:
    s = get_settings()
    return BlockingConnectionPool(
        host=s.falkor_host,
        port=s.falkor_port,
        password=s.falkor_password,
        max_connections=64,
        timeout=None,
        decode_responses=True,
    )


def falkor() -> FalkorDB:
    global _pool, _db
    if _db is None:
        _pool = _make_pool()
        _db = FalkorDB(connection_pool=_pool)
    return _db


def redis() -> Redis:
    global _redis
    if _redis is None:
        s = get_settings()
        _redis = Redis(host=s.falkor_host, port=s.falkor_port, password=s.falkor_password, decode_responses=True)
    return _redis


async def close() -> None:
    global _pool, _db, _redis
    if _pool is not None:
        await _pool.aclose()
    if _redis is not None:
        await _redis.aclose()
    _pool = _db = _redis = None


def org_graph_name(slug: str) -> str:
    return f"{ORG_PREFIX}{slug}"


def now_ms() -> int:
    return int(time.time() * 1000)


def _plain(v: Any) -> Any:
    if isinstance(v, Node):
        return dict(v.properties)
    if isinstance(v, Edge):
        d = dict(v.properties)
        d["_type"] = v.relation
        return d
    if isinstance(v, Path):
        return {"nodes": [_plain(n) for n in v.nodes()], "edges": [_plain(e) for e in v.edges()]}
    if isinstance(v, list):
        return [_plain(x) for x in v]
    if isinstance(v, dict):
        return {k: _plain(x) for k, x in v.items()}
    return v


async def query(graph: str, cypher: str, params: dict | None = None, *, readonly: bool = False) -> list[dict]:
    g = falkor().select_graph(graph)
    res = await (g.ro_query if readonly else g.query)(cypher, params or {})
    cols = [h[1] for h in (res.header or [])]
    return [{c: _plain(v) for c, v in zip(cols, row)} for row in (res.result_set or [])]


async def one(graph: str, cypher: str, params: dict | None = None, *, readonly: bool = False) -> dict | None:
    rows = await query(graph, cypher, params, readonly=readonly)
    return rows[0] if rows else None


async def scalar(graph: str, cypher: str, params: dict | None = None, default: Any = None) -> Any:
    row = await one(graph, cypher, params, readonly=True)
    if not row:
        return default
    return next(iter(row.values()))


async def list_graphs() -> list[str]:
    return await falkor().list_graphs()
