import { useMemo, useState, type FormEvent } from "react";
import { api } from "../api";
import { useResource } from "../hooks";
import type { Landmark, LandmarkList } from "../types";
import { Dialog } from "./Dialogs";

const SOURCE_LABEL: Record<string, string> = { hand: "Area list", osm: "OpenStreetMap", app: "Added here" };
const MAX_ROWS = 60;

function errorText(e: unknown) {
  return e instanceof Error ? e.message : String(e);
}

function matches(l: Landmark, q: string) {
  if (!q) return true;
  return l.name.toLowerCase().includes(q) || l.aliases.some((a) => a.includes(q)) || String(l.ward) === q;
}

/** Landmarks of the shared region graph. Coordinators add the local names that people use in messages. */
export function PlacesDialog({ onClose }: { onClose: () => void }) {
  const list = useResource<LandmarkList>("/api/region/landmarks");
  const [query, setQuery] = useState("");
  const [picked, setPicked] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [result, setResult] = useState<string | null>(null);

  const all = list.data?.landmarks ?? [];
  const q = query.trim().toLowerCase();
  const shown = useMemo(() => all.filter((l) => matches(l, q)), [all, q]);
  const current = all.find((l) => l.id === picked) ?? null;
  const hasOsm = all.some((l) => l.source === "osm");

  const done = async (text: string) => {
    setResult(text);
    await list.reload();
  };

  return (
    <Dialog title="Places and local names" onClose={onClose} wide>
      <p>
        Intake finds the place in a message by the name of a landmark or by a local name, for example “sarkari
        aspatal”. Add the names that people in your area use. All organisations share these places.
      </p>
      {adding ? (
        <NewLandmarkForm
          kinds={list.data?.kinds ?? []}
          landmarks={all}
          onCancel={() => setAdding(false)}
          onDone={async (lm) => {
            setAdding(false);
            setPicked(lm.id);
            setQuery(lm.name.toLowerCase());
            await done(`${lm.name} is now a landmark in ward ${lm.ward}. Intake uses it for the next message.`);
          }}
        />
      ) : (
        <>
          <div className="row">
            <div className="field places-search">
              <label htmlFor="places-q">Search landmarks</label>
              <input
                id="places-q"
                className="input"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Type a name, a local name or a ward number"
                autoComplete="off"
              />
            </div>
            <button type="button" className="btn" onClick={() => setAdding(true)}>
              Add a new landmark
            </button>
          </div>
          {list.error && <p className="error">{list.error}</p>}
          {current && (
            <AliasForm
              landmark={current}
              onDone={(alias) => done(`“${alias}” now finds ${current.name}. Intake uses it for the next message.`)}
            />
          )}
          {result && <p className="result-line">{result}</p>}
          <div className="places-list" role="listbox" aria-label="Landmarks">
            {shown.slice(0, MAX_ROWS).map((l) => (
              <button
                key={l.id}
                type="button"
                role="option"
                aria-selected={l.id === picked}
                className={`place-row${l.id === picked ? " on" : ""}`}
                onClick={() => {
                  setPicked(l.id);
                  setResult(null);
                }}
              >
                <span className="place-name">
                  <b>{l.name}</b>
                  <span className="muted">
                    Ward {l.ward}, {l.kind}
                  </span>
                  <span className={`chip src-${l.source ?? "hand"}`}>{SOURCE_LABEL[l.source ?? "hand"]}</span>
                </span>
                {l.aliases.length > 0 && <span className="place-aliases">{l.aliases.join(", ")}</span>}
              </button>
            ))}
            {list.data && shown.length === 0 && <p className="result-line">No landmark has this name.</p>}
          </div>
          <p className="result-line">
            {list.data
              ? shown.length > MAX_ROWS
                ? `The list shows ${MAX_ROWS} of ${shown.length} landmarks. Type more letters to find a landmark.`
                : `${shown.length} of ${all.length} landmarks.`
              : "Loading the landmarks…"}
            {hasOsm && " Places marked OpenStreetMap: © OpenStreetMap contributors (ODbL)."}
          </p>
        </>
      )}
    </Dialog>
  );
}

