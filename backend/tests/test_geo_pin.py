"""Pins outside the town: no database needed."""
from reliefnet import geo

WARDS = [{"num": n, "lat": 25.60 + n * 0.001, "lon": 85.12 + n * 0.001} for n in range(1, 17)]


def test_snap_uses_the_ward_the_person_chose():
    s = geo.snap_point(WARDS, ward_hint=7, seed="M-1001")
    assert s["ward"] == 7 and s["snapped"] and s["geo_confidence"] == "low" and s["landmark"] == ""
    assert abs(s["lat"] - WARDS[6]["lat"]) < 0.005 and abs(s["lon"] - WARDS[6]["lon"]) < 0.005


def test_snap_without_a_ward_picks_one_that_is_stable_for_the_same_message():
    a = geo.snap_point(WARDS, ward_hint=0, seed="M-1002")
    b = geo.snap_point(WARDS, ward_hint=0, seed="M-1002")
    assert a == b and a["ward"] in {w["num"] for w in WARDS}


def test_different_messages_are_spread_across_the_town():
    wards = {geo.snap_point(WARDS, 0, f"M-{1000 + i}")["ward"] for i in range(60)}
    assert len(wards) >= 8


def test_snapping_follows_the_area_unless_set(monkeypatch):
    s = geo.get_settings()
    monkeypatch.setattr(s, "demo_snap_pins", None)
    monkeypatch.setattr(s, "area", "patna")
    assert not geo.snap_pins()  # a real map: a far pin is a real place, not a test phone
    monkeypatch.setattr(s, "area", "ganga_nagar")
    assert geo.snap_pins()
    monkeypatch.setattr(s, "demo_snap_pins", False)
    assert not geo.snap_pins()


def test_town_center_is_the_mean_of_the_wards():
    lat, lon = geo._town_center(WARDS)
    assert abs(lat - 25.6085) < 1e-6 and abs(lon - 85.1285) < 1e-6
