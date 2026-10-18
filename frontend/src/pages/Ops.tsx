import { OrganizationSwitcher } from "@clerk/react";
import {
  ChevronDownIcon,
  FileTextIcon,
  MapPinIcon,
  MessageSquarePlusIcon,
  PlayIcon,
  SparklesIcon,
  UsersIcon,
  WaypointsIcon,
  XIcon,
} from "lucide-react";
import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type HTMLAttributes,
  type ReactNode,
} from "react";
import { api } from "../api";
import { useSession } from "../auth";
import { ChartMap, type Flash } from "../components/ChartMap";
import { BriefingDialog, DrillDialog, MessageDialog } from "../components/Dialogs";
import { FamilyDrawer, type DrawerState, type SheetTab } from "../components/FamilyDrawer";
import { BrandMark, Eyebrow, SerifTitle } from "../components/kit";
import { LayersMenu, useMapLayers } from "../components/LayersMenu";
import { memorySummary } from "../components/memory";
import { AgentsPanel, FeedPanel, LessonsPanel, QueuePanel } from "../components/Panels";
import { PlacesDialog } from "../components/PlacesDialog";
import { TeamsDialog } from "../components/TeamsDialog";
import { ThemeToggle } from "../components/ThemeToggle";
import { clock, useLiveEvents, useNow, useResource, useThrottled } from "../hooks";
import type { AgentInfo, Lesson, LiveEvent, QueueItem, Region, Road, Snapshot, Stats, Trace } from "../types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Kbd } from "@/components/ui/kbd";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";

// deck.gl and the map code load only when the server has a Google Maps key.
const GoogleMap = lazy(() => import("../components/GoogleMap").then((m) => ({ default: m.GoogleMap })));

type Tab = "queue" | "feed" | "agents" | "lessons";

const PIPELINE: { key: string; name: string }[] = [
  { key: "NEW", name: "New" },
  { key: "RESOLVED", name: "Deduplicated" },
  { key: "TRIAGED", name: "Triaged" },
  { key: "ASSIGNED", name: "Assigned" },
  { key: "DELIVERED", name: "Delivered" },
];

const LEGEND_STORE = "reliefnet.legend";

/** A floating card on the map. */
function MapCard({ className, children, ...rest }: { className?: string; children: ReactNode } & HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn("absolute rounded-xl border bg-background/95 shadow-sm backdrop-blur", className)} {...rest}>
      {children}
    </div>
  );
}

function Swatch({ kind }: { kind: string }) {
  const box = "grid w-6 shrink-0 place-items-center";
  switch (kind) {
    case "waiting":
      return <span className={box}><span className="size-2.5 rounded-full" style={{ background: "var(--waiting)" }} /></span>;
    case "assigned":
      return <span className={box}><span className="size-2.5 rounded-full" style={{ background: "var(--route)" }} /></span>;
    case "served":
      return <span className={box}><span className="size-2.5 rounded-full border-2" style={{ borderColor: "var(--served)" }} /></span>;
    case "priority":
      return <span className={box}><span className="num rounded-full bg-critical px-1 text-[8px] leading-[14px] font-bold text-white">90</span></span>;
    case "cluster":
      return <span className={box}><span className="num grid size-3.5 place-items-center rounded-full bg-foreground text-[8px] font-bold text-background">3</span></span>;
    case "team":
      return <span className={box}><span className="h-3 w-5 rounded-full bg-foreground" /></span>;
    case "shelter":
      return <span className={box}><span className="size-3 rounded-full border bg-success-soft" style={{ borderColor: "var(--served)" }} /></span>;
    case "route":
      return <span className={box}><span className="h-1.5 w-5 rounded-full border border-(--direction-edge)" style={{ background: "var(--direction)" }} /></span>;
    case "low":
      return <span className={box}><span className="h-0.5 w-5" style={{ background: "var(--water-ink)" }} /></span>;
    case "flooded":
      return <span className={box}><span className="h-1 w-5 rounded-full" style={{ background: "var(--hazard)" }} /></span>;
    case "reported":
      return <span className={box}><span className="h-0 w-5 border-t-[3px] border-dashed" style={{ borderColor: "var(--waiting)" }} /></span>;
    default:
      return <span className={box}><span className="h-3 w-5 rounded border border-primary" style={{ background: "var(--mask)" }} /></span>;
  }
}

