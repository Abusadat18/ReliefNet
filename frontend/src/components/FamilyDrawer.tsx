import { useEffect, useMemo } from "react";
import { needLabel } from "../hooks";
import type { Trace, TraceNode } from "../types";

const COLS: { label: string; title: string }[] = [
  { label: "Message", title: "Messages" },
  { label: "Request", title: "Requests" },
  { label: "Agent", title: "Agents" },
  { label: "Team", title: "Teams and deliveries" },
  { label: "Lesson", title: "Lessons" },
];

function colOf(n: TraceNode) {
  if (n.label === "Family") return 1;
  if (n.label === "Delivery") return 3;
  return Math.max(0, COLS.findIndex((c) => c.label === n.label));
}

/** The household's memory as columns: what was said, what it became, who handled it, who went, what was learned. */
function PathGraph({ trace }: { trace: Trace }) {
  const layout = useMemo(() => {
    const W = 560;
    const colW = W / COLS.length;
    const rowH = 30;
    const buckets: TraceNode[][] = COLS.map(() => []);
    const fam = trace.graph.nodes.find((n) => n.label === "Family");
    for (const n of trace.graph.nodes) if (n !== fam) buckets[colOf(n)].push(n);
    const rows = Math.max(...buckets.map((b) => b.length), 1) + (fam ? 1 : 0);
    const pos = new Map<string, { x: number; y: number }>();
    buckets.forEach((b, ci) =>
      b.forEach((n, ri) => pos.set(n.id, { x: ci * colW + colW / 2, y: 40 + ri * rowH })),
    );
    const H = 40 + rows * rowH + 10;
    if (fam) pos.set(fam.id, { x: colW * 1.5, y: H - 26 });
    return { W, H, colW, pos, fam };
  }, [trace]);

  const { W, H, colW, pos } = layout;
  const boxW = colW - 12;
  return (
    <svg className="pathgraph" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Graph of this household's memory">
      {COLS.map((c, i) => (
        <text key={c.label} className="col-label" x={i * colW + colW / 2} y={18} textAnchor="middle">
          {c.title}
        </text>
      ))}
      {trace.graph.edges.map((e, i) => {
        const a = pos.get(e.from);
        const b = pos.get(e.to);
        if (!a || !b) return null;
        const mx = (a.x + b.x) / 2;
        return <path key={i} className={`e-${e.type}`} d={`M${a.x},${a.y} C${mx},${a.y} ${mx},${b.y} ${b.x},${b.y}`} />;
      })}
      {trace.graph.nodes.map((n) => {
        const p = pos.get(n.id);
        if (!p) return null;
        const w = n.label === "Family" ? colW * 1.6 : boxW;
        const text = n.label === "Lesson" ? n.title.slice(0, 18) + "…" : n.title;
        return (
          <g key={n.id} className={`n-${n.label}`}>
            <title>{n.label === "Message" ? n.text : n.title}</title>
            <rect x={p.x - w / 2} y={p.y - 11} width={w} height={22} rx={4} />
            <text x={p.x} y={p.y + 4} textAnchor="middle">
              {n.label === "Family" ? `Household ${text}` : text}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

interface Props {
  trace: Trace | null;
  answer: { text: string; by: string; question: string } | null;
  loading: boolean;
  onClose: () => void;
  onShowRoute: (requestId: string) => void;
}

export function FamilyDrawer({ trace, answer, loading, onClose, onShowRoute }: Props) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const f = trace?.family;
  const title = answer && !trace ? "No household found" : f ? (f.name as string) || f.id : "Looking it up…";
  return (
    <>
      <div className="scrim" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-modal="true" aria-label={title}>
        <div className="drawer-head">
          <div>
            <h2>{title}</h2>
            {f && (
              <div className="sub">
                {f.id}, ward {String(f.ward)} {String(f.landmark || "")}{" "}
                <span className={`chip s-${f.status}`}>{String(f.status).toLowerCase()}</span>
              </div>
            )}
          </div>
          <button type="button" className="btn quiet" onClick={onClose} aria-label="Close">
            Close
          </button>
        </div>
        <div className="drawer-body">
          {loading && <p>Reading this household's path through the graph…</p>}
          {answer && (
            <section>
              <h3>{answer.question}</h3>
              <div className="answer">
                {answer.text}
                <span className="by">
                  {answer.by === "claude" ? "Written by Claude from the graph timeline" : "Read directly from the graph timeline"}
                </span>
              </div>
            </section>
          )}
          {f && (
            <section className="facts" aria-label="Household facts">
              <div>
                <b className="num">{String(f.people)}</b>
                <span>people</span>
              </div>
              <div>
                <b className="num">{String(f.elderly ?? 0)}</b>
                <span>elderly</span>
              </div>
              <div>
                <b className="num">{String(f.children ?? 0)}</b>
                <span>children</span>
              </div>
              <div>
                <b className="num">{String(f.requests ?? 1)}</b>
                <span>{Number(f.requests ?? 1) === 1 ? "message about them" : "messages, merged into one household"}</span>
              </div>
              <div style={{ gridColumn: "1 / -1" }}>
                <b>{((f.needs as string[]) ?? []).map(needLabel).join(", ") || "none"}</b>
                <span>needs</span>
              </div>
            </section>
          )}
          {trace?.current?.status === "ASSIGNED" && (
            <div>
              <button type="button" className="btn" onClick={() => onShowRoute(trace.current!.id)}>
                Show {trace.current.team}'s route on the chart
              </button>
            </div>
          )}
          {trace && (
            <section>
              <h3>Path through shared memory</h3>
              <PathGraph trace={trace} />
            </section>
          )}
          {trace && (
            <section>
              <h3>Timeline</h3>
              <ol className="timeline">
                {trace.timeline.map((s, i) => (
                  <li key={i} className={`k-${s.kind}`}>
                    <time className="num">{s.time}</time>
                    <span className="pin" aria-hidden="true" />
                    <span>
                      <b>{s.who}</b> {s.what}
                    </span>
                  </li>
                ))}
              </ol>
            </section>
          )}
        </div>
      </aside>
    </>
  );
}
