import { PlusIcon, SearchIcon } from "lucide-react";
import { useMemo, useState, type FormEvent } from "react";
import { api } from "../api";
import { useResource } from "../hooks";
import type { Landmark, LandmarkList } from "../types";
import { Dialog } from "./Dialogs";
import { ErrorLine, ResultLine } from "./kit";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { InputGroup, InputGroupAddon, InputGroupInput } from "@/components/ui/input-group";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";
import { cn } from "@/lib/utils";

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
    <Dialog
      title="Places and"
      serif="local names"
      onClose={onClose}
      wide
      description={
        <>
          Intake finds the place in a message by the name of a landmark or by a local name, for example “sarkari aspatal”.
          Add the names that people in your area use. All organisations share these places.
        </>
      }
    >
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
          <div className="flex items-end gap-2">
            <Field className="flex-1">
              <FieldLabel htmlFor="places-q">Search landmarks</FieldLabel>
              <InputGroup>
                <InputGroupAddon>
                  <SearchIcon />
                </InputGroupAddon>
                <InputGroupInput
                  id="places-q"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Type a name, a local name or a ward number"
                  autoComplete="off"
                />
              </InputGroup>
            </Field>
            <Button variant="outline" onClick={() => setAdding(true)}>
              <PlusIcon data-icon="inline-start" />
              New landmark
            </Button>
          </div>
          {list.error && <ErrorLine>{list.error}</ErrorLine>}
          {current && (
            <AliasForm landmark={current} onDone={(alias) => done(`“${alias}” now finds ${current.name}. Intake uses it for the next message.`)} />
          )}
          {result && <ResultLine>{result}</ResultLine>}
          <div className="flex max-h-80 flex-col gap-1 overflow-y-auto rounded-xl border p-1" role="listbox" aria-label="Landmarks">
            {shown.slice(0, MAX_ROWS).map((l) => (
              <button
                key={l.id}
                type="button"
                role="option"
                aria-selected={l.id === picked}
                className={cn(
                  "flex flex-col gap-0.5 rounded-lg px-3 py-2 text-left hover:bg-muted",
                  l.id === picked && "bg-info-soft hover:bg-info-soft",
                )}
                onClick={() => {
                  setPicked(l.id);
                  setResult(null);
                }}
              >
                <span className="flex flex-wrap items-center gap-2">
                  <b className="text-sm font-medium">{l.name}</b>
                  <span className="text-xs text-muted-foreground">
                    Ward {l.ward}, {l.kind}
                  </span>
                  <Badge variant="outline">{SOURCE_LABEL[l.source ?? "hand"]}</Badge>
                </span>
                {l.aliases.length > 0 && <span className="text-xs text-muted-foreground">{l.aliases.join(", ")}</span>}
              </button>
            ))}
            {list.data && shown.length === 0 && <ResultLine className="px-3 py-2">No landmark has this name.</ResultLine>}
          </div>
          <ResultLine className="text-xs">
            {list.data
              ? shown.length > MAX_ROWS
                ? `The list shows ${MAX_ROWS} of ${shown.length} landmarks. Type more letters to find a landmark.`
                : `${shown.length} of ${all.length} landmarks.`
              : "Loading the landmarks…"}
            {hasOsm && " Places marked OpenStreetMap: © OpenStreetMap contributors (ODbL)."}
          </ResultLine>
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
      const r = await api.post<Landmark>(`/api/region/landmarks/${encodeURIComponent(landmark.id)}/aliases`, { alias: text });
      setAlias("");
      onDone(r.aliases[r.aliases.length - 1] ?? text);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="rounded-xl bg-muted p-3">
      <Field>
        <FieldLabel htmlFor="alias">Add a local name for {landmark.name}</FieldLabel>
        <div className="flex gap-2">
          <Input
            id="alias"
            className="bg-background"
            value={alias}
            maxLength={60}
            onChange={(e) => setAlias(e.target.value)}
            placeholder="For example: bada mandir"
            autoComplete="off"
          />
          <Button type="submit" disabled={busy || alias.trim().length < 2}>
            Add the name
          </Button>
        </div>
        <FieldDescription>
          Do not add a word that many places share, such as “mandir” alone. Intake then cannot tell the places apart.
        </FieldDescription>
      </Field>
      {error && <ErrorLine>{error}</ErrorLine>}
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
    <form onSubmit={submit} className="flex flex-col gap-5">
      <h3 className="text-base font-medium">Add a new landmark</h3>
      <FieldGroup>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field>
            <FieldLabel htmlFor="lm-name">Name</FieldLabel>
            <Input id="lm-name" value={name} maxLength={80} onChange={(e) => setName(e.target.value)} />
          </Field>
          <Field>
            <FieldLabel htmlFor="lm-kind">Kind</FieldLabel>
            <NativeSelect id="lm-kind" value={kind} onChange={(e) => setKind(e.target.value)}>
              {(kinds.length ? kinds : ["landmark"]).map((k) => (
                <NativeSelectOption key={k} value={k}>
                  {k}
                </NativeSelectOption>
              ))}
            </NativeSelect>
          </Field>
        </div>
        <Field>
          <FieldLabel htmlFor="lm-aliases">Local names, separated by commas</FieldLabel>
          <Input id="lm-aliases" value={aliases} onChange={(e) => setAliases(e.target.value)} placeholder="For example: pani tanki, water tank" />
        </Field>
        <Field>
          <FieldLabel htmlFor="lm-near">Position: start at a landmark nearby</FieldLabel>
          <NativeSelect id="lm-near" value={near} onChange={(e) => pickNear(e.target.value)}>
            <NativeSelectOption value="">Select a landmark</NativeSelectOption>
            {sorted.map((l) => (
              <NativeSelectOption key={l.id} value={l.id}>
                {l.name} (ward {l.ward})
              </NativeSelectOption>
            ))}
          </NativeSelect>
        </Field>
        <div className="grid grid-cols-2 gap-4">
          <Field>
            <FieldLabel htmlFor="lm-lat">Latitude</FieldLabel>
            <Input id="lm-lat" className="num" inputMode="decimal" value={lat} onChange={(e) => setLat(e.target.value)} />
          </Field>
          <Field>
            <FieldLabel htmlFor="lm-lon">Longitude</FieldLabel>
            <Input id="lm-lon" className="num" inputMode="decimal" value={lon} onChange={(e) => setLon(e.target.value)} />
          </Field>
        </div>
        <FieldDescription>Change the latitude and longitude to move the point. The point must be inside a ward of the area.</FieldDescription>
      </FieldGroup>
      {error && <ErrorLine>{error}</ErrorLine>}
      <div className="flex justify-end gap-2">
        <Button type="button" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" disabled={busy || !ready}>
          Add the landmark
        </Button>
      </div>
    </form>
  );
}
