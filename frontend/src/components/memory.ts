import type { FamilyPoint, Snapshot, TeamPoint, Trace, TraceEdge } from "../types";

/** One node of a household's memory, drawn around the household on the map. */
export interface MemoryChip {
  id: string;
  /** The edge label, e.g. "DUPLICATE_OF 1.0". */
  edge: string;
  label: string;
  kind: "message" | "request" | "agent" | "lesson";
}

/** The household the Memory layer shows, with the nodes the graph links to it. */
export interface MemoryView {
  family: FamilyPoint;
  chips: MemoryChip[];
  team: TeamPoint | null;
}

/** Distance of the chips from the household, in screen pixels. */
export const MEMORY_RADIUS = 118;
const MAX_CHIPS = 8;

const triagePriority = (e: TraceEdge) => (e.type === "PROCESSED_BY" ? /^priority (\d+)/.exec(e.reason ?? "")?.[1] : undefined);
const lessonName = (key: string) => key.split(":")[1]?.trim() || key;

/** The household's messages, requests, Triage score and lessons, from its trace. */
export function memoryChips(trace: Trace): MemoryChip[] {
  const { nodes, edges } = trace.graph;
  const chips: MemoryChip[] = [];
  const add = (c: MemoryChip) => {
    if (!chips.some((x) => x.id === c.id)) chips.push(c);
  };
  for (const n of nodes.filter((n) => n.label === "Message")) add({ id: n.id, edge: "BECAME", label: n.id, kind: "message" });
  for (const r of trace.requests) {
    const dup = edges.find((e) => e.type === "DUPLICATE_OF" && e.from === r.id);
    if (dup) {
      const score = dup.props?.split(":")[1];
      add({ id: r.id, edge: score ? `DUPLICATE_OF ${score}` : "DUPLICATE_OF", label: `${r.id} · merged`, kind: "request" });
    } else add({ id: r.id, edge: "FOR", label: r.id, kind: "request" });
  }
  // The last Triage score is the one in effect.
  const scored = edges.filter((e) => triagePriority(e)).at(-1);
  if (scored) add({ id: `${scored.to}#score`, edge: "PROCESSED_BY", label: `${scored.to} · ${triagePriority(scored)}`, kind: "agent" });
  for (const e of edges.filter((e) => e.type === "DERIVED_FROM" || e.type === "USED_LESSON")) {
    const key = e.type === "DERIVED_FROM" ? e.from : e.to;
    add({ id: key, edge: e.type, label: `Lesson · ${lessonName(key)}`, kind: "lesson" });
  }
  return chips.slice(0, MAX_CHIPS);
}

/** The team that holds the household's active assignment. */
export function memoryTeam(trace: Trace): string | null {
  const current = trace.current;
  return current?.status === "ASSIGNED" ? current.team : null;
}

/** The Memory view of a trace, placed with the household and team positions of the snapshot. */
export function memoryView(trace: Trace | null | undefined, snapshot: Snapshot | null | undefined): MemoryView | null {
  const family = trace && snapshot?.families.find((f) => f.id === trace.family.id);
  if (!trace || !snapshot || !family) return null;
  const team = memoryTeam(trace);
  return { family, chips: memoryChips(trace), team: (team && snapshot.teams.find((t) => t.name === team)) || null };
}

/** Screen offsets of the chips: evenly round the household, starting at the upper left. */
export function chipOffsets(count: number, radius = MEMORY_RADIUS): [number, number][] {
  return Array.from({ length: count }, (_, i) => {
    const a = ((-140 + (i * 360) / Math.max(count, 1)) * Math.PI) / 180;
    return [Math.cos(a) * radius, Math.sin(a) * radius];
  });
}

/** One plain sentence for each kind of memory the household has. */
export function memorySummary(trace: Trace): string {
  const { nodes, edges } = trace.graph;
  const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? "" : "s"}`;
  const messages = nodes.filter((n) => n.label === "Message").length;
  const parts = [`${plural(messages, "message")} became ${plural(trace.requests.length, "request")}.`];
  for (const e of edges.filter((e) => e.type === "DUPLICATE_OF")) parts.push(`Dedupe merged ${e.from} into ${e.to}.`);
  const scored = edges.filter((e) => triagePriority(e)).at(-1);
  if (scored) parts.push(`${scored.to} scored ${triagePriority(scored)}.`);
  const team = memoryTeam(trace);
  if (team) parts.push(`${team} holds the assignment.`);
  else if (edges.some((e) => e.type === "SERVED")) parts.push("A team delivered help.");
  for (const e of edges.filter((e) => e.type === "DERIVED_FROM")) parts.push(`The ${lessonName(e.from)} lesson cites this household.`);
  return parts.join(" ");
}
