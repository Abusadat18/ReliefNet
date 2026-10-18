"""Download one area's roads, bridges, drains and railway from OpenStreetMap.

    python -m reliefnet.areas.import_osm patna
    python -m reliefnet.areas.import_osm patna --cache osm.json   # reuse a download
    python -m reliefnet.areas.import_osm patna --places           # named places only

The script writes `<area>.json` next to the area module. Commit that file. The
app reads it at seed time and never calls OpenStreetMap while it runs.

`--places` writes only `<area>_places.json`: temples, mosques, hospitals, schools,
markets, stations, parks and other named places (see `places.py`). It does not
touch the roads, so the junction ids and every organisation's graph stay valid.

The graph keeps the streets that connect: short dead ends go, but the side
lanes stay, because they are the detours when a main road floods."""
from __future__ import annotations

import argparse
import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

from . import haversine_m, module, places

OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter"]
MAIN = {"trunk", "primary", "secondary", "tertiary", "unclassified"}
MINOR = {"residential", "living_street"}
# min_lane: an unnamed minor street stays only if it is at least this long. 0 keeps every street, because
# the short side lanes are the detours when a main road floods.
# stub: unnamed dead ends shorter than this are removed. Both in metres; the command line can change them.
LIMITS = {"min_lane": 0.0, "stub": 150.0}
DRAIN_NEAR_M = 110.0
NAMESAKE_GAP_M = 300.0
BRIDGE_WORDS = ("bridge", "flyover", "setu", "overbridge", "pul")


def overpass_query(bbox: tuple[float, float, float, float], pad: float = 0.006) -> str:
    s, w, n, e = bbox
    box = f"{s},{w},{n},{e}"
    wide = f"{s - pad},{w - pad},{n + pad},{e + pad}"
    hw = "trunk|primary|secondary|tertiary|unclassified|residential|living_street"
    return (
        "[out:json][timeout:120];("
        f'way["highway"~"^({hw})(_link)?$"]({box});'
        f'way["waterway"~"^(river|canal|drain|stream|ditch)$"]({wide});'
        f'way["railway"="rail"][!"service"]({box});'
        ");out geom;"
    )


def places_query(bbox: tuple[float, float, float, float]) -> str:
    s, w, n, e = bbox
    box = f"{s},{w},{n},{e}"
    amenity = ("place_of_worship|hospital|clinic|school|college|university|marketplace|bus_station|police|"
               "post_office|fire_station|townhall|bank")
    return (
        "[out:json][timeout:120];("
        f'nwr["amenity"~"^({amenity})$"]["name"]({box});'
        f'nwr["railway"~"^(station|halt)$"]["name"]({box});'
        f'nwr["leisure"~"^(park|stadium|sports_centre)$"]["name"]({box});'
        f'nwr["shop"="mall"]["name"]({box});'
        ");out tags center;"
    )


def download(query: str) -> dict:
    # The public Overpass servers are often busy, so try each one a few times.
    last: Exception | None = None
    for attempt in range(3):
        for url in OVERPASS:
            req = urllib.request.Request(
                url, data=urllib.parse.urlencode({"data": query}).encode(),
                headers={"User-Agent": "ReliefNet-importer/0.1 (+https://github.com/Abusadat18/ReliefNet)"},
            )
            try:
                with urllib.request.urlopen(req, timeout=240) as r:
                    return json.loads(r.read().decode("utf-8"))
            except (urllib.error.URLError, TimeoutError) as e:
                print(f"{url}: {e}; trying again")
                last = e
        time.sleep(10 * (attempt + 1))
    raise SystemExit(f"OpenStreetMap download failed: {last}")


# ------------------------------------------------------------------ geometry
def _xy(lat: float, lon: float, lat0: float) -> tuple[float, float]:
    return lon * 111_320 * math.cos(math.radians(lat0)), lat * 110_540


def _seg_dist_m(p, a, b, lat0) -> float:
    px, py = _xy(*p, lat0)
    ax, ay = _xy(*a, lat0)
    bx, by = _xy(*b, lat0)
    dx, dy = bx - ax, by - ay
    t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - ax - t * dx, py - ay - t * dy)


