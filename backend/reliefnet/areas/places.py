"""Named places from OpenStreetMap, added to an area's landmark list.

`import_osm.py --places` writes `<area>_places.json` next to the area module.
At seed time, `merge()` adds these places to the hand-written `LANDMARKS`.
The hand-written landmarks stay authoritative: when an OpenStreetMap place is
the same place, the hand-written name, position and aliases win.

Each landmark has a `source`: "hand" (the area module), "osm" (this file) or
"app" (added by a coordinator, see `gazetteer.py`).

The same file holds the named neighbourhoods (`neighbourhoods()`). Intake uses
them as a location clue that narrows the area, together with the ward."""
from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from types import ModuleType

from rapidfuzz import fuzz

from . import haversine_m, point_in_polygon, polygon_area_m2, polygon_centre

ATTRIBUTION = "Place data © OpenStreetMap contributors (ODbL)"

# Words that name a kind of place, not one place. An alias made only of these words
# ("mandir", "govt school") fits many places, so automatic aliases never use one alone.
GENERIC = {
    "mandir", "temple", "masjid", "mosque", "church", "gurudwara", "gurdwara", "girja", "dargah", "math",
    "hospital", "aspatal", "clinic", "dispensary", "nursing", "home", "health", "centre", "center", "medical",
    "care", "school", "vidyalaya", "college", "mahavidyalaya", "university", "academy", "institute",
    "public", "high", "middle", "primary", "senior", "secondary", "girls", "boys", "government", "govt", "sarkari",
    "market", "bazar", "bazaar", "mandi", "mall", "station", "halt", "railway", "junction", "bus", "stand",
    "park", "stadium", "ground", "maidan", "police", "thana", "post", "office", "bank", "atm", "branch",
    "colony", "nagar", "road", "chowk", "gali", "lane", "the", "of", "and", "new", "old", "shri", "shree", "sri",
    "sree", "ji", "baba", "devi", "mata", "complex", "hall", "bhawan", "bhavan", "kendra",
}
HONORIFICS = ("shri ", "shree ", "sri ", "sree ")
# One word for one other, so "Durga Mandir" is also found as "durga temple".
SWAPS = [("mandir", "temple"), ("masjid", "mosque"), ("gurudwara", "gurdwara"), ("hospital", "aspatal"),
         ("police station", "thana"), ("post office", "dakghar"), ("bazar", "bazaar")]
WORSHIP = {"temple", "mosque", "church"}
TYPE_WORDS = ("mandir", "temple", "masjid", "mosque", "church", "gurudwara", "gurdwara")

# An OpenStreetMap place this close to a hand-written landmark with a similar name is the same place.
SAME_PLACE_M = 600.0
SAME_NAME_SCORE = 85
# Two OpenStreetMap elements with the same name this close are one place (a node and its building).
OSM_TWIN_M = 300.0
MIN_CORE_LEN = 6


def path(m: ModuleType) -> Path:
    return Path(m.__file__).with_name(f"{m.NAME}_places.json")


def load(m: ModuleType) -> list[dict]:
    """The area's OpenStreetMap places, or an empty list when the area has no places file."""
    p = path(m)
    if not p.exists():
        return []
    return json.loads(p.read_text(encoding="utf-8"))["places"]


def load_neighbourhoods(m: ModuleType) -> list[dict]:
    """The area's OpenStreetMap neighbourhoods, or an empty list."""
    p = path(m)
    if not p.exists():
        return []
    return json.loads(p.read_text(encoding="utf-8")).get("neighbourhoods", [])


def norm(text: str) -> str:
    # Keep letters, digits and the vowel signs of Devanagari; punctuation becomes a space.
    t = text.casefold().replace("'", "").replace("’", "")
    t = "".join(" " if unicodedata.category(c)[0] in "PSZ" else c for c in t)
    return " ".join(t.split())


def _bare(text: str) -> str:
    t = norm(text)
    for h in HONORIFICS:
        if t.startswith(h):
            return t[len(h):]
    return t


