"""Geocoding against the region graph's own gazetteer.

Public geocoders do not know "Shiv mandir, ward 12". The region graph does:
every landmark carries the local names people use for it."""
from __future__ import annotations

import hashlib
import json
import math
import time

from rapidfuzz import fuzz, process

from .db import REGION_GRAPH, query
from .region_data import haversine_m

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
