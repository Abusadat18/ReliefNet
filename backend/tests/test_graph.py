"""Tests against a real FalkorDB. Skipped when none is reachable.

Uses its own org slug and leaves the shared region graph as it found it."""
import asyncio

import pytest

from reliefnet import db, field_ops, memory, routing
from reliefnet.agents.base import Agent
from reliefnet.db import org_graph_name, query
from reliefnet.seed import seed_org, seed_region

ORG = "pytest_org"


@pytest.fixture
async def graph():
    try:
        await db.redis().ping()
    except Exception:
        pytest.skip("FalkorDB not reachable")
    await seed_region()
    await seed_org(ORG, "Pytest Org", reset=True)
    yield org_graph_name(ORG)
    await db.falkor().select_graph(org_graph_name(ORG)).delete()
    await db.redis().hdel("rn:orgs", ORG)
    await db.close()


class Probe(Agent):
    kind = "probe"
    label = "Request"
    in_status = "TRIAGED"
    order = "r.priority DESC"


async def test_parallel_claims_never_overlap(graph):
    await query(graph, "UNWIND range(1, 30) AS i CREATE (:Request {id:'T-' + toString(i), status:'TRIAGED', priority:i})")
    agents = [Probe(f"P-{i}") for i in range(30)]
    items = await asyncio.gather(*(a.claim(ORG) for a in agents))
    ids = [i.id for i in items if i]
    assert len(ids) == 30 and len(set(ids)) == 30


async def test_expired_lease_is_reclaimed_and_old_owner_cannot_finish(graph):
    await query(graph, "CREATE (:Request {id:'T-1', status:'TRIAGED', priority:1})")
    a, b = Probe("P-a"), Probe("P-b")
    assert (await a.claim(ORG)).id == "T-1"
    assert await b.claim(ORG) is None  # lease still valid
    await query(graph, "MATCH (r:Request {id:'T-1'}) SET r.lease_until = 0")  # simulate a crash
    assert (await b.claim(ORG)).id == "T-1"
    assert not await memory.finish_step(ORG, a.me, "T-1", "ASSIGNED", {}, "late")
    assert await memory.finish_step(ORG, b.me, "T-1", "ASSIGNED", {}, "ok")
    n = await db.scalar(graph, "MATCH (:Request {id:'T-1'})-[p:PROCESSED_BY]->() RETURN count(p)")
    assert n == 2  # the reclaim and the finish are both on record


async def test_flooded_road_is_avoided():
    try:
        await db.redis().ping()
    except Exception:
        pytest.skip("FalkorDB not reachable")
    await seed_region()
    before = await routing.road_state("NH-12 Bridge")
    try:
        await routing.set_road_status("NH-12 Bridge", "flooded")
        r = await routing.route("J25", "J55")
        assert r is not None and "NH-12 Bridge" not in r["roads"]
        await routing.set_road_status("NH-12 Bridge", "open")
        r2 = await routing.route("J25", "J55")
        assert "NH-12 Bridge" in r2["roads"]
    finally:
        await routing.set_road_status("NH-12 Bridge", before or "open")
        await db.close()


async def test_lesson_penalty_steers_route():
    try:
        await db.redis().ping()
    except Exception:
        pytest.skip("FalkorDB not reachable")
    await seed_region()
    before = await routing.road_state("NH-12 Bridge")
    try:
        await routing.set_road_status("NH-12 Bridge", "open")
        plain = await routing.route("J25", "J55")
        steered = await routing.route("J25", "J55", {"NH-12 Bridge": 3500.0})
        assert "NH-12 Bridge" in plain["roads"] and "NH-12 Bridge" not in steered["roads"]
    finally:
        await routing.set_road_status("NH-12 Bridge", before or "open")
        await db.close()


async def test_one_team_report_is_not_enough_to_close_a_road(graph):
    before = await routing.road_state("Old Iron Bridge")
    try:
        r1 = await field_ops.report_road(ORG, "old iron bridge", "flooded", reporter="v1", team="Team 1")
        assert r1["status"] == "reported"
        r2 = await field_ops.report_road(ORG, "Old Iron Bridge", "flooded", reporter="v2", team="Team 2")
        assert r2["status"] == "flooded"
    finally:
        await routing.set_road_status("Old Iron Bridge", before or "open")
        await query("region", "MATCH (p:Report {org:$o}) DELETE p", {"o": ORG})
