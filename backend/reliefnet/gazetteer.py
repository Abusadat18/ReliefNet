"""The landmarks and neighbourhoods in the shared region graph, and the local names that coordinators add.

A coordinator can add a local name to a landmark or to a neighbourhood (`add_alias`).
A region rebuild deletes the region graph, so the graph alone cannot keep a name
that a coordinator added. Each added landmark and alias is also kept in Redis, in
the same FalkorDB instance, under the area's name. `apply_local_names()` writes
them again after each rebuild.

Each change raises a revision number. `geo.landmarks()` checks it, so the Intake
agent in the workers process uses a new name for its next message."""
from __future__ import annotations

import json
import secrets

from . import areas, db, events, geo, orgs
from .config import get_settings
from .db import REGION_GRAPH, now_ms, query

REV_KEY = geo.LANDMARKS_REV
KINDS = ("temple", "mosque", "church", "hospital", "school", "market", "transport", "ground", "office",
         "locality", "junction", "ghat", "landmark")
MAX_ALIASES = 30
# Local names work the same way for a landmark and for a neighbourhood.
PLACE = "MATCH (l) WHERE (l:Landmark OR l:Neighbourhood)"


class GazetteerError(ValueError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _key(part: str, area: str | None = None) -> str:
    return f"rn:gazetteer:{area or get_settings().area}:{part}"


def clean_alias(text: str) -> str:
    alias = " ".join(text.lower().split())
    if not 2 <= len(alias) <= 60:
        raise GazetteerError(400, "A local name must have 2 to 60 characters.")
    return alias


async def bump() -> None:
    await db.redis().incr(REV_KEY)
    geo.invalidate()


async def create_landmarks(rows: list[dict]) -> None:
    for i in range(0, len(rows), 500):
        await query(
            REGION_GRAPH,
            "UNWIND $rows AS l CREATE (:Landmark {id:l.id, name:l.name, aliases:l.aliases, ward:l.ward, kind:l.kind,"
            " lat:l.lat, lon:l.lon, source:l.source})",
            {"rows": rows[i:i + 500]},
        )


async def create_neighbourhoods(rows: list[dict]) -> None:
    await query(
        REGION_GRAPH,
        "UNWIND $rows AS n CREATE (:Neighbourhood {id:n.id, name:n.name, aliases:n.aliases, ward:n.ward, lat:n.lat,"
        " lon:n.lon, polygon:n.polygon, source:n.source})",
        {"rows": [{**n, "polygon": json.dumps(n["polygon"]) if n["polygon"] else None} for n in rows]},
    )


async def apply_local_names(area: str | None = None) -> int:
    """Write the coordinators' landmarks and aliases into the region graph again. Returns how many."""
    r = db.redis()
    added = [json.loads(v) for v in (await r.hgetall(_key("landmarks", area))).values()]
    for lm in added:
        await query(
            REGION_GRAPH,
            "MERGE (l:Landmark {id:$l.id}) SET l.name=$l.name, l.aliases=$l.aliases, l.ward=$l.ward, l.kind=$l.kind,"
            " l.lat=$l.lat, l.lon=$l.lon, l.source='app'",
            {"l": lm},
        )
    names = await r.hgetall(_key("alias_of", area))
    n = len(added)
    for lid, name in names.items():
        aliases = sorted(await r.smembers(_key(f"alias:{lid}", area)))
        params = {"id": lid, "name": name, "aliases": aliases}
        update = " WITH l LIMIT 1 SET l.aliases = l.aliases + [a IN $aliases WHERE NOT a IN l.aliases] RETURN l.id AS id"
        rows = await query(REGION_GRAPH, PLACE + " AND l.id = $id" + update, params)
        if not rows:
            # A new OpenStreetMap import can give a place a new id; then its name finds it.
            rows = await query(REGION_GRAPH, PLACE + " AND l.name = $name" + update, params)
        n += len(rows) * len(aliases)
    return n


async def refresh_landmarks(reg: areas.Region, version: str) -> None:
    """Replace the landmarks and neighbourhoods only. The roads, their flood state and the junction ids stay."""
    await query(REGION_GRAPH, "MATCH (l:Landmark) DELETE l")
    await query(REGION_GRAPH, "MATCH (n:Neighbourhood) DELETE n")
    await create_landmarks(reg.landmarks)
    await create_neighbourhoods(reg.neighbourhoods)
    await apply_local_names(reg.name)
    await query(
        REGION_GRAPH,
        "UNWIND $rows AS m MERGE (x:Meta {key:m.k}) SET x.value = m.v",
        {"rows": [{"k": "landmarks", "v": version}, {"k": "attribution", "v": reg.attribution}]},
    )
    await bump()


async def _find(lid: str) -> dict | None:
    return await db.one(
        REGION_GRAPH,
        PLACE + " AND l.id = $id RETURN l.id AS id, l.name AS name, l.aliases AS aliases, l.ward AS ward,"
        " l.kind AS kind, l.lat AS lat, l.lon AS lon, l.source AS source",
        {"id": lid},
        readonly=True,
    )


async def _owner_of_name(alias: str) -> dict | None:
    return await db.one(
        REGION_GRAPH, PLACE + " AND toLower(l.name) = $a RETURN l.id AS id, l.name AS name LIMIT 1",
        {"a": alias}, readonly=True,
    )


async def _announce(text: str, **data) -> None:
    # The region graph is shared, so every organisation's dashboard hears about the change.
    for o in await orgs.all_orgs():
        await events.publish(o["slug"], "landmark", text, **data)


async def add_alias(lid: str, text: str, by: str) -> dict:
    alias = clean_alias(text)
    lm = await _find(lid)
    if not lm:
        raise GazetteerError(404, "No landmark or neighbourhood has this id.")
    if alias == lm["name"].lower() or alias in lm["aliases"]:
        raise GazetteerError(409, f"\"{alias}\" is already a name of {lm['name']}.")
    other = await _owner_of_name(alias)
    if other and other["id"] != lid:
        raise GazetteerError(409, f"\"{alias}\" is the name of another landmark, {other['name']}.")
    if len(lm["aliases"]) >= MAX_ALIASES:
        raise GazetteerError(400, f"A landmark can have {MAX_ALIASES} local names or fewer.")
    r = db.redis()
    await r.sadd(_key(f"alias:{lid}"), alias)
    await r.hset(_key("alias_of"), lid, lm["name"])
    row = await db.one(
        REGION_GRAPH,
        PLACE + " AND l.id = $id SET l.aliases = l.aliases + [a IN [$a] WHERE NOT a IN l.aliases],"
        " l.updated_at = $now, l.updated_by = $by RETURN l.aliases AS aliases",
        {"id": lid, "a": alias, "now": now_ms(), "by": by},
    )
    await bump()
    await _announce(f"New local name \"{alias}\" for {lm['name']}", landmark=lid, alias=alias)
    return {**lm, "aliases": row["aliases"] if row else lm["aliases"] + [alias]}


async def add_landmark(name: str, aliases: list[str], kind: str, lat: float, lon: float, by: str) -> dict:
    name = " ".join(name.split())
    if not 3 <= len(name) <= 80:
        raise GazetteerError(400, "A landmark name must have 3 to 80 characters.")
    if kind not in KINDS:
        raise GazetteerError(400, f"The kind must be one of: {', '.join(KINDS)}.")
    if await _owner_of_name(name.lower()):
        raise GazetteerError(409, f"A landmark with the name {name} exists.")
    ward = await geo.ward_at(lat, lon)
    if not ward:
        raise GazetteerError(400, "The point is outside the area. Choose a point inside a ward.")
    clean: list[str] = []
    for text in aliases:
        alias = clean_alias(text)
        if alias == name.lower() or alias in clean:
            continue
        other = await _owner_of_name(alias)
        if other:
            raise GazetteerError(409, f"\"{alias}\" is the name of another landmark, {other['name']}.")
        clean.append(alias)
    if len(clean) > 10:
        raise GazetteerError(400, "Add 10 local names or fewer with a new landmark.")
    lm = {"id": f"La{secrets.token_hex(4)}", "name": name, "aliases": clean, "kind": kind, "ward": ward,
          "lat": round(lat, 6), "lon": round(lon, 6), "source": "app"}
    await db.redis().hset(_key("landmarks"), lm["id"], json.dumps(lm))
    await query(
        REGION_GRAPH,
        "CREATE (:Landmark {id:$l.id, name:$l.name, aliases:$l.aliases, ward:$l.ward, kind:$l.kind, lat:$l.lat,"
        " lon:$l.lon, source:'app', updated_at:$now, updated_by:$by})",
        {"l": lm, "now": now_ms(), "by": by},
    )
    await bump()
    await _announce(f"New landmark {name} in ward {ward}", landmark=lm["id"])
    return lm


async def forget(lid: str) -> None:
    """Remove a coordinator's landmark or the aliases added to one landmark. For tests and clean-up."""
    r = db.redis()
    await r.hdel(_key("landmarks"), lid)
    added = await r.smembers(_key(f"alias:{lid}"))
    await r.delete(_key(f"alias:{lid}"))
    await r.hdel(_key("alias_of"), lid)
    await query(REGION_GRAPH, "MATCH (l:Landmark {id:$id, source:'app'}) DELETE l", {"id": lid})
    if added:
        await query(
            REGION_GRAPH,
            PLACE + " AND l.id = $id SET l.aliases = [a IN l.aliases WHERE NOT a IN $added]",
            {"id": lid, "added": sorted(added)},
        )
    await bump()