const LEGEND: [string, string][] = [
  ["waiting", "Waiting for help"],
  ["assigned", "Team on the way"],
  ["served", "Served"],
  ["priority", "Priority 70 or more"],
  ["cluster", "Several households"],
  ["team", "Team"],
  ["shelter", "Shelter"],
  ["route", "Selected route"],
  ["low", "Low road near a drain"],
  ["flooded", "Flooded road"],
  ["reported", "Reported, not confirmed"],
  ["outside", "Outside the operation"],
];

function Legend() {
  const [open, setOpen] = useState(() => {
    try {
      return localStorage.getItem(LEGEND_STORE) !== "closed";
    } catch {
      return true;
    }
  });
  const toggle = () =>
    setOpen((o) => {
      try {
        localStorage.setItem(LEGEND_STORE, o ? "closed" : "open");
      } catch {
        /* not kept in private mode */
      }
      return !o;
    });
  return (
    <MapCard className="pointer-events-auto relative flex min-h-0 w-52 shrink flex-col p-3" aria-label="Legend">
      <button type="button" className="flex w-full items-center justify-between" onClick={toggle} aria-expanded={open}>
        <Eyebrow className="text-foreground">Legend</Eyebrow>
        <ChevronDownIcon className={cn("size-3.5 text-muted-foreground transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <ul className="mt-2 flex min-h-0 flex-col gap-1.5 overflow-y-auto">
          {LEGEND.map(([k, label]) => (
            <li key={k} className="flex items-center gap-2 text-xs">
              <Swatch kind={k} />
              {label}
            </li>
          ))}
        </ul>
      )}
    </MapCard>
  );
}

