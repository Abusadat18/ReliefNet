"""Road network state and routing on the shared region graph.

Road status is shared by every org: a flooded bridge is flooded for everyone.
Edge `cost` carries that shared state; per-org lessons are applied on top when
ranking candidate paths, so one org's lessons never change another's routes."""
from __future__ import annotations

import heapq
import time

from rapidfuzz import fuzz, process

from .db import REGION_GRAPH, now_ms, query

FLOOD_COST = 1_000_000.0
REPORTED_FACTOR = 4.0

_names_cache: tuple[float, list[str]] | None = None


def cost_for(status: str, length_m: float) -> float:
    if status == "flooded":
        return length_m + FLOOD_COST
    if status == "reported":
        return length_m * REPORTED_FACTOR
    return length_m


async def road_names() -> list[str]:
    global _names_cache
    if _names_cache and time.monotonic() - _names_cache[0] < 30:
        return _names_cache[1]
    rows = await query(REGION_GRAPH, "MATCH ()-[r:ROAD]->() RETURN DISTINCT r.name AS n", readonly=True)
    names = sorted(r["n"] for r in rows)
    _names_cache = (time.monotonic(), names)
    return names


async def match_road(text: str) -> str | None:
    if not text:
        return None
    names = await road_names()
    t = text.lower().replace("nh12", "nh-12").replace(" pul", " bridge")
    exact = [n for n in names if n.lower() in t]
    if exact:
        return max(exact, key=len)
    best = process.extractOne(t, {n: n.lower() for n in names}, scorer=fuzz.WRatio, score_cutoff=80)
    return best[2] if best else None


async def set_road_status(name: str, status: str) -> int:
    rows = await query(
        REGION_GRAPH,
        "MATCH ()-[r:ROAD {name:$name}]->()"
        " SET r.status = $status, r.updated_at = $now,"
        " r.cost = CASE $status WHEN 'flooded' THEN r.length_m + $flood"
        "   WHEN 'reported' THEN r.length_m * $rep ELSE r.length_m END"
        " RETURN count(r) AS n",
        {"name": name, "status": status, "now": now_ms(), "flood": FLOOD_COST, "rep": REPORTED_FACTOR},
    )
    return rows[0]["n"] if rows else 0


async def road_state(name: str) -> str | None:
    rows = await query(
        REGION_GRAPH, "MATCH ()-[r:ROAD {name:$n}]->() RETURN r.status AS s LIMIT 1", {"n": name}, readonly=True
    )
    return rows[0]["s"] if rows else None


async def route(src: str, dst: str, penalties: dict[str, float] | None = None, k: int = 4) -> dict | None:
    """Best route from junction `src` to `dst`, or None if every path is flooded.

    `penalties` maps road name -> extra cost in metres from lessons. It is added once
    per road: it models the risk of getting stuck there, not extra distance."""
    if src == dst:
        rows = await query(
            REGION_GRAPH, "MATCH (j:Junction {id:$id}) RETURN j.lat AS lat, j.lon AS lon", {"id": src}, readonly=True
        )
        return {"weight": 0.0, "length_m": 0.0, "roads": [], "coords": [[rows[0]["lat"], rows[0]["lon"]]],
                "lessons_applied": []}
    rows = await query(
        REGION_GRAPH,
        "MATCH (a:Junction {id:$src}), (b:Junction {id:$dst})"
        " CALL algo.SPpaths({sourceNode:a, targetNode:b, relTypes:['ROAD'], weightProp:'cost', pathCount:$k})"
        " YIELD path, pathWeight"
        " RETURN pathWeight AS weight,"
        " [n IN nodes(path) | [n.lat, n.lon]] AS coords,"
        " [r IN relationships(path) | r.name] AS names,"
        " [r IN relationships(path) | r.length_m] AS lens",
        {"src": src, "dst": dst, "k": k + 3 if penalties else k},
        readonly=True,
    )
    if not rows:
        return None
    penalties = penalties or {}
    if penalties and any(n in penalties for r in rows for n in r["names"]):
        # k-shortest paths tend to be near-copies of each other, so a detour
        # around a risky road may not be among them. Find it exactly.
        detour = await _dijkstra(src, dst, penalties)
        if detour:
            rows.append(detour)
    considered = sorted({n for r in rows for n in r["names"]})
    best = None
    for r in rows:
        applied = sorted({n for n in r["names"] if n in penalties})
        extra = sum(penalties[n] for n in applied)
        score = r["weight"] + extra
        cand = {
            "weight": score,
            "length_m": round(sum(r["lens"]), 1),
            "roads": list(dict.fromkeys(r["names"])),
            "coords": r["coords"],
            "lessons_applied": applied,
            "flooded": r["weight"] >= FLOOD_COST,
        }
        if best is None or cand["weight"] < best["weight"]:
            best = cand
    if best["flooded"]:
        return None
    best["considered"] = considered
    return best


async def _dijkstra(src: str, dst: str, penalties: dict[str, float]) -> dict | None:
    """Exact shortest path on the live road graph with per-road penalties added on entry."""
    edges = await query(
        REGION_GRAPH,
        "MATCH (a:Junction)-[r:ROAD]->(b:Junction)"
        " RETURN a.id AS a, b.id AS b, r.name AS name, r.cost AS cost, r.length_m AS len,"
        " [a.lat, a.lon] AS pa, [b.lat, b.lon] AS pb",
        readonly=True,
    )
    adj: dict[str, list[dict]] = {}
    pos: dict[str, list[float]] = {}
    for e in edges:
        adj.setdefault(e["a"], []).append(e)
        pos[e["a"]], pos[e["b"]] = e["pa"], e["pb"]
    dist = {src: 0.0}
    prev: dict[str, dict] = {}
    heap = [(0.0, src)]
    while heap:
        d, u = heapq.heappop(heap)
        if u == dst:
            break
        if d > dist.get(u, float("inf")):
            continue
        for e in adj.get(u, []):
            # Charge a road's penalty once, when the path first enters it.
            entering = u not in prev or prev[u]["name"] != e["name"]
            nd = d + e["cost"] + (penalties.get(e["name"], 0.0) if entering else 0.0)
            if nd < dist.get(e["b"], float("inf")):
                dist[e["b"]], prev[e["b"]] = nd, e
                heapq.heappush(heap, (nd, e["b"]))
    if dst not in prev:
        return None
    path: list[dict] = []
    node = dst
    while node != src:
        e = prev[node]
        path.append(e)
        node = e["a"]
    path.reverse()
    return {
        "weight": sum(e["cost"] for e in path),
        "coords": [pos[src]] + [pos[e["b"]] for e in path],
        "names": [e["name"] for e in path],
        "lens": [e["len"] for e in path],
    }


async def snapshot() -> list[dict]:
    return await query(
        REGION_GRAPH,
        "MATCH (a:Junction)-[r:ROAD]->(b:Junction) WHERE a.id < b.id"
        " RETURN r.id AS id, r.name AS name, r.kind AS kind, r.status AS status, r.low_lying AS low_lying,"
        " [[a.lat, a.lon], [b.lat, b.lon]] AS coords",
        readonly=True,
    )
