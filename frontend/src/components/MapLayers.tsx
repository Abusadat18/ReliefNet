import type { FamilyPoint, Region, Road, Snapshot, Trace } from "../types";
import { clusterFamilies, clusterRing } from "./clusters";
import type { Visible } from "./LayersMenu";
import { chipOffsets, memoryView, type MemoryChip, type MemoryView } from "./memory";

export interface Flash {
  id: string;
  lat: number;
  lon: number;
}

/** Projects a position to SVG units. */
export type Project = (lat: number, lon: number) => [number, number];

export interface LayerProps {
  region: Region;
  snapshot: Snapshot | null;
  selected: string | null;
  focusRequest: string | null;
  flashes: Flash[];
  /** Layers this viewer has turned on (the Layers menu). */
  show: Visible;
  /** The household the Memory layer shows. */
  memory?: Trace | null;
  onSelectFamily: (id: string) => void;
  onRoadClick: (road: Road, at: { x: number; y: number }) => void;
}

interface Props extends LayerProps {
  P: Project;
  /** SVG units (metres) per screen pixel. */
  u: number;
  showLabels: boolean;
  onZoomTo: (lat: number, lon: number) => void;
}

const M_PER_DEG_LAT = 111_000;

/**
 * Flooded roads always get a label; bridges only when zoomed in. A label that would
 * overlap one already placed is left out, flooded roads first.
 */
function roadLabels(roads: Road[], P: Project, u: number, zoomedIn: boolean) {
  const wanted = roads
    .filter((r) => r.status === "flooded" || (zoomedIn && r.kind !== "road"))
    .filter((r, i, all) => all.findIndex((x) => x.name === r.name) === i)
    .sort((a, b) => Number(b.status === "flooded") - Number(a.status === "flooded"));
  const placed: { r: Road; x: number; y: number }[] = [];
  for (const r of wanted) {
    const [x, y] = middle(P, r.coords);
    const clear = placed.every((p) => Math.abs(p.x - x) / u > 150 || Math.abs(p.y - y) / u > 18);
    if (clear) placed.push({ r, x, y });
  }
  return placed;
}

const line = (P: Project, pts: [number, number][], close = false) =>
  pts.map(([la, lo], i) => `${i ? "L" : "M"}${P(la, lo).join(",")}`).join("") + (close ? "Z" : "");

function middle(P: Project, coords: [number, number][]): [number, number] {
  return P(...coords[Math.floor((coords.length - 1) / 2)]);
}

const CHIP: Record<MemoryChip["kind"], { fill: string; ink: string }> = {
  message: { fill: "var(--popover)", ink: "var(--ink)" },
  agent: { fill: "var(--popover)", ink: "var(--ink)" },
  request: { fill: "var(--info-soft)", ink: "var(--info)" },
  lesson: { fill: "var(--served-soft)", ink: "var(--served)" },
};

/** The Memory layer of the chart: a veil, then the household with its graph neighbours in a ring. */
function MemoryRing({ m, P, u }: { m: MemoryView; P: Project; u: number }) {
  const [hx, hy] = P(m.family.lat, m.family.lon);
  const offsets = chipOffsets(m.chips.length);
  const tag = (x: number, y: number, text: string, size: number, fill: string, ink: string, padX: number, h: number, key: string) => {
    const w = (text.length * size * 0.62 + padX * 2) * u;
    return (
      <g key={key}>
        <rect x={x - w / 2} y={y - (h * u) / 2} width={w} height={h * u} rx={h > 20 ? 6 * u : 4 * u} fill={fill} stroke="var(--border)" strokeWidth={h > 20 ? 1 : 0} vectorEffect="non-scaling-stroke" />
        <text x={x} y={y + size * 0.36 * u} textAnchor="middle" fontSize={size * u} fill={ink} className="num" fontWeight={h > 20 ? 600 : 700}>
          {text}
        </text>
      </g>
    );
  };
  const team = m.team && P(m.team.lat, m.team.lon);
  return (
    <g className="memory" pointerEvents="none" aria-label={`Memory of ${m.family.name || m.family.id}`}>
      <rect x={-1e7} y={-1e7} width={2e7} height={2e7} fill="var(--paper)" opacity={0.7} />
      {team && (
        <>
          <line x1={hx} y1={hy} x2={team[0]} y2={team[1]} stroke="var(--route)" strokeWidth={2} strokeDasharray="4 3" vectorEffect="non-scaling-stroke" />
          <circle cx={team[0]} cy={team[1]} r={6 * u} fill="var(--ink)" stroke="var(--paper)" strokeWidth={2} vectorEffect="non-scaling-stroke" />
          {tag(team[0], team[1] - 22 * u, `${m.team!.name} · ${m.team!.load} jobs`, 11, "var(--ink)", "var(--paper)", 9, 22, "team")}
          {tag((hx + team[0]) / 2, (hy + team[1]) / 2, "ASSIGNED_TO", 9, "var(--paper)", "var(--primary)", 5, 16, "team-edge")}
        </>
      )}
      {m.chips.map((ch, i) => (
        <line
          key={`l${ch.id}`}
          x1={hx}
          y1={hy}
          x2={hx + offsets[i][0] * u}
          y2={hy + offsets[i][1] * u}
          stroke="var(--primary)"
          strokeOpacity={0.7}
          strokeWidth={1.5}
          vectorEffect="non-scaling-stroke"
        />
      ))}
      <circle cx={hx} cy={hy} r={9 * u} fill={m.family.status === "ASSIGNED" ? "var(--route)" : m.family.status === "SERVED" ? "var(--paper)" : "var(--waiting)"} stroke="var(--ink)" strokeWidth={3} vectorEffect="non-scaling-stroke" />
      {m.chips.map((ch, i) => tag(hx + offsets[i][0] * u * 0.5, hy + offsets[i][1] * u * 0.5, ch.edge, 9, "var(--paper)", "var(--primary)", 5, 16, `e${ch.id}`))}
      {m.chips.map((ch, i) => tag(hx + offsets[i][0] * u, hy + offsets[i][1] * u, ch.label, 11, CHIP[ch.kind].fill, CHIP[ch.kind].ink, 9, 26, `n${ch.id}`))}
    </g>
  );
}

