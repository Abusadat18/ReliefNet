"""Create the shared region graph and the per-org graphs.

    python -m reliefnet.seed            # create anything missing
    python -m reliefnet.seed --reset    # wipe org data and region state, then reseed
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging

from . import areas, db, events, orgs
from .config import get_settings
from .db import REGION_GRAPH, org_graph_name, query

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


async def region_meta() -> dict | None:
    """What the region graph holds now (area, version, junctions), or None if there is no region graph."""
    if REGION_GRAPH not in await db.list_graphs():
        return None
    rows = await query(REGION_GRAPH, "MATCH (m:Meta) RETURN m.key AS k, m.value AS v", readonly=True)
    meta = {r["k"]: r["v"] for r in rows}
    # A region graph without these keys was made before areas existed: it is Ganga Nagar.
    return {"area": meta.get("area", "ganga_nagar"), "version": meta.get("version", ""),
            "junctions": meta.get("junctions", "")}


async def seed_region(reset: bool = False) -> None:
    if REGION_GRAPH in await db.list_graphs():
        have = await region_meta()
        current = have["area"] == get_settings().area and have["version"] == areas.version()
        if not reset and current and await db.scalar(REGION_GRAPH, "MATCH (j:Junction) RETURN count(j)", default=0):
            return
        await db.falkor().select_graph(REGION_GRAPH).delete()
    reg = areas.region()
    for stmt in REGION_INDEXES:
        await _safe(REGION_GRAPH, stmt)
    await query(
        REGION_GRAPH,
        "UNWIND $rows AS j CREATE (:Junction {id:j.id, lat:j.lat, lon:j.lon,"
        " loc: point({latitude:j.lat, longitude:j.lon})})",
        {"rows": [j.__dict__ for j in reg.junctions]},
    )
    # Roads are undirected in reality, so store both directions with the same id.
    # Each direction keeps the road's shape in its own direction of travel.
    rows = []
    for r in reg.roads:
        geom = r.geom or []
        rows.append({**r.__dict__, "geom": json.dumps(geom), "rgeom": json.dumps(geom[::-1])})
    for i in range(0, len(rows), 500):
        await query(
            REGION_GRAPH,
            "UNWIND $rows AS r MATCH (a:Junction {id:r.a}), (b:Junction {id:r.b})"
            " CREATE (a)-[:ROAD {id:r.id, name:r.name, kind:r.kind, low_lying:r.low_lying, length_m:r.length_m,"
            " cost:r.length_m, status:'open', updated_at:0, geom:r.geom}]->(b)"
            " CREATE (b)-[:ROAD {id:r.id, name:r.name, kind:r.kind, low_lying:r.low_lying, length_m:r.length_m,"
            " cost:r.length_m, status:'open', updated_at:0, geom:r.rgeom}]->(a)",
            {"rows": rows[i:i + 500]},
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
    meta = {
        "area": reg.name,
        "version": areas.version(),
        "junctions": areas.junction_version(),
        "title": reg.title,
        "attribution": reg.attribution,
        "water_areas": json.dumps(reg.water_areas),
        "water_lines": json.dumps(reg.water_lines),
        "rail": json.dumps(reg.rail),
    }
    await query(REGION_GRAPH, "UNWIND $rows AS m CREATE (:Meta {key:m.k, value:m.v})",
                {"rows": [{"k": k, "v": v} for k, v in meta.items()]})
    log.info("region seeded: %s, %d junctions, %d roads", reg.name, len(reg.junctions), len(reg.roads))


async def seed_org(slug: str, name: str, reset: bool = False) -> None:
    await orgs.register(slug, name)
    g = org_graph_name(slug)
    if reset and g in await db.list_graphs():
        await db.falkor().select_graph(g).delete()
        await events.reset_metrics(slug)
    await ensure_org_schema(slug)
    if await db.scalar(g, "MATCH (t:Team) RETURN count(t)", default=0):
        return
    teams = areas.team_bases(slug)
    reg = areas.region()
    rows = []
    for t in teams:
        j = areas.nearest_junction(reg, t.lat, t.lon)
        rows.append({"name": t.name, "supplies": t.supplies, "base": j.id, "capacity": t.capacity,
                     "lat": j.lat, "lon": j.lon})
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
        {"id": f"vol_{slug}_{i}", "name": n, "team": t.name, "phone": None}
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
        have = await region_meta()
        # Team bases and routes in every org graph point at junction ids. New junctions make them wrong.
        moved = have is not None and (have["area"] != get_settings().area
                                      or have["junctions"] != areas.junction_version())
        if moved:
            log.warning("The area's junctions changed (%s to %s): rebuilding the region and every org graph",
                        have["area"], get_settings().area)
        await seed_region(reset=reset or moved)
        for slug, name in default_org_list():
            await seed_org(slug, name, reset=reset or moved)
        if moved:
            defaults = {s for s, _ in default_org_list()}
            for org in await orgs.all_orgs():
                if org["slug"] not in defaults:
                    await seed_org(org["slug"], org["name"], reset=True)
        if reset or moved:
            await r.delete("rn:agents")
            areas.region.cache_clear()
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
