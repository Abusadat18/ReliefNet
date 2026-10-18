import {
  ArrowUpWideNarrowIcon,
  CopyIcon,
  FileTextIcon,
  GitBranchIcon,
  InboxIcon,
  KeyRoundIcon,
  RefreshCwIcon,
  RotateCcwIcon,
  RouteIcon,
  SquareIcon,
  UsersIcon,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { api } from "../api";
import { ago, clock, needLabel, useNow } from "../hooks";
import type { AgentInfo, Lesson, LiveEvent, QueueItem, Stats, Trace, TraceEdge, TraceNode } from "../types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import { Spinner } from "@/components/ui/spinner";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { cn } from "@/lib/utils";
import { EDGE_FILTERS, graphWrite, queueReceipt, type Tone } from "./graph";
import { Eyebrow, GraphReceipt, ScoreTile, SerifTitle } from "./kit";

export type OpenFamily = (familyId: string, tab?: "why" | "timeline" | "graph") => void;

const STAGES: { status: string; title: string }[] = [
  { status: "TRIAGED", title: "Waiting for a team" },
  { status: "ASSIGNED", title: "Team on the way" },
  { status: "RESOLVED", title: "Being scored" },
  { status: "NEW", title: "Checking for duplicates" },
];

function PanelEmpty({ icon: Icon, title, children }: { icon: LucideIcon; title: string; children: ReactNode }) {
  return (
    <Empty className="m-4 border">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <Icon />
        </EmptyMedia>
        <EmptyTitle>{title}</EmptyTitle>
        <EmptyDescription>{children}</EmptyDescription>
      </EmptyHeader>
    </Empty>
  );
}

function StatusLine({ q, now }: { q: QueueItem; now: number }) {
  const lease = q.claimed_by && q.lease_until && q.lease_until > now;
  const expired = q.claimed_by && q.lease_until && q.lease_until <= now;
  const [dot, text, cls] = lease
    ? ["bg-info", `${q.claimed_by} holds the lease · ${Math.ceil((q.lease_until! - now) / 1000)} s left`, ""]
    : expired
      ? ["bg-warning", `Lease from ${q.claimed_by} expired · another agent can take it`, "text-warning"]
      : q.blocked
        ? ["bg-critical", q.blocked, "text-critical"]
        : q.status === "ASSIGNED"
          ? ["bg-primary", `${q.team ?? "Team"} · ETA ${q.eta} min`, ""]
          : ["bg-warning", `Waiting ${ago(q.created_at, now).replace(" ago", "")}`, ""];
  return (
    <span className={cn("num flex items-start gap-1.5 text-[11px] leading-snug text-muted-foreground", cls)}>
      <span className={cn("mt-[5px] size-1.5 shrink-0 rounded-full", dot)} aria-hidden="true" />
      {text}
    </span>
  );
}

// FOR and MADE only repeat what the other edges say; the receipt keeps the decisions.
const RECEIPT_EDGES = new Set(["BECAME", "PROCESSED_BY", "DUPLICATE_OF", "ASSIGNED_TO", "HANDED_OFF", "USED_LESSON", "SERVED"]);
// Numbers that explain the edge go inside the pattern; the action and status are in the reason already.
const PATTERN_PROPS = new Set(["DUPLICATE_OF", "ASSIGNED_TO"]);

/** One edge as a Cypher pattern: (R-111)-[:DUPLICATE_OF {score:1.0}]->(R-101). */
export function edgePattern(e: TraceEdge, nodes: TraceNode[]) {
  const name = (id: string) => {
    const n = nodes.find((x) => x.id === id);
    return n?.label === "Lesson" ? `Lesson '${id}'` : id;
  };
  const props = PATTERN_PROPS.has(e.type) && e.props ? ` {${e.props}}` : "";
  return `(${name(e.from)})-[:${e.type}${props}]->(${name(e.to)})`;
}

/** The household's edges, read from the graph when a receipt opens. */
function ReceiptDetail({ familyId, graphName, onOpen }: { familyId: string; graphName: string; onOpen: OpenFamily }) {
  const [trace, setTrace] = useState<Trace | null>(null);
  const [readAt, setReadAt] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    let live = true;
    api
      .get<Trace>(`/api/ops/family/${encodeURIComponent(familyId)}`)
      .then((t) => {
        if (!live) return;
        setTrace(t);
        setReadAt(Date.now());
      })
      .catch((e) => live && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      live = false;
    };
  }, [familyId]);
  const edges = (trace?.graph.edges ?? [])
    .filter((e) => RECEIPT_EDGES.has(e.type))
    .sort((a, b) => (a.at ?? 0) - (b.at ?? 0))
    .slice(-8);
  const cypher =
    `MATCH (r:Request)-[:FOR]->(:Family {id:'${familyId}'})\n` +
    "OPTIONAL MATCH (m:Message)-[:BECAME]->(r)\n" +
    "OPTIONAL MATCH (r)-[p:PROCESSED_BY]->(a:Agent)\n" +
    "RETURN r, m, p, a";
  return (
    <div className="mx-3.5 mt-2 overflow-hidden rounded-xl border bg-card">
      {!trace && !error && (
        <p className="flex items-center gap-2 px-3 py-2.5 text-xs text-muted-foreground">
          <Spinner /> Reading this household's edges…
        </p>
      )}
      {error && <p className="px-3 py-2.5 text-xs text-destructive">{error}</p>}
      {trace && (
        <ol className="px-3 py-2">
          {edges.map((e, i) => {
            const last = i === edges.length - 1;
            return (
              <li key={i} className="relative flex gap-2.5 pb-2 last:pb-0">
                {!last && <span className="absolute top-3 bottom-0 left-[2.5px] w-px bg-border" aria-hidden="true" />}
                <span
                  className={cn("relative mt-[5px] size-1.5 shrink-0 rounded-full", last ? "bg-primary" : "bg-foreground/40")}
                  aria-hidden="true"
                />
                <span className="flex min-w-0 flex-col gap-0.5">
                  <span className={cn("num text-[10.5px] font-semibold break-all", last && "text-primary")}>
                    {edgePattern(e, trace.graph.nodes)}
                  </span>
                  {e.reason && <span className="text-[11.5px] leading-snug text-muted-foreground">{e.reason}</span>}
                </span>
              </li>
            );
          })}
        </ol>
      )}
      <div className="flex items-center justify-between gap-2 bg-muted px-3 py-1.5">
        <span className="num min-w-0 truncate text-[10px] text-muted-foreground" title={graphName}>
          {trace ? `${graphName} · read ${clock(readAt)}` : "FalkorDB"}
        </span>
        <span className="flex shrink-0 gap-1">
          <Button
            variant="ghost"
            size="xs"
            onClick={() => {
              void navigator.clipboard?.writeText(cypher).then(() => setCopied(true));
            }}
          >
            <CopyIcon data-icon="inline-start" />
            {copied ? "Copied" : "Copy Cypher"}
          </Button>
          <Button variant="ghost" size="xs" onClick={() => onOpen(familyId, "graph")}>
            <GitBranchIcon data-icon="inline-start" />
            Open in graph
          </Button>
        </span>
      </div>
    </div>
  );
}

