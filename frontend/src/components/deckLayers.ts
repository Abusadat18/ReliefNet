import type { Layer, Position } from "@deck.gl/core";
import { PathStyleExtension, type PathStyleExtensionProps } from "@deck.gl/extensions";
import { IconLayer, PathLayer, ScatterplotLayer, SolidPolygonLayer, TextLayer } from "@deck.gl/layers";
import type { FamilyPoint, Landmark, Region, Road, RouteLine, Shelter, TeamPoint, Ward } from "../types";
import { clusterFamilies, clusterRing, type Cluster } from "./clusters";
import type { Visible } from "./LayersMenu";
import type { Flash } from "./MapLayers";
import { chipOffsets, type MemoryChip, type MemoryView } from "./memory";

type RGBA = [number, number, number, number];
type LonLat = [number, number];

/** The map tokens (map.css), read for the current day or night theme. */
export function chartColours() {
  const cs = getComputedStyle(document.documentElement);
  const rgb = (name: string, alpha = 255): RGBA => {
    const hex = cs.getPropertyValue(name).trim().replace("#", "");
    const n = parseInt(hex.length === 3 ? [...hex].map((c) => c + c).join("") : hex, 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255, alpha];
  };
  return {
    ink: rgb("--ink"),
    ink2: rgb("--ink-2"),
    ink3: rgb("--ink-3"),
    paper: rgb("--paper"),
    hazard: rgb("--hazard"),
    route: rgb("--route"),
    served: rgb("--served"),
    servedSoft: rgb("--served-soft"),
    waiting: rgb("--waiting"),
    waterInk: rgb("--water-ink"),
    direction: rgb("--direction"),
    directionEdge: rgb("--direction-edge"),
    primary: rgb("--primary"),
    info: rgb("--info"),
    infoSoft: rgb("--info-soft"),
    popover: rgb("--popover"),
    hex: (name: string) => cs.getPropertyValue(name).trim(),
  };
}
export type Colours = ReturnType<typeof chartColours>;

export interface AreaBounds {
  south: number;
  north: number;
  west: number;
  east: number;
}

export interface DeckInput {
  region: Region;
  bounds: AreaBounds;
  families: FamilyPoint[];
  routes: RouteLine[];
  teams: TeamPoint[];
  pending: { id: string; lat: number; lon: number }[];
  flashes: Flash[];
  selected: string | null;
  focusRequest: string | null;
  memory: MemoryView | null;
  zoom: number;
  show: Visible;
  colours: Colours;
  night: boolean;
  onSelectFamily: (id: string) => void;
  onZoomTo: (lat: number, lon: number) => void;
  onRoadClick: (road: Road, at: { x: number; y: number }) => void;
}

const ll = ([lat, lon]: [number, number]): LonLat => [lon, lat];
const middle = (coords: [number, number][]): LonLat => ll(coords[Math.floor((coords.length - 1) / 2)]);
const FONT = "'Inter Variable', Inter, system-ui, sans-serif";
const MONO = "'JetBrains Mono Variable', ui-monospace, monospace";
const dashed = [new PathStyleExtension({ dash: true })];
const alpha = (c: RGBA, a: number): RGBA => [c[0], c[1], c[2], a];

function svgIcon(svg: string, size: number) {
  return { url: `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`, width: size, height: size };
}

function clientPoint(event: unknown, fallback: { x: number; y: number }) {
  const src = (event as { srcEvent?: { clientX?: number; clientY?: number } } | undefined)?.srcEvent;
  return src?.clientX !== undefined && src.clientY !== undefined ? { x: src.clientX, y: src.clientY } : fallback;
}

/** Pixels per degree of latitude at a Web Mercator zoom level. */
const pxPerDeg = (zoom: number) => (256 * 2 ** zoom) / 360;

/**
 * The operational layers as deck.gl layers, drawn in the Google map's own frame,
 * so they stay in place while the map zooms, tilts or turns.
 * The look follows MapLayers.tsx (the built-in chart) and the map tokens in map.css.
 */
