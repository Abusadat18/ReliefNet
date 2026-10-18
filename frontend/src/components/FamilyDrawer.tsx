import { ArrowRightIcon, Maximize2Icon, RouteIcon } from "lucide-react";
import { useMemo, useState, type FormEvent } from "react";
import { needLabel } from "../hooks";
import type { Trace, TraceEdge, TraceNode } from "../types";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Spinner } from "@/components/ui/spinner";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";
import { Eyebrow, SerifTitle, urgency } from "./kit";

export type SheetTab = "why" | "timeline" | "graph";

export interface DrawerState {
  trace: Trace | null;
  answer: { text: string; by: string; question: string } | null;
  loading: boolean;
  tab: SheetTab;
  /** How long the read of the household took, from the browser. */
  ms?: number;
}

const COLS: { label: string; title: string }[] = [
  { label: "Message", title: "Messages" },
  { label: "Request", title: "Requests" },
  { label: "Agent", title: "Agents" },
  { label: "Team", title: "Team · delivery" },
  { label: "Lesson", title: "Lessons" },
];

function colOf(n: TraceNode) {
  if (n.label === "Family") return 1;
  if (n.label === "Delivery") return 3;
  return Math.max(0, COLS.findIndex((c) => c.label === n.label));
}

/** An edge label with the one number that explains it: the merge score, the ETA or the Triage priority. */
function edgeLabel(e: TraceEdge) {
  const value = e.props?.split(":")[1];
  if (e.type === "DUPLICATE_OF" && value) return `DUPLICATE_OF ${value}`;
  if (e.type === "ASSIGNED_TO" && value) return `ASSIGNED_TO ${value} min`;
  const priority = e.type === "PROCESSED_BY" ? /^priority (\d+)/.exec(e.reason ?? "")?.[1] : undefined;
  return priority ? `PROCESSED_BY · ${priority}` : e.type;
}

/** The household's memory as columns: what was said, what it became, who handled it, who went, what was learned. */
export function PathGraph({ trace, labels = false }: { trace: Trace; labels?: boolean }) {
  const layout = useMemo(() => {
    const W = 472;
    const colW = W / COLS.length;
    const rowH = labels ? 40 : 30;
    const buckets: TraceNode[][] = COLS.map(() => []);
    const fam = trace.graph.nodes.find((n) => n.label === "Family");
    for (const n of trace.graph.nodes) if (n !== fam) buckets[colOf(n)].push(n);
    const rows = Math.max(...buckets.map((b) => b.length), 1) + (fam ? 1 : 0);
    const pos = new Map<string, { x: number; y: number }>();
    buckets.forEach((b, ci) => b.forEach((n, ri) => pos.set(n.id, { x: ci * colW + colW / 2, y: 40 + ri * rowH })));
    const H = 40 + rows * rowH + 14;
    if (fam) pos.set(fam.id, { x: W / 2, y: H - 22 });
    return { W, H, colW, pos };
  }, [trace, labels]);

  const { W, H, colW, pos } = layout;
  const boxW = colW - 10;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full rounded-xl bg-muted" role="img" aria-label="Graph of this household's memory">
      {COLS.map((c, i) => (
        <text key={c.label} x={i * colW + colW / 2} y={20} textAnchor="middle" className="fill-muted-foreground font-mono text-[8px] uppercase">
          {c.title}
        </text>
      ))}
      {trace.graph.edges.map((e, i) => {
        const a = pos.get(e.from);
        const b = pos.get(e.to);
        if (!a || !b) return null;
        const mx = (a.x + b.x) / 2;
        return (
          <path
            key={i}
            d={`M${a.x},${a.y} C${mx},${a.y} ${mx},${b.y} ${b.x},${b.y}`}
            fill="none"
            stroke="var(--primary)"
            strokeOpacity={0.45}
            strokeWidth={1.2}
          />
        );
      })}
      {trace.graph.nodes.map((n) => {
        const p = pos.get(n.id);
        if (!p) return null;
        const isFam = n.label === "Family";
        const w = isFam ? 150 : boxW;
        const text = n.label === "Lesson" ? n.title.slice(0, 14) + "…" : n.title;
        return (
          <g key={n.id}>
            <title>{n.label === "Message" ? n.text : n.title}</title>
            <rect
              x={p.x - w / 2}
              y={p.y - 11}
              width={w}
              height={22}
              rx={n.label === "Agent" ? 11 : 5}
              fill={isFam ? "var(--foreground)" : n.label === "Request" ? "var(--info-soft)" : "var(--background)"}
              stroke={isFam ? "none" : "var(--border)"}
            />
            <text
              x={p.x}
              y={p.y + 3.5}
              textAnchor="middle"
              className={cn("font-mono text-[9px] font-semibold", isFam ? "fill-background" : n.label === "Request" ? "fill-info" : "fill-foreground")}
            >
              {isFam ? `${n.id} · ${text}` : text}
            </text>
          </g>
        );
      })}
      {/* Labels after the nodes, so a node box never hides one. */}
      {labels &&
        trace.graph.edges.map((e, i) => {
          const a = pos.get(e.from);
          const b = pos.get(e.to);
          if (!a || !b) return null;
          // Between the columns, pulled toward the target row, so labels of edges that leave one node spread out.
          // An edge within one row has no room between the boxes, so its label sits in the gap below the row.
          const x = (a.x + b.x) / 2;
          const y = Math.abs(a.y - b.y) < 1 ? a.y + 17 : a.y + (b.y - a.y) * 0.8;
          const text = edgeLabel(e);
          const w = text.length * 4.6 + 8;
          return (
            <g key={`l${i}`}>
              <rect x={x - w / 2} y={y - 6} width={w} height={12} rx={3} fill="var(--background)" />
              <text x={x} y={y + 3} textAnchor="middle" className="fill-primary font-mono text-[7.5px] font-semibold">
                {text}
              </text>
            </g>
          );
        })}
    </svg>
  );
}

