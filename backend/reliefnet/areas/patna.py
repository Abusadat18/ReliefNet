"""Rajendra Nagar and Kankarbagh, Patna.

In September 2019, days of heavy rain left these neighbourhoods under water
for more than a week. The roads, bridges, drains and railway come from
OpenStreetMap (`patna.json`, made by `import_osm.py`). The landmark positions
come from OpenStreetMap too; the local names people use are added by hand.

The wards are 16 simple zones, not the official Patna Municipal Corporation
wards. The shelters, teams and families are simulated."""
from __future__ import annotations

import json
from pathlib import Path

from . import DrillScript, Junction, Region, Road, TeamBase, nearest_junction, ward_at

NAME = "patna"
TITLE = "Rajendra Nagar and Kankarbagh, Patna"
FICTIONAL = False
# south, west, north, east
BBOX = (25.585, 85.140, 25.618, 85.180)
SNAPSHOT = Path(__file__).with_name("patna.json")

# Zone edges. The railway runs east-west near 25.603, so it is one zone edge.
LAT_EDGES = [25.618, 25.611, 25.6035, 25.594, 25.585]
LON_EDGES = [85.140, 85.150, 85.160, 85.170, 85.180]
WARD_NAMES = {
    1: "Gandhi Maidan East", 2: "Bakarganj", 3: "Makhania Kuan", 4: "Saidpur",
    5: "Kadamkuan West", 6: "Lohanipur", 7: "Rajendra Nagar", 8: "Bazar Samiti",
    9: "Lohia Nagar", 10: "Kankarbagh", 11: "Kankarbagh East", 12: "Bahadurpur",
    13: "Ashok Nagar", 14: "Malahi Pakri", 15: "Hanuman Nagar", 16: "Bhootnath",
}