const RING = { hazard: "var(--hazard)", waiting: "var(--waiting)", route: "var(--water-ink)" };

/** The operational layers of the built-in chart. deckLayers.ts draws the same on the Google map. */
export function MapLayers(props: Props) {
  const { region, snapshot, selected, focusRequest, flashes, onSelectFamily, onRoadClick, onZoomTo, P, u, showLabels, show } = props;
  const memory = memoryView(props.memory, snapshot);
  const fams = (snapshot?.families ?? []).filter((f) => show.served || f.status !== "SERVED");
  const selectedReq = fams.find((f) => f.id === selected)?.request ?? null;
  const focus = focusRequest ?? selectedReq;
  const all = snapshot?.routes ?? [];
  const routes = show.routes ? all.filter((r) => r.id !== focus) : [];
  // The route a coordinator opened stays visible even with routes hidden.
  const focusRoute = all.find((r) => r.id === focus);
  const structure = (r: Road) => r.kind !== "road";
  // Households closer than 22 px on screen become one count bubble, until the chart is close in.
  const groups = u < 0.6 ? fams.map((f) => ({ lat: f.lat, lon: f.lon, members: [f] })) : clusterFamilies(fams, M_PER_DEG_LAT / u);

  const household = (f: FamilyPoint) => {
    const [x, y] = P(f.lat, f.lon);
    const pill = f.status !== "SERVED" && (f.priority ?? 0) >= 70;
    const text = String(f.priority);
    const w = (text.length * 7 + 14) * u;
    const h = 20 * u;
    return (
      <g
        key={f.id}
        data-click
        className={`household ${f.status}${selected === f.id ? " selected" : ""}`}
        onClick={() => onSelectFamily(f.id)}
        role="button"
        tabIndex={0}
        aria-label={`${f.name || f.id}, ${f.people} people, ${f.status.toLowerCase()}${pill ? `, priority ${f.priority}` : ""}`}
        onKeyDown={(e) => e.key === "Enter" && onSelectFamily(f.id)}
      >
        {pill ? (
          <>
            <rect className="pill" x={x - w / 2} y={y - h / 2} width={w} height={h} rx={h / 2} />
            <text className="pill-text" x={x} y={y + 4 * u} textAnchor="middle" fontSize={11 * u}>
              {text}
            </text>
          </>
        ) : (
          <circle className="dot" cx={x} cy={y} r={(selected === f.id ? 8 : 7) * u} />
        )}
      </g>
    );
  };

  return (
    <>
      {show.wards && region.wards.map((w) => <path key={`l${w.num}`} className="ward-line" d={line(P, w.polygon, true)} fill="none" />)}
      {show.wards &&
        region.wards.map((w) => {
          const [x, y] = P(w.polygon[0][0], w.polygon[0][1]);
          return (
            <text key={`t${w.num}`} className="ward-label" x={x + 10 * u} y={y + 18 * u} fontSize={10 * u}>
              WARD {w.num}
            </text>
          );
        })}

      {region.roads.map((r) => {
        const d = line(P, r.coords);
        const cls = `road ${structure(r) ? "bridge" : ""} ${r.low_lying && show.low ? "low" : ""} ${r.status !== "open" ? r.status : ""}`;
        const [mx, my] = middle(P, r.coords);
        return (
          <g key={r.id}>
            <path
              className="road-hit"
              data-click
              d={d}
              tabIndex={structure(r) ? 0 : -1}
              aria-label={`${r.name}, ${r.status}`}
              onClick={(e) => onRoadClick(r, { x: e.clientX, y: e.clientY })}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  const box = (e.target as Element).getBoundingClientRect();
                  onRoadClick(r, { x: box.x + box.width / 2, y: box.y + box.height / 2 });
                }
              }}
            />
            <path className={cls} d={d} />
            {r.status === "flooded" && (
              <g className="flood-mark" transform={`translate(${mx} ${my})`}>
                <line x1={-7 * u} y1={-7 * u} x2={7 * u} y2={7 * u} />
                <line x1={-7 * u} y1={7 * u} x2={7 * u} y2={-7 * u} />
              </g>
            )}
          </g>
        );
      })}

      {roadLabels(region.roads, P, u, showLabels).map(({ r, x, y }) => (
        <text
          key={`bl${r.id}`}
          className="road-label"
          x={x + 9 * u}
          y={y}
          fontSize={11.5 * u}
          strokeWidth={3 * u}
          fill={r.status === "flooded" ? "var(--hazard)" : "var(--ink)"}
        >
          {r.name}
        </text>
      ))}

      {routes.map((rt) => (
        <path key={rt.id} className="route" d={line(P, rt.route)} />
      ))}
      {focusRoute && (
        <>
          <path className="route-casing" d={line(P, focusRoute.route)} />
          <path className="route focus" d={line(P, focusRoute.route)} />
        </>
      )}

      {show.places &&
        region.shelters.map((s) => {
          const [x, y] = P(s.lat, s.lon);
          const k = 11 * u;
          return (
            <g key={s.id} className="shelter">
              <circle cx={x} cy={y} r={k} />
              <path
                d={`M${x - 5 * u},${y + 4 * u}L${x},${y - 5 * u}L${x + 5 * u},${y + 4 * u}Z`}
                fill="none"
                stroke="var(--served)"
                strokeWidth={1.4}
                vectorEffect="non-scaling-stroke"
              />
              {showLabels && (
                <text x={x + k + 4 * u} y={y + 4 * u} fontSize={10.5 * u}>
                  {s.name}
                </text>
              )}
            </g>
          );
        })}

      {showLabels &&
        show.places &&
        region.landmarks.map((l) => {
          const [x, y] = P(l.lat, l.lon);
          return (
            <g key={l.id} className="landmark">
              <circle cx={x} cy={y} r={2.5 * u} />
              {l.source !== "osm" && (
                <text x={x + 5 * u} y={y - 4 * u} fontSize={10.5 * u}>
                  {l.name}
                </text>
              )}
            </g>
          );
        })}

      {(snapshot?.pending ?? []).map((p) => {
        const [x, y] = P(p.lat, p.lon);
        return <circle key={p.id} className="pending" cx={x} cy={y} r={3 * u} />;
      })}

      {groups.map((g) => {
        if (g.members.length === 1) return household(g.members[0]);
        const [x, y] = P(g.lat, g.lon);
        return (
          <g
            key={g.members.map((m) => m.id).join("|")}
            className="cluster"
            data-click
            role="button"
            tabIndex={0}
            aria-label={`${g.members.length} households here. Zoom in to see each one.`}
            onClick={() => onZoomTo(g.lat, g.lon)}
            onKeyDown={(e) => e.key === "Enter" && onZoomTo(g.lat, g.lon)}
            style={{ cursor: "zoom-in" }}
          >
            <circle cx={x} cy={y} r={15 * u} stroke={RING[clusterRing(g.members)]} />
            <text x={x} y={y + 4.5 * u} textAnchor="middle" fontSize={13 * u}>
              {g.members.length}
            </text>
          </g>
        );
      })}

      {(snapshot?.teams ?? []).map((t) => {
        const [x, y] = P(t.lat, t.lon);
        const label = `${t.name} · ${t.load} job${t.load === 1 ? "" : "s"}`;
        const w = (label.length * 6.2 + 18) * u;
        const h = 22 * u;
        return (
          <g key={t.name} className="team">
            <circle cx={x} cy={y} r={6 * u} fill="var(--ink)" stroke="var(--paper)" strokeWidth={2} vectorEffect="non-scaling-stroke" />
            <rect x={x - w / 2} y={y - 22 * u - h / 2} width={w} height={h} rx={h / 2} />
            <text x={x} y={y - 22 * u + 4 * u} textAnchor="middle" fontSize={11 * u}>
              {label}
            </text>
          </g>
        );
      })}

      {flashes.map((f) => {
        const [x, y] = P(f.lat, f.lon);
        return <circle key={f.id} className="pulse" cx={x} cy={y} r={6 * u} />;
      })}

      {memory && <MemoryRing m={memory} P={P} u={u} />}
    </>
  );
}

export { line as pathOf };