def is_generic(alias: str) -> bool:
    words = norm(alias).split()
    return not words or all(w in GENERIC or w.isdigit() for w in words)


# ------------------------------------------------------------------ OpenStreetMap elements
def kind_of(tags: dict) -> str | None:
    amenity, leisure = tags.get("amenity"), tags.get("leisure")
    if amenity == "place_of_worship":
        return {"muslim": "mosque", "christian": "church"}.get(tags.get("religion", ""), "temple")
    if amenity in ("hospital", "clinic"):
        return "hospital"
    if amenity in ("school", "college", "university"):
        return "school"
    if amenity == "marketplace" or tags.get("shop") == "mall":
        return "market"
    if amenity in ("police", "post_office", "fire_station", "townhall", "bank"):
        return "office"
    if amenity == "bus_station" or tags.get("railway") in ("station", "halt"):
        return "transport"
    if leisure in ("park", "stadium", "sports_centre"):
        return "ground"
    return None


def _clean(raw: str, city: str = "") -> str:
    raw = re.sub(r"\([^()]*(\([^()]*\)[^()]*)*\)", " ", raw)
    raw = re.sub(r"[\s,.]*\b(pvt|private)\.?\s*(ltd|limited)\b\.?", "", raw, flags=re.I)
    raw = re.sub(r"\s+(ltd|limited)\.?$", "", raw, flags=re.I)
    if city:
        raw = re.sub(rf"\s*[,\-–]\s*{re.escape(city)}\s*$", "", raw, flags=re.I)
    raw = " ".join(raw.split()).strip(" ,-")
    return raw.title() if raw.islower() or raw.isupper() else raw


def from_osm(osm: dict, bbox: tuple[float, float, float, float], city: str = "") -> list[dict]:
    """The named places in an Overpass answer (`out tags center`), one row for each real place.

    `city` is removed from the end of a name: "Heart Hospital, Patna" becomes "Heart Hospital"."""
    s, w, n, e = bbox
    rows: list[dict] = []
    for el in osm.get("elements", []):
        tags = el.get("tags", {})
        kind = kind_of(tags)
        lat = el.get("lat", el.get("center", {}).get("lat"))
        lon = el.get("lon", el.get("center", {}).get("lon"))
        en = (tags.get("name:en") or "").strip()
        local = (tags.get("name") or "").strip()
        name = _clean(en or local, city)
        if not kind or not name or lat is None or not (s <= lat <= n and w <= lon <= e):
            continue
        # A name such as "Mandir" or "Colony Park" does not tell one place from another. A name in
        # another script only stays as an alias: the dashboard and the help form show Latin names.
        if is_generic(name) or not re.search(r"[a-z]", name.casefold()) or "atm" in norm(name).split():
            continue
        # People type the local and English names, and the old and short names too.
        others = [local, tags.get("name:hi", "")]
        for key in ("alt_name", "old_name", "short_name", "official_name", "loc_name", "alt_name:en"):
            others += tags.get(key, "").split(";")
        alt = sorted({_clean(x, city) for x in others if x.strip() and norm(_clean(x, city)) != norm(name)})
        rows.append({"osm": f"{el['type'][0]}{el['id']}", "name": name, "alt": alt, "kind": kind,
                     "lat": round(lat, 6), "lon": round(lon, 6)})

    out: list[dict] = []
    for r in sorted(rows, key=lambda r: (r["osm"][0] != "n", r["osm"])):
        twin = next((o for o in out if o["kind"] == r["kind"] and fuzz.ratio(norm(o["name"]), norm(r["name"])) >= 90
                     and haversine_m(o["lat"], o["lon"], r["lat"], r["lon"]) < OSM_TWIN_M), None)
        if twin:
            twin["alt"] = sorted(set(twin["alt"]) | {a for a in r["alt"] if norm(a) != norm(twin["name"])})
        else:
            out.append(r)
    return sorted(out, key=lambda r: (r["kind"], r["name"], r["osm"]))


