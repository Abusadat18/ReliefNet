import { PlusIcon } from "lucide-react";
import { useMemo, useState, type FormEvent } from "react";
import { api } from "../api";
import { needLabel, useResource } from "../hooks";
import type { Region, Team, TeamRules } from "../types";
import { Dialog } from "./Dialogs";
import { ErrorLine, ResultLine } from "./kit";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Field, FieldDescription, FieldGroup, FieldLabel, FieldLegend, FieldSet } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { NativeSelect, NativeSelectOptGroup, NativeSelectOption } from "@/components/ui/native-select";
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/utils";

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
          : `${r.name} is off duty.` + (r.rerouted.length ? ` ${r.rerouted.length} assignment(s) went back to Dispatch.` : ""),
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
    <Dialog
      title="Teams"
      onClose={onClose}
      wide
      description={
        view.kind === "list"
          ? `Dispatch gives requests only to teams on duty. A team off duty keeps its history.${isAdmin ? "" : " Only an admin can add or edit a team."}`
          : undefined
      }
      footer={
        view.kind === "list" && isAdmin ? (
          <Button
            onClick={() => {
              setResult(null);
              setView({ kind: "add" });
            }}
          >
            <PlusIcon data-icon="inline-start" />
            Add team
          </Button>
        ) : undefined
      }
    >
      {view.kind === "list" ? (
        <>
          {teams.error && <ErrorLine>{teams.error}</ErrorLine>}
          {teams.data && list.length === 0 && (
            <ResultLine>{isAdmin ? "No teams yet. Add your first team." : "No teams yet. Ask an admin to add a team."}</ResultLine>
          )}
          {list.length > 0 && (
            <div className="overflow-hidden rounded-xl border">
              <Table>
                <TableHeader>
                  <TableRow className="bg-muted/50">
                    <TableHead>Team</TableHead>
                    <TableHead>Supplies</TableHead>
                    <TableHead>Load</TableHead>
                    <TableHead>Members</TableHead>
                    <TableHead>Duty</TableHead>
                    {isAdmin && (
                      <TableHead>
                        <span className="sr-only">Edit</span>
                      </TableHead>
                    )}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {list.map((t) => {
                    const onDuty = t.status === "active";
                    return (
                      <TableRow key={t.name} className={cn(!onDuty && "text-muted-foreground")}>
                        <TableCell className="font-medium">{t.name}</TableCell>
                        <TableCell>
                          <span className="flex flex-wrap gap-1">
                            {(t.supplies ?? []).map((s) => (
                              <Badge key={s} variant="secondary">
                                {needLabel(s)}
                              </Badge>
                            ))}
                          </span>
                        </TableCell>
                        <TableCell className="num">
                          {t.load} / {t.capacity}
                        </TableCell>
                        <TableCell className="max-w-40 truncate">{t.members.length ? t.members.join(", ") : "None"}</TableCell>
                        <TableCell>
                          <label className="flex items-center gap-2 text-xs">
                            <Switch
                              checked={onDuty}
                              disabled={busy === t.name}
                              onCheckedChange={(on) => void setDuty(t, on)}
                              aria-label={`${t.name} on duty`}
                            />
                            {onDuty ? "On duty" : "Off duty"}
                          </label>
                        </TableCell>
                        {isAdmin && (
                          <TableCell>
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => {
                                setResult(null);
                                setView({ kind: "edit", team: t });
                              }}
                            >
                              Edit
                            </Button>
                          </TableCell>
                        )}
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          )}
          {error && <ErrorLine>{error}</ErrorLine>}
          {result && <ResultLine>{result}</ResultLine>}
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

  const toggle = (s: string, on: boolean) => setSupplies((cur) => (on ? [...cur, s] : cur.filter((x) => x !== s)));

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
    <form onSubmit={submit} className="flex flex-col gap-5">
      <h3 className="text-base font-medium">{team ? `Edit ${team.name}` : "Add a team"}</h3>
      <FieldGroup>
        {team ? (
          <ResultLine>You cannot change the name of a team. Assignments and lessons use the name.</ResultLine>
        ) : (
          <Field>
            <FieldLabel htmlFor="team-name">Name</FieldLabel>
            <Input
              id="team-name"
              value={name}
              maxLength={rules?.name_max ?? 40}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Boat Team North"
              autoComplete="off"
              required
            />
          </Field>
        )}
        <FieldSet>
          <FieldLegend variant="label">Supplies</FieldLegend>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            {(rules?.supplies ?? []).map((s) => (
              <Field key={s} orientation="horizontal">
                <Checkbox id={`sup-${s}`} checked={supplies.includes(s)} onCheckedChange={(c) => toggle(s, c === true)} />
                <FieldLabel htmlFor={`sup-${s}`} className="font-normal">
                  {needLabel(s)}
                </FieldLabel>
              </Field>
            ))}
          </div>
        </FieldSet>
        <Field>
          <FieldLabel htmlFor="team-cap">Capacity: active assignments at one time (1 to {max})</FieldLabel>
          <Input
            id="team-cap"
            className="num w-28"
            type="number"
            min={1}
            max={max}
            value={capacity}
            onChange={(e) => setCapacity(Math.round(+e.target.value))}
          />
        </Field>
        <Field>
          <FieldLabel htmlFor="team-base">{team ? "Base (optional)" : "Base"}</FieldLabel>
          <Input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Type to filter landmarks and shelters"
            aria-label="Filter the base list"
            autoComplete="off"
          />
          <NativeSelect id="team-base" value={base} onChange={(e) => setBase(e.target.value)}>
            <NativeSelectOption value="">{team ? "Keep the current base" : "Select a landmark or a shelter"}</NativeSelectOption>
            {landmarks.length > 0 && (
              <NativeSelectOptGroup label="Landmarks">
                {landmarks.map((p) => (
                  <NativeSelectOption key={p.key} value={p.key}>
                    {p.label}
                  </NativeSelectOption>
                ))}
              </NativeSelectOptGroup>
            )}
            {shelters.length > 0 && (
              <NativeSelectOptGroup label="Shelters">
                {shelters.map((p) => (
                  <NativeSelectOption key={p.key} value={p.key}>
                    {p.label}
                  </NativeSelectOption>
                ))}
              </NativeSelectOptGroup>
            )}
          </NativeSelect>
          <FieldDescription>The team starts its routes from the nearest road junction.</FieldDescription>
        </Field>
      </FieldGroup>
      {error && <ErrorLine>{error}</ErrorLine>}
      <div className="flex justify-end gap-2">
        <Button type="button" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" disabled={busy || !rules}>
          {team ? "Save" : "Add team"}
        </Button>
      </div>
    </form>
  );
}