export function buildLayers(d: DeckInput): Layer[] {
  const c = d.colours;
  const zoomedIn = d.zoom >= 16;
  const show = d.show;
  const news = d.region.roads.filter((r) => r.kind !== "road" || r.status !== "open" || (show.low && r.low_lying));
  const families = d.families.filter((f) => show.served || f.status !== "SERVED");
  const selectedReq = d.families.find((f) => f.id === d.selected)?.request ?? null;
  const focus = d.focusRequest ?? selectedReq;
  // The route a coordinator opened stays visible even with routes hidden.
  const routes = show.routes ? d.routes : d.routes.filter((rt) => rt.id === focus);
  const focused = routes.filter((rt) => rt.id === focus);
  const flooded = d.region.roads.filter((r) => r.status === "flooded");
  const roadLabels = [
    ...new Map(
      d.region.roads.filter((r) => r.status === "flooded" || (zoomedIn && r.kind !== "road")).map((r) => [r.name, r] as const),
    ).values(),
  ];
  const statusKey = d.region.roads.map((r) => r.status[0]).join("");

  // Households closer than 22 px on screen become one count bubble, until the map is close in.
  const groups: Cluster[] = d.zoom >= 17.5 ? families.map((f) => ({ lat: f.lat, lon: f.lon, members: [f] })) : clusterFamilies(families, pxPerDeg(d.zoom));
  const clusters = groups.filter((g) => g.members.length > 1);
  const singles = groups.filter((g) => g.members.length === 1).map((g) => g.members[0]);
  const pills = singles.filter((f) => f.status !== "SERVED" && (f.priority ?? 0) >= 70);
  const dots = singles.filter((f) => !pills.includes(f));

  const roadColour = (r: Road): RGBA =>
    r.status === "flooded" ? c.hazard
    : r.status === "reported" ? c.waiting
    : r.kind !== "road" ? alpha(c.ink, 150)
    : alpha(c.waterInk, 140);
  const roadWidth = (r: Road) => (r.status === "flooded" ? 5 : r.status === "reported" ? 3.5 : r.kind !== "road" ? 3 : 1.6);
  // Dash lengths are in multiples of half the line width; only reported roads dash.
  const roadDash = (r: Road): [number, number] => (r.status === "reported" ? [3.4, 2.9] : [0, 0]);

  const famFill = (f: FamilyPoint): RGBA => (f.status === "SERVED" ? c.paper : f.status === "ASSIGNED" ? c.route : c.waiting);
  const famLine = (f: FamilyPoint): RGBA => (d.selected === f.id ? c.ink : f.status === "SERVED" ? c.served : c.paper);
  const ringOf = (g: Cluster): RGBA => {
    const r = clusterRing(g.members);
    // A dark ring would vanish on the dark bubble, so "team on the way" uses the light water blue.
    return r === "hazard" ? c.hazard : r === "waiting" ? c.waiting : c.waterInk;
  };

  const shelterIcon = svgIcon(
    `<svg xmlns="http://www.w3.org/2000/svg" width="44" height="44"><circle cx="22" cy="22" r="19" fill="${c.hex("--served-soft")}" stroke="${c.hex("--served")}" stroke-width="3"/><path d="M13 30 L22 14 L31 30 Z M22 30 L22 22" fill="none" stroke="${c.hex("--served")}" stroke-width="2.6" stroke-linejoin="round"/></svg>`,
    44,
  );

  const text = {
    fontFamily: FONT,
    fontWeight: 600,
    characterSet: "auto" as const,
    fontSettings: { sdf: true },
    // Relative to the font size.
    outlineWidth: 0.25,
    outlineColor: c.paper,
    sizeUnits: "pixels" as const,
  };
  const pill = {
    ...text,
    outlineWidth: 0,
    background: true,
    backgroundBorderRadius: 999,
    getBorderColor: c.paper,
    getBorderWidth: 2,
  };

  // The world outside the operation area is dimmed, so the eye stays on the area.
  const b = d.bounds;
  const pad = 1;
  const mask: { polygon: Position[][] }[] = [
    {
      polygon: [
        [
          [b.west - pad, b.south - pad],
          [b.east + pad, b.south - pad],
          [b.east + pad, b.north + pad],
          [b.west - pad, b.north + pad],
        ],
        [
          [b.west, b.south],
          [b.west, b.north],
          [b.east, b.north],
          [b.east, b.south],
        ],
      ],
    },
  ];

  const base: Layer[] = [
    new SolidPolygonLayer<{ polygon: Position[][] }>({
      id: "outside-mask",
      data: mask,
      getPolygon: (m) => m.polygon,
      getFillColor: d.night ? [11, 17, 20, 150] : [248, 246, 241, 160],
      updateTriggers: { getFillColor: d.night },
    }),
    new PathLayer<{ path: LonLat[] }>({
      id: "area-edge",
      data: [{ path: [[b.west, b.south], [b.west, b.north], [b.east, b.north], [b.east, b.south], [b.west, b.south]] }],
      getPath: (p) => p.path,
      getColor: alpha(c.route, 140),
      getWidth: 1.5,
      widthUnits: "pixels",
    }),
    new PathLayer<Ward, PathStyleExtensionProps<Ward>>({
      id: "wards",
      data: show.wards ? d.region.wards : [],
      getPath: (w) => [...w.polygon, w.polygon[0]].map(ll),
      getColor: alpha(c.ink3, 150),
      getWidth: 1,
      widthUnits: "pixels",
      getDashArray: [8, 8],
      extensions: dashed,
    }),
    new TextLayer<Ward>({
      id: "ward-numbers",
      data: show.wards ? d.region.wards : [],
      getPosition: (w) => ll(w.polygon[0]),
      getText: (w) => `WARD ${w.num}`,
      getPixelOffset: [12, 14],
      getTextAnchor: "start",
      getSize: 10,
      getColor: c.ink3,
      ...text,
      fontFamily: MONO,
    }),
    // Every road can be clicked to report it. The paths are transparent because Google
    // draws the streets; deck.gl still picks transparent paths.
    new PathLayer<Road>({
      id: "road-hit",
      data: d.region.roads,
      getPath: (r) => r.coords.map(ll),
      getColor: [0, 0, 0, 0],
      getWidth: 14,
      widthUnits: "pixels",
      pickable: true,
      onClick: (info, event) => {
        if (info.object) d.onRoadClick(info.object, clientPoint(event, { x: info.x, y: info.y }));
        return true;
      },
    }),
    new PathLayer<Road, PathStyleExtensionProps<Road>>({
      id: "roads",
      data: news,
      getPath: (r) => r.coords.map(ll),
      getColor: roadColour,
      getWidth: roadWidth,
      widthUnits: "pixels",
      capRounded: true,
      jointRounded: true,
      getDashArray: roadDash,
      extensions: dashed,
      updateTriggers: { getColor: [statusKey, c.hazard], getWidth: statusKey, getDashArray: statusKey },
    }),
    new PathLayer<RouteLine>({
      id: "routes",
      data: routes.filter((rt) => rt.id !== focus),
      getPath: (rt) => rt.route.map(ll),
      getColor: alpha(c.route, 90),
      getWidth: 2,
      widthUnits: "pixels",
      capRounded: true,
      jointRounded: true,
    }),
    new PathLayer<RouteLine>({
      id: "route-focus-casing",
      data: focused,
      getPath: (rt) => rt.route.map(ll),
      getColor: c.directionEdge,
      getWidth: 8,
      widthUnits: "pixels",
      capRounded: true,
      jointRounded: true,
    }),
    new PathLayer<RouteLine>({
      id: "route-focus",
      data: focused,
      getPath: (rt) => rt.route.map(ll),
      getColor: c.direction,
      getWidth: 4,
      widthUnits: "pixels",
      capRounded: true,
      jointRounded: true,
    }),
    new TextLayer<Road>({
      id: "flood-marks",
      data: flooded,
      getPosition: (r) => middle(r.coords),
      getText: () => "✕",
      getSize: 16,
      getColor: c.hazard,
      ...text,
      fontWeight: 700,
    }),
    new IconLayer<Shelter>({
      id: "shelters",
      data: show.places ? d.region.shelters : [],
      getPosition: (s) => [s.lon, s.lat],
      getIcon: () => shelterIcon,
      getSize: 22,
      sizeUnits: "pixels",
      updateTriggers: { getIcon: shelterIcon.url },
    }),
    new TextLayer<Shelter>({
      id: "shelter-names",
      data: zoomedIn && show.places ? d.region.shelters : [],
      getPosition: (s) => [s.lon, s.lat],
      getText: (s) => s.name,
      getPixelOffset: [16, 0],
      getTextAnchor: "start",
      getSize: 11,
      getColor: c.served,
      ...text,
    }),
    new ScatterplotLayer<Landmark>({
      id: "landmarks",
      data: zoomedIn && show.places ? d.region.landmarks : [],
      getPosition: (l) => [l.lon, l.lat],
      getRadius: 2.5,
      radiusUnits: "pixels",
      getFillColor: c.paper,
      getLineColor: c.ink2,
      stroked: true,
      lineWidthUnits: "pixels",
      getLineWidth: 1,
    }),
    new TextLayer<Landmark>({
      id: "landmark-names",
      // OpenStreetMap adds hundreds of small places; name them only when the map is close in.
      data: zoomedIn && show.places ? d.region.landmarks.filter((l) => l.source !== "osm" || d.zoom >= 17.5) : [],
      getPosition: (l) => [l.lon, l.lat],
      getText: (l) => l.name,
      getPixelOffset: [6, -8],
      getTextAnchor: "start",
      getSize: 11,
      getColor: c.ink2,
      ...text,
      fontWeight: 500,
    }),
    new ScatterplotLayer<{ id: string; lat: number; lon: number }>({
      id: "pending",
      data: d.pending,
      getPosition: (p) => [p.lon, p.lat],
      getRadius: 3,
      radiusUnits: "pixels",
      getFillColor: c.ink3,
    }),
    new ScatterplotLayer<FamilyPoint>({
      id: "households",
      data: dots,
      getPosition: (f) => [f.lon, f.lat],
      getRadius: (f) => (d.selected === f.id ? 8 : 7),
      radiusUnits: "pixels",
      stroked: true,
      getFillColor: famFill,
      getLineColor: famLine,
      getLineWidth: (f) => (d.selected === f.id ? 3 : 2),
      lineWidthUnits: "pixels",
      pickable: true,
      onClick: (info) => {
        if (info.object) d.onSelectFamily(info.object.id);
        return true;
      },
      updateTriggers: { getLineColor: [d.selected, c.ink], getLineWidth: d.selected, getRadius: d.selected, getFillColor: c.route },
    }),
    // Priority 70 or more: the score itself, on a pill, so it cannot be mistaken for a map pin.
    new TextLayer<FamilyPoint>({
      id: "priority-pills",
      data: pills,
      getPosition: (f) => [f.lon, f.lat],
      getText: (f) => String(f.priority),
      getSize: 11,
      getColor: (f) => (f.status === "ASSIGNED" && d.night ? c.paper : [255, 255, 255, 255]),
      getBackgroundColor: (f) => (f.status === "ASSIGNED" ? c.route : c.hazard),
      backgroundPadding: [7, 4],
      ...pill,
      fontFamily: MONO,
      fontWeight: 700,
      pickable: true,
      onClick: (info) => {
        if (info.object) d.onSelectFamily(info.object.id);
        return true;
      },
      updateTriggers: { getColor: d.night, getBackgroundColor: c.route },
    }),
    new ScatterplotLayer<Cluster>({
      id: "clusters",
      data: clusters,
      getPosition: (g) => [g.lon, g.lat],
      getRadius: 15,
      radiusUnits: "pixels",
      stroked: true,
      getFillColor: c.ink,
      getLineColor: ringOf,
      getLineWidth: 3,
      lineWidthUnits: "pixels",
      pickable: true,
      onClick: (info) => {
        if (info.object) d.onZoomTo(info.object.lat, info.object.lon);
        return true;
      },
      updateTriggers: { getLineColor: c.hazard, getFillColor: c.ink },
    }),
    new TextLayer<Cluster>({
      id: "cluster-counts",
      data: clusters,
      getPosition: (g) => [g.lon, g.lat],
      getText: (g) => String(g.members.length),
      getSize: 13,
      getColor: c.paper,
      ...text,
      outlineWidth: 0,
      fontWeight: 700,
    }),
    new ScatterplotLayer<TeamPoint>({
      id: "team-anchors",
      data: d.teams,
      getPosition: (t) => [t.lon, t.lat],
      getRadius: 6,
      radiusUnits: "pixels",
      stroked: true,
      getFillColor: c.ink,
      getLineColor: c.paper,
      getLineWidth: 2,
      lineWidthUnits: "pixels",
    }),
    // The team by its name and load, not by two letters.
    new TextLayer<TeamPoint>({
      id: "team-pills",
      data: d.teams,
      getPosition: (t) => [t.lon, t.lat],
      getText: (t) => `${t.name} · ${t.load} job${t.load === 1 ? "" : "s"}`,
      getPixelOffset: [0, -22],
      getSize: 11,
      getColor: c.paper,
      getBackgroundColor: c.ink,
      backgroundPadding: [9, 5],
      ...pill,
      getBorderWidth: 0,
    }),
    new TextLayer<Road>({
      id: "road-names",
      data: roadLabels,
      getPosition: (r) => middle(r.coords),
      getText: (r) => r.name,
      getPixelOffset: [12, 0],
      getTextAnchor: "start",
      getSize: 12,
      getColor: (r) => (r.status === "flooded" ? c.hazard : c.ink),
      ...text,
      updateTriggers: { getColor: [statusKey, c.hazard] },
    }),
    new ScatterplotLayer<Flash>({
      id: "flashes",
      data: d.flashes,
      getPosition: (f) => [f.lon, f.lat],
      getRadius: 22,
      radiusUnits: "pixels",
      filled: false,
      stroked: true,
      getLineColor: c.hazard,
      getLineWidth: 2,
      lineWidthUnits: "pixels",
    }),
  ];
  return [...base, ...memoryLayers(d, pill)];
}

