import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { api } from "../api";
import { useSession } from "../auth";
import { clock, needLabel, useLiveEvents } from "../hooks";
import type { Assignment, ChatTurn, LiveEvent } from "../types";

interface FieldMe {
  user: { id: string; name: string; team: string | null; org: string };
  assignments: Assignment[];
  telegram_linked: boolean;
}

const ACTION_LABEL: Record<string, string> = {
  mark_delivered: "Delivery recorded",
  report_road: "Road report sent",
  report_new_need: "New request logged",
  report_observation: "Observation saved",
  my_assignments: "Checked assignments",
  nearest_shelters: "Found shelters",
  road_status: "Checked roads",
};

export function Field() {
  const { me, config, signOut, refresh } = useSession();
  const [data, setData] = useState<FieldMe | null>(null);
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const [link, setLink] = useState<{ code: string; deep_link: string | null; bot: string | null } | null>(null);
  const [teams, setTeams] = useState<{ name: string }[]>([]);
  const threadRef = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    setData(await api.get<FieldMe>("/api/field/me"));
  }, []);

  useEffect(() => {
    void load();
    api.get<ChatTurn[]>("/api/field/history").then(setTurns);
    api.get<{ name: string }[]>("/api/ops/teams").then(setTeams);
  }, [load]);

  useLiveEvents(
    useCallback(
      (e: LiveEvent) => {
        if (["assigned", "delivered", "rerouted", "road"].includes(e.kind)) void load();
      },
      [load],
    ),
  );

  useEffect(() => {
    threadRef.current?.scrollTo({ top: threadRef.current.scrollHeight, behavior: "smooth" });
  }, [turns]);

  const send = async (msg: string) => {
    const t = msg.trim();
    if (!t || sending) return;
    setSending(true);
    setText("");
    setTurns((x) => [...x, { role: "user", text: t, at: Date.now() }]);
    try {
      const r = await api.post<{ reply: string; actions: ChatTurn["actions"] }>("/api/field/chat", { text: t });
      setTurns((x) => [...x, { role: "agent", text: r.reply, at: Date.now(), actions: r.actions }]);
      void load();
    } catch (e) {
      setTurns((x) => [
        ...x,
        { role: "agent", text: `Not sent: ${e instanceof Error ? e.message : String(e)}. Try again.`, at: Date.now() },
      ]);
    } finally {
      setSending(false);
    }
  };

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    void send(text);
  };

  const photo = async (file: File) => {
    const form = new FormData();
    form.append("file", file);
    setTurns((x) => [...x, { role: "user", text: `Photo: ${file.name}`, at: Date.now() }]);
    try {
      await api.upload("/api/field/photo", form);
      setTurns((x) => [...x, { role: "agent", text: "Photo saved for the coordinators.", at: Date.now() }]);
    } catch (e) {
      setTurns((x) => [...x, { role: "agent", text: `Photo not saved: ${e instanceof Error ? e.message : e}`, at: Date.now() }]);
    }
  };

  const jobs = data?.assignments ?? [];
  const next = jobs[0];
  const team = data?.user.team ?? me?.team;

  return (
    <div className="field-app">
      <header className="field-head">
        <div>
          <b>{team ?? "No team yet"}</b>
          <span>
            {me?.name}, {me?.org_name}
          </span>
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          <button
            type="button"
            className="btn small"
            onClick={async () => setLink(await api.post("/api/field/telegram-link"))}
            disabled={!!data?.telegram_linked}
          >
            {data?.telegram_linked ? "Telegram linked" : "Link Telegram"}
          </button>
          <button type="button" className="btn small" onClick={signOut}>
            Sign out
          </button>
        </div>
      </header>

      {!team ? (
        <section className="next-job none">
          <h2>Join your team</h2>
          <p className="line">Choose the team you are working with today. Assignments for that team will appear here.</p>
          {teams.length === 0 && (
            <p className="line">Your organisation has no teams yet. Ask an admin to add a team.</p>
          )}
          <div className="quick" style={{ flexWrap: "wrap" }}>
            {teams.map((t) => (
              <button
                key={t.name}
                type="button"
                onClick={async () => {
                  await api.post("/api/field/team", { team: t.name });
                  refresh();
                  void load();
                }}
              >
                {t.name}
              </button>
            ))}
          </div>
        </section>
      ) : next ? (
        <section className="next-job" aria-label="Next assignment">
          <h2>
            {next.name || next.family}, ward {next.ward}
          </h2>
          <div className="line">
            {next.landmark ? `Near ${next.landmark}. ` : ""}
            {next.people} people. Needs {next.needs.map(needLabel).join(", ")}.
          </div>
          <div className="route-line">
            {next.id}, ETA {next.eta_min} min{next.roads?.length ? ` via ${next.roads.join(", ")}` : ""}
          </div>
          {jobs.length > 1 && (
            <button type="button" className="more" onClick={() => setShowAll((v) => !v)}>
              {showAll ? "Hide other assignments" : `${jobs.length - 1} more assignment${jobs.length > 2 ? "s" : ""}`}
            </button>
          )}
          {showAll && (
            <div className="jobs">
              {jobs.slice(1).map((j) => (
                <div key={j.id}>
                  <b>{j.name || j.family}</b>, ward {j.ward} {j.landmark}: {j.needs.map(needLabel).join(", ")} ({j.id}, ETA{" "}
                  {j.eta_min} min)
                </div>
              ))}
            </div>
          )}
        </section>
      ) : (
        <section className="next-job none">
          <h2>No assignment right now</h2>
          <div className="line">Dispatch will send the next household here. You can still report roads and new needs.</div>
        </section>
      )}

      <div className="thread" ref={threadRef} aria-live="polite">
        {turns.length === 0 && (
          <div className="bubble agent">
            Tell me what is happening. For example: "done {next?.id ?? "R-123"}, gave water and tablets", "{config?.area.example_road_report}",
            or "7 people on a roof near the school, ward 10".
          </div>
        )}
        {turns.map((t, i) => (
          <div key={i} className={`bubble ${t.role}`}>
            {t.text}
            {t.actions && t.actions.length > 0 && (
              <span className="acts">
                {t.actions.map((a, j) => (
                  <span key={j} className="chip s-DELIVERED">
                    {ACTION_LABEL[a.tool] ?? a.tool}
                  </span>
                ))}
              </span>
            )}
            <time>{clock(t.at)}</time>
          </div>
        ))}
        {sending && <div className="bubble agent">Recording…</div>}
      </div>

      <form className="composer" onSubmit={onSubmit}>
        <div className="quick" aria-label="Quick replies">
          {next && (
            <button type="button" onClick={() => setText(`Done ${next.id}, gave ${next.needs.map(needLabel).join(" and ")}`)}>
              Delivered to {next.name || next.family}
            </button>
          )}
          <button type="button" className="hz" onClick={() => setText(config?.area.example_road_report ?? "")}>
            Road flooded
          </button>
          <button type="button" onClick={() => void send("What are my tasks?")}>
            My tasks
          </button>
          <button type="button" onClick={() => void send("Nearest shelter with space?")}>
            Nearest shelter
          </button>
        </div>
        <div className="compose-row">
          <button type="button" className="icon-btn" aria-label="Send a photo" onClick={() => fileRef.current?.click()}>
            <svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true">
              <path d="M4 7h3l2-2h6l2 2h3v12H4z M12 10a3.5 3.5 0 1 0 0 7a3.5 3.5 0 1 0 0-7" fill="none" stroke="currentColor" strokeWidth="1.8" />
            </svg>
          </button>
          <input
            ref={fileRef}
            type="file"
            accept="image/*"
            capture="environment"
            hidden
            onChange={(e) => e.target.files?.[0] && void photo(e.target.files[0])}
          />
          <label htmlFor="say" className="sr-only">
            Message to the Field agent
          </label>
          <textarea
            id="say"
            rows={1}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void send(text);
              }
            }}
            placeholder="Type in English or Hinglish"
          />
          <button type="submit" className="icon-btn send" aria-label="Send" disabled={sending || !text.trim()}>
            <svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true">
              <path d="M3 20l18-8L3 4v6l12 2l-12 2z" fill="currentColor" />
            </svg>
          </button>
        </div>
      </form>

      {link && (
        <>
          <div className="scrim" onClick={() => setLink(null)} />
          <div className="dialog" role="dialog" aria-modal="true" aria-label="Link Telegram">
            <h2>Link Telegram</h2>
            {link.deep_link ? (
              <p>
                Open <a href={link.deep_link}>@{link.bot}</a> and press Start. The code links automatically.
              </p>
            ) : (
              <p>
                Open the ReliefNet bot in Telegram{config?.telegram_bot ? ` (@${config.telegram_bot})` : ""} and send this
                message:
              </p>
            )}
            <p style={{ fontSize: "var(--step-3)", fontWeight: 850, color: "var(--ink)" }} className="num">
              /link {link.code}
            </p>
            <p>The code works once and expires in 15 minutes. After linking, new assignments arrive in Telegram too.</p>
            <div className="row">
              <button type="button" className="btn primary" onClick={() => setLink(null)}>
                Done
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