export function QueuePanel({ items, graphName, onOpen }: { items: QueueItem[]; graphName: string; onOpen: OpenFamily }) {
  const now = useNow(1000);
  const [openReceipt, setOpenReceipt] = useState<string | null>(null);
  if (!items.length)
    return (
      <PanelEmpty icon={InboxIcon} title="No open requests">
        Start a flood drill, or paste a message from the helpline, to see the agents work.
      </PanelEmpty>
    );
  return (
    <div>
      <p className="flex items-center gap-2 border-b bg-info-soft px-4 py-2 text-xs text-info">
        <GitBranchIcon className="size-3.5 shrink-0" aria-hidden="true" />
        Every line below is read from the graph. Open a receipt to see the edges.
      </p>
      {STAGES.map((st) => {
        const rows = items.filter((i) => i.status === st.status);
        if (!rows.length) return null;
        return (
          <section key={st.status} aria-label={st.title}>
            <div className="sticky top-0 z-10 flex items-center gap-2 border-b bg-background px-4 py-2">
              <Eyebrow className="text-foreground">{st.title}</Eyebrow>
              <span className="num text-[11px] text-muted-foreground">{rows.length}</span>
            </div>
            {rows.map((q) => {
              const r = queueReceipt(q);
              const open = openReceipt === q.id;
              return (
                <div key={q.id} className={cn("border-b pb-3", open && "bg-info-soft")}>
                  <button
                    type="button"
                    className="flex w-full gap-3 px-3.5 pt-3 text-left hover:bg-muted/50"
                    onClick={() => q.family && onOpen(q.family)}
                  >
                    <ScoreTile priority={q.priority} />
                    <span className="flex min-w-0 flex-1 flex-col gap-1">
                      <span className="flex items-baseline gap-2">
                        <span className="truncate text-sm font-semibold">{q.name || q.family || q.id}</span>
                        <span className="num text-[11px] text-muted-foreground">{q.id}</span>
                      </span>
                      <span className="text-[13px] text-muted-foreground">
                        Ward {q.ward} · {q.landmark}
                      </span>
                      {q.needs.length > 0 && (
                        <span className="flex flex-wrap gap-1">
                          {q.needs.map((n) => (
                            <Badge key={n} variant="secondary">
                              {needLabel(n)}
                            </Badge>
                          ))}
                        </span>
                      )}
                      <StatusLine q={q} now={now} />
                    </span>
                  </button>
                  {q.family && (
                    <div className="mt-2 pl-[70px] pr-3.5">
                      <GraphReceipt edge={r.edge} text={r.text} open={open} onClick={() => setOpenReceipt(open ? null : q.id)} />
                    </div>
                  )}
                  {open && q.family && <ReceiptDetail familyId={q.family} graphName={graphName} onOpen={onOpen} />}
                </div>
              );
            })}
          </section>
        );
      })}
    </div>
  );
}

