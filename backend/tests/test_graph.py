"""Tests against a real FalkorDB. Skipped when none is reachable.

Uses its own org slug and leaves the shared region graph as it found it."""
import asyncio

import pytest

from reliefnet import areas, db, field_ops, memory, routing
from reliefnet.agents.base import Agent
from reliefnet.agents.coordinator import family_trace
from reliefnet.db import org_graph_name, query
from reliefnet.seed import seed_org, seed_region

ORG = "pytest_org"

# Road names and junctions come from the active area (AREA), so the tests run on any map.
FLOOD = areas.drill().flood_road
OTHER = sorted(r.name for r in areas.region().roads if r.kind == "bridge" and r.name != FLOOD)[0]
SRC, DST = areas.module().route_check()


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
    before = await routing.road_state(FLOOD)
    try:
        await routing.set_road_status(FLOOD, "flooded")
        r = await routing.route(SRC, DST)
        assert r is not None and FLOOD not in r["roads"]
        await routing.set_road_status(FLOOD, "open")
        r2 = await routing.route(SRC, DST)
        assert FLOOD in r2["roads"]
    finally:
        await routing.set_road_status(FLOOD, before or "open")
        await db.close()


async def test_lesson_override_wins_over_confidence(graph):
    weak = "area_risk:ward 3:"
    strong = "area_risk:ward 4:"
    for key, conf in ((weak, 0.3), (strong, 0.8)):
        await query(graph, "CREATE (:Lesson {key:$k, kind:'area_risk', text:$k, confidence:$c})", {"k": key, "c": conf})
    used = lambda ls: {l.key for l in ls}  # noqa: E731
    assert used(await memory.active_lessons(ORG, ["area_risk"])) == {strong}
    await memory.set_lesson_override(ORG, weak, "on", "pytest")
    await memory.set_lesson_override(ORG, strong, "off", "pytest")
    assert used(await memory.active_lessons(ORG, ["area_risk"])) == {weak}
    await memory.set_lesson_override(ORG, strong, None, "pytest")
    assert used(await memory.active_lessons(ORG, ["area_risk"])) == {weak, strong}
    assert await memory.set_lesson_override(ORG, "no such lesson", "on", "pytest") is None


async def test_call_number_prefers_the_contact_number(graph):
    await query(
        graph,
        "CREATE (:Request {id:'R-901', phone:'9800000001', alt_phone:'9800000002'}),"
        " (:Request {id:'R-902', phone:'9800000003', alt_phone:''}), (:Request {id:'R-903'})",
    )
    numbers = await field_ops.call_numbers(ORG, ["R-901", "R-902", "R-903"])
    assert numbers == {"R-901": "9800000002", "R-902": "9800000003"}



async def test_family_trace_edges_carry_their_reasons(graph):
    await query(
        graph,
        "CREATE (f:Family {id:'F-901', name:'Pytest', status:'UNSERVED'}),"
        " (m:Message {id:'M-901', text:'help'})-[:BECAME]->(r:Request {id:'R-901', status:'TRIAGED', created_at:1,"
        " channel:'web'})-[:FOR]->(f), (r)-[:PROCESSED_BY {at:3, action:'triage', reason:'priority 54'}]->"
        "(:Agent {name:'Triage-1'}), (d:Request {id:'R-902', status:'MERGED', created_at:2})-[:FOR]->(f),"
        " (d)-[:DUPLICATE_OF {at:2, score:0.9, evidence:\"{'distance_m': 38}\", reason:'', decided_by:'rules'}]->(r),"
        " (:Lesson {key:'area_risk:ward 9:', text:'Ward 9 is a hotspot', created_at:4, confidence:0.6})-[:DERIVED_FROM]->(f)",
    )
    edges = (await family_trace(ORG, "F-901"))["graph"]["edges"]
    by_type = {e["type"]: e for e in edges}
    assert by_type["PROCESSED_BY"]["reason"] == "priority 54"
    assert by_type["PROCESSED_BY"]["props"] == "action:triage"
    assert by_type["DUPLICATE_OF"]["reason"] == "38 m"
    assert by_type["DUPLICATE_OF"]["props"] == "score:0.9"
    assert by_type["DERIVED_FROM"]["from"] == "area_risk:ward 9:"
    assert [e["at"] for e in edges] == sorted(e["at"] or 0 for e in edges)


async def test_lesson_penalty_steers_route():
    try:
        await db.redis().ping()
    except Exception:
        pytest.skip("FalkorDB not reachable")
    await seed_region()
    before = await routing.road_state(FLOOD)
    try:
        await routing.set_road_status(FLOOD, "open")
        plain = await routing.route(SRC, DST)
        steered = await routing.route(SRC, DST, {FLOOD: 3500.0})
        assert FLOOD in plain["roads"] and FLOOD not in steered["roads"]
    finally:
        await routing.set_road_status(FLOOD, before or "open")
        await db.close()


async def test_one_team_report_is_not_enough_to_close_a_road(graph):
    before = await routing.road_state(OTHER)
    try:
        r1 = await field_ops.report_road(ORG, OTHER.lower(), "flooded", reporter="v1", team="Team 1")
        assert r1["status"] == "reported"
        r2 = await field_ops.report_road(ORG, OTHER, "flooded", reporter="v2", team="Team 2")
        assert r2["status"] == "flooded"
    finally:
        await routing.set_road_status(OTHER, before or "open")
        await query("region", "MATCH (p:Report {org:$o}) DELETE p", {"o": ORG})
