"""Operation areas: the real or fictional place that the region graph describes.

Each area is one module in this package. It provides `build_region()`, its
team bases, and the names the flood drill uses. `AREA` in the settings
selects one; the region graph holds one area at a time.

To add an area, copy `patna.py`, change the box and the local names, then run
`python -m reliefnet.areas.import_osm <name>` to download its roads, and
`python -m reliefnet.areas.import_osm <name> --places` for its named places."""
from __future__ import annotations

import hashlib
import importlib
import json
import math
from dataclasses import dataclass, field
from functools import lru_cache
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
    # Named neighbourhoods (see `places.neighbourhoods`), each with an outline or only a centre.
    neighbourhoods: list[dict] = field(default_factory=list)
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
    from . import places

    m = module(name)
    reg = m.build_region()
    osm = places.load(m)
    if osm or places.load_neighbourhoods(m):
        reg.attribution = f"{reg.attribution}. {places.ATTRIBUTION}" if reg.attribution else places.ATTRIBUTION
    reg.neighbourhoods = places.neighbourhoods(getattr(m, "NEIGHBOURHOODS", []), places.load_neighbourhoods(m),
                                               reg.wards)
    blocked = [reg.title, *(w["name"] for w in reg.wards), *{r.name for r in reg.roads},
               *(n["name"] for n in reg.neighbourhoods)]
    reg.landmarks = places.merge(reg.landmarks, osm, reg.wards, blocked)
    return reg


def _digest(data) -> str:
    return hashlib.sha1(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()[:12]


def version(name: str | None = None) -> str:
    """Changes when the roads, wards or shelters change. Landmarks have their own `landmark_version`,
    so a new landmark or alias does not rebuild the roads and lose their flood state."""
    reg = region(name)
    return _digest({"roads": [r.__dict__ for r in reg.roads], "junctions": [j.__dict__ for j in reg.junctions],
                    "wards": reg.wards, "shelters": reg.shelters, "water": [reg.water_areas, reg.water_lines],
                    "rail": reg.rail})


def landmark_version(name: str | None = None) -> str:
    """Changes when a hand-written landmark, an imported OpenStreetMap place or a neighbourhood changes."""
    reg = region(name)
    return _digest({"landmarks": reg.landmarks, "neighbourhoods": reg.neighbourhoods,
                    "attribution": reg.attribution})


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


def _xy(lat: float, lon: float, lat0: float) -> tuple[float, float]:
    return lon * 111_320 * math.cos(math.radians(lat0)), lat * 110_540


def nearest_on_line(lat: float, lon: float, line: list[list[float]]) -> tuple[float, list[float]]:
    """The point on a polyline nearest to (lat, lon), and its distance in metres."""
    if len(line) == 1:
        return haversine_m(lat, lon, *line[0]), list(line[0])
    px, py = _xy(lat, lon, lat)
    best = (math.inf, list(line[0]))
    for a, b in zip(line, line[1:]):
        ax, ay = _xy(*a, lat)
        bx, by = _xy(*b, lat)
        dx, dy = bx - ax, by - ay
        t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
        d = math.hypot(px - ax - t * dx, py - ay - t * dy)
        if d < best[0]:
            best = (d, [a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])])
    return best


def polygon_area_m2(poly: list[list[float]]) -> float:
    if len(poly) < 3:
        return 0.0
    lat0 = sum(p[0] for p in poly) / len(poly)
    pts = [_xy(*p, lat0) for p in poly]
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]))) / 2


def polygon_centre(poly: list[list[float]]) -> tuple[float, float]:
    """The area centroid of a polygon, or the mean of its points when it has no area."""
    a = cx = cy = 0.0
    for (y1, x1), (y2, x2) in zip(poly, poly[1:] + poly[:1]):
        cross = x1 * y2 - x2 * y1
        a += cross
        cx += (x1 + x2) * cross
        cy += (y1 + y2) * cross
    if abs(a) < 1e-12:
        return sum(p[0] for p in poly) / len(poly), sum(p[1] for p in poly) / len(poly)
    return cy / (3 * a), cx / (3 * a)


def nearest_junction(reg: Region, lat: float, lon: float) -> Junction:
    return min(reg.junctions, key=lambda j: haversine_m(lat, lon, j.lat, j.lon))


def team_bases(slug: str, name: str | None = None) -> list[TeamBase]:
    m = module(name)
    return m.TEAM_BASES.get(slug, [])


def drill(name: str | None = None) -> DrillScript:
    return module(name).DRILL
