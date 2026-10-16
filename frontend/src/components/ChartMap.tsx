import { useCallback, useEffect, useMemo, useRef, useState, type PointerEvent, type WheelEvent } from "react";
import type { FamilyPoint, Region, Road, Snapshot } from "../types";

const M_PER_DEG_LAT = 111_000;
const M_PER_DEG_LON = 100_300;

interface View {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface Flash {
  id: string;
  lat: number;
  lon: number;
}

interface Props {
  region: Region;
  snapshot: Snapshot | null;
  selected: string | null;
  focusRequest: string | null;
  flashes: Flash[];
  onSelectFamily: (id: string) => void;
  onRoadClick: (road: Road, at: { x: number; y: number }) => void;
}

export function ChartMap({ region, snapshot, selected, focusRequest, flashes, onSelectFamily, onRoadClick }: Props) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [size, setSize] = useState({ w: 1000, h: 700 });

  const origin = useMemo(() => {
    const pts = region.wards.flatMap((w) => w.polygon);
    const lats = pts.map((p) => p[0]);
    const lons = pts.map((p) => p[1]);
    return { lat: Math.max(...lats), lon: Math.min(...lons), maxLat: Math.min(...lats), maxLon: Math.max(...lons) };
  }, [region]);

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

  const path = (pts: [number, number][], close = false) =>
    pts.map(([la, lo], i) => `${i ? "L" : "M"}${P(la, lo).join(",")}`).join("") + (close ? "Z" : "");

  const riverPath = useMemo(() => path(region.river, true), [region, P]);
  const riverMid = useMemo(() => {
    const half = region.river.length / 2;
    const top = region.river.slice(0, half);
    const bottom = region.river.slice(half).reverse();
    return top.map((t, i): [number, number] => [(t[0] + bottom[i][0]) / 2, t[1]]);
  }, [region]);

  const showLabels = u < 3.2;
  const fams = snapshot?.families ?? [];
  const routes = snapshot?.routes ?? [];
  const focusRoute = routes.find((r) => r.id === focusRequest);

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
        aria-label="Chart of Ganga Nagar with wards, the river, roads, households and team routes"
      >
        {region.wards.map((w) => (
          <path key={w.num} className="land" d={path(w.polygon, true)} />
        ))}
        <path className="river" d={riverPath} />
        {[0.55, 0.25].map((k) => (
          <path
            key={k}
            className="contour"
            d={path(
              region.river.map(([la, lo], i): [number, number] => {
                const mid = riverMid[i < riverMid.length ? i : region.river.length - 1 - i] ?? [la, lo];
                return [mid[0] + (la - mid[0]) * k, lo];
              }),
              true,
            )}
          />
        ))}
        {region.wards.map((w) => (
          <path key={`l${w.num}`} className="ward-line" d={path(w.polygon, true)} fill="none" />
        ))}
        {region.wards.map((w) => {
          const [x, y] = P(w.polygon[0][0], w.polygon[0][1]);
          return (
            <text key={`t${w.num}`} className="ward-label" x={x + 10 * u} y={y + 18 * u} fontSize={13 * u}>
              {w.num}
            </text>
          );
        })}
        {(() => {
          const mid = riverMid[Math.floor(riverMid.length * 0.3)];
          if (!mid) return null;
          const [x, y] = P(mid[0], mid[1]);
          return (
            <text className="water-label" x={x} y={y + 7 * u} fontSize={20 * u}>
              Ganga
            </text>
          );
        })()}