# ------------------------------------------------------------------ neighbourhoods
NEIGHBOURHOOD_PLACES = ("suburb", "quarter", "neighbourhood")
# An outline smaller than this is a building or a joke edit ("friend's house"), not a neighbourhood.
MIN_NEIGHBOURHOOD_M2 = 20_000.0
OUTLINE_STEP_M = 15.0


def _ring(members: list[dict]) -> list[list[float]]:
    """The largest closed ring made from the outer ways of a multipolygon relation."""
    parts = [[[p["lat"], p["lon"]] for p in mb["geometry"]] for mb in members
             if mb.get("type") == "way" and mb.get("role", "outer") in ("outer", "") and mb.get("geometry")]
    rings: list[list[list[float]]] = []
    while parts:
        ring = parts.pop(0)
        grown = True
        while grown and ring[0] != ring[-1]:
            grown = False
            for i, part in enumerate(parts):
                if part[0] == ring[-1]:
                    ring += part[1:]
                elif part[-1] == ring[-1]:
                    ring += part[::-1][1:]
                elif part[-1] == ring[0]:
                    ring = part + ring[1:]
                elif part[0] == ring[0]:
                    ring = part[::-1] + ring[1:]
                else:
                    continue
                parts.pop(i)
                grown = True
                break
        rings.append(ring)
    return max(rings, key=polygon_area_m2, default=[])


def _thin(ring: list[list[float]]) -> list[list[float]]:
    if ring and ring[0] == ring[-1]:
        ring = ring[:-1]
    out: list[list[float]] = []
    for p in ring:
        if not out or haversine_m(*out[-1], *p) >= OUTLINE_STEP_M:
            out.append([round(p[0], 6), round(p[1], 6)])
    return out


def neighbourhoods_from_osm(osm: dict, bbox: tuple[float, float, float, float], city: str = "") -> list[dict]:
    """The named suburbs, quarters and neighbourhoods in an Overpass answer (`out geom`).

    A way or a relation keeps its outline. A node has only a centre, and its `polygon` is None."""
    s, w, n, e = bbox
    rows: list[dict] = []
    for el in osm.get("elements", []):
        tags = el.get("tags", {})
        if tags.get("place") not in NEIGHBOURHOOD_PLACES:
            continue
        en = (tags.get("name:en") or "").strip()
        local = (tags.get("name") or "").strip()
        name = _clean(en or local, city)
        if not name or is_generic(name) or not re.search(r"[a-z]", name.casefold()):
            continue
        poly = None
        if el["type"] == "node":
            lat, lon = el["lat"], el["lon"]
        else:
            if el["type"] == "way":
                ring = [[p["lat"], p["lon"]] for p in el.get("geometry", [])]
            else:
                ring = _ring(el.get("members", []))
            poly = _thin(ring)
            if len(poly) < 3 or polygon_area_m2(poly) < MIN_NEIGHBOURHOOD_M2:
                continue
            lat, lon = polygon_centre(poly)
        inside = s <= lat <= n and w <= lon <= e
        if not inside and not any(s <= p[0] <= n and w <= p[1] <= e for p in poly or []):
            continue
        others = [local, tags.get("name:hi", "")]
        for key in ("alt_name", "old_name", "short_name", "loc_name", "alt_name:en"):
            others += tags.get(key, "").split(";")
        alt = sorted({_clean(x, city) for x in others if x.strip() and norm(_clean(x, city)) != norm(name)})
        rows.append({"osm": f"{el['type'][0]}{el['id']}", "name": name, "alt": alt, "place": tags["place"],
                     "lat": round(lat, 6), "lon": round(lon, 6), "polygon": poly})
    # A node and an outline with one name are one neighbourhood. Keep the outline.
    out: list[dict] = []
    for r in sorted(rows, key=lambda r: (r["polygon"] is None, r["osm"])):
        twin = next((o for o in out if norm(o["name"]) == norm(r["name"]) and (
            (o["polygon"] and point_in_polygon(r["lat"], r["lon"], o["polygon"]))
            or haversine_m(o["lat"], o["lon"], r["lat"], r["lon"]) < OSM_TWIN_M)), None)
        if twin:
            twin["alt"] = sorted(set(twin["alt"]) | {a for a in r["alt"] if norm(a) != norm(twin["name"])})
        else:
            out.append(r)
    return sorted(out, key=lambda r: (r["name"], r["osm"]))