// FOR and MADE are structure, not decisions, so the chips leave them out.
const QUIET_EDGES = new Set(["FOR", "MADE"]);

/** The path graph as a button that opens it large, with edge labels, for a clear view. */
function ExpandableGraph({ trace, labels = false }: { trace: Trace; labels?: boolean }) {
  const [open, setOpen] = useState(false);
  const f = trace.family;
  return (
    <>
      <button
        type="button"
        className="group relative block w-full cursor-zoom-in rounded-xl focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none"
        onClick={() => setOpen(true)}
        aria-label="Enlarge the graph"
      >
        <PathGraph trace={trace} labels={labels} />
        <span className="num absolute top-2 right-2 inline-flex items-center gap-1 rounded-full bg-background/90 px-2 py-0.5 text-[10px] text-muted-foreground opacity-70 shadow-sm transition-opacity group-hover:opacity-100">
          <Maximize2Icon className="size-3" aria-hidden="true" />
          Enlarge
        </span>
      </button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-h-[calc(100dvh-2rem)] gap-4 overflow-y-auto p-6 sm:max-w-[min(1100px,calc(100vw-4rem))]">
          <DialogHeader className="pr-8">
            <DialogTitle className="text-[22px] font-normal tracking-tight">
              {f.name || f.id} <span className="accent-serif">in the graph</span>
            </DialogTitle>
            <DialogDescription>
              {f.id} · {trace.graph.nodes.length} nodes · {trace.graph.edges.length} edges, read from FalkorDB.
            </DialogDescription>
          </DialogHeader>
          <PathGraph trace={trace} labels />
        </DialogContent>
      </Dialog>
    </>
  );
}

