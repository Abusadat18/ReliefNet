"""OpenStreetMap places: import, merge with the hand-written landmarks, and aliases. No network, no database."""
import pytest

from reliefnet import areas
from reliefnet.areas import places
from reliefnet.parsing import parse_message

WARDS = [{"num": 1, "name": "Kankarbagh", "polygon": [[25.62, 85.10], [25.62, 85.20], [25.58, 85.20], [25.58, 85.10]]}]
HAND = [
    {"id": "L01", "name": "Shiv Mandir", "aliases": ["temple", "mandir", "shiv temple"], "kind": "temple",
     "ward": 1, "lat": 25.600, "lon": 85.150},
    {"id": "L02", "name": "Kankarbagh Police Station", "aliases": ["kankarbagh thana", "thana"], "kind": "office",
     "ward": 1, "lat": 25.598, "lon": 85.156},
]


def place(osm, name, lat, lon, kind="temple", alt=()):
    return {"osm": osm, "name": name, "alt": list(alt), "kind": kind, "lat": lat, "lon": lon}


def test_overpass_answer_becomes_clean_places():
    osm = {"elements": [
        {"type": "node", "id": 1, "lat": 25.6, "lon": 85.15,
         "tags": {"amenity": "place_of_worship", "religion": "muslim", "name": "Jama Masjid", "name:hi": "जामा मस्जिद"}},
        # The same mosque drawn as a building: one place, not two.
        {"type": "way", "id": 2, "center": {"lat": 25.6001, "lon": 85.1501},
         "tags": {"amenity": "place_of_worship", "religion": "muslim", "name": "Jama Masjid", "alt_name": "Badi Masjid"}},
        {"type": "node", "id": 3, "lat": 25.61, "lon": 85.16, "tags": {"amenity": "hospital",
                                                                      "name": "Heart Hospital Pvt. Ltd., Patna"}},
        {"type": "node", "id": 4, "lat": 25.61, "lon": 85.16, "tags": {"amenity": "place_of_worship", "name": "Mandir"}},
        {"type": "node", "id": 5, "lat": 25.61, "lon": 85.16, "tags": {"amenity": "bank", "name": "SBI ATM"}},
        {"type": "node", "id": 6, "lat": 26.5, "lon": 85.16, "tags": {"amenity": "school", "name": "Far School"}},
        {"type": "node", "id": 7, "lat": 25.61, "lon": 85.16, "tags": {"shop": "bakery", "name": "Cake Shop"}},
    ]}
    rows = places.from_osm(osm, (25.58, 85.10, 25.62, 85.20), city="Patna")
    assert [(r["name"], r["kind"]) for r in rows] == [("Heart Hospital", "hospital"), ("Jama Masjid", "mosque")]
    assert set(rows[1]["alt"]) == {"जामा मस्जिद", "Badi Masjid"}


def test_hand_landmarks_win_and_duplicates_are_dropped():
    osm = [
        place("n1", "Shri Shiv Mandir", 25.6005, 85.1503),  # the hand-written Shiv Mandir
        place("n2", "Kankarbagh police station", 25.5982, 85.1561, kind="office"),
        place("n3", "Jaleshwar Mandir", 25.605, 85.160),
        place("n4", "Outside Mandir", 25.70, 85.15),  # outside every ward
        place("n5", "Kankarbagh", 25.61, 85.15, kind="ground"),  # the ward itself
    ]
    out = places.merge(HAND, osm, WARDS)
    assert [l["name"] for l in out] == ["Shiv Mandir", "Kankarbagh Police Station", "Jaleshwar Mandir"]
    assert [l["source"] for l in out] == ["hand", "hand", "osm"]
    assert out[0] == {**HAND[0], "source": "hand"}
    assert out[2]["id"] == "Ln3" and out[2]["ward"] == 1


def test_same_name_far_away_is_a_second_place_with_the_ward_in_its_name():
    out = places.merge(HAND, [place("n1", "Shiv Mandir", 25.615, 85.190)], WARDS)
    second = out[2]
    assert second["name"] == "Shiv Mandir, Kankarbagh" and second["source"] == "osm"
    assert "shiv mandir" in second["aliases"]
    # On a tie the first landmark wins, and the hand-written list comes first.
    lm = [(l["name"], l["aliases"]) for l in out]
    assert parse_message("5 log fanse hain shiv mandir ke paas", lm)["landmark"] == "Shiv Mandir"


def test_automatic_aliases_are_never_only_generic_words():
    aliases = places.auto_aliases("Sri Ram Hospital", ["Govt Hospital", "श्री राम अस्पताल"])
    assert "ram hospital" in aliases and "sri ram aspatal" in aliases and "श्री राम अस्पताल" in aliases
    assert "govt hospital" not in aliases and "hospital" not in aliases
    assert all(not places.is_generic(a) for a in aliases)
    assert places.is_generic("Govt. Middle School") and not places.is_generic("Gayatri Mandir")


def test_short_form_only_when_no_other_place_or_ward_uses_it():
    osm = [place("n1", "Jaleshwar Mandir", 25.605, 85.160), place("n2", "Kankarbagh Post Office", 25.606, 85.161,
                                                                  kind="office"),
           place("n3", "Gayatri Mandir", 25.607, 85.162), place("n4", "Gayatri Nagar Park", 25.608, 85.163,
                                                                 kind="ground")]
    out = {l["name"]: l for l in places.merge(HAND, osm, WARDS)}
    assert "jaleshwar" in out["Jaleshwar Mandir"]["aliases"]
    assert "kankarbagh" not in out["Kankarbagh Post Office"]["aliases"]
    assert "gayatri" not in out["Gayatri Mandir"]["aliases"]  # "Gayatri Nagar Park" uses it too
    lm = [(l["name"], l["aliases"]) for l in out.values()]
    assert parse_message("ward 1 kankarbagh mein paani", lm)["landmark"] == ""
    assert parse_message("jaleshwar ke paas 4 log", lm)["landmark"] == "Jaleshwar Mandir"


def test_landmark_change_keeps_the_road_version(monkeypatch):
    name = "ganga_nagar"
    areas.region.cache_clear()
    roads, marks, junctions = areas.version(name), areas.landmark_version(name), areas.junction_version(name)
    reg = areas.region(name)
    w = reg.wards[0]
    extra = [place("n9", "Pytest Gurudwara", w["lat"], w["lon"])]
    monkeypatch.setattr(places, "load", lambda m: extra if m.NAME == name else [])
    areas.region.cache_clear()
    try:
        assert areas.version(name) == roads
        assert areas.landmark_version(name) != marks
        assert areas.junction_version(name) == junctions
        assert any(l["name"] == "Pytest Gurudwara" for l in areas.region(name).landmarks)
    finally:
        areas.region.cache_clear()


@pytest.mark.parametrize("name", list(areas.AREAS))
def test_every_landmark_has_a_source_and_a_unique_id(name):
    lms = areas.region(name).landmarks
    assert len({l["id"] for l in lms}) == len(lms)
    assert {l["source"] for l in lms} <= {"hand", "osm"}
    assert [l["source"] for l in lms] == sorted((l["source"] for l in lms), key=lambda s: s != "hand")
    names = [l["name"].lower() for l in lms]
    assert len(names) == len(set(names)), "landmark names must be unique"
