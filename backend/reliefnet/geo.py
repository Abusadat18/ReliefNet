"""Geocoding against the region graph's own gazetteer.

Public geocoders do not know "Shiv mandir, ward 12". The region graph does:
every landmark carries the local names people use for it."""
from __future__ import annotations

import hashlib
import json
import math
import time

from rapidfuzz import fuzz, process

from .config import get_settings
from .db import REGION_GRAPH, query, redis
from . import areas
from .areas import haversine_m, nearest_on_line, point_in_polygon
from .areas.places import is_generic
from .parsing import road_forms

_cache: dict[str, tuple[float, object]] = {}
TTL = 30.0


async def _cached(key: str, loader):
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < TTL:
        return hit[1]
    val = await loader()
    _cache[key] = (time.monotonic(), val)
    return val


def invalidate() -> None:
    _cache.clear()


# gazetteer.py raises this number after each landmark change.
LANDMARKS_REV = "rn:gazetteer:rev"
_seen_rev: dict[str, str | None] = {}


async def _check_rev() -> None:
    # A coordinator can add a name in the API process; the workers see it on their next call.
    rev = await redis().get(LANDMARKS_REV)
    if _seen_rev.get("landmarks", "") != rev:
        _cache.pop("landmarks", None)
        _cache.pop("neighbourhoods", None)
        _seen_rev["landmarks"] = rev


async def landmarks() -> list[dict]:
    """Hand-written landmarks first, then the coordinators' landmarks, then OpenStreetMap places.

    On a tie, a name match picks the first landmark, so this order matters."""
    await _check_rev()

    async def load():
        return await query(
            REGION_GRAPH,
            "MATCH (l:Landmark) RETURN l.id AS id, l.name AS name, l.aliases AS aliases, l.ward AS ward,"
            " l.kind AS kind, l.lat AS lat, l.lon AS lon, coalesce(l.source, 'hand') AS source"
            " ORDER BY CASE coalesce(l.source, 'hand') WHEN 'hand' THEN 0 WHEN 'app' THEN 1 ELSE 2 END, l.id",
            readonly=True,
        )

    return await _cached("landmarks", load)


async def neighbourhoods() -> list[dict]:
    """Named neighbourhoods. `polygon` is a list of [lat, lon], or None when only the centre is known."""
    await _check_rev()

    async def load():
        rows = await query(
            REGION_GRAPH,
            "MATCH (n:Neighbourhood) RETURN n.id AS id, n.name AS name, n.aliases AS aliases, n.ward AS ward,"
            " n.lat AS lat, n.lon AS lon, n.polygon AS polygon"
            " ORDER BY CASE coalesce(n.source, 'hand') WHEN 'hand' THEN 0 ELSE 1 END, n.id",
            readonly=True,
        )
        for r in rows:
            r["polygon"] = json.loads(r["polygon"]) if r["polygon"] else None
        return rows

    return await _cached("neighbourhoods", load)


async def road_lines() -> dict[str, list[list[list[float]]]]:
    """Each road name with the shapes of its pieces, for placing a household on a named road."""
    from .routing import snapshot

    async def load():
        out: dict[str, list] = {}
        for r in await snapshot():
            out.setdefault(r["name"], []).append(r["coords"])
        return out

    return await _cached("road_lines", load)


async def wards() -> list[dict]:
    async def load():
        rows = await query(
            REGION_GRAPH,
            "MATCH (w:Ward) RETURN w.num AS num, w.name AS name, w.bank AS bank, w.lat AS lat, w.lon AS lon,"
            " w.polygon AS polygon ORDER BY w.num",
            readonly=True,
        )
        for r in rows:
            r["polygon"] = json.loads(r["polygon"])
        return rows

    return await _cached("wards", load)


async def junctions() -> list[dict]:
    async def load():
        return await query(
            REGION_GRAPH, "MATCH (j:Junction) RETURN j.id AS id, j.lat AS lat, j.lon AS lon", readonly=True
        )

    return await _cached("junctions", load)


async def landmark_names() -> list[tuple[str, list[str]]]:
    return [(l["name"], l["aliases"]) for l in await landmarks()]


async def neighbourhood_names() -> list[tuple[str, list[str]]]:
    return [(n["name"], n["aliases"]) for n in await neighbourhoods()]


async def clue_road_names() -> list[str]:
    """Road names that people type. Generated names ("Lane near Kali Mandir 3") are left out."""
    return [n for n in await road_lines() if road_forms(n)]


