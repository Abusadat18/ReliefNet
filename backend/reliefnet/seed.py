"""Create the shared region graph and the per-org graphs.

    python -m reliefnet.seed            # create anything missing
    python -m reliefnet.seed --reset    # wipe org data and region state, then reseed
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging

from . import db, events, orgs
from .config import get_settings
from .db import REGION_GRAPH, org_graph_name, query
from .region_data import DEFAULT_TEAMS, TEAM_BASES, build_region

log = logging.getLogger(__name__)

ORG_INDEXES = [
    "CREATE INDEX FOR (n:Message) ON (n.id)",
    "CREATE INDEX FOR (n:Message) ON (n.status)",
    "CREATE INDEX FOR (n:Request) ON (n.id)",
    "CREATE INDEX FOR (n:Request) ON (n.status)",
    "CREATE INDEX FOR (n:Family) ON (n.id)",
    "CREATE INDEX FOR (n:Team) ON (n.name)",
    "CREATE INDEX FOR (n:Agent) ON (n.name)",
    "CREATE INDEX FOR (n:Volunteer) ON (n.id)",
    "CREATE INDEX FOR (n:Volunteer) ON (n.telegram_chat_id)",
    "CREATE INDEX FOR (n:Lesson) ON (n.key)",
    "CREATE INDEX FOR (n:Need) ON (n.name)",
]

REGION_INDEXES = [
    "CREATE INDEX FOR (n:Junction) ON (n.id)",
    "CREATE INDEX FOR (n:Landmark) ON (n.name)",
    "CREATE INDEX FOR ()-[r:ROAD]-() ON (r.name)",
]


async def _safe(graph: str, cypher: str) -> None:
    try:
        await query(graph, cypher)
    except Exception as e:  # index already exists
        if "already" not in str(e).lower():
            raise


async def ensure_org_schema(slug: str) -> None:
    g = org_graph_name(slug)
    for stmt in ORG_INDEXES:
        await _safe(g, stmt)
    dim = get_settings().embed_dim
    await _safe(
        g,
        f"CREATE VECTOR INDEX FOR (r:Request) ON (r.embedding) OPTIONS {{dimension:{dim}, similarityFunction:'cosine'}}",
    )
    await _safe(
        g,
        f"CREATE VECTOR INDEX FOR (l:Lesson) ON (l.embedding) OPTIONS {{dimension:{dim}, similarityFunction:'cosine'}}",
    )


async def seed_region(reset: bool = False) -> None:
    if REGION_GRAPH in await db.list_graphs():
        if not reset and await db.scalar(REGION_GRAPH, "MATCH (j:Junction) RETURN count(j)", default=0):
            return
        await db.falkor().select_graph(REGION_GRAPH).delete()
    reg = build_region()
    for stmt in REGION_INDEXES:
        await _safe(REGION_GRAPH, stmt)
    await query(
        REGION_GRAPH,
        "UNWIND $rows AS j CREATE (:Junction {id:j.id, lat:j.lat, lon:j.lon, row:j.row, col:j.col,"
        " loc: point({latitude:j.lat, longitude:j.lon})})",
        {"rows": [j.__dict__ for j in reg.junctions]},
    )
    # Roads are undirected in reality, so store both directions with the same id.
    await query(
        REGION_GRAPH,
        "UNWIND $rows AS r MATCH (a:Junction {id:r.a}), (b:Junction {id:r.b})"
        " CREATE (a)-[:ROAD {id:r.id, name:r.name, kind:r.kind, low_lying:r.low_lying, length_m:r.length_m,"
        " cost:r.length_m, status:'open', updated_at:0}]->(b)"
        " CREATE (b)-[:ROAD {id:r.id, name:r.name, kind:r.kind, low_lying:r.low_lying, length_m:r.length_m,"
        " cost:r.length_m, status:'open', updated_at:0}]->(a)",
        {"rows": [r.__dict__ for r in reg.roads]},
    )
    await query(
        REGION_GRAPH,
        "UNWIND $rows AS w CREATE (:Ward {num:w.num, name:w.name, bank:w.bank, lat:w.lat, lon:w.lon, polygon:w.polygon})",
        {"rows": [{**w, "polygon": json.dumps(w["polygon"])} for w in reg.wards]},
    )
    await query(
        REGION_GRAPH,
        "UNWIND $rows AS l CREATE (:Landmark {id:l.id, name:l.name, aliases:l.aliases, ward:l.ward, kind:l.kind,"
        " lat:l.lat, lon:l.lon})",
        {"rows": reg.landmarks},
    )
    await query(
        REGION_GRAPH,
        "UNWIND $rows AS s CREATE (:Shelter {id:s.id, name:s.name, ward:s.ward, capacity:s.capacity, occupancy:0,"
        " open:true, lat:s.lat, lon:s.lon})",
        {"rows": reg.shelters},
    )
    await query(REGION_GRAPH, "CREATE (:Meta {key:'river', polygon:$p})", {"p": json.dumps(reg.river)})
    log.info("region seeded: %d junctions, %d roads", len(reg.junctions), len(reg.roads))


async def seed_org(slug: str, name: str, reset: bool = False) -> None:
    await orgs.register(slug, name)
    g = org_graph_name(slug)
    if reset and g in await db.list_graphs():
        await db.falkor().select_graph(g).delete()
        await events.reset_metrics(slug)
    await ensure_org_schema(slug)
    if await db.scalar(g, "MATCH (t:Team) RETURN count(t)", default=0):
        return
    teams = TEAM_BASES.get(slug, DEFAULT_TEAMS)
    jrows = await query(REGION_GRAPH, "MATCH (j:Junction) RETURN j.id AS id, j.lat AS lat, j.lon AS lon")
    jpos = {r["id"]: r for r in jrows}
    rows = []
    for tname, supplies, base, cap in teams:
        p = jpos[base]
        rows.append(
            {"name": tname, "supplies": supplies, "base": base, "capacity": cap, "lat": p["lat"], "lon": p["lon"]}
        )
    await query(
        g,
        "UNWIND $rows AS t CREATE (:Team {name:t.name, supplies:t.supplies, base_junction:t.base, capacity:t.capacity,"
        " lat:t.lat, lon:t.lon, status:'active'})",
        {"rows": rows},
    )
    # One field agent per team; Dispatch hands off to it.
    await query(
        g,
        "MATCH (t:Team) MERGE (a:Agent {name:'Field-' + t.name}) SET a.kind='field'"
        " MERGE (a)-[:WORKS_FOR]->(t)",
    )
    # Demo volunteers so the field app works before anyone signs up.
    vols = [
        {"id": f"vol_{slug}_{i}", "name": n, "team": t[0], "phone": None}
        for i, (n, t) in enumerate(zip(_VOLUNTEER_NAMES, teams))
    ]
    await query(
        g,
        "UNWIND $rows AS v MATCH (t:Team {name:v.team})"
        " CREATE (vol:Volunteer {id:v.id, name:v.name, role:'volunteer', created_at:timestamp()})-[:MEMBER_OF]->(t)",
        {"rows": vols},
    )
    log.info("org %s seeded with %d teams", slug, len(teams))


_VOLUNTEER_NAMES = ["Asha Devi", "Imran Khan", "Priya Singh", "Rohit Yadav", "Neha Kumari"]


def default_org_list() -> list[tuple[str, str]]:
    out = []
    for part in get_settings().default_orgs.split(","):
        if ":" in part:
            slug, name = part.split(":", 1)
            out.append((slug.strip(), name.strip()))
    return out


async def seed_all(reset: bool = False) -> None:
    # The API and the workers both start by seeding; only one may do it at a time.
    r = db.redis()
    while not await r.set("rn:lock:seed", "1", nx=True, ex=120):
        await asyncio.sleep(0.5)
    try:
        await seed_region(reset=reset)
        for slug, name in default_org_list():
            await seed_org(slug, name, reset=reset)
        if reset:
            await r.delete("rn:agents")
    finally:
        await r.delete("rn:lock:seed")


async def _main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO)
    await seed_all(reset=args.reset)
    await db.close()


if __name__ == "__main__":
    asyncio.run(_main())