function QueryTab({ trace, ms }: { trace: Trace; ms?: number }) {
  const id = trace.family.id;
  const counts = useMemo(() => {
    const m = new Map<string, number>();
    for (const e of trace.graph.edges) if (!QUIET_EDGES.has(e.type)) m.set(e.type, (m.get(e.type) ?? 0) + 1);
    return [...m.entries()].sort((a, b) => b[1] - a[1]);
  }, [trace]);
  const messages = trace.graph.nodes.filter((n) => n.label === "Message").length;
  const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;
  const lines: [string, string][] = [
    [`MATCH (r:Request)-[:FOR]->(:Family {id:'${id}'})`, "text-white"],
    ["OPTIONAL MATCH (m:Message)-[:BECAME]->(r)", "text-white"],
    ["RETURN r.id, r.status, r.priority, m.id, m.text", "text-rain"],
    [" ", ""],
    ["MATCH (r:Request)-[p:PROCESSED_BY]->(a:Agent)", "text-white"],
    ["WHERE r.id IN $ids", "text-white"],
    ["RETURN r.id, a.name, p.at, p.action, p.reason", "text-rain"],
    ["// + DUPLICATE_OF · ASSIGNED_TO · HANDED_OFF", "text-[#7f8c92]"],
    ["//   REROUTED · USED_LESSON · MADE → SERVED", "text-[#7f8c92]"],
  ];
  return (
    <div className="flex flex-col gap-5">
      <section className="flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <Eyebrow className="text-foreground">Query that built the answer</Eyebrow>
          <span className="num text-[10px] text-muted-foreground">memory.household_history() · read-only</span>
        </div>
        <pre className="num overflow-x-auto rounded-xl bg-slate px-4 py-3 text-[10.5px] leading-relaxed">
          {lines.map(([l, c], i) => (
            <div key={i} className={c}>
              {l}
            </div>
          ))}
        </pre>
        <div className="flex flex-wrap gap-1.5">
          <span className="num rounded-full bg-muted px-2 py-0.5 text-[10px]">{plural(trace.requests.length, "request")}</span>
          <span className="num rounded-full bg-muted px-2 py-0.5 text-[10px]">{plural(messages, "message")}</span>
          {counts.map(([t, n]) => (
            <span key={t} className="num rounded-full bg-info-soft px-2 py-0.5 text-[10px] text-info">
              {n} {t}
            </span>
          ))}
          {ms != null && <span className="num rounded-full bg-success-soft px-2 py-0.5 text-[10px] text-success">{ms} ms</span>}
        </div>
      </section>
      <section className="flex flex-col gap-2">
        <SerifTitle as="h3" sans="Path with" serif="edge labels" className="text-[15px] font-medium" />
        <ExpandableGraph trace={trace} labels />
      </section>
    </div>
  );
}

interface Props {
  state: DrawerState;
  onTab: (t: SheetTab) => void;
  onAsk: (question: string) => void;
  onClose: () => void;
  onShowRoute: (requestId: string) => void;
}

