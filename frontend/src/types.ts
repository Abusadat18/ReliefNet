export type Role = "volunteer" | "coordinator" | "admin";

export interface Me {
  id: string;
  name: string;
  org: string;
  org_name?: string;
  role: Role;
  team: string | null;
}

export interface AppConfig {
  auth_mode: "dev" | "clerk";
  llm: "claude" | "rules";
  models: { fast: string; smart: string } | null;
  embed: string;
  telegram_bot: string | null;
  orgs: { slug: string; name: string }[];
}

export interface Road {
  id: string;
  name: string;
  kind: "road" | "bridge";
  status: "open" | "reported" | "flooded";
  low_lying: boolean;
  coords: [number, number][];
}

export interface Ward {
  num: number;
  name: string;
  bank: string;
  lat: number;
  lon: number;
  polygon: [number, number][];
}

export interface Landmark {
  id: string;
  name: string;
  aliases: string[];
  ward: number;
  kind: string;
  lat: number;
  lon: number;
}

export interface Shelter {
  id: string;
  name: string;
  ward: number;
  capacity: number;
  occupancy: number;
  open: boolean;
  lat: number;
  lon: number;
}

export interface Region {
  roads: Road[];
  wards: Ward[];
  landmarks: Landmark[];
  shelters: Shelter[];
  river: [number, number][];
}

export interface FamilyPoint {
  id: string;
  name: string;
  lat: number;
  lon: number;
  status: "UNSERVED" | "ASSIGNED" | "SERVED";
  people: number;
  elderly: number;
  children: number;
  needs: string[];
  ward: number;
  landmark: string;
  requests: number;
  first_seen: number;
  request: string | null;
  request_status: string | null;
  priority: number | null;
  team: string | null;
  blocked: string | null;
}

export interface RouteLine {
  id: string;
  team: string;
  route: [number, number][];
  eta: number;
  roads: string[];
  priority: number;
}

export interface TeamPoint {
  name: string;
  lat: number;
  lon: number;
  supplies: string[];
  capacity: number;
  status: string;
  load: number;
  delivered: number;
}

export interface Snapshot {
  families: FamilyPoint[];
  routes: RouteLine[];
  teams: TeamPoint[];
  pending: { id: string; lat: number; lon: number; status: string }[];
  at: number;
}

export interface QueueItem {
  id: string;
  status: string;
  priority: number | null;
  summary: string;
  ward: number;
  landmark: string;
  needs: string[];
  team: string | null;
  eta: number | null;
  claimed_by: string | null;
  lease_until: number | null;
  reason: string | null;
  blocked: string | null;
  created_at: number;
  merged: number | null;
  family: string | null;
  name: string | null;
  channel: string;
}

export interface Stats {
  requests: Record<string, number>;
  messages: Record<string, number>;
  families: Record<string, number>;
  metrics: Record<string, number>;
  rates: { messages_per_min: number; assigned_per_min: number; delivered_per_min: number };
  duplicate_dispatches: number;
  dedupe: { precision: number | null; recall: number | null; true_pairs: number; merged_pairs: number };
  lessons_active: number;
  llm: string;
}

export interface LiveEvent {
  org: string;
  kind: string;
  text: string;
  at: number;
  data: Record<string, unknown>;
}

export interface AgentInfo {
  name: string;
  kind: string;
  state: "idle" | "working" | "dead" | "stale";
  job: string | null;
  org: string | null;
  processed: number;
  last_seen: number;
  killed: boolean;
}

export interface Lesson {
  key: string;
  kind: string;
  text: string;
  target: string;
  need: string;
  confidence: number;
  seen: number;
  created_at: number;
  updated_at: number;
  by: string;
  evidence: string[];
  used: number;
}

export interface TimelineStep {
  at: number;
  time: string;
  who: string;
  what: string;
  kind: string;
}

export interface TraceNode {
  id: string;
  label: string;
  title: string;
  status?: string;
  text?: string;
}

export interface Trace {
  family: Record<string, unknown> & { id: string; name?: string; status?: string };
  requests: { id: string; status: string; priority: number | null; team: string | null; channel: string }[];
  current: { id: string; status: string; priority: number | null; team: string | null } | null;
  timeline: TimelineStep[];
  graph: { nodes: TraceNode[]; edges: { from: string; to: string; type: string }[] };
}

export interface Assignment {
  id: string;
  family: string;
  name: string;
  people: number;
  needs: string[];
  landmark: string;
  ward: number;
  priority: number;
  eta_min: number;
  roads: string[];
  summary: string;
}

export interface ChatTurn {
  role: "user" | "agent";
  text: string;
  at: number;
  actions?: { tool: string; input: Record<string, unknown>; result: unknown }[];
}