def _crosses(a1, a2, b1, b2) -> bool:
    def orient(p, q, r):
        return (q[1] - p[1]) * (r[0] - p[0]) - (q[0] - p[0]) * (r[1] - p[1])

    d1, d2 = orient(b1, b2, a1), orient(b1, b2, a2)
    d3, d4 = orient(a1, a2, b1), orient(a1, a2, b2)
    return d1 * d2 < 0 and d3 * d4 < 0


def _length(geom: list[list[float]]) -> float:
    return sum(haversine_m(*geom[i], *geom[i + 1]) for i in range(len(geom) - 1))


def _clip_runs(nodes: list[int], geom: list[dict], bbox) -> list[list[tuple[int, float, float]]]:
    s, w, n, e = bbox
    runs, cur = [], []
    for nid, p in zip(nodes, geom):
        if s <= p["lat"] <= n and w <= p["lon"] <= e:
            cur.append((nid, p["lat"], p["lon"]))
        else:
            if len(cur) > 1:
                runs.append(cur)
            cur = []
    if len(cur) > 1:
        runs.append(cur)
    return runs


def _clean_name(tags: dict) -> str | None:
    raw = (tags.get("name:en") or tags.get("name") or "").strip()
    if not raw:
        return None
    raw = " ".join(raw.split())
    if raw.islower() or raw.isupper():
        raw = raw.title()
    return raw


# ------------------------------------------------------------------ graph
class Graph:
    def __init__(self):
        self.pos: dict[int, tuple[float, float]] = {}
        self.edges: dict[int, dict] = {}
        self.adj: dict[int, set[int]] = defaultdict(set)
        self._next = 0

    def add(self, nodes: list[int], attrs: dict) -> None:
        if nodes[0] == nodes[-1]:
            return
        eid = self._next
        self._next += 1
        self.edges[eid] = {**attrs, "nodes": nodes}
        self.adj[nodes[0]].add(eid)
        self.adj[nodes[-1]].add(eid)

    def remove(self, eid: int) -> None:
        e = self.edges.pop(eid)
        for n in (e["nodes"][0], e["nodes"][-1]):
            self.adj[n].discard(eid)
            if not self.adj[n]:
                del self.adj[n]

    def length(self, eid: int) -> float:
        return _length([list(self.pos[n]) for n in self.edges[eid]["nodes"]])

    def largest_component(self) -> None:
        seen: set[int] = set()
        best: set[int] = set()
        for start in list(self.adj):
            if start in seen:
                continue
            comp, stack = set(), [start]
            while stack:
                u = stack.pop()
                if u in comp:
                    continue
                comp.add(u)
                for eid in self.adj[u]:
                    e = self.edges[eid]["nodes"]
                    stack.append(e[-1] if e[0] == u else e[0])
            seen |= comp
            if len(comp) > len(best):
                best = comp
        for eid in [i for i, e in self.edges.items() if e["nodes"][0] not in best]:
            self.remove(eid)

    def contract(self) -> None:
        """Join two pieces of the same road where nothing else meets them."""
        changed = True
        while changed:
            changed = False
            for n in list(self.adj):
                eids = list(self.adj.get(n, ()))
                if len(eids) != 2:
                    continue
                e1, e2 = (self.edges[i] for i in eids)
                if (e1["name"], e1["kind"]) != (e2["name"], e2["kind"]):
                    continue
                a = e1["nodes"] if e1["nodes"][-1] == n else e1["nodes"][::-1]
                b = e2["nodes"] if e2["nodes"][0] == n else e2["nodes"][::-1]
                if a[0] == b[-1]:
                    continue  # a closed loop; keep it as two roads
                attrs = {k: v for k, v in e1.items() if k != "nodes"}
                attrs["main"] = e1["main"] or e2["main"]
                for i in eids:
                    self.remove(i)
                self.add(a + b[1:], attrs)
                changed = True

    def prune_stubs(self) -> None:
        changed = True
        while changed:
            changed = False
            for n in list(self.adj):
                eids = self.adj.get(n)
                if not eids or len(eids) != 1:
                    continue
                eid = next(iter(eids))
                e = self.edges[eid]
                if e["kind"] == "road" and not e["name"] and self.length(eid) < LIMITS["stub"]:
                    self.remove(eid)
                    changed = True

    def dedupe(self) -> None:
        best: dict[tuple, int] = {}
        for eid, e in list(self.edges.items()):
            key = (frozenset((e["nodes"][0], e["nodes"][-1])), e["name"], e["kind"])
            if key in best:
                keep = min(best[key], eid, key=self.length)
                drop = eid if keep == best[key] else best[key]
                self.remove(drop)
                best[key] = keep
            else:
                best[key] = eid


