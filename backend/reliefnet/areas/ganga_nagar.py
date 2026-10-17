"""Deterministic generator for "Ganga Nagar", the fictional demo town.

The town is a street grid split west-to-east by a river. Only three bridges
cross it, so a flooded bridge forces real detours. Wards, landmarks (with the
Hinglish names people actually use) and shelters sit on top of the grid."""
from __future__ import annotations

import math
import random

from . import DrillScript, Junction, Region, Road, TeamBase, haversine_m

NAME = "ganga_nagar"
# Not a real place: pins shared from real phones are snapped into it (see geo.from_pin).
FICTIONAL = True
BASE_LAT = 25.6200
BASE_LON = 85.1000
DLAT = 0.0034  # ~380 m
DLON = 0.0038  # ~380 m at this latitude
RIVER_GAP = 0.0062  # wider spacing between the two river banks
COLS = 10
ROWS = 8  # rows 0-3 north bank, 4-7 south bank
BRIDGES = {1: "Old Iron Bridge", 5: "NH-12 Bridge", 8: "Rail Bridge"}
ROW_NAMES = [
    "Ring Road North",
    "Canal Road",
    "Market Road",
    "Ganga Path",
    "Ghat Road",
    "Station Road",
    "School Road",
    "Ring Road South",
]
LOW_LYING_ROWS = {3, 4}


def col_name(c: int) -> str:
    return "NH-12" if c == 5 else f"Lane {c + 1}"


def row_lat(r: int) -> float:
    lat = BASE_LAT - r * DLAT
    if r >= 4:
        lat -= RIVER_GAP - DLAT
    return lat


def river_center_lat(lon: float) -> float:
    mid = (row_lat(3) + row_lat(4)) / 2
    return mid + 0.0007 * math.sin((lon - BASE_LON) * 260)


def ward_of(row: int, col: int) -> int:
    group = 0 if col <= 2 else 1 if col <= 4 else 2 if col <= 6 else 3
    band = 0 if row <= 1 else 1 if row <= 3 else 2 if row <= 5 else 3
    return band * 4 + group + 1


# (name, aliases, ward, kind, (dx, dy) offset inside the ward box 0..1)
LANDMARKS = [
    ("Collectorate", ["dm office", "collector office", "kachahri"], 1, "office", (0.4, 0.4)),
    ("Durga Mandir", ["durga temple", "durga ji mandir"], 2, "temple", (0.5, 0.3)),
    ("District Hospital", ["hospital", "sadar aspatal", "sadar hospital", "aspatal"], 2, "hospital", (0.3, 0.7)),
    ("Gandhi Maidan", ["maidan", "gandhi ground"], 3, "ground", (0.5, 0.5)),
    ("Ganga Nagar College", ["college", "degree college"], 3, "school", (0.8, 0.2)),
    ("Bus Stand", ["bus adda", "bus station"], 4, "transport", (0.6, 0.5)),
    ("Jama Masjid", ["masjid", "mosque", "badi masjid"], 5, "mosque", (0.4, 0.3)),
    ("Post Office", ["dakghar", "head post office"], 5, "office", (0.7, 0.7)),
    ("Sabzi Mandi", ["market", "mandi", "sabji mandi", "vegetable market"], 6, "market", (0.4, 0.4)),
    ("Patel Chowk", ["patel chauraha"], 6, "junction", (0.8, 0.8)),
    ("Kali Mandir", ["kali temple", "kali asthan"], 7, "temple", (0.5, 0.6)),
    ("Chhath Ghat", ["ghat", "chhath ghat", "river ghat"], 8, "ghat", (0.5, 0.85)),
    ("Hanuman Mandir", ["hanuman temple", "bajrang bali mandir"], 9, "temple", (0.4, 0.4)),
    ("Dhobi Ghat", ["dhobi ghat"], 9, "ghat", (0.6, 0.15)),
    ("Gurudwara", ["gurdwara", "sikh temple"], 10, "temple", (0.5, 0.5)),
    ("Govt Middle School", ["school", "sarkari school", "middle school", "school roof"], 10, "school", (0.3, 0.8)),
    ("Railway Station", ["station", "railway junction", "ganga nagar junction"], 11, "transport", (0.5, 0.4)),
    ("Cinema Hall", ["talkies", "picture hall", "cinema"], 11, "landmark", (0.7, 0.8)),
    ("Shiv Mandir", ["temple", "mandir", "shiv temple", "shiv ji mandir", "mahadev mandir"], 12, "temple", (0.35, 0.35)),
    ("Lane 4", ["lane no 4", "gali 4", "gali number 4", "lane four"], 12, "locality", (0.7, 0.7)),
    ("Eidgah", ["idgah", "eidgah maidan"], 13, "mosque", (0.4, 0.5)),
    ("Community Hall", ["samudayik bhawan", "community bhawan"], 13, "hall", (0.75, 0.3)),
    ("Water Tank", ["tanki", "pani tanki", "water tower"], 14, "landmark", (0.3, 0.3)),
    ("Stadium", ["sports stadium", "khel maidan"], 14, "ground", (0.7, 0.6)),
    ("Primary Health Centre", ["phc", "health centre", "swasthya kendra"], 15, "hospital", (0.4, 0.5)),
    ("Petrol Pump", ["petrol pump", "indian oil pump"], 15, "landmark", (0.8, 0.2)),
    ("Ambedkar Chowk", ["ambedkar chauraha", "ambedkar statue"], 16, "junction", (0.3, 0.4)),
    ("Rice Mill", ["chawal mill", "rice mill"], 16, "landmark", (0.75, 0.75)),
]

