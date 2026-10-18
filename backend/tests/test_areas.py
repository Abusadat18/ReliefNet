"""Every area must give the agents a usable map. No database needed."""
import pytest

from reliefnet import areas
from reliefnet.parsing import parse_message


@pytest.mark.parametrize("name", list(areas.AREAS))
def test_area_is_connected_and_complete(name):
    reg = areas.region(name)
    adj: dict[str, set[str]] = {}
    for r in reg.roads:
        adj.setdefault(r.a, set()).add(r.b)
        adj.setdefault(r.b, set()).add(r.a)
    seen, todo = set(), [reg.junctions[0].id]
    while todo:
        j = todo.pop()
        if j not in seen:
            seen.add(j)
            todo += adj.get(j, set()) - seen
    assert len(seen) == len(reg.junctions), "every junction must be reachable"
    assert len({r.id for r in reg.roads}) == len(reg.roads)

    names = {r.name for r in reg.roads}
    assert areas.drill(name).flood_road in names
    # A flood report closes every road with that name, so a generated name must not repeat.
    generated = [r.name for r in reg.roads if r.name.startswith(("Lane near ", "Road near "))]
    assert len(generated) == len(set(generated)), "generated road names must be unique"
    src, dst = areas.module(name).route_check()
    assert {src, dst} <= {j.id for j in reg.junctions}
    assert all(lm["ward"] for lm in reg.landmarks), "every landmark must sit inside a ward"
    assert all(s["ward"] for s in reg.shelters)
    m = areas.module(name)
    for teams in m.TEAM_BASES.values():
        assert all(areas.ward_at(reg, t.lat, t.lon) for t in teams), "team bases must sit inside the area"
    assert set(areas.drill(name).hotspot_wards) <= {w["num"] for w in reg.wards}


PATNA_LM = [(l["name"], l["aliases"]) for l in areas.region("patna").landmarks]


def test_patna_drill_duplicates_point_to_one_landmark():
    d = areas.drill("patna")
    first = parse_message(d.messages[0][2], PATNA_LM)
    second = parse_message(d.messages[1][2], PATNA_LM)
    assert first["landmark"] == second["landmark"] == "Shiv Mandir"
    assert first["ward"] == second["ward"] == 11


def test_patna_localities_and_road_report():
    d = areas.drill("patna")
    assert parse_message(d.messages[2][2], PATNA_LM)["landmark"] == "Road No. 6"
    assert parse_message(d.messages[3][2], PATNA_LM)["landmark"] == "Malahi Pakri"
    report = parse_message(f"{d.flood_road} flooded, do not send vehicles", PATNA_LM)
    assert report["kind"] == "road_report" and report["road_name"] == "malahi pakdi road"


def test_patna_bridges_have_unique_real_names():
    reg = areas.region("patna")
    bridges = {r.name for r in reg.roads if r.kind == "bridge"}
    assert {"Rajendra Nagar Flyover", "Chiriya Taar overbridge", "Dhanush Setu Flyover"} <= bridges
    assert not any(" near " in n and n.count(" near ") > 1 for n in bridges)
