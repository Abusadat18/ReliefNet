"""Deterministic generator for "Ganga Nagar", the fictional demo town.

The town is a street grid split west-to-east by a river. Only three bridges
cross it, so a flooded bridge forces real detours. Wards, landmarks (with the
Hinglish names people actually use) and shelters sit on top of the grid."""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

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


@dataclass
class Junction:
    id: str
    lat: float
    lon: float
    row: int
    col: int


@dataclass
class Road:
    id: str
    a: str
    b: str
    name: str
    kind: str
    low_lying: bool
    length_m: float


@dataclass
class Region:
    junctions: list[Junction] = field(default_factory=list)
    roads: list[Road] = field(default_factory=list)
    wards: list[dict] = field(default_factory=list)
    landmarks: list[dict] = field(default_factory=list)
    shelters: list[dict] = field(default_factory=list)
    river: list[list[float]] = field(default_factory=list)


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


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
    reg = Region()
    jmap: dict[tuple[int, int], Junction] = {}
    for r in range(ROWS):
        for c in range(COLS):
            jit_lat = 0.0 if r in LOW_LYING_ROWS else rng.uniform(-0.12, 0.12) * DLAT
            j = Junction(
                id=f"J{r}{c}",
                lat=row_lat(r) + jit_lat,
                lon=BASE_LON + c * DLON + rng.uniform(-0.12, 0.12) * DLON,
                row=r,
                col=c,
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
    reg.river = north_edge + south_edge[::-1]
    for w in reg.wards:
        w.pop("box")
    return reg


TEAM_BASES = {
    # slug -> list of (team name, supplies, base junction, capacity)
    "redcross": [
        ("Team A", ["food", "water", "boat"], "J15", 3),
        ("Team B", ["medicine", "water", "first_aid", "baby_food"], "J25", 3),
        ("Team C", ["boat", "evacuation", "first_aid"], "J52", 2),
        ("Team D", ["food", "blankets", "water"], "J67", 3),
    ],
    "local_ngo": [
        ("Team Alpha", ["food", "water", "blankets"], "J12", 3),
        ("Team Beta", ["medicine", "first_aid", "baby_food"], "J57", 2),
        ("Team Gamma", ["boat", "evacuation", "water"], "J48", 2),
    ],
}

DEFAULT_TEAMS = [
    ("Team 1", ["food", "water", "medicine"], "J24", 3),
    ("Team 2", ["boat", "evacuation", "first_aid"], "J55", 2),
]