        {region.roads.map((r) => {
          const [a, b] = r.coords.map(([la, lo]) => P(la, lo));
          const cls = `road ${r.kind === "bridge" ? "bridge" : ""} ${r.status !== "open" ? r.status : ""}`;
          return (
            <g key={r.id}>
              <line
                className="road-hit"
                data-click
                x1={a[0]}
                y1={a[1]}
                x2={b[0]}
                y2={b[1]}
                tabIndex={r.kind === "bridge" ? 0 : -1}
                aria-label={`${r.name}, ${r.status}`}
                onClick={(e) => onRoadClick(r, { x: e.clientX, y: e.clientY })}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    const box = (e.target as Element).getBoundingClientRect();
                    onRoadClick(r, { x: box.x + box.width / 2, y: box.y + box.height / 2 });
                  }
                }}
              />
              <line className={cls} x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} />
              {r.status === "flooded" && (
                <g className="flood-mark" transform={`translate(${(a[0] + b[0]) / 2} ${(a[1] + b[1]) / 2})`}>
                  <line x1={-7 * u} y1={-7 * u} x2={7 * u} y2={7 * u} />
                  <line x1={-7 * u} y1={7 * u} x2={7 * u} y2={-7 * u} />
                </g>
              )}
            </g>
          );
        })}

        {region.roads
          .filter((r) => r.kind === "bridge")
          .filter((r, i, all) => all.findIndex((x) => x.name === r.name) === i)
          .map((r) => {
            const [a, b] = r.coords.map(([la, lo]) => P(la, lo));
            return (
              <text
                key={`bl${r.id}`}
                x={(a[0] + b[0]) / 2 + 9 * u}
                y={(a[1] + b[1]) / 2}
                fontSize={11.5 * u}
                fontWeight={700}
                fill={r.status === "flooded" ? "var(--hazard)" : "var(--ink)"}
                style={{ fontVariationSettings: '"wdth" 85' }}
              >
                {r.name}
              </text>
            );
          })}

        {routes.map((rt) => (
          <path key={rt.id} className={`route${rt.id === focusRequest ? " focus" : ""}`} d={path(rt.route)} />
        ))}
        {focusRoute && <path className="route focus" d={path(focusRoute.route)} />}

        {region.shelters.map((s) => {
          const [x, y] = P(s.lat, s.lon);
          const k = 9 * u;
          return (
            <g key={s.id} className="shelter">
              <path d={`M${x - k},${y + k * 0.8}L${x},${y - k}L${x + k},${y + k * 0.8}Z`} />
              {showLabels && (
                <text x={x + k + 3 * u} y={y + 4 * u} fontSize={10.5 * u} fill="var(--served)">
                  {s.name}
                </text>
              )}
            </g>
          );
        })}

        {showLabels &&
          region.landmarks.map((l) => {
            const [x, y] = P(l.lat, l.lon);
            return (
              <g key={l.id} className="landmark">
                <circle cx={x} cy={y} r={2.5 * u} />
                <text x={x + 5 * u} y={y - 4 * u} fontSize={10.5 * u}>
                  {l.name}
                </text>
              </g>
            );
          })}

        {(snapshot?.pending ?? []).map((p) => {
          const [x, y] = P(p.lat, p.lon);
          return <circle key={p.id} className="pending" cx={x} cy={y} r={3 * u} />;
        })}

        {fams.map((f: FamilyPoint) => {
          const [x, y] = P(f.lat, f.lon);
          const r = (4 + Math.sqrt(f.people || 1) * 2.2) * u;
          const critical = f.status !== "SERVED" && (f.priority ?? 0) >= 70;
          return (
            <g
              key={f.id}
              data-click
              className={`household ${f.status}${selected === f.id ? " selected" : ""}`}
              onClick={() => onSelectFamily(f.id)}
              role="button"
              tabIndex={0}
              aria-label={`${f.name || f.id}, ${f.people} people, ${f.status.toLowerCase()}`}
              onKeyDown={(e) => e.key === "Enter" && onSelectFamily(f.id)}
            >
              {critical && <circle className="critical" cx={x} cy={y} r={r + 4 * u} />}
              <circle className="dot" cx={x} cy={y} r={r} />
            </g>
          );
        })}

        {(snapshot?.teams ?? []).map((t) => {
          const [x, y] = P(t.lat, t.lon);
          const k = 9 * u;
          return (
            <g key={t.name} className="team">
              <rect x={x - k} y={y - k} width={k * 2} height={k * 2} rx={2 * u} />
              <text x={x} y={y + 3.5 * u} textAnchor="middle" fontSize={10 * u}>
                {t.name.replace("Team ", "").slice(0, 2)}
              </text>
            </g>
          );
        })}

        {flashes.map((f) => {
          const [x, y] = P(f.lat, f.lon);
          return <circle key={f.id} className="pulse" cx={x} cy={y} r={6 * u} />;
        })}
      </svg>
      <div className="neatline" aria-hidden="true" />
      <div className="zoom">
        <button type="button" aria-label="Zoom in" onClick={() => zoomAt(1 / 1.4)}>
          +
        </button>
        <button type="button" aria-label="Zoom out" onClick={() => zoomAt(1.4)}>
          −
        </button>
        <button type="button" aria-label="Show whole town" onClick={() => setView(full)} style={{ fontSize: 13 }}>
          ⤢
        </button>
      </div>
    </>
  );
}