def build(osm: dict, area) -> dict:
    bbox = area.BBOX
    lat0 = (bbox[0] + bbox[2]) / 2
    g = Graph()
    runs: list[tuple[list[tuple[int, float, float]], dict]] = []
    water_lines, rail = [], []
    s, w, n, e = bbox
    for el in osm["elements"]:
        if el.get("type") != "way" or "geometry" not in el:
            continue
        tags = el.get("tags", {})
        if "waterway" in tags:
            line = [[round(p["lat"], 6), round(p["lon"], 6)] for p in el["geometry"]]
            water_lines.append({"name": _clean_name(tags) or "", "kind": tags["waterway"], "line": line})
            continue
        if tags.get("railway") == "rail":
            for run in _clip_runs(el["nodes"], el["geometry"], bbox):
                rail.append([[round(la, 6), round(lo, 6)] for _, la, lo in run])
            continue
        hw = tags.get("highway", "")
        base = hw.removesuffix("_link")
        name = _clean_name(tags)
        bridge = tags.get("bridge") not in (None, "no")
        tunnel = tags.get("tunnel") in ("yes", "building_passage")
        geom_len = _length([[p["lat"], p["lon"]] for p in el["geometry"]])
        if base in MINOR and not (name or bridge or tunnel or geom_len >= LIMITS["min_lane"]):
            continue
        attrs = {"name": name, "kind": "bridge" if bridge else "underpass" if tunnel else "road",
                 "main": base in MAIN}
        for run in _clip_runs(el["nodes"], el["geometry"], bbox):
            runs.append((run, attrs))

    uses = Counter()
    for run, _ in runs:
        for nid, la, lo in run:
            g.pos[nid] = (la, lo)
            uses[nid] += 1
        uses[run[0][0]] += 1
        uses[run[-1][0]] += 1
    for run, attrs in runs:
        piece = [run[0][0]]
        for nid, _, _ in run[1:]:
            piece.append(nid)
            if uses[nid] > 1:
                g.add(piece, attrs)
                piece = [nid]
        if len(piece) > 1:
            g.add(piece, attrs)

    g.largest_component()
    for _ in range(3):
        g.contract()
        g.prune_stubs()
    g.dedupe()
    g.contract()

    return _finish(g, area, water_lines, rail, lat0)