type ChipAt = MemoryChip & { at: LonLat; mid: LonLat };

/**
 * The Memory layer: a veil over the other layers, then the selected household with
 * its graph neighbours in a ring. The ring keeps its size in pixels at every zoom.
 */
function memoryLayers(d: DeckInput, pill: Record<string, unknown>): Layer[] {
  const m = d.memory;
  if (!m) return [];
  const c = d.colours;
  const ppd = pxPerDeg(d.zoom);
  const home: LonLat = [m.family.lon, m.family.lat];
  const cos = Math.cos((m.family.lat * Math.PI) / 180);
  const shift = ([dx, dy]: [number, number], f = 1): LonLat => [home[0] + (dx * f) / ppd, home[1] - (dy * f * cos) / ppd];
  const offsets = chipOffsets(m.chips.length);
  const chips: ChipAt[] = m.chips.map((ch, i) => ({ ...ch, at: shift(offsets[i]), mid: shift(offsets[i], 0.5) }));
  const team = m.team;
  const fill = (ch: MemoryChip): RGBA => (ch.kind === "request" ? c.infoSoft : ch.kind === "lesson" ? c.servedSoft : c.popover);
  const ink = (ch: MemoryChip): RGBA => (ch.kind === "request" ? c.info : ch.kind === "lesson" ? c.served : c.ink);
  const big = 1e3;
  return [
    new SolidPolygonLayer<{ polygon: Position[] }>({
      id: "memory-veil",
      data: [{ polygon: [[-big, -85], [big, -85], [big, 85], [-big, 85]] }],
      getPolygon: (v) => v.polygon,
      getFillColor: d.night ? [11, 17, 20, 170] : [248, 246, 241, 175],
      updateTriggers: { getFillColor: d.night },
    }),
    new PathLayer<{ path: LonLat[] }, PathStyleExtensionProps<{ path: LonLat[] }>>({
      id: "memory-team-link",
      data: team ? [{ path: [home, [team.lon, team.lat]] }] : [],
      getPath: (l) => l.path,
      getColor: c.route,
      getWidth: 2,
      widthUnits: "pixels",
      getDashArray: [4, 3],
      extensions: dashed,
    }),
    new PathLayer<ChipAt>({
      id: "memory-links",
      data: chips,
      getPath: (ch) => [home, ch.at],
      getColor: alpha(c.primary, 170),
      getWidth: 1.5,
      widthUnits: "pixels",
    }),
    new ScatterplotLayer<TeamPoint>({
      id: "memory-team",
      data: team ? [team] : [],
      getPosition: (t) => [t.lon, t.lat],
      getRadius: 6,
      radiusUnits: "pixels",
      stroked: true,
      getFillColor: c.ink,
      getLineColor: c.paper,
      getLineWidth: 2,
      lineWidthUnits: "pixels",
    }),
    new TextLayer<TeamPoint>({
      id: "memory-team-pill",
      data: team ? [team] : [],
      getPosition: (t) => [t.lon, t.lat],
      getText: (t) => `${t.name} · ${t.load} job${t.load === 1 ? "" : "s"}`,
      getPixelOffset: [0, -22],
      getSize: 11,
      getColor: c.paper,
      getBackgroundColor: c.ink,
      backgroundPadding: [9, 5],
      ...pill,
      getBorderWidth: 0,
    }),
    new TextLayer<{ at: LonLat }>({
      id: "memory-team-edge",
      data: team ? [{ at: [(home[0] + team.lon) / 2, (home[1] + team.lat) / 2] }] : [],
      getPosition: (l) => l.at,
      getText: () => "ASSIGNED_TO",
      getSize: 9,
      getColor: c.primary,
      getBackgroundColor: c.paper,
      backgroundPadding: [5, 2],
      ...pill,
      backgroundBorderRadius: 4,
      getBorderWidth: 0,
      fontFamily: MONO,
      fontWeight: 700,
    }),
    new ScatterplotLayer<FamilyPoint>({
      id: "memory-household",
      data: [m.family],
      getPosition: (f) => [f.lon, f.lat],
      getRadius: 9,
      radiusUnits: "pixels",
      stroked: true,
      getFillColor: m.family.status === "SERVED" ? c.paper : m.family.status === "ASSIGNED" ? c.route : c.waiting,
      getLineColor: c.ink,
      getLineWidth: 3,
      lineWidthUnits: "pixels",
    }),
    new TextLayer<ChipAt>({
      id: "memory-edges",
      data: chips,
      getPosition: (ch) => ch.mid,
      getText: (ch) => ch.edge,
      getSize: 9,
      getColor: c.primary,
      getBackgroundColor: c.paper,
      backgroundPadding: [5, 2],
      ...pill,
      backgroundBorderRadius: 4,
      getBorderWidth: 0,
      fontFamily: MONO,
      fontWeight: 700,
    }),
    new TextLayer<ChipAt>({
      id: "memory-nodes",
      data: chips,
      getPosition: (ch) => ch.at,
      getText: (ch) => ch.label,
      getSize: 11,
      getColor: ink,
      getBackgroundColor: fill,
      backgroundPadding: [9, 6],
      ...pill,
      backgroundBorderRadius: 6,
      getBorderColor: alpha(c.ink3, 120),
      getBorderWidth: 1,
      fontFamily: MONO,
      fontWeight: 600,
    }),
  ];
}
