import { useMemo, useState, type FormEvent } from "react";
import { api } from "../api";
import { needLabel, useResource } from "../hooks";
import type { Region, Team, TeamRules } from "../types";
import { Dialog } from "./Dialogs";

interface Place {
  key: string;
  label: string;
  lat: number;
  lon: number;
}

type View = { kind: "list" } | { kind: "add" } | { kind: "edit"; team: Team };

function errorText(e: unknown) {
  return e instanceof Error ? e.message : String(e);
}

/** Teams of this organisation. Admins add and edit teams; coordinators and admins set duty. */
export function TeamsDialog({
  isAdmin,
  region,
  startWithForm = false,
  onClose,
}: {
  isAdmin: boolean;
  region: Region | null;
  startWithForm?: boolean;
  onClose: () => void;
}) {
  const teams = useResource<Team[]>("/api/ops/teams", 5000);
  const rules = useResource<TeamRules>("/api/ops/supplies");
  const [view, setView] = useState<View>(startWithForm && isAdmin ? { kind: "add" } : { kind: "list" });
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const places = useMemo<{ landmarks: Place[]; shelters: Place[] }>(() => {
    const byName = (a: Place, b: Place) => a.label.localeCompare(b.label);
    return {
      landmarks: (region?.landmarks ?? [])
        .map((l, i) => ({ key: `lm:${i}`, label: l.ward ? `${l.name} (ward ${l.ward})` : l.name, lat: l.lat, lon: l.lon }))
        .sort(byName),
      shelters: (region?.shelters ?? [])
        .map((s, i) => ({ key: `sh:${i}`, label: s.ward ? `${s.name} (ward ${s.ward})` : s.name, lat: s.lat, lon: s.lon }))
        .sort(byName),
    };
  }, [region]);

  const setDuty = async (t: Team, onDuty: boolean) => {
    if (!onDuty && t.load > 0) {
      const ok = window.confirm(
        `${t.name} has ${t.load} active assignment(s). Dispatch will give them to other teams. Put ${t.name} off duty?`,
      );
      if (!ok) return;
    }
    setBusy(t.name);
    setError(null);
    setResult(null);
    try {
      const r = await api.post<{ name: string; status: string; rerouted: string[] }>(
        `/api/ops/teams/${encodeURIComponent(t.name)}/duty`,
        { on_duty: onDuty },
      );
      setResult(
        r.status === "active"
          ? `${r.name} is on duty. Dispatch can give it new requests.`
          : `${r.name} is off duty.` +
              (r.rerouted.length ? ` ${r.rerouted.length} assignment(s) went back to Dispatch.` : ""),
      );
      await teams.reload();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(null);
    }
  };

  const list = teams.data ?? [];

  return (
    <Dialog title="Teams" onClose={onClose} wide>
      {view.kind === "list" ? (
        <>
          <p>
            Dispatch gives requests only to teams on duty. A team off duty keeps its history.
            {isAdmin ? "" : " Only an admin can add or edit a team."}
          </p>
          {isAdmin && (
            <div className="row">
              <button
                type="button"
                className="btn primary"
                onClick={() => {
                  setResult(null);
                  setView({ kind: "add" });
                }}
              >
                Add team
              </button>
            </div>
          )}
          {teams.error && <p className="error">{teams.error}</p>}
          {teams.data && list.length === 0 && (
            <p>{isAdmin ? "No teams yet. Add your first team." : "No teams yet. Ask an admin to add a team."}</p>
          )}
          {list.length > 0 && (
            <div className="team-table-wrap">
              <table className="team-table">
                <thead>
                  <tr>
                    <th scope="col">Team</th>
                    <th scope="col">Supplies</th>
                    <th scope="col">Load</th>
                    <th scope="col">Members</th>
                    <th scope="col">Duty</th>
                    {isAdmin && (
                      <th scope="col">
                        <span className="sr-only">Edit</span>
                      </th>
                    )}
                  </tr>
                </thead>
                <tbody>
                  {list.map((t) => {
                    const onDuty = t.status === "active";
                    return (
                      <tr key={t.name} className={onDuty ? "" : "off"}>
                        <th scope="row">{t.name}</th>
                        <td>
                          <span className="chips">
                            {(t.supplies ?? []).map((s) => (
                              <span key={s} className="chip">
                                {needLabel(s)}
                              </span>
                            ))}
                          </span>
                        </td>
                        <td className="num">
                          {t.load} of {t.capacity}
                        </td>
                        <td>{t.members.length ? t.members.join(", ") : <span className="muted">None</span>}</td>
                        <td>
                          <label className="toggle duty">
                            <input
                              type="checkbox"
                              role="switch"
                              checked={onDuty}
                              disabled={busy === t.name}
                              onChange={(e) => void setDuty(t, e.target.checked)}
                            />
                            {onDuty ? "On duty" : "Off duty"}
                          </label>
                        </td>
                        {isAdmin && (
                          <td>
                            <button
                              type="button"
                              className="btn small quiet"
                              onClick={() => {
                                setResult(null);
                                setView({ kind: "edit", team: t });
                              }}
                            >
                              Edit
                            </button>
                          </td>
                        )}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          {error && <p className="error">{error}</p>}
          {result && <p className="result-line">{result}</p>}
        </>
      ) : (
        <TeamForm
          team={view.kind === "edit" ? view.team : null}
          rules={rules.data}
          places={places}
          onCancel={() => setView({ kind: "list" })}
          onSaved={(text) => {
            setResult(text);
            setError(null);
            setView({ kind: "list" });
            void teams.reload();
          }}
        />
      )}
    </Dialog>
  );
}

function TeamForm({
  team,
  rules,
  places,
  onCancel,
  onSaved,
}: {
  team: Team | null;
  rules: TeamRules | null;
  places: { landmarks: Place[]; shelters: Place[] };
  onCancel: () => void;
  onSaved: (text: string) => void;
}) {
  const [name, setName] = useState("");
  const [supplies, setSupplies] = useState<string[]>(team?.supplies ?? []);
  const [capacity, setCapacity] = useState(team?.capacity ?? 3);
  const [filter, setFilter] = useState("");
  const [base, setBase] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const all = useMemo(() => [...places.landmarks, ...places.shelters], [places]);
  const match = (p: Place) => !filter.trim() || p.label.toLowerCase().includes(filter.trim().toLowerCase());
  const landmarks = places.landmarks.filter(match);
  const shelters = places.shelters.filter(match);
  const max = rules?.capacity_max ?? 20;

  const toggle = (s: string, on: boolean) =>
    setSupplies((cur) => (on ? [...cur, s] : cur.filter((x) => x !== s)));

  const submit = async (ev: FormEvent) => {
    ev.preventDefault();
    setError(null);
    const place = all.find((p) => p.key === base);
    if (!team && !place) {
      setError("Select a base for the team.");
      return;
    }
    setBusy(true);
    try {
      const where = place ? { lat: place.lat, lon: place.lon } : {};
      if (team) {
        await api.patch<Team>(`/api/ops/teams/${encodeURIComponent(team.name)}`, { supplies, capacity, ...where });
        onSaved(`${team.name} is saved.`);
      } else {
        const t = await api.post<Team>("/api/ops/teams", { name, supplies, capacity, ...where });
        onSaved(`${t.name} is added and on duty. Dispatch can give it requests now.`);
      }
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="team-form" onSubmit={submit}>
      <h3>{team ? `Edit ${team.name}` : "Add a team"}</h3>
      {team ? (
        <p>You cannot change the name of a team. Assignments and lessons use the name.</p>
      ) : (
        <div className="field">
          <label htmlFor="team-name">Name</label>
          <input
            id="team-name"
            className="input"
            value={name}
            maxLength={rules?.name_max ?? 40}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Boat Team North"
            autoComplete="off"
            required
          />
        </div>
      )}
      <fieldset className="field supplies">
        <legend>Supplies</legend>
        <div className="supply-grid">
          {(rules?.supplies ?? []).map((s) => (
            <label key={s} className="toggle">
              <input type="checkbox" checked={supplies.includes(s)} onChange={(e) => toggle(s, e.target.checked)} />
              {needLabel(s)}
            </label>
          ))}
        </div>
      </fieldset>
      <div className="field">
        <label htmlFor="team-cap">Capacity: active assignments at one time (1 to {max})</label>
        <input
          id="team-cap"
          className="input num"
          style={{ width: 110 }}
          type="number"
          min={1}
          max={max}
          value={capacity}
          onChange={(e) => setCapacity(Math.round(+e.target.value))}
        />
      </div>
      <div className="field">
        <label htmlFor="team-base">{team ? "Base (optional)" : "Base"}</label>
        <input
          className="input"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Type to filter landmarks and shelters"
          aria-label="Filter the base list"
          autoComplete="off"
        />
        <select id="team-base" className="input" value={base} onChange={(e) => setBase(e.target.value)}>
          <option value="">{team ? "Keep the current base" : "Select a landmark or a shelter"}</option>
          {landmarks.length > 0 && (
            <optgroup label="Landmarks">
              {landmarks.map((p) => (
                <option key={p.key} value={p.key}>
                  {p.label}
                </option>
              ))}
            </optgroup>
          )}
          {shelters.length > 0 && (
            <optgroup label="Shelters">
              {shelters.map((p) => (
                <option key={p.key} value={p.key}>
                  {p.label}
                </option>
              ))}
            </optgroup>
          )}
        </select>
        <span className="result-line">The team starts its routes from the nearest road junction.</span>
      </div>
      {error && <p className="error">{error}</p>}
      <div className="row">
        <button type="submit" className="btn primary" disabled={busy || !rules}>
          {team ? "Save" : "Add team"}
        </button>
        <button type="button" className="btn quiet" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}
