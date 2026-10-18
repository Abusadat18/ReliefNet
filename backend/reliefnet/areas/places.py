"""Named places from OpenStreetMap, added to an area's landmark list.

`import_osm.py --places` writes `<area>_places.json` next to the area module.
At seed time, `merge()` adds these places to the hand-written `LANDMARKS`.
The hand-written landmarks stay authoritative: when an OpenStreetMap place is
the same place, the hand-written name, position and aliases win.

Each landmark has a `source`: "hand" (the area module), "osm" (this file) or
"app" (added by a coordinator, see `gazetteer.py`)."""
from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from types import ModuleType

from rapidfuzz import fuzz

from . import haversine_m, point_in_polygon

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
