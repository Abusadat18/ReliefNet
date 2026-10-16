import { useState } from "react";
import { api } from "../api";
import { ago, clock, needLabel, useNow } from "../hooks";
import type { AgentInfo, Lesson, LiveEvent, QueueItem } from "../types";

const STAGES: { status: string; title: string; note: string }[] = [
  { status: "TRIAGED", title: "Waiting for a team", note: "Dispatch takes the highest priority first" },
  { status: "ASSIGNED", title: "Team on the way", note: "" },
  { status: "RESOLVED", title: "Being scored", note: "" },
  { status: "NEW", title: "Checking for duplicates", note: "" },
];

export function QueuePanel({ items, onOpen }: { items: QueueItem[]; onOpen: (familyId: string) => void }) {
  const now = useNow(1000);
  if (!items.length)
    return (
      <p className="empty">
        No open requests. Start a flood drill, or paste a message from the helpline, to see the agents work.
      </p>
    );
  return (
    <div>
      {STAGES.map((st) => {
        const rows = items.filter((i) => i.status === st.status);
        if (!rows.length) return null;
        return (
          <section key={st.status} aria-label={st.title}>
            <div className="group-head">
              <span>{st.title}</span>
              <span className="num">{rows.length}</span>
            </div>
            {rows.map((q) => {
              const lease = q.claimed_by && q.lease_until && q.lease_until > now;
              const expired = q.claimed_by && q.lease_until && q.lease_until <= now;
              return (
                <button key={q.id} type="button" className="qrow" onClick={() => q.family && onOpen(q.family)}>
                  <span className={`prio num${(q.priority ?? 0) >= 70 ? " high" : ""}`}>{q.priority ?? "–"}</span>
                  <span className="qwho">
                    <span>{q.name || q.family || q.id}</span>
                    <span className={`chip s-${q.status}`}>{q.team ?? q.id}</span>
                  </span>
                  <span className="what">
                    Ward {q.ward} {q.landmark}. Needs {q.needs.map(needLabel).join(", ")}.
                    {q.merged ? ` ${q.merged} duplicate message${q.merged > 1 ? "s" : ""} merged.` : ""}
                  </span>
                  {lease ? (
                    <span className="lease">
                      {q.claimed_by} holds the lease, {Math.ceil((q.lease_until! - now) / 1000)} s left
                    </span>
                  ) : expired ? (
                    <span className="lease blocked">Lease from {q.claimed_by} expired. Another agent can take it.</span>
                  ) : q.blocked ? (
                    <span className="lease blocked">{q.blocked}</span>
                  ) : q.status === "ASSIGNED" ? (
                    <span className="lease">ETA {q.eta} min</span>
                  ) : (
                    <span className="lease" style={{ color: "var(--ink-3)" }}>
                      Waiting {ago(q.created_at, now).replace(" ago", "")}
                    </span>
                  )}
                </button>
              );
            })}
          </section>
        );
      })}
    </div>
  );
}

const FEED_FILTERS: { key: string; label: string; kinds: string[] | null }[] = [
  { key: "all", label: "Everything", kinds: null },
  { key: "decisions", label: "Decisions", kinds: ["merged", "triaged", "assigned", "rerouted", "unreachable"] },
  { key: "field", label: "Field", kinds: ["delivered", "road", "road_report", "field_chat", "photo"] },
  { key: "memory", label: "Memory", kinds: ["lesson", "briefing", "reclaimed", "agent_down", "agent_kill", "agent_revive"] },
];

