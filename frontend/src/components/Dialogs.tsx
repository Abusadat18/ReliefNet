import { useEffect, useState, type ReactNode } from "react";
import { api } from "../api";
import { clock } from "../hooks";
import { Md } from "./Md";

function Dialog({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <>
      <div className="scrim" onClick={onClose} />
      <div className="dialog" role="dialog" aria-modal="true" aria-label={title}>
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h2>{title}</h2>
          <button type="button" className="btn quiet" onClick={onClose}>
            Close
          </button>
        </div>
        {children}
      </div>
    </>
  );
}

interface SimStatus {
  running: boolean;
  sent: number;
  rate_per_min?: number;
  log?: string[];
}

export function DrillDialog({ isAdmin, onClose }: { isAdmin: boolean; onClose: () => void }) {
  const [status, setStatus] = useState<SimStatus | null>(null);
  const [rate, setRate] = useState(20);
  const [autoField, setAutoField] = useState(true);
  const [scenario, setScenario] = useState<"demo" | "flood">("demo");
  const [burst, setBurst] = useState(300);
  const [result, setResult] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = () => api.get<SimStatus>("/api/sim/status").then(setStatus);
  useEffect(() => {
    void refresh();
    const t = window.setInterval(refresh, 2000);
    return () => window.clearInterval(t);
  }, []);

  const run = async (fn: () => Promise<unknown>, done?: (r: unknown) => string) => {
    setBusy(true);
    setResult(null);
    try {
      const r = await fn();
      if (done) setResult(done(r));
      await refresh();
    } catch (e) {
      setResult(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog title="Flood drill" onClose={onClose}>
      <p>
        The drill sends realistic, messy help messages to this organisation, including the same household writing
        twice. Simulated field teams deliver when they arrive, and two teams report NH-12 Bridge flooded about a
        minute in.
      </p>
      <div className="field">
        <label htmlFor="scenario">Scenario</label>
        <select id="scenario" className="input" value={scenario} onChange={(e) => setScenario(e.target.value as "demo" | "flood")}>
          <option value="demo">Demo script: Kumar duplicate, lane 4, Das family, bridge flood</option>
          <option value="flood">Random flood: messages only</option>
        </select>
      </div>
      <div className="field">
        <label htmlFor="rate">Messages per minute: {rate}</label>
        <input id="rate" type="range" min={5} max={240} step={5} value={rate} onChange={(e) => setRate(+e.target.value)} />
      </div>
      <label className="toggle">
        <input type="checkbox" checked={autoField} onChange={(e) => setAutoField(e.target.checked)} />
        Simulate field teams delivering help
      </label>
      <div className="row">
        {status?.running ? (
          <button type="button" className="btn hazard" disabled={busy} onClick={() => run(() => api.post("/api/sim/stop"))}>
            Stop the drill
          </button>
        ) : (
          <button
            type="button"
            className="btn primary"
            disabled={busy}
            onClick={() =>
              run(() => api.post("/api/sim/start", { rate_per_min: rate, auto_field: autoField, scenario }))
            }
          >
            Start the drill
          </button>
        )}
        <span className="result-line num">
          {status ? `${status.running ? "Running" : "Stopped"}, ${status.sent} messages sent` : "Checking…"}
        </span>
      </div>
      {status?.log?.length ? (
        <ul className="result-line" style={{ margin: 0, paddingLeft: 18 }}>
          {status.log.map((l, i) => (
            <li key={i}>{l}</li>
          ))}
        </ul>
      ) : null}

      <hr style={{ border: 0, borderTop: "1px solid var(--rule)", width: "100%", margin: 0 }} />
      <h2 style={{ fontSize: "var(--step-1)" }}>Load test</h2>
      <p>Send many messages at once and watch the agents drain the queue without handling any request twice.</p>
      <div className="row">
        <input
          className="input num"
          style={{ width: 110 }}
          type="number"
          min={10}
          max={5000}
          value={burst}
          onChange={(e) => setBurst(+e.target.value)}
          aria-label="Number of messages"
        />
        <button
          type="button"
          className="btn"
          disabled={busy}
          onClick={() =>
            run(
              () => api.post<{ count: number; ms: number; per_min: number }>("/api/sim/burst", { count: burst }),
              (r) => {
                const x = r as { count: number; ms: number; per_min: number };
                return `Accepted ${x.count} messages in ${x.ms} ms (${x.per_min.toLocaleString()} per minute).`;
              },
            )
          }
        >
          Send {burst} messages
        </button>
      </div>

      {isAdmin && (
        <>
          <hr style={{ border: 0, borderTop: "1px solid var(--rule)", width: "100%", margin: 0 }} />
          <div className="row">
            <button
              type="button"
              className="btn"
              disabled={busy}
              onClick={() =>
                run(() => api.post<{ reopened: string[] }>("/api/sim/reset-roads"), (r) => {
                  const x = r as { reopened: string[] };
                  return x.reopened.length ? `Reopened ${x.reopened.join(", ")}.` : "All roads were already open.";
                })
              }
            >
              Reopen all roads
            </button>
            <button
              type="button"
              className="btn hazard"
              disabled={busy}
              onClick={() => run(() => api.post("/api/sim/reset"), () => "This organisation's memory is empty again.")}
            >
              Erase this organisation's memory
            </button>
          </div>
        </>
      )}
      {result && <p className="result-line">{result}</p>}
    </Dialog>
  );
}

interface Briefing {
  id: string;
  at: number;
  shift: string;
  text: string;
  by: string;
}

export function BriefingDialog({ onClose }: { onClose: () => void }) {
  const [list, setList] = useState<Briefing[] | null>(null);
  const [current, setCurrent] = useState<Briefing | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.get<Briefing[]>("/api/ops/briefings").then((l) => {
      setList(l);
      setCurrent(l[0] ?? null);
    });
  }, []);

  const write = async () => {
    setBusy(true);
    setError(null);
    try {
      const b = await api.post<Briefing>("/api/ops/briefing");
      setCurrent(b);
      setList((l) => [b, ...(l ?? [])]);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog title="Shift handover" onClose={onClose}>
      <div className="row">
        <button type="button" className="btn primary" disabled={busy} onClick={write}>
          {busy ? "Writing the briefing…" : "Write a briefing now"}
        </button>
        {list && list.length > 1 && (
          <select
            className="input"
            style={{ width: "auto" }}
            aria-label="Earlier briefings"
            value={current?.id}
            onChange={(e) => setCurrent(list.find((b) => b.id === e.target.value) ?? null)}
          >
            {list.map((b) => (
              <option key={b.id} value={b.id}>
                {b.shift}, {clock(b.at)}
              </option>
            ))}
          </select>
        )}
      </div>
      {error && <p className="error">{error}</p>}
      {current ? (
        <div>
          <Md text={current.text} />
          <p className="result-line">
            {current.by === "rules" ? "Assembled from the graph" : `Written by ${current.by}`} at {clock(current.at)}. The Shift
            Coordinator also writes one automatically at each shift change.
          </p>
        </div>
      ) : (
        list && <p>No briefing yet for this organisation.</p>
      )}
    </Dialog>
  );
}

export function MessageDialog({ onClose }: { onClose: () => void }) {
  const [text, setText] = useState("");
  const [channel, setChannel] = useState("phone");
  const [sent, setSent] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  return (
    <Dialog title="Add a helpline message" onClose={onClose}>
      <p>Paste or type a message exactly as it came in. The Intake agent reads Hinglish and typos.</p>
      <div className="field">
        <label htmlFor="msg">Message</label>
        <textarea
          id="msg"
          className="input"
          rows={4}
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="e.g. Das family ward 14 near water tanki, 6 log, nani bimar hai"
        />
      </div>
      <div className="field">
        <label htmlFor="ch">Came in by</label>
        <select id="ch" className="input" value={channel} onChange={(e) => setChannel(e.target.value)}>
          <option value="phone">Phone call</option>
          <option value="whatsapp">WhatsApp</option>
          <option value="social">Social media</option>
          <option value="sms">SMS</option>
        </select>
      </div>
      <div className="row">
        <button
          type="button"
          className="btn primary"
          disabled={busy || text.trim().length < 3}
          onClick={async () => {
            setBusy(true);
            try {
              const r = await api.post<{ id: string }>("/api/ops/messages", { text, channel });
              setSent(r.id);
              setText("");
            } finally {
              setBusy(false);
            }
          }}
        >
          Add message
        </button>
        {sent && <span className="result-line">Added as {sent}. Watch it move through the pipeline.</span>}
      </div>
    </Dialog>
  );
}