def _jitter(seed: str, meters: float = 70.0) -> tuple[float, float]:
    h = hashlib.sha1(seed.encode()).digest()
    ang = h[0] / 255 * 2 * math.pi
    dist = 15 + h[1] / 255 * meters
    return (dist * math.cos(ang)) / 111_000, (dist * math.sin(ang)) / 100_300


async def resolve(landmark: str, ward: int, location_text: str, seed: str, neighbourhood: str = "",
                  road: str = "") -> dict:
    """Return lat/lon plus how sure we are. `seed` keeps one family's jitter stable. See `locate`."""
    return locate(await landmarks(), await wards(), await neighbourhoods() if neighbourhood else [],
                  await road_lines() if road else {}, landmark=landmark, ward=ward, location_text=location_text,
                  seed=seed, neighbourhood=neighbourhood, road=road)


NEAR_ROAD_M = 300.0  # a landmark this close to the named road is on that road
NEAR_ROAD_AREA_M = 700.0  # the same for a landmark that is an area ("locality"), not a point
HOOD_POINT_M = 1200.0  # how far a neighbourhood with only a centre reaches; a suburb is about this big
HOOD_EDGE_M = 150.0  # a point this close outside a neighbourhood outline still counts as inside
ROAD_STEP_M = 25.0


def _in_hood(nb: dict, lat: float, lon: float) -> bool:
    poly = nb.get("polygon")
    if poly:
        return point_in_polygon(lat, lon, poly) or nearest_on_line(lat, lon, poly + poly[:1])[0] <= HOOD_EDGE_M
    return haversine_m(lat, lon, nb["lat"], nb["lon"]) <= HOOD_POINT_M


def _ward_of(wlist: list[dict], lat: float, lon: float) -> int:
    return next((w["num"] for w in wlist if point_in_polygon(lat, lon, w["polygon"])), 0)


def match_neighbourhood(nbs: list[dict], text: str) -> dict | None:
    """The neighbourhood with this name or local name; a close spelling counts too."""
    t = text.strip().lower()
    if not t:
        return None
    for nb in nbs:
        if t == nb["name"].lower() or t in nb["aliases"]:
            return nb
    choices = {f"{i}|{a}": a.lower() for i, nb in enumerate(nbs) for a in [nb["name"], *nb["aliases"]]}
    best = process.extractOne(t, choices, scorer=fuzz.ratio, score_cutoff=88)
    return nbs[int(best[2].split("|")[0])] if best else None


def road_candidates(lines: dict[str, list], road: str) -> dict[str, list]:
    """Every road that a message's road name can mean: "Road No.1" is in two colonies."""
    want = road_forms(road)
    return {name: shapes for name, shapes in lines.items() if want & road_forms(name)}