export function FeedPanel({ events, onOpen }: { events: LiveEvent[]; onOpen: (familyId: string) => void }) {
  const [filter, setFilter] = useState("all");
  const kinds = FEED_FILTERS.find((f) => f.key === filter)?.kinds;
  const shown = events.filter((e) => !kinds || kinds.includes(e.kind)).slice(0, 250);
  return (
    <div>
      <div className="feed-filter" role="group" aria-label="Filter the log">
        {FEED_FILTERS.map((f) => (
          <button
            key={f.key}
            type="button"
            className={`btn small${filter === f.key ? " primary" : ""}`}
            aria-pressed={filter === f.key}
            onClick={() => setFilter(f.key)}
          >
            {f.label}
          </button>
        ))}
      </div>
      {shown.length ? (
        <ol className="feed" aria-live="polite">
          {shown.map((e, i) => {
            const fam = (e.data?.family as string) || undefined;
            return (
              <li key={`${e.at}-${i}`} className={`k-${e.kind}`}>
                <time className="num">{clock(e.at)}</time>
                <span>
                  {e.text}
                  {fam && (
                    <>
                      {" "}
                      <button type="button" className="btn quiet small" onClick={() => onOpen(fam)}>
                        Open {fam}
                      </button>
                    </>
                  )}
                </span>
              </li>
            );
          })}
        </ol>
      ) : (
        <p className="empty">Nothing here yet. Events appear the moment an agent writes to the graph.</p>
      )}
    </div>
  );
}

export function AgentsPanel({ agents, onChange }: { agents: AgentInfo[]; onChange: () => void }) {
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
      <p className="empty">
        No agents are running. Start them with <code>python -m reliefnet.workers</code>.
      </p>
    );
  return (
    <div>
      <p className="note">
        Agents never message each other. Each one claims work in the graph with a lease that it must keep renewing.
        Stop a Dispatch agent while it works: its lease runs out and another copy picks up the request.
      </p>
      {agents.map((a) => (
        <div key={a.name} className={`agent-row ${a.state}`}>
          <span className="nm">{a.name}</span>
          {a.state === "dead" ? (
            <button type="button" className="btn small" disabled={busy === a.name} onClick={() => act(a.name, "revive")}>
              Restart
            </button>
          ) : (
            <button
              type="button"
              className="btn small hazard"
              disabled={busy === a.name || a.kind === "learner" || a.kind === "coordinator"}
              onClick={() => act(a.name, "kill")}
            >
              Stop
            </button>
          )}
          <span className="st">
            {a.state === "dead"
              ? "Stopped mid-shift. Its leases will expire."
              : a.state === "stale"
                ? "No heartbeat. The worker process may be down."
                : a.state === "working"
                  ? `Working${a.job ? ` on ${a.job}` : ""}`
                  : "Waiting for work"}
            . {a.processed} finished.
          </span>
          <span />
          <span className="bar" aria-hidden="true">
            <i />
          </span>
        </div>
      ))}
    </div>
  );
}

const LESSON_KIND: Record<string, string> = {
  road_risk: "Changes routes",
  team_skill: "Changes team choice",
  area_risk: "Changes priority",
  general: "For coordinators",
};

export function LessonsPanel({ lessons, onLearn }: { lessons: Lesson[]; onLearn: () => Promise<void> }) {
  const [busy, setBusy] = useState(false);
  return (
    <div>
      <p className="note">
        The Learner reads field reports, delivery times and observations, then writes lessons back into the graph.
        Dispatch and Triage apply lessons above 50% confidence.
      </p>
      <div style={{ padding: "0 16px 12px" }}>
        <button
          type="button"
          className="btn small"
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
          {busy ? "Learning…" : "Run the Learner now"}
        </button>
      </div>
      {lessons.length === 0 && (
        <p className="empty">No lessons yet. They appear after repeated road reports or deliveries.</p>
      )}
      {lessons.map((l) => (
        <div key={l.key} className="lesson">
          <p>{l.text}</p>
          <div className={`conf${l.confidence < 0.5 ? " weak" : ""}`} aria-label={`Confidence ${Math.round(l.confidence * 100)}%`}>
            <i style={{ width: `${Math.round(l.confidence * 100)}%` }} />
          </div>
          <div className="meta">
            <span className="num">{Math.round(l.confidence * 100)}% confident</span>
            <span>{LESSON_KIND[l.kind] ?? l.kind}</span>
            <span>{l.evidence.length} pieces of evidence</span>
            <span>Used in {l.used} decisions</span>
            {l.by === "claude" && <span>Proposed by Claude</span>}
          </div>
        </div>
      ))}
    </div>
  );
}