def _finish(g: Graph, area, water_lines: list[dict], rail: list, lat0: float) -> dict:
    landmarks = [(l[0], l[3], l[4]) for l in area.LANDMARKS]

    def near(lat: float, lon: float) -> str:
        if not landmarks:
            return f"{lat:.4f}, {lon:.4f}"
        return min(landmarks, key=lambda l: haversine_m(lat, lon, l[1], l[2]))[0]

    drains = [wl for wl in water_lines if wl["kind"] in ("drain", "canal", "ditch", "stream")]

    def geom(eid: int) -> list[list[float]]:
        return [[round(g.pos[n][0], 6), round(g.pos[n][1], 6)] for n in g.edges[eid]["nodes"]]

    def mid(eid: int) -> list[float]:
        pts = geom(eid)
        return pts[len(pts) // 2]

    def crossed_water(eid: int) -> dict | None:
        pts = geom(eid)
        for wl in water_lines:
            for i in range(len(pts) - 1):
                for j in range(len(wl["line"]) - 1):
                    if _crosses(pts[i], pts[i + 1], wl["line"][j], wl["line"][j + 1]):
                        return wl
        return None

    def near_drain(eid: int) -> bool:
        for p in geom(eid)[:: max(1, len(geom(eid)) // 6)]:
            for wl in drains:
                line = wl["line"]
                for j in range(len(line) - 1):
                    if _seg_dist_m(p, line[j], line[j + 1], lat0) < DRAIN_NEAR_M:
                        return True
        return False

    def named_structure(raw: str | None) -> bool:
        return bool(raw) and raw.lower() != "flyover" and any(k in raw.lower() for k in BRIDGE_WORDS)

    # A bridge or underpass is one structure, even when OSM splits it or a dual carriageway doubles it.
    # A structure with its own name ("Dhanush Setu") is one structure however long it is.
    structures: list[dict] = []
    for eid, e in g.edges.items():
        if e["kind"] == "road":
            continue
        m = mid(eid)
        raw = (e["name"] or "").lower()
        home = next((s for s in structures if (s["raw"] or "").lower() == raw and s["kind"] == e["kind"]
                     and (named_structure(e["name"]) or haversine_m(*m, *s["at"]) < 180)), None)
        if home:
            home["edges"].append(eid)
        else:
            structures.append({"raw": e["name"], "kind": e["kind"], "at": m, "edges": [eid]})

    used: Counter = Counter()

    def unique(name: str, lat: float, lon: float) -> str:
        """A name no other road has: "X", then "X near L", then "X near L 2", "X near L 3", ..."""
        if used[name]:
            base = name if " near " in name else f"{name} near {near(lat, lon)}"
            name, n = base, 1
            while used[name]:
                n += 1
                name = f"{base} {n}"
        used[name] += 1
        return name

    names: dict[int, str] = {}
    for s in structures:
        raw, at = s["raw"], s["at"]
        word = "Bridge" if s["kind"] == "bridge" else "Underpass"
        if raw and raw.lower() != "flyover":
            name = raw if named_structure(raw) else f"{raw} {word}"
        elif raw:
            name = f"Flyover near {near(*at)}"
        else:
            water = crossed_water(s["edges"][0]) if s["kind"] == "bridge" else None
            prefix = f"{water['name'] or 'Nala'} Bridge" if water else word
            name = f"{prefix} near {near(*at)}"
        name = unique(name, *at)
        for eid in s["edges"]:
            names[eid] = name

    # Named roads keep their name on every piece; that is how people report them.
    canon: dict[str, str] = {}
    spellings: dict[str, Counter] = defaultdict(Counter)
    for eid, e in g.edges.items():
        if e["kind"] == "road" and e["name"]:
            spellings[e["name"].lower()][e["name"]] += 1
    for low, c in spellings.items():
        canon[low] = c.most_common(1)[0][0]
    for eid, e in g.edges.items():
        if eid in names:
            continue
        if e["name"]:
            names[eid] = canon[e["name"].lower()]
        else:
            m = mid(eid)
            names[eid] = unique(f"{'Road' if e['main'] else 'Lane'} near {near(*m)}", *m)
    _split_distant_namesakes(g, names, area, mid)

    ends = sorted({n for e in g.edges.values() for n in (e["nodes"][0], e["nodes"][-1])},
                  key=lambda n: (-g.pos[n][0], g.pos[n][1]))
    jid = {n: f"J{i + 1:03d}" for i, n in enumerate(ends)}
    junctions = [{"id": jid[n], "lat": round(g.pos[n][0], 6), "lon": round(g.pos[n][1], 6)} for n in ends]
    low_names = {x.lower() for x in getattr(area, "LOW_ROADS", [])}
    roads = []
    for eid, e in sorted(g.edges.items(), key=lambda kv: (names[kv[0]], jid[kv[1]["nodes"][0]])):
        gm = geom(eid)
        roads.append({
            "a": jid[e["nodes"][0]], "b": jid[e["nodes"][-1]], "name": names[eid], "kind": e["kind"],
            "low_lying": e["kind"] == "underpass" or names[eid].lower() in low_names or near_drain(eid),
            "length_m": round(_length(gm), 1), "geom": gm,
        })
    for i, r in enumerate(roads):
        r["id"] = f"S{i + 1:03d}"
    return {"junctions": junctions, "roads": roads, "water_lines": water_lines, "water_areas": [], "rail": rail}


def _split_distant_namesakes(g: Graph, names: dict[int, str], area, mid) -> None:
    """Two separate streets can share a name ("Road No.1" in two colonies).

    A flood report names one street, so give each separate piece its ward's name."""
    from . import Region, ward_at

    reg = Region(wards=area.wards())
    ward_name = {w["num"]: w["name"] for w in reg.wards}
    by_name: dict[str, list[int]] = defaultdict(list)
    for eid, e in g.edges.items():
        if e["kind"] == "road":
            by_name[names[eid]].append(eid)
    for name, eids in by_name.items():
        parent = {eid: eid for eid in eids}

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        at_node: dict[int, int] = {}
        for eid in eids:
            for n in (g.edges[eid]["nodes"][0], g.edges[eid]["nodes"][-1]):
                if n in at_node:
                    parent[find(eid)] = find(at_node[n])
                at_node[n] = eid
        groups: dict[int, list[int]] = defaultdict(list)
        for eid in eids:
            groups[find(eid)].append(eid)
        # OSM often breaks one street for a few metres at a junction; only a real gap makes two streets.
        pieces = list(groups.values())
        ends = [[g.pos[n] for eid in p for n in (g.edges[eid]["nodes"][0], g.edges[eid]["nodes"][-1])]
                for p in pieces]
        cluster = list(range(len(pieces)))
        for i in range(len(pieces)):
            for j in range(i + 1, len(pieces)):
                if min(haversine_m(*a, *b) for a in ends[i] for b in ends[j]) < NAMESAKE_GAP_M:
                    old, new = cluster[j], cluster[i]
                    cluster = [new if c == old else c for c in cluster]
        if len(set(cluster)) < 2:
            continue
        streets: dict[int, list[int]] = defaultdict(list)
        for c, p in zip(cluster, pieces):
            streets[c].extend(p)
        for grp in streets.values():
            ward = ward_name.get(ward_at(reg, *mid(max(grp, key=g.length))))
            if ward:
                for eid in grp:
                    names[eid] = f"{name}, {ward}"


def write_places(osm: dict, area) -> None:
    rows = places.from_osm(osm, area.BBOX, city=getattr(area, "CITY", area.TITLE.rsplit(",", 1)[-1].strip()))
    out = {
        "area": area.NAME,
        "bbox": area.BBOX,
        "attribution": places.ATTRIBUTION,
        "osm_timestamp": osm.get("osm3s", {}).get("timestamp_osm_base", ""),
        "imported": date.today().isoformat(),
        "places": rows,
    }
    target = places.path(area)
    # One place on each line keeps a new import easy to review.
    body = ",\n".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) for r in rows)
    head = json.dumps({k: v for k, v in out.items() if k != "places"}, ensure_ascii=False, separators=(",", ":"))
    target.write_text(f'{head[:-1]},"places":[\n{body}\n]}}\n', encoding="utf-8")
    kinds = Counter(r["kind"] for r in rows)
    print(f"{target.name}: {len(rows)} places {dict(sorted(kinds.items()))}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("area")
    ap.add_argument("--cache", help="read the OSM download from this file, or write it there if missing")
    ap.add_argument("--min-lane", type=float, default=LIMITS["min_lane"],
                    help="keep an unnamed minor street only if it is at least this long, in metres")
    ap.add_argument("--stub", type=float, default=LIMITS["stub"], help="remove unnamed dead ends shorter than this, in metres")
    ap.add_argument("--places", action="store_true",
                    help="download only the named places and write <area>_places.json; the roads stay as they are")
    args = ap.parse_args()
    LIMITS.update(min_lane=args.min_lane, stub=args.stub)
    area = module(args.area)
    cache = Path(args.cache) if args.cache else None
    if cache and cache.exists():
        osm = json.loads(cache.read_text(encoding="utf-8"))
    else:
        osm = download(places_query(area.BBOX) if args.places else overpass_query(area.BBOX))
        if cache:
            cache.write_text(json.dumps(osm), encoding="utf-8")
    if args.places:
        write_places(osm, area)
        return
    out = build(osm, area)
    out = {
        "area": area.NAME,
        "bbox": area.BBOX,
        "attribution": "Road, bridge, drain and railway data © OpenStreetMap contributors (ODbL)",
        "osm_timestamp": osm.get("osm3s", {}).get("timestamp_osm_base", ""),
        "imported": date.today().isoformat(),
        **out,
    }
    area.SNAPSHOT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    kinds = Counter(r["kind"] for r in out["roads"])
    print(f"{area.SNAPSHOT.name}: {len(out['junctions'])} junctions, {len(out['roads'])} roads {dict(kinds)},"
          f" {sum(r['low_lying'] for r in out['roads'])} low-lying, {len(out['water_lines'])} water lines,"
          f" {len(out['rail'])} rail lines")
    for name in sorted({r["name"] for r in out["roads"] if r["kind"] != "road"}):
        print("  ", name)


if __name__ == "__main__":
    main()
