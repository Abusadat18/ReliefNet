"""Operation areas: the real or fictional place that the region graph describes.

Each area is one module in this package. It provides `build_region()`, its
team bases, and the names the flood drill uses. `AREA` in the settings
selects one; the region graph holds one area at a time.

To add an area, copy `patna.py`, change the box and the local names, then run
`python -m reliefnet.areas.import_osm <name>` to download its roads."""
from __future__ import annotations

import hashlib
import importlib
import math
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from types import ModuleType

AREAS = {
    "patna": "Rajendra Nagar and Kankarbagh, Patna (real roads, 2019 waterlogging)",
    "ganga_nagar": "Ganga Nagar (fictional grid town, works offline)",
}


@dataclass
class Junction:
    id: str
    lat: float
    lon: float


@dataclass
class Road:
    id: str
    a: str
    b: str
    name: str
    kind: str  # road | bridge | underpass
    low_lying: bool
    length_m: float
    # The road's shape from a to b; straight when empty.
    geom: list[list[float]] = field(default_factory=list)


@dataclass
class TeamBase:
    name: str
    supplies: list[str]
    lat: float
    lon: float
    capacity: int


@dataclass
class DrillScript:
    """The scripted moments of the demo drill, in the area's own names."""

    # (seconds after start, channel, text, ground-truth household id)
    messages: list[tuple[int, str, str, str]]
    # The road that two teams report flooded, and which teams report it.
    flood_road: str
    flood_reporters: tuple[str, str] = ("Team A", "Team C")
    flood_at_s: tuple[int, int] = (55, 62)
    # Wards that flood worst; the drill sends more requests from them.
    hotspot_wards: list[int] = field(default_factory=list)
    # Example lines for the volunteer chat and help form.
    example_road_report: str = ""
    example_help: str = ""


@dataclass
class Region:
    name: str = ""
    title: str = ""
    junctions: list[Junction] = field(default_factory=list)
    roads: list[Road] = field(default_factory=list)
    wards: list[dict] = field(default_factory=list)
    landmarks: list[dict] = field(default_factory=list)
    shelters: list[dict] = field(default_factory=list)
    # Water areas as closed polygons (a wide river) and lines (drains, canals).
    water_areas: list[dict] = field(default_factory=list)
    water_lines: list[dict] = field(default_factory=list)
    rail: list[list[list[float]]] = field(default_factory=list)
    attribution: str = ""


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def module(name: str | None = None) -> ModuleType:
    if name is None:
        from ..config import get_settings

        name = get_settings().area
    if name not in AREAS:
        raise ValueError(f"unknown AREA {name!r}; choose one of {', '.join(AREAS)}")
    return importlib.import_module(f"{__name__}.{name}")


@lru_cache
def region(name: str | None = None) -> Region:
    return module(name).build_region()


def version(name: str | None = None) -> str:
    """Changes when anything in the area changes: a new OSM import, a new landmark alias."""
    m = module(name)
    snap = getattr(m, "SNAPSHOT", None)
    raw = (snap.read_bytes() if snap else b"") + Path(m.__file__).read_bytes()
    return hashlib.sha1(raw).hexdigest()[:12]


def junction_version(name: str | None = None) -> str:
    """Changes only when the junctions change. Org graphs store junction ids (team bases)."""
    raw = "|".join(f"{j.id},{j.lat},{j.lon}" for j in region(name).junctions)
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


def ward_at(reg: Region, lat: float, lon: float) -> int:
    for w in reg.wards:
        if point_in_polygon(lat, lon, w["polygon"]):
            return w["num"]
    return 0


def point_in_polygon(lat: float, lon: float, poly: list[list[float]]) -> bool:
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        (yi, xi), (yj, xj) = poly[i], poly[j]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def nearest_junction(reg: Region, lat: float, lon: float) -> Junction:
    return min(reg.junctions, key=lambda j: haversine_m(lat, lon, j.lat, j.lon))


def team_bases(slug: str, name: str | None = None) -> list[TeamBase]:
    m = module(name)
    return m.TEAM_BASES.get(slug, m.DEFAULT_TEAMS)


def drill(name: str | None = None) -> DrillScript:
    return module(name).DRILL