SHELTERS = [
    ("SH-1", "Gandhi Maidan Relief Camp", 3, 400, (0.45, 0.6)),
    ("SH-2", "Ganga Nagar College Shelter", 3, 250, (0.85, 0.3)),
    ("SH-3", "Stadium Relief Camp", 14, 500, (0.65, 0.5)),
    ("SH-4", "Community Hall Shelter", 13, 150, (0.8, 0.35)),
]


def build_region(seed: int = 7) -> Region:
    rng = random.Random(seed)
    reg = Region(name="ganga_nagar", title="Ganga Nagar",
                 attribution="Ganga Nagar is a fictional town. All data is illustrative.")
    jmap: dict[tuple[int, int], Junction] = {}
    for r in range(ROWS):
        for c in range(COLS):
            jit_lat = 0.0 if r in LOW_LYING_ROWS else rng.uniform(-0.12, 0.12) * DLAT
            j = Junction(
                id=f"J{r}{c}",
                lat=row_lat(r) + jit_lat,
                lon=BASE_LON + c * DLON + rng.uniform(-0.12, 0.12) * DLON,
            )
            jmap[(r, c)] = j
            reg.junctions.append(j)

    def add(a: Junction, b: Junction, name: str, kind: str, low: bool) -> None:
        rid = f"S{len(reg.roads) + 1:03d}"
        reg.roads.append(Road(rid, a.id, b.id, name, kind, low, round(haversine_m(a.lat, a.lon, b.lat, b.lon), 1)))

    for r in range(ROWS):
        for c in range(COLS - 1):
            # Thin out a few interior street segments so the grid is less regular.
            if r not in (0, 3, 4, 5, ROWS - 1) and rng.random() < 0.12:
                continue
            add(jmap[(r, c)], jmap[(r, c + 1)], ROW_NAMES[r], "road", r in LOW_LYING_ROWS)
    for c in range(COLS):
        for r in range(ROWS - 1):
            if r == 3:
                if c in BRIDGES:
                    add(jmap[(3, c)], jmap[(4, c)], BRIDGES[c], "bridge", True)
                continue
            if c not in (0, 5, COLS - 1) and rng.random() < 0.15:
                continue
            add(jmap[(r, c)], jmap[(r + 1, c)], col_name(c), "road", False)

    # Ward boxes from the junction grid.
    north_top = row_lat(0) + DLAT * 0.5
    south_bottom = row_lat(ROWS - 1) - DLAT * 0.5
    bank_n = row_lat(3) - DLAT * 0.25
    bank_s = row_lat(4) + DLAT * 0.25
    lat_bands = [
        (north_top, (row_lat(1) + row_lat(2)) / 2),
        ((row_lat(1) + row_lat(2)) / 2, bank_n),
        (bank_s, (row_lat(5) + row_lat(6)) / 2),
        ((row_lat(5) + row_lat(6)) / 2, south_bottom),
    ]
    west = BASE_LON - DLON * 0.5
    east = BASE_LON + (COLS - 1) * DLON + DLON * 0.5
    col_edges = [west, BASE_LON + 2.5 * DLON, BASE_LON + 4.5 * DLON, BASE_LON + 6.5 * DLON, east]
    for band, (top, bottom) in enumerate(lat_bands):
        for g in range(4):
            num = band * 4 + g + 1
            left, right = col_edges[g], col_edges[g + 1]
            reg.wards.append(
                {
                    "num": num,
                    "name": f"Ward {num}",
                    "bank": "north" if band < 2 else "south",
                    "polygon": [[top, left], [top, right], [bottom, right], [bottom, left]],
                    "lat": (top + bottom) / 2,
                    "lon": (left + right) / 2,
                    "box": (top, bottom, left, right),
                }
            )

    def place(ward: int, off: tuple[float, float]) -> tuple[float, float]:
        top, bottom, left, right = reg.wards[ward - 1]["box"]
        return top + (bottom - top) * off[1], left + (right - left) * off[0]

    for i, (name, aliases, ward, kind, off) in enumerate(LANDMARKS):
        lat, lon = place(ward, off)
        reg.landmarks.append(
            {"id": f"L{i + 1:02d}", "name": name, "aliases": aliases, "ward": ward, "kind": kind, "lat": lat, "lon": lon}
        )
    for sid, name, ward, cap, off in SHELTERS:
        lat, lon = place(ward, off)
        reg.shelters.append({"id": sid, "name": name, "ward": ward, "capacity": cap, "lat": lat, "lon": lon})

    steps = 60
    north_edge, south_edge = [], []
    for i in range(steps + 1):
        lon = west - DLON + (east - west + 2 * DLON) * i / steps
        mid = river_center_lat(lon)
        north_edge.append([mid + 0.0011, lon])
        south_edge.append([mid - 0.0011, lon])
    reg.water_areas = [{"name": "Ganga", "polygon": north_edge + south_edge[::-1]}]
    for w in reg.wards:
        w.pop("box")
    return reg