# (name, aliases, kind, lat, lon). Each alias is a name people type in a message.
LANDMARKS = [
    ("Rajendra Nagar Terminal", ["rajendra nagar station", "terminal", "rajendra nagar terminal station",
                                 "railway station"], "transport", 25.60301, 85.16235),
    ("Moin-ul-Haq Stadium", ["moinul haq stadium", "moin ul haq", "stadium", "cricket stadium"], "ground",
     25.60789, 85.16745),
    ("Bazar Samiti", ["bazaar samiti", "bazar samiti", "mandi", "sabzi mandi", "market"], "market",
     25.60562, 85.17064),
    ("Nalanda Medical College Hospital", ["nmch", "nalanda medical college", "medical college", "sarkari aspatal",
                                          "hospital", "aspatal"], "hospital", 25.60025, 85.17400),
    ("Patliputra Stadium", ["patliputra sports complex", "sports complex", "stadium", "patliputra stadium"],
     "ground", 25.59482, 85.15349),
    ("Kankarbagh Police Station", ["kankarbagh thana", "thana", "police station"], "office", 25.59836, 85.15597),
    ("Patrakar Nagar Police Station", ["patrakar nagar thana", "patrakar nagar", "thana"], "office",
     25.58972, 85.15981),
    ("Shiv Mandir", ["temple", "mandir", "shiv temple", "shiv ji mandir", "mahadev mandir"], "temple",
     25.59483, 85.16312),
    ("Jaleshwar Mandir", ["jaleshwar temple", "jaleshwar mahadev", "jaleshwar"], "temple", 25.59603, 85.16160),
    ("Gayatri Mandir", ["gaytri mandir", "gayatri temple", "mandir"], "temple", 25.59791, 85.15445),
    ("Sankat Mochan Mandir", ["sankat mochan", "sankat mochan temple"], "temple", 25.60051, 85.16504),
    ("Bhootnath Shiv Mandir", ["bhootnath mandir", "bhutnath mandir", "bhootnath temple", "mandir"], "temple",
     25.59731, 85.17492),
    ("Durga Mandir", ["durga temple", "durga ji mandir", "mandir"], "temple", 25.59334, 85.16007),
    ("Kali Mandir", ["kali temple", "kali asthan", "kali mandir road"], "temple", 25.59045, 85.16262),
    ("Hanuman Mandir", ["hanuman temple", "bajrang bali mandir", "mandir"], "temple", 25.59148, 85.14947),
    ("Shani Dev Mandir", ["shani mandir", "shani temple"], "temple", 25.59617, 85.17454),
    ("Malahi Pakri", ["malahi pakdi", "malahi pakri chowk", "malahi pakri halt", "pakri"], "junction",
     25.59351, 85.15712),
    ("Bhootnath Halt", ["bhootnath station", "bhootnath", "bhutnath"], "transport", 25.58547, 85.17358),
    ("Kendriya Vidyalaya", ["kv", "kv school", "kendriya vidyalaya kankarbagh", "school"], "school",
     25.59872, 85.16102),
    ("College of Commerce", ["commerce college", "college of commerce", "college"], "school", 25.60127, 85.16201),
    ("Patliputra University", ["university", "patliputra university"], "school", 25.60239, 85.15946),
    ("Govt Boys School", ["sarkari school", "government school", "boys school", "school"], "school",
     25.60575, 85.16788),
    ("Rabindra Balika Vidyalaya", ["rabindra school", "girls school", "balika vidyalaya", "school"], "school",
     25.60881, 85.15807),
    ("Tinkonia Park", ["tin konia park", "tinkonia", "teen konia park"], "ground", 25.60779, 85.15739),
    ("Patel Park", ["patel park"], "ground", 25.60187, 85.15297),
    ("Lohia Park", ["lohiya park", "lohia nagar park", "lohia nagar"], "ground", 25.60035, 85.14960),
    ("Doctors Colony", ["doctors colony park", "doctor colony"], "locality", 25.60110, 85.15883),
    ("LIC Colony", ["lic colony park", "lic colony"], "locality", 25.59652, 85.16236),
    ("Joggers Park", ["jogger park", "joggers park"], "ground", 25.60912, 85.16053),
    ("Gravity Mall", ["mall", "gravity"], "landmark", 25.60271, 85.15575),
    ("M Bazaar", ["m bazar", "big bazaar"], "market", 25.59565, 85.17500),
    ("Mahavir Arogya Sansthan", ["mahavir arogya", "arogya sansthan", "hospital"], "hospital", 25.60239, 85.14343),
    ("Rajendra Nagar Hospital", ["rajendra nagar aspatal", "hospital"], "hospital", 25.60732, 85.16240),
    ("Kankarbagh Dispensary", ["dispensary", "sarkari dispensary"], "hospital", 25.60227, 85.15481),
    ("Road No. 6", ["road no 6", "road number 6", "road no. 6", "road 6", "gali 6", "gali number 6"], "locality",
     25.60800, 85.16300),
    ("Road No. 3", ["road no 3", "road number 3", "road no. 3", "road 3", "gali 3"], "locality",
     25.60900, 85.16000),
    ("Hanuman Nagar", ["hanuman nagar main road", "hanuman nagar"], "locality", 25.59000, 85.16050),
    ("Navneet Colony", ["navneet housing colony", "navneet colony"], "locality", 25.59100, 85.16400),
    ("Bahadurpur Housing Colony", ["bahadurpur", "housing colony", "bahadurpur colony"], "locality",
     25.59291, 85.17115),
    ("Saidpur", ["saidpur road", "saidpur hostel", "saidpur nala"], "locality", 25.61200, 85.16900),
    ("Gandhi Maidan", ["maidan", "gandhi ground"], "ground", 25.61700, 85.14700),
]

# Simulated relief camps, at real public grounds and schools.
SHELTERS = [
    ("SH-1", "Moin-ul-Haq Stadium Relief Camp", 500, 25.60740, 85.16790),
    ("SH-2", "Patliputra Stadium Relief Camp", 400, 25.59520, 85.15300),
    ("SH-3", "College of Commerce Shelter", 250, 25.60100, 85.16240),
    ("SH-4", "Kendriya Vidyalaya Shelter", 200, 25.59840, 85.16140),
]


def _lm(name: str) -> tuple[float, float]:
    row = next(l for l in LANDMARKS if l[0] == name)
    return row[3], row[4]


