import type { LiveEvent, QueueItem } from "../types";

/** The tint of a log row: memory (blue), field (green), lease trouble (orange), coordinator (red), routine. */
export type Tone = "memory" | "field" | "lease" | "hazard" | "plain";

export interface GraphWrite {
  who: string;
  edge: string;
  /** The edge type the filter uses, e.g. "PROCESSED_BY". */
  type: string;
  tone: Tone;
}

const s = (v: unknown) => (v == null ? "?" : String(v));

/**
 * The graph write behind a live event, written as a Cypher pattern. The agents publish an
 * event right after their guarded write, so the pattern names the nodes and edge they made.
 */
export function graphWrite(e: LiveEvent): GraphWrite | null {
  const d = e.data ?? {};
  switch (e.kind) {
    case "message":
      return { who: "Intake", edge: `(:Message {id:'${s(d.id)}', channel:'${s(d.channel)}'})`, type: "Message", tone: "plain" };
    case "intake":
      return { who: "Intake", edge: `(${s(d.message)})-[:BECAME]->(${s(d.id)})`, type: "BECAME", tone: "plain" };
    case "family":
      return { who: "Dedupe", edge: `(${s(d.id)})-[:FOR]->(${s(d.family)})`, type: "FOR", tone: "memory" };
    case "merged":
      return {
        who: "Dedupe",
        edge: `(${s(d.id)})-[:DUPLICATE_OF {score:${s(d.score)}}]->(${s(d.match)})`,
        type: "DUPLICATE_OF",
        tone: "memory",
      };
    case "triaged":
      return { who: "Triage", edge: `(${s(d.id)})-[:PROCESSED_BY {to:'TRIAGED'}]->(Triage)`, type: "PROCESSED_BY", tone: "plain" };
    case "assigned":
      return {
        who: "Dispatch",
        edge: `(${s(d.id)})-[:ASSIGNED_TO {eta_min:${s(d.eta)}}]->(${s(d.team)})`,
        type: "ASSIGNED_TO",
        tone: "plain",
      };
    case "unreachable":
      return { who: "Dispatch", edge: `(${s(d.id)}) released · not_before = now + 15 s`, type: "PROCESSED_BY", tone: "lease" };
    case "reclaimed":
      return {
        who: s(d.agent),
        edge: `(${s(d.id)})-[:PROCESSED_BY {action:'reclaimed'}]->(${s(d.agent)})`,
        type: "PROCESSED_BY",
        tone: "lease",
      };
    case "rerouted":
      return {
        who: "Coordinator",
        edge: `(:Request)-[:REROUTED {road:'${s(d.road)}'}]->(:Team) × ${Array.isArray(d.ids) ? d.ids.length : 0}`,
        type: "REROUTED",
        tone: "hazard",
      };
    case "road":
      return d.road
        ? { who: "Field", edge: `(:Report {id:'${s(d.report)}', road:'${s(d.road)}', status:'${s(d.status)}'})`, type: "Report", tone: d.status === "flooded" ? "hazard" : "field" }
        : null;
    case "road_report":
      return { who: "Field", edge: `(:Volunteer)-[:REPORTED]->(${s(d.report)})`, type: "REPORTED", tone: "field" };
    case "delivered":
      return {
        who: `Field · ${s(d.team)}`,
        edge: `(${s(d.team)})-[:MADE]->(${s(d.delivery)})-[:SERVED]->(${s(d.family)})`,
        type: "SERVED",
        tone: "field",
      };
    case "field_chat":
    case "photo":
      return { who: "Field", edge: `(:Volunteer)-[:SAID]->(${s(d.observation)})`, type: "SAID", tone: "field" };
    case "lesson":
      return { who: "Learner", edge: `(:Lesson {key:'${s(d.key)}'})-[:DERIVED_FROM]->(evidence)`, type: "DERIVED_FROM", tone: "memory" };
    case "briefing":
      return { who: "Coordinator", edge: `(:Briefing {id:'${s(d.id)}'})`, type: "Briefing", tone: "memory" };
    case "team":
      return { who: "Coordinator", edge: `(:Team {name:'${s(d.team)}'}) ${s(d.change)}`, type: "Team", tone: "plain" };
    case "landmark":
      return { who: "Coordinator", edge: "(:Landmark) in the region graph", type: "Landmark", tone: "plain" };
    default:
      return null;
  }
}

/** The receipt for a queue row: the edge that put the request at its current step. */
export function queueReceipt(q: QueueItem): { edge: string; text: string } {
  if (q.status === "ASSIGNED") return { edge: "ASSIGNED_TO", text: `${q.team ?? "team"}${q.eta != null ? ` · ETA ${q.eta} min` : ""}` };
  if (q.merged) return { edge: "DUPLICATE_OF", text: `${q.merged} message${q.merged > 1 ? "s" : ""} merged` };
  const by: Record<string, string> = { NEW: "Intake", RESOLVED: "Dedupe", TRIAGED: "Triage" };
  return { edge: "PROCESSED_BY", text: by[q.status] ?? q.status.toLowerCase() };
}

export const EDGE_FILTERS = ["PROCESSED_BY", "DUPLICATE_OF", "ASSIGNED_TO", "SERVED"] as const;