export function FamilyDrawer({ state, onTab, onAsk, onClose, onShowRoute }: Props) {
  const { trace, answer, loading, tab } = state;
  const [follow, setFollow] = useState("");
  const f = trace?.family;
  const title = answer && !trace ? "No household found" : f ? (f.name as string) || f.id : "Looking it up…";
  const prio = trace?.current?.priority ?? null;
  const u = urgency(prio);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const q = follow.trim();
    if (!q) return;
    setFollow("");
    onAsk(q);
  };

  return (
    <Sheet open onOpenChange={(open) => !open && onClose()}>
      <SheetContent side="right" className="w-full gap-0 p-0 sm:max-w-[520px] sm:rounded-l-2xl">
        <SheetHeader className="gap-1.5 border-b px-6 pt-5 pb-4">
          <Eyebrow>{f ? `Household · ${f.id}` : "Household"}</Eyebrow>
          <div className="flex flex-wrap items-center gap-2 pr-8">
            <SheetTitle className="text-2xl font-medium tracking-tight">{title}</SheetTitle>
            {f?.status && (
              <Badge variant="outline" className="num uppercase">
                {String(f.status)}
              </Badge>
            )}
            {prio != null && (
              <span className={cn("num inline-flex h-5 items-center gap-1 rounded-full px-2 text-[10px] font-semibold", u.bg, u.text)}>
                PRIORITY {prio}
              </span>
            )}
          </div>
          {f && (
            <SheetDescription>
              Ward {String(f.ward)} · {String(f.landmark || "")}
            </SheetDescription>
          )}
        </SheetHeader>

        <Tabs value={tab} onValueChange={(v) => onTab(v as SheetTab)} className="flex min-h-0 flex-1 gap-0">
          <TabsList variant="line" className="h-10 w-full justify-start rounded-none border-b px-4">
            <TabsTrigger value="why" className="flex-none px-3">
              Why
            </TabsTrigger>
            <TabsTrigger value="timeline" className="flex-none px-3" disabled={!trace}>
              Timeline
              {trace && <span className="num rounded bg-muted px-1 text-[10px] leading-4 text-muted-foreground">{trace.timeline.length}</span>}
            </TabsTrigger>
            <TabsTrigger value="graph" className="flex-none px-3" disabled={!trace}>
              Graph query
            </TabsTrigger>
          </TabsList>

          <TabsContent value="why" className="min-h-0 overflow-y-auto px-6 py-5">
            <div className="flex flex-col gap-5">
              {loading && (
                <p className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Spinner /> Reading this household's path through the graph…
                </p>
              )}
              {answer && (
                <section className="flex flex-col gap-2.5 rounded-xl bg-info-soft p-5">
                  <Eyebrow className="text-info">You asked</Eyebrow>
                  <p className="font-serif text-[22px] leading-tight italic">{answer.question}</p>
                  <p className="text-sm leading-relaxed whitespace-pre-line">{answer.text}</p>
                  <span className="eyebrow">
                    [ {answer.by === "rules" ? "Read directly from the graph timeline" : `Written by ${answer.by} from the graph timeline`}
                    {trace ? ` · ${trace.graph.edges.length} edges` : ""} ]
                  </span>
                </section>
              )}
              {f && (
                <section className="grid grid-cols-4 rounded-xl border px-4" aria-label="Household facts">
                  {(
                    [
                      [f.people, "people"],
                      [f.elderly ?? 0, "elderly"],
                      [f.children ?? 0, "children"],
                      [f.requests ?? 1, Number(f.requests ?? 1) === 1 ? "message" : "messages, merged"],
                    ] as [unknown, string][]
                  ).map(([v, l]) => (
                    <div key={l} className="flex flex-col gap-0.5 py-3">
                      <b className="num text-[22px] font-semibold">{String(v)}</b>
                      <span className="text-xs text-muted-foreground">{l}</span>
                    </div>
                  ))}
                </section>
              )}
              {f && (
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="flex flex-wrap items-center gap-1.5">
                    <span className="eyebrow">NEEDS</span>
                    {((f.needs as string[]) ?? []).map((n) => (
                      <Badge key={n} variant="secondary">
                        {needLabel(n)}
                      </Badge>
                    ))}
                    {!((f.needs as string[]) ?? []).length && <span className="text-sm text-muted-foreground">none</span>}
                  </span>
                  {trace?.current?.status === "ASSIGNED" && (
                    <Button variant="outline" size="sm" onClick={() => onShowRoute(trace.current!.id)}>
                      <RouteIcon data-icon="inline-start" />
                      Show {trace.current.team}'s route
                    </Button>
                  )}
                </div>
              )}
              {trace && (
                <section className="flex flex-col gap-2">
                  <div className="flex items-center justify-between">
                    <SerifTitle as="h3" sans="Path through" serif="shared memory" className="text-[15px] font-medium" />
                    <span className="num text-[10px] text-muted-foreground">FALKORDB</span>
                  </div>
                  <ExpandableGraph trace={trace} />
                </section>
              )}
            </div>
          </TabsContent>

          <TabsContent value="timeline" className="min-h-0 overflow-y-auto px-6 py-5">
            {trace && (
              <ol className="flex flex-col">
                {trace.timeline.map((s, i) => (
                  <li key={i} className="flex gap-3 border-b py-2.5 last:border-b-0">
                    <time className="num w-12 shrink-0 text-[11px] text-muted-foreground">{s.time}</time>
                    <span className="num w-24 shrink-0 text-[10px] font-semibold uppercase">{s.who}</span>
                    <span className="text-[13px] leading-snug">{s.what}</span>
                  </li>
                ))}
              </ol>
            )}
          </TabsContent>

          <TabsContent value="graph" className="min-h-0 overflow-y-auto px-6 py-5">
            {trace && <QueryTab trace={trace} ms={state.ms} />}
          </TabsContent>
        </Tabs>

        <form className="flex items-center gap-2 border-t px-6 py-3.5" onSubmit={submit}>
          <label htmlFor="follow" className="sr-only">
            Ask a follow-up question
          </label>
          <input
            id="follow"
            value={follow}
            onChange={(e) => setFollow(e.target.value)}
            placeholder={tab === "graph" ? "Ask in plain words, or edit the query" : "Ask a follow-up: “Which team is closest if this one is delayed?”"}
            autoComplete="off"
            className="h-9 min-w-0 flex-1 rounded-full border bg-background px-4 text-[13px] outline-none placeholder:text-muted-foreground focus-visible:ring-3 focus-visible:ring-ring/50"
          />
          <Button type="submit" disabled={!follow.trim()}>
            <ArrowRightIcon data-icon="inline-start" />
            Ask
          </Button>
        </form>
      </SheetContent>
    </Sheet>
  );
}
