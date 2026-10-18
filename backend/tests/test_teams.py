"""Team management against a real FalkorDB. Skipped when none is reachable.

Uses its own org slug, so it does not touch the demo organisations or other tests."""
import pytest

from reliefnet import areas, db, events, field_ops, memory
from reliefnet.db import org_graph_name, query
from reliefnet.field_ops import TeamError
from reliefnet.memory import Worker
from reliefnet.seed import seed_org, seed_region

ORG = "pytest_teams"
DISPATCH = Worker("Dispatch-pytest", "dispatch", "Request", "TRIAGED")


def _spot(i: int = 0) -> tuple[float, float]:
    lm = areas.region().landmarks[i]
    return lm["lat"], lm["lon"]


@pytest.fixture
async def graph():
    try:
        await db.redis().ping()
    except Exception:
        pytest.skip("FalkorDB not reachable")
    await seed_region()
    await seed_org(ORG, "Pytest Teams", reset=True)
    yield org_graph_name(ORG)
    await db.falkor().select_graph(org_graph_name(ORG)).delete()
    await db.redis().hdel("rn:orgs", ORG)
    await events.reset_metrics(ORG)
    await db.close()


async def _claimed_request(g: str, rid: str) -> None:
    await query(
        g,
        "CREATE (r:Request {id:$id, status:'TRIAGED', priority:10, claimed_by:$me, lease_until:$far})"
        "-[:FOR]->(:Family {id:$fid, status:'UNSERVED'})",
        {"id": rid, "fid": f"F-{rid}", "me": DISPATCH.name, "far": 2**52},
    )


async def _assign(rid: str, team: str) -> bool:
    route = {"roads": [], "length_m": 0.0}
    return await memory.assign_team(ORG, DISPATCH, rid, team, 5.0, route, "[]", [], "pytest")


async def test_new_org_starts_with_no_teams(graph):
    assert await db.scalar(graph, "MATCH (t:Team) RETURN count(t)") == 0
    assert await db.scalar(graph, "MATCH (v:Volunteer) RETURN count(v)") == 0
    assert await memory.teams_with_load(ORG) == []


async def test_created_team_is_offered_to_dispatch(graph):
    lat, lon = _spot()
    team = await field_ops.create_team(ORG, "  Boat   Crew ", ["boat", "water"], 2, lat, lon, by="admin_test")
    assert team["name"] == "Boat Crew" and team["supplies"] == ["water", "boat"]
    assert team["base"] in {j.id for j in areas.region().junctions}

    offered = await memory.teams_with_load(ORG)
    assert [(t.name, t.base, t.capacity) for t in offered] == [("Boat Crew", team["base"], 2)]
    agent = await db.scalar(graph, "MATCH (a:Agent {name:'Field-Boat Crew'})-[:WORKS_FOR]->(:Team) RETURN a.kind")
    assert agent == "field"

    with pytest.raises(TeamError) as e:
        await field_ops.create_team(ORG, "boat crew", ["food"], 1, lat, lon, by="admin_test")
    assert e.value.status == 409

    edited = await field_ops.update_team(ORG, "Boat Crew", capacity=4, supplies=["boat"], by="admin_test")
    assert edited["capacity"] == 4 and edited["supplies"] == ["boat"]
    with pytest.raises(TeamError) as e:
        await field_ops.update_team(ORG, "No Such Team", capacity=2, by="admin_test")
    assert e.value.status == 404


async def test_off_duty_sends_assignments_back_to_dispatch(graph):
    lat, lon = _spot()
    await field_ops.create_team(ORG, "Night Team", ["food", "medicine"], 3, lat, lon, by="admin_test")
    await _claimed_request(graph, "R-T1")
    assert await _assign("R-T1", "Night Team")

    out = await field_ops.set_team_duty(ORG, "Night Team", False, by="coord_test")
    assert out == {"name": "Night Team", "status": "off_duty", "rerouted": ["R-T1"]}
    rows = await query(
        graph,
        "MATCH (r:Request {id:'R-T1'})-[:FOR]->(f:Family)"
        " OPTIONAL MATCH (r)-[x:REROUTED]->(:Team {name:'Night Team'})"
        " OPTIONAL MATCH (r)-[a:ASSIGNED_TO {active:true}]->()"
        " RETURN r.status AS status, f.status AS family, count(DISTINCT x) AS reroutes, count(DISTINCT a) AS active,"
        " r.reroute_reason AS why",
    )
    assert rows == [{"status": "TRIAGED", "family": "UNSERVED", "reroutes": 1, "active": 0,
                     "why": "Night Team off duty"}]
    assert await memory.teams_with_load(ORG) == []

    # Dispatch read the team list before the change: its write must fail and leave the request alone.
    await _claimed_request(graph, "R-T2")
    assert not await _assign("R-T2", "Night Team")
    assert await db.scalar(graph, "MATCH (r:Request {id:'R-T2'}) RETURN r.status") == "TRIAGED"

    back = await field_ops.set_team_duty(ORG, "Night Team", True, by="coord_test")
    assert back["status"] == "active" and back["rerouted"] == []
    assert [t.name for t in await memory.teams_with_load(ORG)] == ["Night Team"]


async def test_team_list_shows_load_and_members(graph):
    lat, lon = _spot()
    await field_ops.create_team(ORG, "Team X", ["water"], 2, lat, lon, by="admin_test")
    await query(graph, "MATCH (t:Team {name:'Team X'}) CREATE (:Volunteer {id:'v1', name:'Asha'})-[:MEMBER_OF]->(t)")
    await _claimed_request(graph, "R-T3")
    assert await _assign("R-T3", "Team X")
    [row] = await field_ops.list_teams(ORG)
    assert row["name"] == "Team X" and row["load"] == 1 and row["members"] == ["Asha"]
    assert row["status"] == "active" and row["lat"] is not None


async def test_second_assignment_is_refused_and_changes_nothing(graph):
    lat, lon = _spot()
    await field_ops.create_team(ORG, "Team Y", ["food"], 2, lat, lon, by="admin_test")
    await field_ops.create_team(ORG, "Team Z", ["food"], 2, lat, lon, by="admin_test")
    await _claimed_request(graph, "R-T4")
    assert await _assign("R-T4", "Team Y")

    # Put the request back in Dispatch's hands while its first assignment is still active.
    await query(graph, "MATCH (r:Request {id:'R-T4'}) SET r.status = 'TRIAGED', r.claimed_by = $me, r.lease_until = $far",
                {"me": DISPATCH.name, "far": 2**52})
    assert not await _assign("R-T4", "Team Z")
    rows = await query(
        graph,
        "MATCH (r:Request {id:'R-T4'}) OPTIONAL MATCH (r)-[a:ASSIGNED_TO {active:true}]->(t:Team)"
        " OPTIONAL MATCH (r)-[p:PROCESSED_BY]->()"
        " RETURN r.status AS status, r.team AS team, collect(DISTINCT t.name) AS teams, count(DISTINCT p) AS steps",
    )
    assert rows == [{"status": "TRIAGED", "team": "Team Y", "teams": ["Team Y"], "steps": 1}]