const TONE: Record<Tone, { row: string; who: string }> = {
  memory: { row: "bg-info-soft", who: "text-info" },
  field: { row: "bg-success-soft", who: "text-success" },
  lease: { row: "bg-high-soft", who: "text-warning" },
  hazard: { row: "bg-critical-soft", who: "text-critical" },
  plain: { row: "", who: "text-foreground" },
};

export function FeedPanel({ events, graph, onOpen }: { events: LiveEvent[]; graph?: Stats["graph"]; onOpen: OpenFamily }) {
  const [filter, setFilter] = useState<string>("all");
  const rows = events
    .map((e) => ({ e, w: graphWrite(e) }))
    .filter(({ w }) => filter === "all" || w?.type === filter)
    .slice(0, 250);
  return (
    <div>
      <div className="flex flex-col gap-2 border-b px-4 py-3">
        <SerifTitle as="h3" sans="Writes to" serif="the graph" className="text-base font-medium" />
        <p className="text-xs text-muted-foreground">
          {graph
            ? `${graph.edges} edges this shift · ${graph.reasons} with a reason. Filter by edge type.`
            : "Every agent writes to FalkorDB, then publishes the event. Each row shows the edge it wrote."}
        </p>
        <ToggleGroup
          value={[filter]}
          onValueChange={(v: string[]) => setFilter(v[0] ?? "all")}
          variant="outline"
          size="sm"
          className="flex-wrap"
          aria-label="Filter by edge type"
        >
          <ToggleGroupItem value="all" className="num rounded-full! text-[10px]">
            All
          </ToggleGroupItem>
          {EDGE_FILTERS.map((t) => (
            <ToggleGroupItem key={t} value={t} className="num rounded-full! text-[10px]">
              {t}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
      </div>
      {rows.length ? (
        <ol aria-live="polite">
          {rows.map(({ e, w }, i) => {
            const fam = (e.data?.family as string) || undefined;
            const tone = TONE[w?.tone ?? "plain"];
            return (
              <li key={`${e.at}-${i}`} className={cn("flex gap-3 border-b px-4 py-2.5", tone.row)}>
                <time className="num w-14 shrink-0 pt-px text-[10.5px] text-muted-foreground">{clock(e.at)}</time>
                <span className="flex min-w-0 flex-1 flex-col gap-1">
                  {w && <span className={cn("num text-[10.5px] font-semibold tracking-wide uppercase", tone.who)}>{w.who}</span>}
                  {w && <span className="num text-[10.5px] font-semibold break-all text-foreground">{w.edge}</span>}
                  <span className="text-xs leading-snug text-muted-foreground">{e.text}</span>
                  {fam && (
                    <Button variant="link" size="xs" className="h-auto self-start p-0" onClick={() => onOpen(fam)}>
                      Open {fam}
                    </Button>
                  )}
                </span>
              </li>
            );
          })}
        </ol>
      ) : (
        <PanelEmpty icon={GitBranchIcon} title="Nothing here yet">
          Events appear the moment an agent writes to the graph.
        </PanelEmpty>
      )}
    </div>
  );
}

const STATE: Record<AgentInfo["state"], { dot: string; label: string; text: string }> = {
  working: { dot: "bg-success", label: "WORKING", text: "text-success" },
  idle: { dot: "bg-muted-foreground", label: "WAITING", text: "text-muted-foreground" },
  stale: { dot: "bg-warning", label: "STALE", text: "text-warning" },
  dead: { dot: "bg-destructive", label: "STOPPED", text: "text-destructive" },
};

export function AgentsPanel({
  agents,
  queue,
  events,
  leaseMs,
  onChange,
}: {
  agents: AgentInfo[];
  queue: QueueItem[];
  events: LiveEvent[];
  leaseMs: number;
  onChange: () => void;
}) {
  const now = useNow(1000);
  const [busy, setBusy] = useState<string | null>(null);
  const act = async (name: string, action: "kill" | "revive") => {
    setBusy(name);
    try {
      await api.post(`/api/ops/agents/${encodeURIComponent(name)}/${action}`);
      onChange();
    } finally {
      setBusy(null);
    }
  };
  if (!agents.length)
    return (
      <PanelEmpty icon={UsersIcon} title="No agents are running">
        Start them with <code className="num">python -m reliefnet.workers</code>.
      </PanelEmpty>
    );
  return (
    <div>
      <div className="flex flex-col gap-1.5 border-b px-4 py-3">
        <SerifTitle as="h3" sans="Leases live" serif="on the node" className="text-base font-medium" />
        <p className="text-xs leading-relaxed text-muted-foreground">
          An agent claims a request by writing <span className="num">claimed_by</span> and{" "}
          <span className="num">lease_until</span> on it. If it stops, the lease runs out and another copy takes the item.
        </p>
      </div>
      <div className="flex flex-col gap-2.5 p-3">
        {agents.map((a) => {
          const st = STATE[a.state];
          const held = queue.find((q) => q.claimed_by === a.name && (q.lease_until ?? 0) > now);
          const left = held ? Math.max(0, (held.lease_until! - now) / 1000) : 0;
          const lapsed = !held ? queue.find((q) => q.claimed_by === a.name && q.lease_until && q.lease_until <= now) : undefined;
          const taken = a.state === "dead" ? events.find((e) => e.kind === "reclaimed" && e.data?.previous === a.name) : undefined;
          const canStop = !(a.kind === "learner" || a.kind === "coordinator");
          return (
            <div
              key={a.name}
              className={cn(
                "flex flex-col gap-2 rounded-xl border p-3",
                a.state === "dead" ? "border-destructive bg-critical-soft" : "bg-card",
              )}
            >
              <div className="flex items-center gap-2">
                <span className={cn("size-2 rounded-full", st.dot)} aria-hidden="true" />
                <span className="num text-[13px] font-semibold">{a.name}</span>
                <span className={cn("num text-[10px] font-semibold", st.text)}>{st.label}</span>
                <span className="flex-1" />
                {a.state === "dead" ? (
                  <Button variant="outline" size="sm" disabled={busy === a.name} onClick={() => act(a.name, "revive")}>
                    <RotateCcwIcon data-icon="inline-start" />
                    Restart
                  </Button>
                ) : (
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={busy === a.name || !canStop}
                    onClick={() => act(a.name, "kill")}
                  >
                    <SquareIcon data-icon="inline-start" />
                    Stop
                  </Button>
                )}
              </div>
              {held ? (
                <div className="num flex flex-col gap-0.5 rounded-lg bg-muted px-2.5 py-2 text-[10.5px] text-muted-foreground">
                  <span className="font-semibold text-foreground">(:Request {`{id:'${held.id}'}`})</span>
                  <span>&nbsp; claimed_by: '{a.name}'</span>
                  <span className="text-primary">&nbsp; lease_until: now + {left.toFixed(1)} s</span>
                  <span
                    className="mt-1 h-1 overflow-hidden rounded-full bg-background"
                    role="img"
                    aria-label={`${left.toFixed(1)} s of the lease left`}
                  >
                    <span
                      className="block h-full rounded-full bg-primary transition-[width] duration-1000 ease-linear"
                      style={{ width: `${Math.min(100, ((left * 1000) / leaseMs) * 100)}%` }}
                    />
                  </span>
                </div>
              ) : lapsed || taken ? (
                <div className="num flex flex-col gap-0.5 rounded-lg bg-background/70 px-2.5 py-2 text-[10.5px] text-muted-foreground">
                  <span className="font-semibold text-foreground">
                    (:Request {`{id:'${String(taken?.data?.id ?? lapsed?.id)}'}`}) <span className="text-destructive">lease_until passed</span>
                  </span>
                  {taken ? (
                    <>
                      <span>({String(taken.data.id)})-[:PROCESSED_BY {"{action:'reclaimed'}"}]</span>
                      <span>
                        &nbsp; -&gt;({String(taken.data.agent)}) <span className="font-sans italic">“lease held by {a.name} expired”</span>
                      </span>
                    </>
                  ) : (
                    <span>Another copy can take it now.</span>
                  )}
                </div>
              ) : (
                <p className="text-[13px] text-muted-foreground">
                  {a.state === "dead"
                    ? "Stopped mid-shift. Its leases will expire."
                    : a.state === "stale"
                      ? "No heartbeat. The worker process may be down."
                      : a.state === "working"
                        ? `Working${a.job ? ` on ${a.job}` : ""}`
                        : "Waiting for work"}
                </p>
              )}
              <span className="num text-[10.5px] text-muted-foreground">{a.processed} finished</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

const LESSON_KIND: Record<string, { label: string; icon: LucideIcon }> = {
  road_risk: { label: "Changes routes", icon: RouteIcon },
  team_skill: { label: "Changes team choice", icon: UsersIcon },
  area_risk: { label: "Changes priority", icon: ArrowUpWideNarrowIcon },
  general: { label: "For coordinators", icon: FileTextIcon },
};

type Override = Lesson["override"];

/** Whether Triage and Dispatch act on a lesson: a coordinator's override wins over confidence. */
const inUse = (l: Lesson) => l.override !== "off" && (l.override === "on" || l.confidence >= 0.5);

function EdgeBox({ title, edge, children }: { title: string; edge: string; children: ReactNode }) {
  return (
    <div className="overflow-hidden rounded-lg border bg-background">
      <div className="num flex justify-between bg-muted px-3 py-1.5 text-[10px] font-semibold">
        <span>{title}</span>
        <span className="text-primary">{edge}</span>
      </div>
      {children}
    </div>
  );
}

const SHOWN_EVIDENCE = 3;

/** The lesson node with its DERIVED_FROM evidence and the USED_LESSON decisions that cite it. */
function LessonGraph({ l, onOpen }: { l: Lesson; onOpen: OpenFamily }) {
  const nodes = l.evidence_nodes ?? l.evidence.map((id) => ({ id, label: "", name: "" }));
  const rest = nodes.slice(SHOWN_EVIDENCE);
  const describe = (n: (typeof nodes)[number]) => n.name || (n.label === "Family" ? "Household" : n.label);
  const row = "flex w-full items-baseline gap-2.5 border-t px-3 py-1.5 text-left";
  return (
    <div className="flex flex-col gap-2">
      <span className="num text-[10.5px] font-semibold text-muted-foreground">(:Lesson {`{key:'${l.key}'}`})</span>
      {nodes.length > 0 && (
        <EdgeBox title={`Evidence · ${nodes.length}`} edge="DERIVED_FROM">
          {nodes.slice(0, SHOWN_EVIDENCE).map((n) =>
            n.label === "Family" ? (
              <button key={n.id} type="button" className={cn(row, "hover:bg-muted/50")} onClick={() => onOpen(n.id)}>
                <span className="num w-12 shrink-0 text-[11px] font-semibold">{n.id}</span>
                <span className="text-xs text-muted-foreground">{describe(n)}</span>
              </button>
            ) : (
              <div key={n.id} className={row}>
                <span className="num w-12 shrink-0 text-[11px] font-semibold">{n.id}</span>
                <span className="text-xs text-muted-foreground">{describe(n)}</span>
              </div>
            ),
          )}
          {rest.length > 0 && (
            <div className={row}>
              <span className="num w-12 shrink-0 text-[11px] font-semibold">+ {rest.length}</span>
              <span className="text-xs text-muted-foreground">
                {rest
                  .slice(0, 8)
                  .map((n) => [n.id, n.name].filter(Boolean).join(" "))
                  .join(", ")}
                {rest.length > 8 ? ", …" : ""}
              </span>
            </div>
          )}
        </EdgeBox>
      )}
      {l.used_by && l.used_by.length > 0 && (
        <EdgeBox title={`Used by · ${l.used_by.length}`} edge="USED_LESSON">
          {l.used_by.slice(0, 5).map((u) => (
            <button
              key={u.request}
              type="button"
              className={cn(row, "hover:bg-muted/50")}
              disabled={!u.family}
              onClick={() => u.family && onOpen(u.family)}
            >
              <span className="num w-12 shrink-0 text-[11px] font-semibold">{u.request}</span>
              <span className="text-xs text-muted-foreground">
                {u.by || "An agent"} used it for {u.name || u.family || "a household"}
                {u.priority != null ? ` · priority ${u.priority}` : ""}
              </span>
            </button>
          ))}
        </EdgeBox>
      )}
    </div>
  );
}

function LessonCard({
  l,
  onOpen,
  onOverride,
}: {
  l: Lesson;
  onOpen: OpenFamily;
  onOverride: (key: string, o: Override) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const pct = Math.round(l.confidence * 100);
  const strong = l.confidence >= 0.5;
  const active = inUse(l);
  const dismissed = l.override === "off";
  const kind = LESSON_KIND[l.kind] ?? { label: l.kind, icon: FileTextIcon };
  const Icon = kind.icon;
  const set = async (o: Override) => {
    setBusy(true);
    try {
      await onOverride(l.key, o);
    } finally {
      setBusy(false);
    }
  };
  const status = dismissed ? "Dismissed" : l.override === "on" ? "Applied by hand" : active ? "Active" : "Not applied";
  return (
    <div
      className={cn(
        "flex flex-col gap-2.5 rounded-xl border p-3.5",
        dismissed ? "bg-muted/60 text-muted-foreground" : active ? "bg-card" : "border-medium/30 bg-medium-soft",
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <span className={cn("inline-flex h-6 items-center gap-1.5 rounded-full px-2.5 text-xs font-medium", active ? "bg-muted" : "bg-background")}>
          <Icon className="size-3.5" aria-hidden="true" />
          {kind.label}
        </span>
        <span
          className={cn(
            "inline-flex h-6 items-center gap-1.5 rounded-full px-2.5 text-xs font-semibold",
            dismissed ? "bg-background text-muted-foreground" : active ? "bg-success-soft text-success" : "bg-background text-medium",
          )}
        >
          <span
            className={cn("size-1.5 rounded-full", dismissed ? "bg-muted-foreground" : active ? "bg-success" : "bg-medium")}
            aria-hidden="true"
          />
          {status}
        </span>
      </div>
      <p className={cn("text-sm leading-relaxed", dismissed && "line-through decoration-muted-foreground/50")}>{l.text}</p>
      <div className="flex flex-col gap-1.5">
        <div className="flex justify-between text-xs">
          <span className="text-muted-foreground">Confidence</span>
          <span className={cn("num font-semibold", !strong && !dismissed && "text-medium")}>
            {pct}% · {pct >= 75 ? "strong" : strong ? "good" : "weak"}
          </span>
        </div>
        <div className="relative h-3" role="img" aria-label={`Confidence ${pct}%, applied at 50% or more`}>
          <span className={cn("absolute inset-x-0 top-1 h-1 rounded-full", strong ? "bg-muted" : "bg-medium/20")} />
          <span
            className={cn("absolute top-1 left-0 h-1 rounded-full", dismissed ? "bg-muted-foreground/50" : strong ? "bg-primary" : "bg-medium")}
            style={{ width: `${pct}%` }}
          />
          <span className="absolute top-0 left-1/2 h-3 w-px bg-foreground/50" aria-hidden="true" />
        </div>
        {l.override ? (
          <p className="text-xs text-muted-foreground">
            {l.override === "on" ? "Applied" : "Dismissed"} by {l.override_by ?? "a coordinator"}. The Learner still updates the
            confidence.
          </p>
        ) : (
          !strong && <p className="text-xs text-medium">A lesson changes decisions at 50% confidence. It needs more field evidence.</p>
        )}
      </div>
      <div className={cn("flex flex-wrap items-center justify-between gap-2 border-t pt-2", !active && !dismissed && "border-medium/25")}>
        <span className="flex items-center gap-3 text-xs text-muted-foreground">
          <span className="flex items-center gap-1">
            <FileTextIcon className="size-3" aria-hidden="true" />
            {l.evidence.length} {l.evidence.length === 1 ? "piece" : "pieces"} of evidence
          </span>
          <span className="flex items-center gap-1">
            <GitBranchIcon className="size-3" aria-hidden="true" />
            {l.used ? `Used in ${l.used} decisions` : "Not used yet"}
          </span>
        </span>
        <span className="flex items-center gap-1">
          {(l.evidence.length > 0 || l.used > 0) && (
            <Button variant="link" size="xs" className="h-auto px-1" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
              {open ? "Hide evidence" : "View evidence"}
            </Button>
          )}
          {l.override ? (
            <Button variant="outline" size="xs" disabled={busy} onClick={() => set(null)}>
              {dismissed ? "Restore" : "Clear"}
            </Button>
          ) : (
            <>
              <Button variant="ghost" size="xs" disabled={busy} onClick={() => set("off")}>
                Dismiss
              </Button>
              {!strong && (
                <Button variant="outline" size="xs" disabled={busy} onClick={() => set("on")}>
                  Apply now
                </Button>
              )}
            </>
          )}
        </span>
      </div>
      {open && <LessonGraph l={l} onOpen={onOpen} />}
      {l.by && l.by !== "rules" && <span className="num text-[10px] text-muted-foreground">Proposed by {l.by}</span>}
    </div>
  );
}

export function LessonsPanel({
  lessons,
  onOpen,
  onLearn,
  onOverride,
}: {
  lessons: Lesson[];
  onOpen: OpenFamily;
  onLearn: () => Promise<void>;
  onOverride: (key: string, o: Override) => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const groups: [string, Lesson[]][] = [
    ["In use", lessons.filter(inUse)],
    ["Needs more evidence", lessons.filter((l) => !inUse(l) && l.override !== "off")],
    ["Dismissed", lessons.filter((l) => l.override === "off")],
  ];
  const last = lessons.reduce((m, l) => Math.max(m, l.updated_at || 0), 0);
  return (
    <div>
      <div className="flex flex-col gap-2 border-b px-4 py-3.5">
        <div className="flex items-center justify-between gap-2">
          <SerifTitle as="h3" sans="What the team" serif="has learned" className="text-base font-medium" />
          <Button
            variant="outline"
            size="sm"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              try {
                await onLearn();
              } finally {
                setBusy(false);
              }
            }}
          >
            {busy ? <Spinner data-icon="inline-start" /> : <RefreshCwIcon data-icon="inline-start" />}
            {busy ? "Learning…" : "Run now"}
          </Button>
        </div>
        <p className="text-xs leading-relaxed text-muted-foreground">
          The Learner reads field reports and writes rules into the graph. A rule changes new decisions at 50% confidence or
          more. A coordinator can apply a rule sooner or dismiss it. Each lesson links to the field evidence it came from, and
          to every decision that used it.{last ? ` Last change ${clock(last)}.` : ""}
        </p>
      </div>
      {lessons.length === 0 ? (
        <PanelEmpty icon={KeyRoundIcon} title="No lessons yet">
          They appear after repeated road reports or deliveries.
        </PanelEmpty>
      ) : (
        <div className="flex flex-col gap-2 p-3">
          {groups.map(([title, list], i) =>
            list.length ? (
              <section key={title} className="flex flex-col gap-2" aria-label={title}>
                <Eyebrow className={cn("px-1 text-foreground", i > 0 && "mt-2")}>
                  {title} · {list.length}
                </Eyebrow>
                {list.map((l) => (
                  <LessonCard key={l.key} l={l} onOpen={onOpen} onOverride={onOverride} />
                ))}
              </section>
            ) : null,
          )}
        </div>
      )}
    </div>
  );
}