_J = {j.id: j for j in build_region().junctions}


def _base(name: str, supplies: list[str], junction: str, capacity: int) -> TeamBase:
    return TeamBase(name, supplies, _J[junction].lat, _J[junction].lon, capacity)


TEAM_BASES = {
    "redcross": [
        _base("Team A", ["food", "water", "boat"], "J15", 3),
        _base("Team B", ["medicine", "water", "first_aid", "baby_food"], "J25", 3),
        _base("Team C", ["boat", "evacuation", "first_aid"], "J52", 2),
        _base("Team D", ["food", "blankets", "water"], "J67", 3),
    ],
    "local_ngo": [
        _base("Team Alpha", ["food", "water", "blankets"], "J12", 3),
        _base("Team Beta", ["medicine", "first_aid", "baby_food"], "J57", 2),
        _base("Team Gamma", ["boat", "evacuation", "water"], "J48", 2),
    ],
}

DEFAULT_TEAMS = [
    _base("Team 1", ["food", "water", "medicine", "blankets"], "J24", 3),
    _base("Team 2", ["boat", "evacuation", "first_aid"], "J55", 2),
]

DRILL = DrillScript(
    messages=[
        (0, "whatsapp", "pls help 5 ppl stuck near Shiv mandir ward 12, dadi needs BP medicine, paani ghar mein aa raha hai", "KUMAR"),
        (4, "phone", "Call note: R. Kumar family, ward 12 near temple, 5 members, water entering house", "KUMAR"),
        (7, "social", "Ward 12 lane 4: nobody has come here since morning, 3 kids, no food", "LANE4"),
        (10, "whatsapp", "Das family ward 14 near water tanki, 6 log, nani bimar hai, paani ghar mein aa raha hai, boat bhejo", "DAS"),
    ],
    flood_road="NH-12 Bridge",
    # The south bank floods worse.
    hotspot_wards=list(range(9, 17)),
    example_road_report="NH-12 Bridge is flooded",
    example_help="5 log chhat pe fanse hain, Shiv mandir ke paas ward 12, dadi ko BP ki dawai chahiye",
)

def route_check() -> tuple[str, str]:
    """Two junctions whose shortest route uses the drill's flood road, for the routing tests."""
    return ("J25", "J55")
