import type { Layer } from "@deck.gl/core";
import { PathStyleExtension, type PathStyleExtensionProps } from "@deck.gl/extensions";
import { IconLayer, PathLayer, ScatterplotLayer, TextLayer } from "@deck.gl/layers";
import type { FamilyPoint, Landmark, Region, Road, RouteLine, Shelter, TeamPoint, Ward } from "../types";
import type { Visible } from "./LayersMenu";
import type { Flash } from "./MapLayers";

type RGBA = [number, number, number, number];
type LonLat = [number, number];

/** The chart's colour tokens (styles.css), read for the current day or night theme. */
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
    hex: (name: string) => cs.getPropertyValue(name).trim(),
  };
}
export type Colours = ReturnType<typeof chartColours>;

export interface DeckInput {
  region: Region;
  families: FamilyPoint[];
  routes: RouteLine[];
  teams: TeamPoint[];
  pending: { id: string; lat: number; lon: number }[];
  flashes: Flash[];
  selected: string | null;
  focusRequest: string | null;
  zoom: number;
  show: Visible;
  colours: Colours;
  onSelectFamily: (id: string) => void;
  onRoadClick: (road: Road, at: { x: number; y: number }) => void;
}

const ll = ([lat, lon]: [number, number]): LonLat => [lon, lat];
const middle = (coords: [number, number][]): LonLat => ll(coords[Math.floor((coords.length - 1) / 2)]);
const FONT = "Archivo, 'Arial Narrow', system-ui, sans-serif";
const dashed = [new PathStyleExtension({ dash: true })];

function svgIcon(svg: string, size: number) {
  return { url: `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`, width: size, height: size };
}

function clientPoint(event: unknown, fallback: { x: number; y: number }) {
  const src = (event as { srcEvent?: { clientX?: number; clientY?: number } } | undefined)?.srcEvent;
  return src?.clientX !== undefined && src.clientY !== undefined ? { x: src.clientX, y: src.clientY } : fallback;
}

/**
 * The operational layers as deck.gl layers, drawn in the Google map's own frame,
 * so they stay in place while the map zooms, tilts or turns.
 * The look follows MapLayers.tsx (the built-in chart) and the chart's CSS tokens.
 */
