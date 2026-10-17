import type { FamilyPoint, Region, Road, Snapshot } from "../types";

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
  onSelectFamily: (id: string) => void;
  onRoadClick: (road: Road, at: { x: number; y: number }) => void;
}

interface Props extends LayerProps {
  P: Project;
  /** SVG units per screen pixel. */
  u: number;
  showLabels: boolean;
  /**
   * "chart": we draw every road. "basemap": the map below already shows the streets,
   * so we draw only the roads that carry news (bridges, low ground, reports, floods).
   */
  roads: "chart" | "basemap";
}

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

/** The operational layers. The offline chart and the Google map both draw these. */
export function MapLayers(props: Props) {
  const { region, snapshot, selected, focusRequest, flashes, onSelectFamily, onRoadClick, P, u, showLabels } = props;
  const basemap = props.roads === "basemap";
  const fams = snapshot?.families ?? [];
  const routes = snapshot?.routes ?? [];
  const focusRoute = routes.find((r) => r.id === focusRequest);
  const structure = (r: Road) => r.kind !== "road";
  const news = (r: Road) => structure(r) || r.status !== "open" || r.low_lying;

  return (
    <>
      {region.wards.map((w) => (
        <path key={`l${w.num}`} className="ward-line" d={line(P, w.polygon, true)} fill="none" />
      ))}
      {region.wards.map((w) => {
        const [x, y] = P(w.polygon[0][0], w.polygon[0][1]);
        return (
          <text key={`t${w.num}`} className="ward-label" x={x + 10 * u} y={y + 18 * u} fontSize={13 * u}>
            {w.num}
          </text>
        );
      })}

      {region.roads.map((r) => {
        const d = line(P, r.coords);
        const cls = `road ${structure(r) ? "bridge" : ""} ${r.low_lying ? "low" : ""} ${r.status !== "open" ? r.status : ""}`;
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
            {(!basemap || news(r)) && <path className={cls} d={d} />}
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
        <path key={rt.id} className={`route${rt.id === focusRequest ? " focus" : ""}`} d={line(P, rt.route)} />
      ))}
      {focusRoute && <path className="route focus" d={line(P, focusRoute.route)} />}

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
    </>
  );
}

export { line as pathOf };