def _main_ward(wards: list[dict], nb: dict) -> int:
    """The ward that holds most of a neighbourhood, or the ward of its centre."""
    poly = nb.get("polygon")
    if not poly:
        return _ward_of(wards, nb["lat"], nb["lon"])
    lats, lons = [p[0] for p in poly], [p[1] for p in poly]
    votes: Counter = Counter()
    for i in range(12):
        for j in range(12):
            lat = min(lats) + (i + 0.5) / 12 * (max(lats) - min(lats))
            lon = min(lons) + (j + 0.5) / 12 * (max(lons) - min(lons))
            if point_in_polygon(lat, lon, poly):
                votes[_ward_of(wards, lat, lon)] += 1
    votes.pop(0, None)
    return votes.most_common(1)[0][0] if votes else _ward_of(wards, nb["lat"], nb["lon"])


def neighbourhoods(hand: list, osm_rows: list[dict], wards: list[dict]) -> list[dict]:
    """The area's neighbourhoods: the area module's `NEIGHBOURHOODS` first, then OpenStreetMap's.

    A `hand` row is (name, aliases, lat, lon) or (name, aliases, lat, lon, polygon). A neighbourhood
    outside every ward is dropped. Two neighbourhoods with one name get the ward in the name."""
    out: list[dict] = []
    for i, (name, aliases, lat, lon, *rest) in enumerate(hand):
        out.append({"id": f"N{i + 1:02d}", "name": name, "aliases": [norm(a) for a in aliases if not is_generic(a)],
                    "lat": lat, "lon": lon, "polygon": rest[0] if rest else None, "source": "hand"})
    for r in osm_rows:
        if any(norm(o["name"]) == norm(r["name"]) and haversine_m(o["lat"], o["lon"], r["lat"], r["lon"])
               < SAME_PLACE_M for o in out):
            continue
        out.append({"id": f"N{r['osm']}", "name": r["name"], "aliases": auto_aliases(r["name"], r.get("alt", [])),
                    "lat": r["lat"], "lon": r["lon"], "polygon": r.get("polygon"), "source": "osm"})
    keep = []
    for nb in out:
        nb["ward"] = _main_ward(wards, nb)
        if nb["ward"]:
            keep.append(nb)
    ward_name = {wd["num"]: wd["name"] for wd in wards}
    by_name: dict[str, list[dict]] = defaultdict(list)
    for nb in keep:
        by_name[norm(nb["name"])].append(nb)
    for key, group in by_name.items():
        if len(group) < 2:
            continue
        used: Counter = Counter()
        for nb in group:
            base = f"{nb['name']}, {ward_name.get(nb['ward'], nb['ward'])}"
            used[base] += 1
            nb["name"] = base if used[base] == 1 else f"{base} {used[base]}"
            if key not in nb["aliases"]:
                nb["aliases"].insert(0, key)
    return [{k: nb[k] for k in ("id", "name", "aliases", "ward", "lat", "lon", "polygon", "source")} for nb in keep]


# ------------------------------------------------------------------ merge
def _ward_of(wards: list[dict], lat: float, lon: float) -> int:
    for wd in wards:
        if point_in_polygon(lat, lon, wd["polygon"]):
            return wd["num"]
    return 0


def _specific_names(lm: dict) -> list[str]:
    return [lm["name"], *(a for a in lm["aliases"] if not is_generic(a))]


def same_place(place: dict, lm: dict) -> bool:
    if haversine_m(place["lat"], place["lon"], lm["lat"], lm["lon"]) > SAME_PLACE_M:
        return False
    mine = [place["name"], *place.get("alt", [])]
    return any(fuzz.token_sort_ratio(_bare(a), _bare(b)) >= SAME_NAME_SCORE
               for a in mine for b in _specific_names(lm))


