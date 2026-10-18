/**
 * The names on the map: neighbourhoods, roads, landmarks and shelters, all from our own
 * data (OpenStreetMap and the gazetteer). Google's labels are off, so a name on the map
 * is a name that Intake can match. deckLayers.ts and MapLayers.tsx both draw this list,
 * so the Google map and the built-in chart show the same names.
 */
import type { Landmark, Region, Road } from "../types";
import type { Visible } from "./LayersMenu";

export type LabelKind = "hood" | "road" | "flood" | "landmark" | "shelter";

export interface MapLabel {
  id: string;
  kind: LabelKind;
  text: string;
  lat: number;
  lon: number;
  /** Degrees, counter-clockwise from east, always between -90 and 90 so the text stays upright. */
  angle: number;
  size: number;
  weight: number;
  /** "start" labels sit to the right of their point, moved by `dx` and `dy` pixels. */
  anchor: "middle" | "start";
  dx: number;
  dy: number;
  /** Main roads use the strong ink; small streets the quiet one. */
  strong: boolean;
}

export interface MapNames {
  labels: MapLabel[];
  /** Landmarks whose dot shows. A dot without its name is noise, so it follows the name. */
  dots: Landmark[];
}

const FONT = "'Inter Variable', Inter, system-ui, sans-serif";
const M_PER_DEG_LAT = 110_574;
const M_PER_DEG_LON_EQ = 111_320;
const MERCATOR_M_PER_PX_Z0 = 156_543.03;
/** Labels keep this much clear space around them, in pixels. */
const GAP = 4;

/** Metres per screen pixel at a Web Mercator zoom level. */
export const metresPerPx = (zoom: number, lat: number) => (MERCATOR_M_PER_PX_Z0 * Math.cos((lat * Math.PI) / 180)) / 2 ** zoom;
/** The Web Mercator zoom level that shows `mpp` metres per pixel. The chart uses it to share the zoom rules. */
export const zoomFor = (mpp: number, lat: number) => Math.log2((MERCATOR_M_PER_PX_Z0 * Math.cos((lat * Math.PI) / 180)) / mpp);

/** The road importer names a street with no name "Lane near <place> <n>". Intake can match it, but it is not a real name. */
export const isMadeUpName = (name: string) => name.includes(" near ");

/** Uppercase with open letter spacing. TextLayer has no letter-spacing setting, so the spaces are in the text. */
const spaced = (s: string) =>
  s
    .toUpperCase()
    .split(" ")
    .map((w) => [...w].join(" "))
    .join(" ");

let ctx: CanvasRenderingContext2D | null = null;
const widths = new Map<string, number>();
function textWidth(text: string, size: number, weight: number): number {
  const key = `${weight}|${text}`;
  let w = widths.get(key);
  if (w === undefined) {
    ctx ??= document.createElement("canvas").getContext("2d");
    if (ctx) {
      ctx.font = `${weight} 100px ${FONT}`;
      w = ctx.measureText(text).width / 100;
    } else {
      w = text.length * 0.58;
    }
    widths.set(key, w);
  }
  return w * size;
}

interface Candidate extends MapLabel {
  priority: number;
}

function roadLength(r: Road): number {
  let m = 0;
  for (let i = 1; i < r.coords.length; i++) {
    const [la1, lo1] = r.coords[i - 1];
    const [la2, lo2] = r.coords[i];
    const k = Math.cos((la1 * Math.PI) / 180) * M_PER_DEG_LON_EQ;
    m += Math.hypot((lo2 - lo1) * k, (la2 - la1) * M_PER_DEG_LAT);
  }
  return m;
}

/** The point halfway along a polyline. */
function halfway(r: Road): [number, number] {
  const half = roadLength(r) / 2;
  let m = 0;
  for (let i = 1; i < r.coords.length; i++) {
    const a = r.coords[i - 1];
    const b = r.coords[i];
    const k = Math.cos((a[0] * Math.PI) / 180) * M_PER_DEG_LON_EQ;
    const step = Math.hypot((b[1] - a[1]) * k, (b[0] - a[0]) * M_PER_DEG_LAT);
    if (m + step >= half && step > 0) {
      const t = (half - m) / step;
      return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
    }
    m += step;
  }
  return r.coords[Math.floor((r.coords.length - 1) / 2)];
}

/**
 * The direction of a road near a point: the main axis of all points of the same road
 * within `radius` metres. Road segments are short (about 60 m), so one segment alone
 * gives a poor angle for a label that is longer than it.
 */