export function buildLayers(d: DeckInput): Layer[] {
  const c = d.colours;
  const zoomedIn = d.zoom >= 16;
  const show = d.show;
  const news = d.region.roads.filter((r) => r.kind !== "road" || r.status !== "open" || (show.low && r.low_lying));
  const families = d.families.filter((f) => show.served || f.status !== "SERVED");
  // The route a coordinator opened stays visible even with routes hidden.
  const routes = show.routes ? d.routes : d.routes.filter((rt) => rt.id === d.focusRequest);
  const flooded = d.region.roads.filter((r) => r.status === "flooded");
  const roadLabels = [
    ...new Map(
      d.region.roads
        .filter((r) => r.status === "flooded" || (zoomedIn && r.kind !== "road"))
        .map((r) => [r.name, r] as const),
    ).values(),
  ];
  const statusKey = d.region.roads.map((r) => r.status[0]).join("");

  const roadColour = (r: Road): RGBA =>
    r.status === "flooded" ? c.hazard
    : r.status === "reported" ? c.waiting
    : r.kind !== "road" ? [c.ink[0], c.ink[1], c.ink[2], 150]
    : [c.waterInk[0], c.waterInk[1], c.waterInk[2], 190];
  const roadWidth = (r: Road) =>
    r.status === "flooded" ? 5 : r.status === "reported" ? 3.5 : r.kind !== "road" ? 3 : 1.5;
  // Dash lengths are in multiples of half the line width.
  const roadDash = (r: Road): [number, number] =>
    r.status === "reported" ? [3.4, 2.9] : r.status === "flooded" || r.kind !== "road" ? [0, 0] : [2.7, 5.3];

  const radius = (f: FamilyPoint) => 4 + Math.sqrt(f.people || 1) * 2.2;
  const famFill = (f: FamilyPoint): RGBA =>
    f.status === "SERVED" ? c.paper : f.status === "ASSIGNED" ? c.route : c.waiting;
  const famLine = (f: FamilyPoint): RGBA =>
    d.selected === f.id ? c.ink : f.status === "SERVED" ? c.served : c.paper;
  const critical = families.filter((f) => f.status !== "SERVED" && (f.priority ?? 0) >= 70);

  const shelterIcon = svgIcon(
    `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24"><path d="M3 20L12 3L21 20Z" fill="${c.hex("--served-soft")}" stroke="${c.hex("--served")}" stroke-width="2"/></svg>`,
    24,
  );
  const teamIcon = svgIcon(
    `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24"><rect x="1" y="1" width="22" height="22" rx="3" fill="${c.hex("--ink")}"/></svg>`,
    24,
  );
  const text = {
    fontFamily: FONT,
    fontWeight: 700,
    characterSet: "auto" as const,
    fontSettings: { sdf: true },
    // Relative to the font size.
    outlineWidth: 0.25,
    outlineColor: c.paper,
    sizeUnits: "pixels" as const,
  };

  return [
    new PathLayer<Ward, PathStyleExtensionProps<Ward>>({
      id: "wards",
      data: show.wards ? d.region.wards : [],
      getPath: (w) => [...w.polygon, w.polygon[0]].map(ll),
      getColor: [c.ink3[0], c.ink3[1], c.ink3[2], 150],
      getWidth: 1,
      widthUnits: "pixels",
      getDashArray: [8, 8],
      extensions: dashed,
    }),
    new TextLayer<Ward>({
      id: "ward-numbers",
      data: show.wards ? d.region.wards : [],
      getPosition: (w) => ll(w.polygon[0]),
      getText: (w) => String(w.num),
      getPixelOffset: [12, 14],
      getSize: 13,
      getColor: c.ink3,
      ...text,
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
    new PathLayer<RouteLine, PathStyleExtensionProps<RouteLine>>({
      id: "routes",
      data: routes,
      getPath: (rt) => rt.route.map(ll),
      getColor: c.route,
      getWidth: (rt) => (rt.id === d.focusRequest ? 4 : 2.5),
      widthUnits: "pixels",
      capRounded: true,
      getDashArray: (rt) => (rt.id === d.focusRequest ? [0, 0] : [1.6, 4]),
      extensions: dashed,
      updateTriggers: { getWidth: d.focusRequest, getDashArray: d.focusRequest },
    }),
    new TextLayer<Road>({
      id: "flood-marks",
      data: flooded,
      getPosition: (r) => middle(r.coords),
      getText: () => "✕",
      getSize: 16,
      getColor: c.hazard,
      ...text,
    }),
    new IconLayer<Shelter>({
      id: "shelters",
      data: show.places ? d.region.shelters : [],
      getPosition: (s) => [s.lon, s.lat],
      getIcon: () => shelterIcon,
      getSize: 20,
      sizeUnits: "pixels",
      updateTriggers: { getIcon: shelterIcon.url },
    }),
    new TextLayer<Shelter>({
      id: "shelter-names",
      data: zoomedIn && show.places ? d.region.shelters : [],
      getPosition: (s) => [s.lon, s.lat],
      getText: (s) => s.name,
      getPixelOffset: [14, 0],
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
      data: zoomedIn && show.places ? d.region.landmarks : [],
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
      id: "critical",
      data: critical,
      getPosition: (f) => [f.lon, f.lat],
      getRadius: (f) => radius(f) + 4,
      radiusUnits: "pixels",
      filled: false,
      stroked: true,
      getLineColor: c.hazard,
      getLineWidth: 2,
      lineWidthUnits: "pixels",
    }),
    new ScatterplotLayer<FamilyPoint>({
      id: "households",
      data: families,
      getPosition: (f) => [f.lon, f.lat],
      getRadius: radius,
      radiusUnits: "pixels",
      stroked: true,
      getFillColor: famFill,
      getLineColor: famLine,
      getLineWidth: (f) => (d.selected === f.id ? 3 : f.status === "SERVED" ? 2 : 1.5),
      lineWidthUnits: "pixels",
      pickable: true,
      onClick: (info) => {
        if (info.object) d.onSelectFamily(info.object.id);
        return true;
      },
      updateTriggers: { getLineColor: [d.selected, c.ink], getLineWidth: d.selected, getFillColor: c.route },
    }),
    new IconLayer<TeamPoint>({
      id: "teams",
      data: d.teams,
      getPosition: (t) => [t.lon, t.lat],
      getIcon: () => teamIcon,
      getSize: 19,
      sizeUnits: "pixels",
      updateTriggers: { getIcon: teamIcon.url },
    }),
    new TextLayer<TeamPoint>({
      id: "team-initials",
      data: d.teams,
      getPosition: (t) => [t.lon, t.lat],
      getText: (t) => t.name.replace("Team ", "").slice(0, 2),
      getSize: 10,
      getColor: c.paper,
      ...text,
      outlineWidth: 0,
      fontWeight: 800,
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
}