export function Ops() {
  const { me, config, signOut, mode } = useSession();
  const now = useNow(15000);
  const [tab, setTab] = useState<Tab>("queue");
  const region = useResource<Region>("/api/ops/region");
  const snapshot = useResource<Snapshot>("/api/ops/snapshot", 10000);
  const queue = useResource<{ items: QueueItem[] }>("/api/ops/queue", 5000);
  const stats = useResource<Stats>("/api/ops/stats", 8000);
  const agents = useResource<AgentInfo[]>("/api/ops/agents", 2000);
  const lessons = useResource<Lesson[]>("/api/ops/lessons", 20000);
  const roads = useResource<Road[]>("/api/ops/roads");
  const [events, setEvents] = useState<LiveEvent[]>([]);
  const [flashes, setFlashes] = useState<Flash[]>([]);

  const [drawer, setDrawer] = useState<DrawerState | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [focusRequest, setFocusRequest] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [dialog, setDialog] = useState<"drill" | "brief" | "message" | null>(null);
  const [teamsDialog, setTeamsDialog] = useState<"list" | "add" | null>(null);
  const [placesOpen, setPlacesOpen] = useState(false);
  const [roadPop, setRoadPop] = useState<{ road: Road; x: number; y: number } | null>(null);
  const [roadMsg, setRoadMsg] = useState<string | null>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const [mapFailed, setMapFailed] = useState<string | null>(null);
  const [layers, setLayer] = useMapLayers();
  // With the Memory layer on, a click on a household draws its graph on the map instead of opening the sheet.
  const [memoryOn, setMemoryOn] = useState(false);
  const [memory, setMemory] = useState<{ id: string; trace: Trace | null; error?: string } | null>(null);

  useEffect(() => {
    api.get<LiveEvent[]>("/api/ops/events?count=200").then(setEvents).catch(() => undefined);
  }, []);

  const refreshMap = useThrottled(() => {
    void snapshot.reload();
    void queue.reload();
  }, 900);
  const refreshStats = useThrottled(() => void stats.reload(), 1500);
  const refreshRoads = useThrottled(() => void roads.reload(), 500);
  const refreshLessons = useThrottled(() => void lessons.reload(), 1500);

  const mergedRegion = useMemo<Region | null>(() => {
    if (!region.data) return null;
    if (!roads.data) return region.data;
    return { ...region.data, roads: roads.data };
  }, [region.data, roads.data]);

  const onEvent = useCallback(
    (e: LiveEvent) => {
      setEvents((prev) => [e, ...prev].slice(0, 400));
      refreshMap();
      refreshStats();
      if (e.kind === "road") {
        refreshRoads();
        const name = e.data.road as string;
        const seg = roads.data?.find((r) => r.name === name) ?? region.data?.roads.find((r) => r.name === name);
        if (seg && e.data.status === "flooded") {
          const [lat, lon] = seg.coords[Math.floor((seg.coords.length - 1) / 2)];
          const id = `${name}-${e.at}`;
          setFlashes((f) => [...f, { id, lat, lon }]);
          window.setTimeout(() => setFlashes((f) => f.filter((x) => x.id !== id)), 3500);
        }
      }
      if (e.kind === "lesson") refreshLessons();
      if (e.kind === "landmark") void region.reload();
      if (e.kind === "reset") {
        void region.reload();
        refreshRoads();
      }
    },
    [refreshMap, refreshStats, refreshRoads, refreshLessons, roads.data, region],
  );
  const connected = useLiveEvents(onEvent);

  const openFamily = useCallback(async (id: string, tab: SheetTab = "why") => {
    setSelected(id);
    setDrawer({ trace: null, answer: null, loading: true, tab });
    try {
      const t0 = performance.now();
      const trace = await api.get<Trace>(`/api/ops/family/${encodeURIComponent(id)}`);
      setDrawer({ trace, answer: null, loading: false, tab, ms: Math.round(performance.now() - t0) });
    } catch (e) {
      setDrawer({ trace: null, answer: { text: e instanceof Error ? e.message : String(e), by: "rules", question: id }, loading: false, tab });
    }
  }, []);

  const showMemory = useCallback(async (id: string) => {
    setSelected(id);
    setMemory({ id, trace: null });
    try {
      const trace = await api.get<Trace>(`/api/ops/family/${encodeURIComponent(id)}`);
      setMemory((m) => (m?.id === id ? { id, trace } : m));
    } catch (e) {
      setMemory((m) => (m?.id === id ? { id, trace: null, error: e instanceof Error ? e.message : String(e) } : m));
    }
  }, []);

  const toggleMemory = () => {
    if (memoryOn) {
      setMemory(null);
      setSelected(null);
    } else if (selected) void showMemory(selected);
    setMemoryOn(!memoryOn);
  };

  const askWhy = useCallback(async (q: string) => {
    setDrawer({ trace: null, answer: null, loading: true, tab: "why" });
    try {
      const r = await api.post<{ answer: string; trace: Trace | null; by: string }>("/api/ops/why", { question: q });
      setDrawer({ trace: r.trace, answer: { text: r.answer, by: r.by, question: q }, loading: false, tab: "why" });
      if (r.trace) setSelected(r.trace.family.id);
    } catch (e) {
      setDrawer({ trace: null, answer: { text: e instanceof Error ? e.message : String(e), by: "rules", question: q }, loading: false, tab: "why" });
    }
  }, []);

  const ask = (ev: FormEvent) => {
    ev.preventDefault();
    const q = question.trim();
    if (q) void askWhy(q);
  };

  const setRoad = async (status: "flooded" | "open") => {
    if (!roadPop) return;
    try {
      const r = await api.post<{ road: string; status: string; rerouted: string[] }>("/api/ops/roads", {
        road: roadPop.road.name,
        status,
      });
      setRoadMsg(
        `${r.road} is now ${r.status}.` + (r.rerouted.length ? ` ${r.rerouted.length} route(s) sent back to Dispatch.` : ""),
      );
      refreshRoads();
    } catch (e) {
      setRoadMsg(e instanceof Error ? e.message : String(e));
    }
  };

  const mapProps = (r: Region) => ({
    region: r,
    snapshot: snapshot.data,
    selected,
    focusRequest,
    flashes,
    show: layers,
    memory: memoryOn ? memory?.trace : null,
    onSelectFamily: memoryOn ? showMemory : openFamily,
    onRoadClick: (road: Road, at: { x: number; y: number }) => {
      const box = wrapRef.current!.getBoundingClientRect();
      setRoadMsg(null);
      // Keep the whole card (about 260 px tall) above the question bar.
      setRoadPop({
        road,
        x: Math.max(8, Math.min(at.x - box.left + 12, box.width - 296)),
        y: Math.max(8, Math.min(at.y - box.top + 12, box.height - 340)),
      });
    },
  });

  const s = stats.data;
  const fam = s?.families ?? {};
  const totalFam = (fam.SERVED ?? 0) + (fam.ASSIGNED ?? 0) + (fam.UNSERVED ?? 0);
  const deadAgents = (agents.data ?? []).filter((a) => a.state === "dead").length;
  const queueCount = (queue.data?.items ?? []).filter((q) => q.status !== "ASSIGNED").length;
  const areaTitle = config?.area.title ?? region.data?.area?.title ?? "";

  const figures: [string, ReactNode, boolean?][] = [
    ["Households reached", `${fam.SERVED ?? 0} / ${totalFam}`],
    ["Households sent two teams", s?.duplicate_dispatches ?? 0, s?.duplicate_dispatches === 0],
    ["Duplicate messages merged", s?.metrics.merged ?? 0],
    ["Messages, last minute", Math.round(s?.rates.messages_per_min ?? 0)],
    ["Reclaimed after a crash", s?.metrics.reclaimed ?? 0],
    ["Routes changed by floods", s?.metrics.rerouted ?? 0],
    ...(s?.dedupe.precision != null ? ([["Merge accuracy (drill)", `${Math.round(s.dedupe.precision * 100)}%`]] as [string, ReactNode][]) : []),
    ["Lessons in use", s?.lessons_active ?? 0],
  ];

  return (
    <div className="flex h-dvh flex-col bg-background text-foreground">
      <header className="flex h-14 shrink-0 items-stretch border-b">
        <div className="flex w-[300px] shrink-0 items-center gap-3 border-r px-5">
          <BrandMark />
          <div className="flex min-w-0 flex-col leading-tight">
            <span className="font-display text-[15px] font-semibold tracking-tight">ReliefNet</span>
            <span className="num truncate text-[10px] text-muted-foreground">
              {me?.org_name} · {clock(now)}
            </span>
          </div>
        </div>
        <nav className="flex min-w-0 flex-1 items-stretch overflow-x-auto" aria-label="Requests at each stage">
          {PIPELINE.map((p) => {
            const hot = p.key === "TRIAGED" && (s?.requests.TRIAGED ?? 0) > 5;
            const done = p.key === "DELIVERED";
            return (
              <div key={p.key} className={cn("flex items-center gap-2.5 border-r px-4", hot && "bg-high-soft")}>
                <span className="flex flex-col leading-tight">
                  <span className={cn("num text-[10px] tracking-wide uppercase", hot ? "text-high" : "text-muted-foreground")}>{p.name}</span>
                  <span className={cn("num text-[17px] font-semibold", hot && "text-high", done && "text-success")}>
                    {s?.requests[p.key] ?? 0}
                  </span>
                </span>
              </div>
            );
          })}
          <div className="flex items-center gap-2 px-4 text-[13px] whitespace-nowrap text-muted-foreground">
            <span className="num font-semibold text-foreground">{s?.requests.MERGED ?? 0}</span> duplicates merged
          </div>
        </nav>
        <div className="flex shrink-0 items-center gap-2.5 px-4">
          <span
            className={cn(
              "num inline-flex h-6 items-center gap-1.5 rounded-full border px-2.5 text-[10px] font-semibold",
              !connected && "text-warning",
            )}
            role="status"
          >
            <span className={cn("size-1.5 rounded-full", connected ? "bg-success" : "bg-warning")} aria-hidden="true" />
            {connected ? "LIVE" : "RECONNECTING"}
          </span>
          {mode === "clerk" && (
            // Admins invite and manage members from here (Manage organization > Members).
            // A full page load after switching makes every panel reload for the new org.
            <OrganizationSwitcher hidePersonal afterSelectOrganizationUrl="/" afterLeaveOrganizationUrl="/" afterCreateOrganizationUrl="/" />
          )}
          <ThemeToggle />
          <Button variant="ghost" size="sm" onClick={signOut} title={`Signed in as ${me?.name}`}>
            Sign out
          </Button>
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        <div className="flex min-w-0 flex-1 flex-col border-r">
          <div className="flex h-13 shrink-0 items-center justify-between gap-4 border-b pr-4 pl-5">
            <div className="flex min-w-0 items-center gap-2.5">
              <SerifTitle as="h1" sans={areaTitle} serif="flood operation" className="truncate text-[17px]" />
              <Badge variant="outline" className="hidden xl:inline-flex">
                OpenStreetMap roads
              </Badge>
            </div>
            <div className="flex shrink-0 items-center gap-1.5">
              <Button variant="ghost" size="sm" onClick={() => setTeamsDialog("list")}>
                <UsersIcon data-icon="inline-start" />
                Teams
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setPlacesOpen(true)}>
                <MapPinIcon data-icon="inline-start" />
                Places
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setDialog("message")}>
                <MessageSquarePlusIcon data-icon="inline-start" />
                Add message
              </Button>
              <Button variant="outline" size="sm" onClick={() => setDialog("brief")}>
                <FileTextIcon data-icon="inline-start" />
                Shift handover
              </Button>
              <Button size="sm" onClick={() => setDialog("drill")}>
                <PlayIcon data-icon="inline-start" />
                Flood drill
              </Button>
            </div>
          </div>

          <div className="relative min-h-0 flex-1 overflow-hidden" ref={wrapRef} style={{ background: "var(--land)" }}>
            {mergedRegion ? (
              config?.google_maps && !mapFailed ? (
                <Suspense fallback={<p className="p-6 text-sm text-muted-foreground">Loading the map…</p>}>
                  <GoogleMap
                    apiKey={config.google_maps.api_key}
                    mapId={config.google_maps.map_id}
                    mapIdDetailed={config.google_maps.map_id_detailed ?? null}
                    onFail={setMapFailed}
                    {...mapProps(mergedRegion)}
                  />
                </Suspense>
              ) : (
                <ChartMap {...mapProps(mergedRegion)} />
              )
            ) : (
              <p className="p-6 text-sm text-muted-foreground">{region.error ?? "Loading the chart…"}</p>
            )}
            {mapFailed && (
              <p
                className="absolute bottom-24 left-1/2 max-w-[min(520px,calc(100%-32px))] -translate-x-1/2 rounded-lg border border-warning bg-high-soft px-3 py-2 text-xs"
                role="status"
              >
                {mapFailed}
              </p>
            )}

            {mergedRegion && (
              <div className="absolute top-4 right-16 z-10 flex items-center gap-2">
                <Button
                  variant={memoryOn ? "default" : "outline"}
                  size="sm"
                  className={cn("rounded-full shadow-sm", !memoryOn && "bg-background")}
                  aria-pressed={memoryOn}
                  onClick={toggleMemory}
                  title="Show what the graph remembers about a household"
                >
                  <WaypointsIcon data-icon="inline-start" />
                  Memory
                </Button>
                <LayersMenu visible={layers} onChange={setLayer} />
              </div>
            )}

            {snapshot.data && snapshot.data.teams.length === 0 && (
              <MapCard className="top-1/2 left-1/2 w-[min(380px,calc(100%-32px))] -translate-x-1/2 -translate-y-1/2 p-5" role="status">
                <h3 className="font-medium">No teams yet. Add your first team.</h3>
                <p className="mt-1 text-sm text-muted-foreground">
                  Dispatch cannot send help without a team. Requests wait in Triaged until a team is on duty.
                </p>
                <div className="mt-3">
                  {me?.role === "admin" ? (
                    <Button onClick={() => setTeamsDialog("add")}>Add a team</Button>
                  ) : (
                    <p className="text-sm text-muted-foreground">Ask an admin of your organisation to add a team.</p>
                  )}
                </div>
              </MapCard>
            )}

            {memoryOn && (
              <MapCard className="right-4 bottom-20 z-10 flex w-[300px] flex-col gap-2 bg-popover/95 p-4" role="status" aria-live="polite">
                <div className="flex items-start justify-between gap-2">
                  <Eyebrow className="text-foreground">
                    {memory?.trace
                      ? `${memory.trace.family.name || memory.trace.family.id} · ${memory.trace.family.id} · in the graph`
                      : "Memory layer"}
                  </Eyebrow>
                  <button
                    type="button"
                    aria-label="Turn off the Memory layer"
                    className="-mt-1 -mr-1 grid size-6 place-items-center rounded-full text-muted-foreground hover:bg-muted"
                    onClick={toggleMemory}
                  >
                    <XIcon className="size-3.5" />
                  </button>
                </div>
                <p className="text-[13px] leading-snug text-muted-foreground">
                  {memory?.trace
                    ? memorySummary(memory.trace)
                    : memory?.error
                      ? memory.error
                      : memory
                        ? "Reading this household's edges…"
                        : "Click a household to see what the graph remembers about it."}
                </p>
                {memory?.trace && (
                  <Button variant="link" size="xs" className="h-auto self-start p-0" onClick={() => void openFamily(memory.id, "graph")}>
                    Open the graph query
                  </Button>
                )}
              </MapCard>
            )}

            {/* One column, so the legend shrinks and scrolls instead of running under the figures on a short screen. */}
            <div className="pointer-events-none absolute top-4 bottom-4 left-4 z-10 flex flex-col gap-3">
              <Legend />
              <MapCard className="pointer-events-auto relative mt-auto w-[290px] shrink-0 px-4 pt-3.5 pb-2.5" aria-label="Operation figures">
                <Eyebrow className="text-foreground">Shift status · live</Eyebrow>
                <dl className="mt-1">
                  {figures.map(([label, value, zero]) => (
                    <div key={label} className="flex items-end justify-between border-b py-1.5 last:border-b-0">
                      <dt className="text-xs text-muted-foreground">{label}</dt>
                      <dd className={cn("num text-sm font-semibold", zero && "text-success")}>{value}</dd>
                    </div>
                  ))}
                </dl>
                <p className="num mt-1.5 text-[9px] leading-relaxed text-muted-foreground">
                  Understanding: {config?.llm === "live" ? `${config.models?.fast} and ${config.models?.smart}` : "offline rules"}.
                  Memory: FalkorDB org_{me?.org}. {region.data?.area?.attribution}
                </p>
              </MapCard>
            </div>

            <form
              className="absolute bottom-4 left-[322px] right-4 mx-auto flex h-12 max-w-[600px] items-center gap-2.5 rounded-full border bg-background pr-1.5 pl-4 shadow-md"
              onSubmit={ask}
              role="search"
            >
              <SparklesIcon className="size-4 shrink-0 text-primary" aria-hidden="true" />
              <label htmlFor="ask" className="sr-only">
                Ask about a household
              </label>
              <input
                id="ask"
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                placeholder="Ask why: “Why hasn't the Das family been served?”"
                autoComplete="off"
                className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
              />
              <Kbd className="hidden sm:inline-flex">Enter</Kbd>
              <Button type="submit" disabled={!question.trim()}>
                Ask
              </Button>
            </form>

            {roadPop && (
              <MapCard className="z-20 w-[280px] p-4" style={{ left: roadPop.x, top: roadPop.y }} role="dialog" aria-label={roadPop.road.name}>
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <h3 className="font-medium">{roadPop.road.name}</h3>
                    <Badge variant={roadPop.road.status === "flooded" ? "destructive" : "outline"} className="num mt-1 uppercase">
                      {roadPop.road.status}
                    </Badge>
                  </div>
                  <Button variant="ghost" size="icon-sm" onClick={() => setRoadPop(null)} aria-label="Close">
                    <XIcon />
                  </Button>
                </div>
                <p className="mt-2 text-xs text-muted-foreground">
                  Your report counts as confirmed, so it changes routes for every organisation right away.
                </p>
                <div className="mt-3 flex gap-2">
                  <Button variant="destructive" size="sm" onClick={() => setRoad("flooded")}>
                    Mark flooded
                  </Button>
                  <Button variant="outline" size="sm" onClick={() => setRoad("open")}>
                    Mark open
                  </Button>
                </div>
                {roadMsg && <p className="mt-2 text-xs text-muted-foreground">{roadMsg}</p>}
              </MapCard>
            )}
          </div>
        </div>

        <aside className="flex w-[420px] shrink-0 flex-col">
          <Tabs value={tab} onValueChange={(v) => setTab(v as Tab)} className="flex min-h-0 flex-1 gap-0">
            <TabsList variant="line" className="h-10 w-full justify-start rounded-none border-b px-2">
              {(
                [
                  ["queue", "Queue", queueCount || null, false],
                  ["feed", "Live log", null, false],
                  ["agents", "Agents", deadAgents ? `${deadAgents} down` : null, deadAgents > 0],
                  ["lessons", "Lessons", lessons.data?.length || null, false],
                ] as [Tab, string, number | string | null, boolean][]
              ).map(([k, label, badge, bad]) => (
                <TabsTrigger key={k} value={k} className="flex-none px-3">
                  {label}
                  {badge !== null && (
                    <span
                      className={cn(
                        "num rounded px-1 text-[10px] leading-4 font-semibold",
                        bad ? "bg-destructive text-white" : "bg-muted text-muted-foreground",
                      )}
                    >
                      {badge}
                    </span>
                  )}
                </TabsTrigger>
              ))}
            </TabsList>
            <TabsContent value="queue" className="min-h-0 overflow-y-auto">
              <QueuePanel items={queue.data?.items ?? []} graphName={s?.graph?.name ?? (me ? `org_${me.org}` : "")} onOpen={openFamily} />
            </TabsContent>
            <TabsContent value="feed" className="min-h-0 overflow-y-auto">
              <FeedPanel events={events} graph={s?.graph} onOpen={openFamily} />
            </TabsContent>
            <TabsContent value="agents" className="min-h-0 overflow-y-auto">
              <AgentsPanel
                agents={agents.data ?? []}
                queue={queue.data?.items ?? []}
                events={events}
                leaseMs={config?.lease_ms ?? 8000}
                onChange={() => void agents.reload()}
              />
            </TabsContent>
            <TabsContent value="lessons" className="min-h-0 overflow-y-auto">
              <LessonsPanel
                lessons={lessons.data ?? []}
                onOpen={openFamily}
                onLearn={async () => {
                  lessons.setData(await api.post<Lesson[]>("/api/ops/learn"));
                }}
                onOverride={async (key, override) => {
                  lessons.setData(await api.post<Lesson[]>(`/api/ops/lessons/${encodeURIComponent(key)}/override`, { override }));
                  void stats.reload();
                }}
              />
            </TabsContent>
          </Tabs>
        </aside>
      </div>

      {drawer && (
        <FamilyDrawer
          state={drawer}
          onTab={(t) => setDrawer((d) => (d ? { ...d, tab: t } : d))}
          onAsk={(q) => void askWhy(q)}
          onClose={() => {
            setDrawer(null);
            setSelected(null);
          }}
          onShowRoute={(rid) => {
            setFocusRequest(rid);
            setDrawer(null);
          }}
        />
      )}
      {dialog === "drill" && <DrillDialog isAdmin={me?.role === "admin"} onClose={() => setDialog(null)} />}
      {dialog === "brief" && <BriefingDialog onClose={() => setDialog(null)} />}
      {dialog === "message" && <MessageDialog onClose={() => setDialog(null)} />}
      {teamsDialog && (
        <TeamsDialog
          isAdmin={me?.role === "admin"}
          region={mergedRegion}
          startWithForm={teamsDialog === "add"}
          onClose={() => {
            setTeamsDialog(null);
            void snapshot.reload();
          }}
        />
      )}
      {placesOpen && <PlacesDialog onClose={() => setPlacesOpen(false)} />}
    </div>
  );
}