function roadAngle(segments: Road[], at: [number, number], radius: number): number {
  const kx = Math.cos((at[0] * Math.PI) / 180) * M_PER_DEG_LON_EQ;
  const pts: [number, number][] = [];
  for (const s of segments) {
    for (const [la, lo] of s.coords) {
      const x = (lo - at[1]) * kx;
      const y = (la - at[0]) * M_PER_DEG_LAT;
      if (x * x + y * y <= radius * radius) pts.push([x, y]);
    }
  }
  if (pts.length < 2) return 0;
  const mx = pts.reduce((s, p) => s + p[0], 0) / pts.length;
  const my = pts.reduce((s, p) => s + p[1], 0) / pts.length;
  let sxx = 0;
  let syy = 0;
  let sxy = 0;
  for (const [x, y] of pts) {
    sxx += (x - mx) ** 2;
    syy += (y - my) ** 2;
    sxy += (x - mx) * (y - my);
  }
  let deg = ((0.5 * Math.atan2(2 * sxy, sxx - syy)) * 180) / Math.PI;
  if (deg > 90) deg -= 180;
  if (deg < -90) deg += 180;
  return deg;
}

/** The zoom level from which a road's name shows. Longer roads and bridges show first. */
function roadMinZoom(name: string, kind: Road["kind"], length: number): number {
  if (isMadeUpName(name)) return 18;
  if (kind !== "road") return 15;
  if (length >= 1200) return 14.5;
  if (length >= 400) return 15.5;
  return 16.5;
}

const LANDMARK_ZOOM: Record<NonNullable<Landmark["source"]>, number> = { hand: 15, app: 15.5, osm: 16.5 };
const LANDMARK_PRIORITY: Record<NonNullable<Landmark["source"]>, number> = { hand: 700, app: 600, osm: 200 };

function candidates(region: Region, zoom: number, show: Visible, mpp: number): Candidate[] {
  const out: Candidate[] = [];
  const base = { angle: 0, anchor: "middle" as const, dx: 0, dy: 0, strong: false };

  // Flooded roads are alerts, not street names: they show at every zoom, beside their cross.
  const flooded = new Set<string>();
  for (const r of region.roads) {
    if (r.status !== "flooded" || flooded.has(r.name)) continue;
    flooded.add(r.name);
    const [lat, lon] = r.coords[Math.floor((r.coords.length - 1) / 2)];
    out.push({ ...base, id: `flood:${r.id}`, kind: "flood", text: r.name, lat, lon, size: 12, weight: 600, anchor: "start", dx: 12, dy: 0, strong: true, priority: 1000 });
  }

  if (!show.names) return out;

  if (zoom >= 13 && zoom < 16.5) {
    for (const n of region.neighbourhoods ?? []) {
      out.push({ ...base, id: `hood:${n.id}`, kind: "hood", text: spaced(n.name), lat: n.lat, lon: n.lon, size: zoom < 14.5 ? 11 : 13, weight: 600, priority: 900 });
    }
  }

  const byName = new Map<string, Road[]>();
  for (const r of region.roads) {
    if (!r.name) continue;
    const list = byName.get(r.name);
    if (list) list.push(r);
    else byName.set(r.name, [r]);
  }
  for (const [name, segs] of byName) {
    const lengths = new Map(segs.map((s) => [s, roadLength(s)] as const));
    const total = [...lengths.values()].reduce((a, b) => a + b, 0);
    const kind = segs.find((s) => s.kind !== "road")?.kind ?? "road";
    if (zoom < roadMinZoom(name, kind, total)) continue;
    const madeUp = isMadeUpName(name);
    const strong = !madeUp && (kind !== "road" || total >= 1200);
    const size = madeUp ? 10 : strong ? 12 : 11;
    const weight = madeUp ? 500 : 600;
    const width = textWidth(name, size, weight);
    // One name every ~500 px along a long road, the longest segments first.
    const spacing = Math.max(500, width * 2.5) * mpp;
    const anchors: [number, number][] = [];
    const sorted = [...segs].sort((a, b) => lengths.get(b)! - lengths.get(a)!);
    for (const s of sorted) {
      const at = halfway(s);
      const kx = Math.cos((at[0] * Math.PI) / 180) * M_PER_DEG_LON_EQ;
      const far = anchors.every(([la, lo]) => Math.hypot((lo - at[1]) * kx, (la - at[0]) * M_PER_DEG_LAT) >= spacing);
      if (!far) continue;
      anchors.push(at);
      out.push({
        ...base,
        id: `road:${s.id}`,
        kind: "road",
        text: name,
        lat: at[0],
        lon: at[1],
        angle: roadAngle(segs, at, (width / 2) * mpp),
        size,
        weight,
        strong,
        priority: madeUp ? -500 : Math.min(499, (kind !== "road" ? 300 : 0) + Math.round(total / 50)),
      });
    }
  }

  if (show.places) {
    if (zoom >= 15) {
      for (const s of region.shelters) {
        out.push({ ...base, id: `shelter:${s.id}`, kind: "shelter", text: s.name, lat: s.lat, lon: s.lon, size: 11, weight: 600, anchor: "start", dx: 16, dy: 0, priority: 800 });
      }
    }
    for (const l of region.landmarks) {
      const src = l.source ?? "hand";
      if (zoom < LANDMARK_ZOOM[src]) continue;
      out.push({ ...base, id: `landmark:${l.id}`, kind: "landmark", text: l.name, lat: l.lat, lon: l.lon, size: 11, weight: 500, anchor: "start", dx: 6, dy: -8, priority: LANDMARK_PRIORITY[src] });
    }
  }
  return out;
}