def _samples(cands: dict[str, list]) -> list[tuple[str, float, float]]:
    out = []
    for name, shapes in cands.items():
        for line in shapes:
            out.append((name, *line[0]))
            for a, b in zip(line, line[1:]):
                steps = max(1, int(haversine_m(*a, *b) // ROAD_STEP_M))
                for k in range(1, steps + 1):
                    out.append((name, a[0] + (b[0] - a[0]) * k / steps, a[1] + (b[1] - a[1]) * k / steps))
    return out


def _hood_points(nb: dict) -> list[tuple[float, float]]:
    """A grid of points that cover a neighbourhood."""
    poly = nb.get("polygon")
    if poly:
        lats, lons = [p[0] for p in poly], [p[1] for p in poly]
    else:
        dlat, dlon = HOOD_POINT_M / 111_000, HOOD_POINT_M / 100_300
        lats, lons = [nb["lat"] - dlat, nb["lat"] + dlat], [nb["lon"] - dlon, nb["lon"] + dlon]
    s, w, n, e = min(lats), min(lons), max(lats), max(lons)
    pts = [(s + (i + 0.5) / 14 * (n - s), w + (j + 0.5) / 14 * (e - w)) for i in range(14) for j in range(14)]
    return [p for p in pts if _in_hood(nb, *p)] or [(nb["lat"], nb["lon"])]


def _pick_landmark(lms: list[dict], ward: int, texts: tuple[str, ...], nb: dict | None,
                   cands: dict[str, list]) -> dict | None:
    candidates = [l for l in lms if not ward or l["ward"] == ward] or lms
    choices = {f"{l['id']}|{alias}": alias.lower() for l in candidates for alias in [l["name"], *l["aliases"]]}
    for text in texts:
        if not text:
            continue
        if cands and text is not texts[0]:
            # In free text that names a road, a generic alias ("mandir") is often part of the road's name.
            choices = {k: v for k, v in choices.items() if not is_generic(v)}
        hits = process.extract(text.lower(), choices, scorer=fuzz.WRatio, score_cutoff=82, limit=25)
        if not hits:
            continue
        top = hits[0][1]
        ids = list(dict.fromkeys(h[2].split("|")[0] for h in hits if h[1] >= top))
        tied = [next(l for l in lms if l["id"] == i) for i in ids]
        if len(tied) > 1 and (nb or cands):
            # Two places with one name ("shiv mandir"): the other clues say which one.
            def fit(l: dict) -> tuple:
                road_m = min((nearest_on_line(l["lat"], l["lon"], s)[0] for v in cands.values() for s in v),
                             default=0.0)
                return (bool(nb) and not _in_hood(nb, l["lat"], l["lon"]), road_m > NEAR_ROAD_M, road_m)
            return min(tied, key=fit)
        return tied[0]
    return None


def locate(lms: list[dict], wlist: list[dict], nbs: list[dict], lines: dict[str, list], *, landmark: str,
           ward: int, location_text: str, seed: str, neighbourhood: str = "", road: str = "") -> dict:
    """Score the location clues of one request together. No network, no database.

    A landmark gives the point. A road pulls the point onto the road, when the road is near.
    A neighbourhood and a ward narrow the area, and must agree with the point.
    Without a landmark, the point is on the road inside the neighbourhood and the ward, or at the
    neighbourhood's centre. Each clue that agrees adds to `geo_confidence`; a conflict lowers it."""
    nb = match_neighbourhood(nbs, neighbourhood) if neighbourhood else None
    cands = road_candidates(lines, road) if road else {}
    w = next((x for x in wlist if x["num"] == ward), None)
    agree: list[str] = []
    conflict: list[str] = []
    road_name = ""

    def fits(lat: float, lon: float) -> bool:
        return (nb is None or _in_hood(nb, lat, lon)) and (w is None or point_in_polygon(lat, lon, w["polygon"]))

    chosen = _pick_landmark(lms, ward, (landmark, location_text), nb, cands)
    if chosen:
        lat, lon = chosen["lat"], chosen["lon"]
        agree.append(f"landmark {chosen['name']}")
        if ward:
            (agree if chosen["ward"] == ward else conflict).append(f"ward {ward}")
        if nb:
            (agree if _in_hood(nb, lat, lon) else conflict).append(f"neighbourhood {nb['name']}")
        jitter = 70.0
        if cands:
            dist, point, road_name = min(((*nearest_on_line(lat, lon, s), name) for name, v in cands.items()
                                          for s in v), key=lambda x: x[0])
            if dist <= (NEAR_ROAD_AREA_M if chosen.get("kind") == "locality" else NEAR_ROAD_M):
                lat, lon = point
                jitter = 20.0
                agree.append(f"road {road_name} ({dist:.0f} m from the landmark)")
            else:
                conflict.append(f"road {road_name} ({dist:.0f} m from the landmark)")
        out_ward = chosen["ward"]
        conf = "medium" if conflict else "high"
    elif cands:
        pts = _samples(cands)
        in_nb = [p for p in pts if nb is None or _in_hood(nb, p[1], p[2])]
        in_w = [p for p in pts if w is None or point_in_polygon(p[1], p[2], w["polygon"])]
        ok = [p for p in in_nb if fits(p[1], p[2])]
        # When the clues do not meet on the road, trust the neighbourhood before the ward number.
        pool = ok or (in_nb if nb and in_nb else in_w if w and in_w else pts)
        ref = (nb["lat"], nb["lon"]) if nb else (w["lat"], w["lon"]) if w else None
        road_name, lat, lon = min(pool, key=lambda p: haversine_m(p[1], p[2], *ref)) if ref else pool[len(pool) // 2]
        jitter = 20.0
        agree.append(f"road {road_name}")
        if nb:
            (agree if in_nb else conflict).append(f"neighbourhood {nb['name']}")
        if w:
            (agree if (ok if nb and in_nb else in_w) else conflict).append(f"ward {ward}")
        out_ward = _ward_of(wlist, lat, lon) or ward
        conf = "medium" if (nb or w) and not conflict else "low"
    elif nb:
        pts = _hood_points(nb)
        ok = [p for p in pts if w is None or point_in_polygon(*p, w["polygon"])]
        pool = ok or pts
        lat, lon = sum(p[0] for p in pool) / len(pool), sum(p[1] for p in pool) / len(pool)
        # The middle of a curved area can be outside it; then take the nearest point inside.
        if not (fits(lat, lon) if ok else _in_hood(nb, lat, lon)):
            lat, lon = min(pool, key=lambda p: haversine_m(*p, lat, lon))
        jitter = 120.0
        agree.append(f"neighbourhood {nb['name']}")
        if w:
            (agree if ok else conflict).append(f"ward {ward}")
        out_ward = _ward_of(wlist, lat, lon) or nb["ward"]
        conf = "low"
    elif w:
        dlat, dlon = _jitter(seed, 220.0)
        return {"lat": w["lat"] + dlat, "lon": w["lon"] + dlon, "ward": ward, "landmark": "", "neighbourhood": "",
                "road": "", "geo_confidence": "low", "why": f"only ward {ward}"}
    else:
        center = wlist[len(wlist) // 2] if wlist else {"lat": 0.0, "lon": 0.0}
        return {"lat": center["lat"], "lon": center["lon"], "ward": 0, "landmark": "", "neighbourhood": "",
                "road": "", "geo_confidence": "none", "why": "no location clue"}
    dlat, dlon = _jitter(seed, jitter)
    why = ", ".join(agree) + (f"; does not agree: {', '.join(conflict)}" if conflict else "")
    return {"lat": lat + dlat, "lon": lon + dlon, "ward": out_ward, "landmark": chosen["name"] if chosen else "",
            "neighbourhood": nb["name"] if nb else "", "road": road_name, "geo_confidence": conf, "why": why}


TOWN_RADIUS_M = 8000.0  # a pin further than this from the town is not in the flood area


def snap_pins() -> bool:
    """Move far-away pins into the area? DEMO_SNAP_PINS decides; unset, only for a fictional area."""
    setting = get_settings().demo_snap_pins
    return setting if setting is not None else bool(getattr(areas.module(), "FICTIONAL", False))
NEAR_LANDMARK_M = 250.0


def _town_center(wlist: list[dict]) -> tuple[float, float]:
    return sum(w["lat"] for w in wlist) / len(wlist), sum(w["lon"] for w in wlist) / len(wlist)


def snap_point(wlist: list[dict], ward_hint: int, seed: str) -> dict:
    """A stable, believable spot in the flood zone, for a pin that is not in the town.

    In a fictional area, a phone sharing its real GPS from anywhere else would otherwise
    put a request outside the map (see `snap_pins`). The ward is the one the person picked, or one chosen from
    `seed`. The same seed always gives the same spot. Marked low confidence, so Triage asks
    for a call back."""
    ward = next((w for w in wlist if w["num"] == ward_hint), None) or wlist[
        int(hashlib.sha1(seed.encode()).hexdigest(), 16) % len(wlist)
    ]
    dlat, dlon = _jitter(seed, 220.0)
    return {"lat": ward["lat"] + dlat, "lon": ward["lon"] + dlon, "ward": ward["num"], "landmark": "",
            "geo_confidence": "low", "snapped": True}


async def from_pin(lat: float, lon: float, ward_hint: int = 0, seed: str = "") -> dict | None:
    """Location from a shared pin. A pin outside the town is snapped into it (see `snap_point`),
    or returns None when DEMO_SNAP_PINS is off and the caller falls back to ward and landmark."""
    wlist = await wards()
    if wlist:
        clat, clon = _town_center(wlist)
        if haversine_m(lat, lon, clat, clon) > TOWN_RADIUS_M:
            return snap_point(wlist, ward_hint, seed or f"{lat:.4f},{lon:.4f}") if snap_pins() else None
    near, best = "", NEAR_LANDMARK_M
    for l in await landmarks():
        d = haversine_m(lat, lon, l["lat"], l["lon"])
        if d < best:
            near, best = l["name"], d
    return {"lat": lat, "lon": lon, "ward": await ward_at(lat, lon) or ward_hint, "landmark": near,
            "geo_confidence": "high"}


async def nearest_junction(lat: float, lon: float) -> str:
    js = await junctions()
    return min(js, key=lambda j: haversine_m(lat, lon, j["lat"], j["lon"]))["id"]


async def ward_at(lat: float, lon: float) -> int:
    for w in await wards():
        lats = [p[0] for p in w["polygon"]]
        lons = [p[1] for p in w["polygon"]]
        if min(lats) <= lat <= max(lats) and min(lons) <= lon <= max(lons):
            return w["num"]
    return 0
