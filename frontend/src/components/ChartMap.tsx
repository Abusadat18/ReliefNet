import { useCallback, useEffect, useMemo, useRef, useState, type PointerEvent, type WheelEvent } from "react";
import { MapLayers, pathOf, type LayerProps } from "./MapLayers";

const M_PER_DEG_LAT = 111_000;
const M_PER_DEG_LON = 100_300;

interface View {
  x: number;
  y: number;
  w: number;
  h: number;
}

export type { Flash } from "./MapLayers";

/** The built-in chart. It needs no map service, so it also works offline. */
export function ChartMap(props: LayerProps) {
  const { region } = props;
  const svgRef = useRef<SVGSVGElement>(null);
  const [size, setSize] = useState({ w: 1000, h: 700 });

  const origin = useMemo(() => {
    const pts = region.wards.flatMap((w) => w.polygon);
    const lats = pts.map((p) => p[0]);
    const lons = pts.map((p) => p[1]);
    return { lat: Math.max(...lats), lon: Math.min(...lons), maxLat: Math.min(...lats), maxLon: Math.max(...lons) };
  }, [region.wards]);

  const P = useCallback(
    (lat: number, lon: number): [number, number] => [
      (lon - origin.lon) * M_PER_DEG_LON,
      (origin.lat - lat) * M_PER_DEG_LAT,
    ],
    [origin],
  );

  const full = useMemo<View>(() => {
    const [w, h] = P(origin.maxLat, origin.maxLon);
    const pad = 260;
    return { x: -pad, y: -pad, w: w + pad * 2, h: h + pad * 2 };
  }, [P, origin]);

  const [view, setView] = useState<View>(full);
  useEffect(() => setView(full), [full]);

  useEffect(() => {
    const el = svgRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setSize({ w: e.contentRect.width, h: e.contentRect.height }));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Keep the view's aspect equal to the element's, so 1 unit is square.
  const vb = useMemo(() => {
    const aspect = size.w / Math.max(size.h, 1);
    let { x, y, w, h } = view;
    if (w / h > aspect) {
      const nh = w / aspect;
      y -= (nh - h) / 2;
      h = nh;
    } else {
      const nw = h * aspect;
      x -= (nw - w) / 2;
      w = nw;
    }
    return { x, y, w, h };
  }, [view, size]);
  const u = vb.w / Math.max(size.w, 1); // metres per screen pixel

  // Label each named water body once, near the middle of its longest piece.
  const waterNames = useMemo(() => {
    const out: { name: string; at: [number, number]; big: boolean }[] = [];
    for (const wa of region.water_areas ?? []) {
      const pts = wa.polygon;
      if (wa.name && pts.length) out.push({ name: wa.name, at: pts[Math.floor(pts.length * 0.15)], big: true });
    }
    const best = new Map<string, [number, number][]>();
    for (const wl of region.water_lines ?? []) {
      if (wl.name && wl.line.length > (best.get(wl.name)?.length ?? 0)) best.set(wl.name, wl.line);
    }
    best.forEach((pts, name) => {
      if (!out.some((o) => o.name === name)) out.push({ name, at: pts[Math.floor(pts.length / 2)], big: false });
    });
    return out;
  }, [region]);

  const toWorld = (cx: number, cy: number) => {
    const r = svgRef.current!.getBoundingClientRect();
    return { x: vb.x + ((cx - r.left) / r.width) * vb.w, y: vb.y + ((cy - r.top) / r.height) * vb.h };
  };

  const zoomAt = (factor: number, cx?: number, cy?: number) => {
    setView((v) => {
      const p = cx === undefined ? { x: v.x + v.w / 2, y: v.y + v.h / 2 } : toWorld(cx, cy!);
      const w = Math.min(Math.max(v.w * factor, 600), full.w * 2.5);
      const k = w / v.w;
      return { x: p.x - (p.x - v.x) * k, y: p.y - (p.y - v.y) * k, w, h: v.h * k };
    });
  };

  const drag = useRef<{ x: number; y: number; moved: boolean } | null>(null);
  const [dragging, setDragging] = useState(false);
  const onDown = (e: PointerEvent) => {
    if ((e.target as Element).closest("[data-click]")) return;
    drag.current = { x: e.clientX, y: e.clientY, moved: false };
    (e.target as Element).setPointerCapture?.(e.pointerId);
  };
  const onMove = (e: PointerEvent) => {
    const d = drag.current;
    if (!d) return;
    const dx = e.clientX - d.x;
    const dy = e.clientY - d.y;
    if (Math.abs(dx) + Math.abs(dy) > 3) {
      d.moved = true;
      setDragging(true);
    }
    d.x = e.clientX;
    d.y = e.clientY;
    setView((v) => ({ ...v, x: v.x - dx * u, y: v.y - dy * u }));
  };
  const onUp = () => {
    drag.current = null;
    setDragging(false);
  };
  const onWheel = (e: WheelEvent) => zoomAt(e.deltaY > 0 ? 1.15 : 1 / 1.15, e.clientX, e.clientY);

  const path = (pts: [number, number][], close = false) => pathOf(P, pts, close);
  const showLabels = u < 3.2;

  return (
    <>
      <svg
        ref={svgRef}
        className={`chart${dragging ? " dragging" : ""}`}
        viewBox={`${vb.x} ${vb.y} ${vb.w} ${vb.h}`}
        onPointerDown={onDown}
        onPointerMove={onMove}
        onPointerUp={onUp}
        onPointerLeave={onUp}
        onWheel={onWheel}
        role="img"
        aria-label={`Chart of ${region.area?.title || "the area"} with wards, water, roads, households and team routes`}
      >
        {/* Land runs on past the operation zone; it is faded there. */}
        <rect className="land-outside" x={full.x - full.w} y={full.y - full.h} width={full.w * 3} height={full.h * 3} />
        {region.wards.map((w) => (
          <path key={w.num} className="land" d={path(w.polygon, true)} />
        ))}
        {(region.water_areas ?? []).map((wa, i) => (
          <path key={`wa${i}`} className="river" d={path(wa.polygon, true)} />
        ))}
        {(region.water_lines ?? []).map((wl, i) => (
          <path key={`wl${i}`} className={`water-line ${wl.kind}`} d={path(wl.line)} />
        ))}
        {(region.rail ?? []).map((r, i) => (
          <g key={`rl${i}`}>
            <path className="rail" d={path(r)} />
            <path className="rail-ties" d={path(r)} />
          </g>
        ))}
        {waterNames.map((w) => {
          const [x, y] = P(w.at[0], w.at[1]);
          return (
            <text key={w.name} className="water-label" x={x} y={y - 6 * u} fontSize={(w.big ? 18 : 12) * u}>
              {w.name}
            </text>
          );
        })}
        <MapLayers {...props} P={P} u={u} showLabels={showLabels} />
      </svg>
      <div className="neatline" aria-hidden="true" />
      <div className="zoom">
        <button type="button" aria-label="Zoom in" onClick={() => zoomAt(1 / 1.4)}>
          +
        </button>
        <button type="button" aria-label="Zoom out" onClick={() => zoomAt(1.4)}>
          −
        </button>
        <button type="button" aria-label="Show the whole area" onClick={() => setView(full)} style={{ fontSize: 13 }}>
          ⤢
        </button>
      </div>
    </>
  );
}