type Box = [number, number, number, number];

/** The label's screen box in pixels, from a fixed origin, as an axis-aligned box around the turned text. */
function boxOf(c: Candidate, mpp: number, lat0: number): Box {
  const kx = Math.cos((lat0 * Math.PI) / 180) * M_PER_DEG_LON_EQ;
  const px = (c.lon * kx) / mpp + c.dx;
  const py = (-c.lat * M_PER_DEG_LAT) / mpp + c.dy;
  const w = textWidth(c.text, c.size, c.weight) + GAP * 2;
  const h = c.size * 1.25 + GAP * 2;
  if (c.anchor === "start") return [px - GAP, py - h / 2, px - GAP + w, py + h / 2];
  const a = (c.angle * Math.PI) / 180;
  const hw = (Math.abs(Math.cos(a)) * w + Math.abs(Math.sin(a)) * h) / 2;
  const hh = (Math.abs(Math.sin(a)) * w + Math.abs(Math.cos(a)) * h) / 2;
  return [px - hw, py - hh, px + hw, py + hh];
}

/**
 * Greedy placement: the most important label goes first, and a label that touches one
 * already placed is left out. Pixel distances on a Web Mercator map depend only on the
 * zoom, so this works for the Google map and the chart alike.
 */
function place(cands: Candidate[], mpp: number, lat0: number): Candidate[] {
  const CELL = 128;
  const grid = new Map<string, Box[]>();
  const placed: Candidate[] = [];
  const sorted = [...cands].sort((a, b) => b.priority - a.priority);
  for (const c of sorted) {
    const b = boxOf(c, mpp, lat0);
    const x0 = Math.floor(b[0] / CELL);
    const x1 = Math.floor(b[2] / CELL);
    const y0 = Math.floor(b[1] / CELL);
    const y1 = Math.floor(b[3] / CELL);
    let clear = true;
    for (let x = x0; x <= x1 && clear; x++) {
      for (let y = y0; y <= y1 && clear; y++) {
        clear = !(grid.get(`${x},${y}`) ?? []).some((o) => b[0] < o[2] && b[2] > o[0] && b[1] < o[3] && b[3] > o[1]);
      }
    }
    if (!clear) continue;
    placed.push(c);
    for (let x = x0; x <= x1; x++) {
      for (let y = y0; y <= y1; y++) {
        const k = `${x},${y}`;
        const cell = grid.get(k);
        if (cell) cell.push(b);
        else grid.set(k, [b]);
      }
    }
  }
  return placed;
}

let last: { key: string; region: Region; names: MapNames } | null = null;

/**
 * The names to draw at a zoom level. The zoom is rounded to a quarter step, so the list
 * (and the deck.gl data) stays the same while the map moves between two steps.
 */
export function mapNames(region: Region, zoom: number, show: Visible): MapNames {
  const z = Math.round(zoom * 4) / 4;
  const key = `${z}|${show.names}|${show.places}|${region.roads.map((r) => r.status[0]).join("")}`;
  if (last && last.region === region && last.key === key) return last.names;
  const lat0 = region.wards[0]?.lat ?? region.landmarks[0]?.lat ?? 0;
  const mpp = metresPerPx(z, lat0);
  const labels = place(candidates(region, z, show, mpp), mpp, lat0);
  const named = new Set(labels.filter((l) => l.kind === "landmark").map((l) => l.id.slice("landmark:".length)));
  const dots = show.places
    ? region.landmarks.filter((l) => (show.names ? named.has(l.id) : z >= LANDMARK_ZOOM[l.source ?? "hand"]))
    : [];
  const names: MapNames = { labels, dots };
  last = { key, region, names };
  return names;
}
