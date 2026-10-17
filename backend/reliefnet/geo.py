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
from .db import REGION_GRAPH, query
from . import areas
from .areas import haversine_m

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


async def landmarks() -> list[dict]:
    async def load():
        return await query(
            REGION_GRAPH,
            "MATCH (l:Landmark) RETURN l.id AS id, l.name AS name, l.aliases AS aliases, l.ward AS ward,"
            " l.kind AS kind, l.lat AS lat, l.lon AS lon",
            readonly=True,
        )

    return await _cached("landmarks", load)


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


def _jitter(seed: str, meters: float = 70.0) -> tuple[float, float]:
    h = hashlib.sha1(seed.encode()).digest()
    ang = h[0] / 255 * 2 * math.pi
    dist = 15 + h[1] / 255 * meters
    return (dist * math.cos(ang)) / 111_000, (dist * math.sin(ang)) / 100_300


async def resolve(landmark: str, ward: int, location_text: str, seed: str) -> dict:
    """Return lat/lon plus how sure we are. `seed` keeps one family's jitter stable."""
    lms = await landmarks()
    wlist = await wards()
    chosen = None
    candidates = [l for l in lms if not ward or l["ward"] == ward] or lms
    for text in (landmark, location_text):
        if not text:
            continue
        choices = {}
        for l in candidates:
            for alias in [l["name"], *l["aliases"]]:
                choices[f"{l['id']}|{alias}"] = alias.lower()
        best = process.extractOne(text.lower(), choices, scorer=fuzz.WRatio, score_cutoff=82)
        if best:
            lid = best[2].split("|")[0]
            chosen = next(l for l in lms if l["id"] == lid)
            break
    dlat, dlon = _jitter(seed)
    if chosen:
        return {
            "lat": chosen["lat"] + dlat,
            "lon": chosen["lon"] + dlon,
            "ward": chosen["ward"],
            "landmark": chosen["name"],
            "geo_confidence": "high" if ward == chosen["ward"] or not ward else "medium",
        }
    w = next((w for w in wlist if w["num"] == ward), None)
    if w:
        dlat, dlon = _jitter(seed, 220.0)
        return {"lat": w["lat"] + dlat, "lon": w["lon"] + dlon, "ward": ward, "landmark": "", "geo_confidence": "low"}
    center = wlist[len(wlist) // 2] if wlist else {"lat": 0.0, "lon": 0.0}
    return {"lat": center["lat"], "lon": center["lon"], "ward": 0, "landmark": "", "geo_confidence": "none"}


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