def auto_aliases(name: str, alt: list[str]) -> list[str]:
    """The names people type for one place: its other names and simple spelling swaps.

    A name that is only generic words never becomes an alias."""
    out: list[str] = []
    for raw in [name, *alt]:
        base = norm(raw)
        forms = {base, _bare(raw)}
        for a, b in SWAPS:
            for f in list(forms):
                for x, y in ((a, b), (b, a)):
                    if re.search(rf"\b{x}\b", f):
                        forms.add(re.sub(rf"\b{x}\b", y, f))
        out += sorted(forms)
    own = norm(name)
    seen: set[str] = set()
    keep = []
    for a in out:
        if a != own and a not in seen and 3 <= len(a) <= 60 and not is_generic(a):
            seen.add(a)
            keep.append(a)
    return keep


def _core(name: str) -> str:
    """The name without its type words: "Jaleshwar Mandir" gives "jaleshwar"."""
    words = _bare(name).split()
    if not words or words[-1] not in TYPE_WORDS:
        return ""
    while words and words[-1] in GENERIC:
        words.pop()
    while words and words[0] in GENERIC:
        words.pop(0)
    return " ".join(words)


def merge(hand: list[dict], places: list[dict], wards: list[dict], blocked: list[str] = ()) -> list[dict]:
    """Hand-written landmarks first, then each OpenStreetMap place that is not one of them.

    A place outside every ward is dropped. `blocked` holds names that must not become a
    short alias, for example the ward names: "kankarbagh" must not point at "Kankarbagh Post Office"."""
    out = [{**lm, "source": lm.get("source", "hand")} for lm in hand]
    ward_names = {norm(wd["name"]) for wd in wards}
    added: list[dict] = []
    for p in places:
        ward = _ward_of(wards, p["lat"], p["lon"])
        if not ward or norm(p["name"]) in ward_names or any(same_place(p, lm) for lm in out):
            continue
        added.append({"id": f"L{p['osm']}", "name": p["name"], "aliases": auto_aliases(p["name"], p.get("alt", [])),
                      "kind": p["kind"], "ward": ward, "lat": p["lat"], "lon": p["lon"], "source": "osm"})

    # Two different places with one name ("Durga Mandir" in two wards): add the ward to the name,
    # and keep the plain name as an alias that they share, as the hand list does with "mandir".
    by_name: dict[str, list[dict]] = defaultdict(list)
    for lm in out + added:
        by_name[norm(lm["name"])].append(lm)
    ward_name = {wd["num"]: wd["name"] for wd in wards}
    used = Counter(norm(lm["name"]) for lm in out)
    for key, group in by_name.items():
        if len(group) < 2:
            continue
        for lm in group:
            if lm["source"] != "osm":
                continue
            plain = lm["name"]
            name = f"{plain}, {ward_name.get(lm['ward'], lm['ward'])}"
            n = 1
            while used[norm(name)]:
                n += 1
                name = f"{plain}, {ward_name.get(lm['ward'], lm['ward'])} {n}"
            used[norm(name)] += 1
            lm["name"] = name
            if key not in lm["aliases"]:
                lm["aliases"].insert(0, key)

    # A short form ("jaleshwar") is safe only when no other place, ward or road uses those words.
    # Only for places of worship: other places are often named after a person ("Manjhi Park"),
    # and a family name in a message must not move the household to that place.
    taken = [norm(x) for x in blocked] + list(ward_names)
    for lm in out + added:
        taken += [norm(lm["name"]), *lm["aliases"]]
    for lm in added:
        if lm["kind"] not in WORSHIP:
            continue
        core = _core(lm["name"])
        if len(core) < MIN_CORE_LEN or is_generic(core):
            continue
        pat = re.compile(rf"\b{re.escape(core)}\b")
        if sum(1 for t in taken if pat.search(t)) <= 1 + sum(1 for a in lm["aliases"] if pat.search(a)):
            lm["aliases"].append(core)
    return out + added
