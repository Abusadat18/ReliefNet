import { OrganizationSwitcher } from "@clerk/react";
import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { api } from "../api";
import { useSession } from "../auth";
import { ChartMap, type Flash } from "../components/ChartMap";
import { BriefingDialog, DrillDialog, MessageDialog } from "../components/Dialogs";
import { FamilyDrawer } from "../components/FamilyDrawer";
import { AgentsPanel, FeedPanel, LessonsPanel, QueuePanel } from "../components/Panels";
import { ThemeToggle } from "../components/ThemeToggle";
import { clock, useLiveEvents, useNow, useResource, useThrottled } from "../hooks";
import type { AgentInfo, Lesson, LiveEvent, QueueItem, Region, Road, Snapshot, Stats, Trace } from "../types";

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

  const [drawer, setDrawer] = useState<{ trace: Trace | null; answer: { text: string; by: string; question: string } | null; loading: boolean } | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [focusRequest, setFocusRequest] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [dialog, setDialog] = useState<"drill" | "brief" | "message" | null>(null);
  const [roadPop, setRoadPop] = useState<{ road: Road; x: number; y: number } | null>(null);
  const [roadMsg, setRoadMsg] = useState<string | null>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const [mapFailed, setMapFailed] = useState<string | null>(null);

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
      if (e.kind === "reset") {
        void region.reload();
        refreshRoads();
      }
    },
    [refreshMap, refreshStats, refreshRoads, refreshLessons, roads.data, region],
  );
  const connected = useLiveEvents(onEvent);

  const openFamily = useCallback(async (id: string) => {
    setSelected(id);
    setDrawer({ trace: null, answer: null, loading: true });
    try {
      const trace = await api.get<Trace>(`/api/ops/family/${encodeURIComponent(id)}`);
      setDrawer({ trace, answer: null, loading: false });
    } catch (e) {
      setDrawer({ trace: null, answer: { text: e instanceof Error ? e.message : String(e), by: "rules", question: id }, loading: false });
    }
  }, []);

  const ask = async (ev: FormEvent) => {
    ev.preventDefault();
    const q = question.trim();
    if (!q) return;
    setDrawer({ trace: null, answer: null, loading: true });
    try {
      const r = await api.post<{ answer: string; trace: Trace | null; by: string }>("/api/ops/why", { question: q });
      setDrawer({ trace: r.trace, answer: { text: r.answer, by: r.by, question: q }, loading: false });
      if (r.trace) setSelected(r.trace.family.id);
    } catch (e) {
      setDrawer({ trace: null, answer: { text: e instanceof Error ? e.message : String(e), by: "rules", question: q }, loading: false });
    }
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
    onSelectFamily: openFamily,
    onRoadClick: (road: Road, at: { x: number; y: number }) => {
      const box = wrapRef.current!.getBoundingClientRect();
      setRoadMsg(null);
      // Keep the whole card (about 260 px tall) above the question bar.
      setRoadPop({
        road,
        x: Math.max(8, Math.min(at.x - box.left + 12, box.width - 256)),
        y: Math.max(8, Math.min(at.y - box.top + 12, box.height - 340)),
      });
    },
  });

  const s = stats.data;
  const fam = s?.families ?? {};
  const totalFam = (fam.SERVED ?? 0) + (fam.ASSIGNED ?? 0) + (fam.UNSERVED ?? 0);
  const deadAgents = (agents.data ?? []).filter((a) => a.state === "dead").length;
  const queueCount = (queue.data?.items ?? []).filter((q) => q.status !== "ASSIGNED").length;

  return (
    <div className="ops">
      <header className="ops-head">
        <div className="brand">
          <b>ReliefNet</b>
          <span>
            {me?.org_name}, {clock(now)}
          </span>
        </div>
        <nav className="pipeline" aria-label="Requests at each stage">
          {PIPELINE.map((p) => (
            <div
              key={p.key}
              className={`station${p.key === "TRIAGED" && (s?.requests.TRIAGED ?? 0) > 5 ? " hot" : ""}${p.key === "DELIVERED" ? " done" : ""}`}
            >
              <span className="count num">{s?.requests[p.key] ?? 0}</span>
              <span className="name">{p.name}</span>
            </div>
          ))}
          <div className="station aside">
            <span className="count num">{s?.requests.MERGED ?? 0}</span>
            <span className="name">Duplicates merged</span>
          </div>
        </nav>
        <div className="head-tools">
          <span className={`live-dot${connected ? " on" : ""}`}>{connected ? "Live" : "Reconnecting"}</span>
          {mode === "clerk" && (
            // Admins invite and manage members from here (Manage organization > Members).
            // A full page load after switching makes every panel reload for the new org.
            <OrganizationSwitcher
              hidePersonal
              afterSelectOrganizationUrl="/"
              afterLeaveOrganizationUrl="/"
              afterCreateOrganizationUrl="/"
            />
          )}
          <ThemeToggle />
          <button type="button" className="btn quiet small" onClick={signOut} title={`Signed in as ${me?.name}`}>
            Sign out
          </button>
        </div>
      </header>

      <div className="ops-body">
        <div className="chart-wrap" ref={wrapRef}>
          {mergedRegion ? (
            config?.google_maps && !mapFailed ? (
              <Suspense fallback={<p className="empty">Loading the map…</p>}>
                <GoogleMap
                  apiKey={config.google_maps.api_key}
                  mapId={config.google_maps.map_id}
                  onFail={setMapFailed}
                  {...mapProps(mergedRegion)}
                />
              </Suspense>
            ) : (
              <ChartMap {...mapProps(mergedRegion)} />
            )
          ) : (
            <p className="empty">{region.error ?? "Loading the chart…"}</p>
          )}
          {mapFailed && (
            <p className="map-note" role="status">
              {mapFailed}
            </p>
          )}

          <div className="legend" aria-label="Legend">
            <span>
              <i style={{ background: "var(--waiting)" }} /> Waiting for help
            </span>
            <span>
              <i style={{ background: "var(--route)" }} /> Team on the way
            </span>
            <span>
              <i style={{ background: "var(--paper)", border: "2px solid var(--served)" }} /> Served
            </span>
            <span>
              <i style={{ border: "2px solid var(--hazard)" }} /> Priority 70 or more
            </span>
            <span>
              <i className="line" style={{ borderColor: "var(--hazard)" }} /> Flooded road
            </span>
            <span>
              <i className="line" style={{ borderColor: "var(--waiting)", borderTopStyle: "dashed" }} /> Reported, not confirmed
            </span>
            <span>
              <i className="line" style={{ borderColor: "var(--water-ink)", borderTopStyle: "dotted" }} /> Low road near a drain
            </span>
          </div>

          <div className="chart-tools">
            <button type="button" className="btn" onClick={() => setDialog("message")}>
              Add message
            </button>
            <button type="button" className="btn" onClick={() => setDialog("brief")}>
              Shift handover
            </button>
            <button type="button" className="btn primary" onClick={() => setDialog("drill")}>
              Flood drill
            </button>
          </div>

          <section className="cartouche" aria-label="Operation figures">
            <h2>{config?.area.title ?? region.data?.area?.title} flood operation</h2>
            <dl>
              <dt>Households reached</dt>
              <dd className="num">
                {fam.SERVED ?? 0} of {totalFam}
              </dd>
              <dt>Households sent two teams</dt>
              <dd className={`num${s && s.duplicate_dispatches === 0 ? " zero" : ""}`}>{s?.duplicate_dispatches ?? 0}</dd>
              <dt>Duplicate messages merged</dt>
              <dd className="num">{s?.metrics.merged ?? 0}</dd>
              <dt>Messages in the last minute</dt>
              <dd className="num">{Math.round(s?.rates.messages_per_min ?? 0)}</dd>
              <dt>Requests reclaimed after a crash</dt>
              <dd className="num">{s?.metrics.reclaimed ?? 0}</dd>
              <dt>Routes changed by floods</dt>
              <dd className="num">{s?.metrics.rerouted ?? 0}</dd>
              {s?.dedupe.precision != null && (
                <>
                  <dt>Merge accuracy (drill)</dt>
                  <dd className="num">{Math.round(s.dedupe.precision * 100)}%</dd>
                </>
              )}
              <dt>Lessons in use</dt>
              <dd className="num">{s?.lessons_active ?? 0}</dd>
            </dl>
            <p className="foot">
              Understanding: {config?.llm === "live" ? `${config.models?.fast} and ${config.models?.smart}` : "offline rules"}.
              Memory: FalkorDB graph {me ? `org_${me.org}` : ""}.
              {region.data?.area?.attribution && <> {region.data.area.attribution}.</>}
            </p>
          </section>

          <form className="askbar" onSubmit={ask} role="search">
            <label htmlFor="ask" className="sr-only">
              Ask about a household
            </label>
            <input
              id="ask"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="Ask why: “Why hasn't the Das family been served?”"
              autoComplete="off"
            />
            <button type="submit" className="btn primary" disabled={!question.trim()}>
              Ask
            </button>
          </form>

          {roadPop && (
            <div className="road-pop" style={{ left: roadPop.x, top: roadPop.y }} role="dialog" aria-label={roadPop.road.name}>
              <h3>{roadPop.road.name}</h3>
              <span className={`chip s-${roadPop.road.status}`}>{roadPop.road.status}</span>
              <p className="result-line">
                Your report counts as confirmed, so it changes routes for every organisation right away.
              </p>
              <div className="row" style={{ display: "flex", gap: 8 }}>
                <button type="button" className="btn small hazard" onClick={() => setRoad("flooded")}>
                  Mark flooded
                </button>
                <button type="button" className="btn small" onClick={() => setRoad("open")}>
                  Mark open
                </button>
                <button type="button" className="btn small quiet" onClick={() => setRoadPop(null)}>
                  Close
                </button>
              </div>
              {roadMsg && <p className="result-line">{roadMsg}</p>}
            </div>
          )}
        </div>

        <aside className="side">
          <div className="tabs" role="tablist">
            {(
              [
                ["queue", "Queue", queueCount],
                ["feed", "Live log", null],
                ["agents", "Agents", deadAgents ? `${deadAgents} down` : null],
                ["lessons", "Lessons", lessons.data?.length || null],
              ] as [Tab, string, number | string | null][]
            ).map(([k, label, badge]) => (
              <button key={k} type="button" role="tab" aria-selected={tab === k} onClick={() => setTab(k)}>
                {label}
                {badge !== null && badge !== 0 && <span className="badge">{badge}</span>}
              </button>
            ))}
          </div>
          <div className="panel-scroll" role="tabpanel">
            {tab === "queue" && <QueuePanel items={queue.data?.items ?? []} onOpen={openFamily} />}
            {tab === "feed" && <FeedPanel events={events} onOpen={openFamily} />}
            {tab === "agents" && <AgentsPanel agents={agents.data ?? []} onChange={() => void agents.reload()} />}
            {tab === "lessons" && (
              <LessonsPanel
                lessons={lessons.data ?? []}
                onLearn={async () => {
                  lessons.setData(await api.post<Lesson[]>("/api/ops/learn"));
                }}
              />
            )}
          </div>
        </aside>
      </div>

      {drawer && (
        <FamilyDrawer
          trace={drawer.trace}
          answer={drawer.answer}
          loading={drawer.loading}
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
    </div>
  );
}