function AliasForm({ landmark, onDone }: { landmark: Landmark; onDone: (alias: string) => void }) {
  const [alias, setAlias] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (ev: FormEvent) => {
    ev.preventDefault();
    const text = alias.trim();
    if (!text) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api.post<Landmark>(`/api/region/landmarks/${encodeURIComponent(landmark.id)}/aliases`, {
        alias: text,
      });
      setAlias("");
      onDone(r.aliases[r.aliases.length - 1] ?? text);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="place-form" onSubmit={submit}>
      <div className="field">
        <label htmlFor="alias">Add a local name for {landmark.name}</label>
        <div className="row">
          <input
            id="alias"
            className="input"
            value={alias}
            maxLength={60}
            onChange={(e) => setAlias(e.target.value)}
            placeholder="For example: bada mandir"
            autoComplete="off"
          />
          <button type="submit" className="btn primary" disabled={busy || alias.trim().length < 2}>
            Add the name
          </button>
        </div>
      </div>
      <span className="result-line">
        Do not add a word that many places share, such as “mandir” alone. Intake then cannot tell the places apart.
      </span>
      {error && <p className="error">{error}</p>}
    </form>
  );
}

function NewLandmarkForm({
  kinds,
  landmarks,
  onCancel,
  onDone,
}: {
  kinds: string[];
  landmarks: Landmark[];
  onCancel: () => void;
  onDone: (lm: Landmark) => void;
}) {
  const [name, setName] = useState("");
  const [kind, setKind] = useState("landmark");
  const [aliases, setAliases] = useState("");
  const [near, setNear] = useState("");
  const [lat, setLat] = useState("");
  const [lon, setLon] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const sorted = useMemo(() => [...landmarks].sort((a, b) => a.name.localeCompare(b.name)), [landmarks]);

  const pickNear = (id: string) => {
    setNear(id);
    const l = landmarks.find((x) => x.id === id);
    if (l) {
      setLat(l.lat.toFixed(6));
      setLon(l.lon.toFixed(6));
    }
  };

  const submit = async (ev: FormEvent) => {
    ev.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const lm = await api.post<Landmark>("/api/region/landmarks", {
        name: name.trim(),
        kind,
        lat: Number(lat),
        lon: Number(lon),
        aliases: aliases
          .split(",")
          .map((a) => a.trim())
          .filter(Boolean),
      });
      onDone(lm);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  const ready = name.trim().length >= 3 && lat !== "" && lon !== "" && !Number.isNaN(+lat) && !Number.isNaN(+lon);

  return (
    <form className="place-form" onSubmit={submit}>
      <h3>Add a new landmark</h3>
      <div className="field">
        <label htmlFor="lm-name">Name</label>
        <input id="lm-name" className="input" value={name} maxLength={80} onChange={(e) => setName(e.target.value)} />
      </div>
      <div className="field">
        <label htmlFor="lm-kind">Kind</label>
        <select id="lm-kind" className="input" value={kind} onChange={(e) => setKind(e.target.value)}>
          {(kinds.length ? kinds : ["landmark"]).map((k) => (
            <option key={k} value={k}>
              {k}
            </option>
          ))}
        </select>
      </div>
      <div className="field">
        <label htmlFor="lm-aliases">Local names, separated by commas</label>
        <input
          id="lm-aliases"
          className="input"
          value={aliases}
          onChange={(e) => setAliases(e.target.value)}
          placeholder="For example: pani tanki, water tank"
        />
      </div>
      <div className="field">
        <label htmlFor="lm-near">Position: start at a landmark nearby</label>
        <select id="lm-near" className="input" value={near} onChange={(e) => pickNear(e.target.value)}>
          <option value="">Select a landmark</option>
          {sorted.map((l) => (
            <option key={l.id} value={l.id}>
              {l.name} (ward {l.ward})
            </option>
          ))}
        </select>
      </div>
      <div className="row">
        <div className="field">
          <label htmlFor="lm-lat">Latitude</label>
          <input id="lm-lat" className="input num" inputMode="decimal" value={lat} onChange={(e) => setLat(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="lm-lon">Longitude</label>
          <input id="lm-lon" className="input num" inputMode="decimal" value={lon} onChange={(e) => setLon(e.target.value)} />
        </div>
      </div>
      <span className="result-line">
        Change the latitude and longitude to move the point. The point must be inside a ward of the area.
      </span>
      {error && <p className="error">{error}</p>}
      <div className="row">
        <button type="submit" className="btn primary" disabled={busy || !ready}>
          Add the landmark
        </button>
        <button type="button" className="btn quiet" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}