def _base(name: str, supplies: list[str], at: str, capacity: int) -> TeamBase:
    lat, lon = _lm(at)
    return TeamBase(name, supplies, lat, lon, capacity)


TEAM_BASES = {
    "redcross": [
        _base("Team A", ["food", "water", "boat"], "Moin-ul-Haq Stadium", 3),
        _base("Team B", ["medicine", "water", "first_aid", "baby_food"], "Nalanda Medical College Hospital", 3),
        _base("Team C", ["boat", "evacuation", "first_aid"], "Patliputra Stadium", 2),
        _base("Team D", ["food", "blankets", "water"], "Bhootnath Halt", 3),
    ],
    "local_ngo": [
        _base("Team Alpha", ["food", "water", "blankets"], "Tinkonia Park", 3),
        _base("Team Beta", ["medicine", "first_aid", "baby_food"], "Kankarbagh Dispensary", 2),
        _base("Team Gamma", ["boat", "evacuation", "water"], "Bazar Samiti", 2),
    ],
}

DRILL = DrillScript(
    messages=[
        (0, "whatsapp", "pls help 5 ppl stuck near Shiv mandir ward 11 Kankarbagh, dadi needs BP medicine, paani ghar mein aa raha hai", "KUMAR"),
        (4, "phone", "Call note: R. Kumar family, ward 11 near temple, 5 members, water entering house", "KUMAR"),
        (7, "social", "Rajendra Nagar road no 6 ward 7: nobody has come here since morning, 3 kids, no food", "ROAD6"),
        (10, "whatsapp", "Das family ward 14 Malahi Pakri ke paas, 6 log, nani bimar hai, paani ghar mein aa raha hai, boat bhejo", "DAS"),
    ],
    # The main road south through Kankarbagh, past Malahi Pakri.
    flood_road="Malahi Pakdi Road",
    # Rajendra Nagar, Kankarbagh, Malahi Pakri and Hanuman Nagar stayed under water longest in 2019.
    hotspot_wards=[7, 10, 11, 14, 15],
    example_road_report="Malahi Pakdi Road is flooded",
    example_help="5 log chhat pe fanse hain, Shiv mandir ke paas ward 11 Kankarbagh, dadi ko BP ki dawai chahiye",
)


def wards() -> list[dict]:
    out = []
    for r in range(4):
        for c in range(4):
            num = r * 4 + c + 1
            top, bottom = LAT_EDGES[r], LAT_EDGES[r + 1]
            left, right = LON_EDGES[c], LON_EDGES[c + 1]
            out.append({
                "num": num,
                "name": WARD_NAMES[num],
                "bank": "north" if r < 2 else "south",  # of the railway
                "polygon": [[top, left], [top, right], [bottom, right], [bottom, left]],
                "lat": (top + bottom) / 2,
                "lon": (left + right) / 2,
            })
    return out


def build_region() -> Region:
    snap = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    reg = Region(name=NAME, title=TITLE, attribution=snap["attribution"])
    reg.junctions = [Junction(**j) for j in snap["junctions"]]
    reg.roads = [Road(**r) for r in snap["roads"]]
    reg.water_areas = snap.get("water_areas", [])
    reg.water_lines = snap.get("water_lines", [])
    reg.rail = snap.get("rail", [])
    reg.wards = wards()
    for i, (name, aliases, kind, lat, lon) in enumerate(LANDMARKS):
        reg.landmarks.append({"id": f"L{i + 1:02d}", "name": name, "aliases": aliases, "kind": kind,
                              "ward": ward_at(reg, lat, lon), "lat": lat, "lon": lon})
    for sid, name, cap, lat, lon in SHELTERS:
        reg.shelters.append({"id": sid, "name": name, "ward": ward_at(reg, lat, lon), "capacity": cap,
                             "lat": lat, "lon": lon})
    return reg


def route_check() -> tuple[str, str]:
    """Two junctions whose shortest route uses the drill's flood road, for the routing tests."""
    reg = build_region()
    return (nearest_junction(reg, 25.599736, 85.157934).id, nearest_junction(reg, 25.58925, 85.157128).id)
