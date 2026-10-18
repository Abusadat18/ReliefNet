"""Pure-logic tests: no database needed."""
import pytest

from reliefnet.agents.coordinator import evidence_text
from reliefnet.agents.dedupe import score_pair
from reliefnet.agents.triage import cluster_bonus, score
from reliefnet.domain import NEED_SUPPLIES, SUPPLIES, coverage
from reliefnet.field_ops import TeamError, clean_capacity, clean_supplies, clean_team_name, team_base
from reliefnet.models import Candidate, Family, Lesson, Request
from reliefnet.parsing import parse_message
from reliefnet import areas

# The parser logic is the same for every area; these cases use the fictional town.
LM = [(l["name"], l["aliases"]) for l in areas.region("ganga_nagar").landmarks]


def test_parses_hinglish_help_request():
    d = parse_message(
        "pls help 5 ppl stuck near Shiv mandir ward 12, dadi needs BP medicine, paani ghar mein aa raha hai", LM
    )
    assert d["kind"] == "help_request"
    assert d["people"] == 5 and d["elderly"] == 1
    assert "medicine" in d["needs"] and "evacuation" in d["needs"]
    assert d["water_entering"] and d["urgency"] in ("high", "critical")
    assert d["ward"] == 12 and d["landmark"] == "Shiv Mandir"


def test_temple_alias_maps_to_landmark_and_name():
    d = parse_message("R. Kumar family, ward 12 near temple, water entering house", LM)
    assert d["contact_name"] == "R. Kumar"
    assert d["landmark"] == "Shiv Mandir"
    assert "water" not in d["needs"]  # "water entering" is not a drinking-water need


def test_road_report_and_question_are_not_help_requests():
    assert parse_message("NH-12 bridge flooded, do not send vehicles", LM)["kind"] == "road_report"
    assert parse_message("is the stadium camp open?", LM)["kind"] == "info"


def test_unserved_cluster_message_is_help_request():
    d = parse_message("Ward 12 lane 4: nobody has come here since morning, 3 kids", LM)
    assert d["kind"] == "help_request" and d["children"] == 3 and d["landmark"] == "Lane 4"


BASE = dict(lat=25.59, lon=85.12, ward=12, landmark="Shiv Mandir", people=5, elderly=0, children=0, name="")


def _req(**kw) -> Request:
    return Request(id="R-1", **{**BASE, **kw})


def _cand(similarity: float, **kw) -> Candidate:
    return Candidate(id="R-2", family="F-1", similarity=similarity, **{**BASE, **kw})


def test_dedupe_merges_same_household_with_partial_details():
    s, _ = score_pair(_req(elderly=1), _cand(0.9, lat=25.5905, name="R. Kumar"))
    assert s >= 0.78


def test_dedupe_keeps_neighbours_apart():
    s, ev = score_pair(_req(name="R. Kumar"), _cand(0.9, lat=25.5902, people=3, children=2, name="Das"))
    assert s < 0.3 and ev["conflicts"]


def test_dedupe_ignores_far_requests():
    s, _ = score_pair(_req(), _cand(0.99, lat=25.61))
    assert s == 0.0


def test_triage_scores_medical_elderly_water_highest():
    fam = Family(id="F-1")
    hi, reasons, _ = score(Request(id="R-1", needs=["medicine"], medical="BP", elderly=1, water_entering=True,
                                   people=5, geo_confidence="high"), fam, None, [])
    lo, _, _ = score(Request(id="R-2", needs=["food"], people=2, geo_confidence="high"), fam, None, [])
    assert hi >= 70 > lo
    assert any("medical" in r for r in reasons)


def test_cluster_bonus_needs_several_unserved_households():
    assert cluster_bonus({"unserved": 2, "oldest_wait_h": 5}) == 0
    assert 0 < cluster_bonus({"unserved": 14, "oldest_wait_h": 6}) <= 17


def test_area_lesson_raises_priority():
    req = Request(id="R-1", needs=["food"], people=2, ward=12)
    lesson = Lesson(key="area_risk:ward 12:", kind="area_risk", target="ward 12", confidence=0.8, text="Ward 12 hotspot")
    base, _, _ = score(req, None, None, [])
    boosted, reasons, _ = score(req, None, None, [lesson])
    assert boosted > base and any("lesson" in r for r in reasons)


def test_coverage():
    assert coverage(["medicine", "evacuation"], ["medicine", "boat"]) == 1.0
    assert coverage(["medicine", "evacuation"], ["food"]) == 0.0


def test_ganga_nagar_has_three_bridges():
    bridges = {r.name for r in areas.region("ganga_nagar").roads if r.kind == "bridge"}
    assert bridges == {"Old Iron Bridge", "NH-12 Bridge", "Rail Bridge"}


def test_team_name_rules():
    assert clean_team_name("  Boat   Crew 2 ") == "Boat Crew 2"
    for bad in ["", "   ", "x" * 41, "Team/1", "-Team", "Team;DROP"]:
        with pytest.raises(TeamError):
            clean_team_name(bad)


def test_team_supplies_and_capacity_rules():
    assert {s for opts in NEED_SUPPLIES.values() for s in opts} <= set(SUPPLIES)
    assert clean_supplies(["Boat", "food", "food "]) == ["food", "boat"]
    for bad in [[], [" "], ["food", "helicopter"]]:
        with pytest.raises(TeamError):
            clean_supplies(bad)
    assert clean_capacity(1) == 1 and clean_capacity(20) == 20
    for bad in [0, 21, -3, True, 2.5]:
        with pytest.raises(TeamError):
            clean_capacity(bad)


def test_team_base_must_be_inside_the_area():
    reg = areas.region()
    lm = reg.landmarks[0]
    assert team_base(lm["lat"], lm["lon"]).id in {j.id for j in reg.junctions}
    with pytest.raises(TeamError):
        team_base(lm["lat"] + 1.0, lm["lon"])


def test_seeded_team_supplies_are_known():
    for teams in areas.module().TEAM_BASES.values():
        assert all(set(t.supplies) <= set(SUPPLIES) for t in teams)


def test_duplicate_evidence_reads_as_text():
    ev = {"similarity": 0.903, "distance_m": 38, "same_ward": True, "same_landmark": True, "people": "7 vs 7",
          "name": "unknown", "conflicts": []}
    want = "similarity 0.903 · 38 m · same landmark · 7 vs 7 people"
    assert evidence_text(ev) == want
    assert evidence_text(str(ev)) == want  # older edges keep the dict as text
    assert evidence_text("not a dict") == "not a dict"
    assert evidence_text(None) == ""
