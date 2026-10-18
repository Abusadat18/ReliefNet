import type { FamilyPoint } from "../types";

export interface Cluster {
  lat: number;
  lon: number;
  members: FamilyPoint[];
}

/** The worst urgency in a group decides its ring: a high-priority household that waits comes first. */
export function clusterRing(members: FamilyPoint[]): "hazard" | "waiting" | "route" {
  if (members.some((f) => f.status === "UNSERVED" && (f.priority ?? 0) >= 70)) return "hazard";
  if (members.some((f) => f.status === "UNSERVED")) return "waiting";
  return "route";
}

/**
 * Greedy screen-space grouping. `pxPerDeg` converts degrees to pixels at the current zoom,
 * so households closer than `radiusPx` on screen become one count bubble.
 */
export function clusterFamilies(families: FamilyPoint[], pxPerDeg: number, radiusPx = 22): Cluster[] {
  const used = new Set<number>();
  const out: Cluster[] = [];
  const kx = (lat: number) => pxPerDeg * Math.cos((lat * Math.PI) / 180);
  families.forEach((f, i) => {
    if (used.has(i)) return;
    used.add(i);
    const members = [f];
    families.forEach((g, j) => {
      if (used.has(j)) return;
      const dx = (g.lon - f.lon) * kx(f.lat);
      const dy = (g.lat - f.lat) * pxPerDeg;
      if (Math.hypot(dx, dy) < radiusPx) {
        members.push(g);
        used.add(j);
      }
    });
    out.push({
      lat: members.reduce((s, m) => s + m.lat, 0) / members.length,
      lon: members.reduce((s, m) => s + m.lon, 0) / members.length,
      members,
    });
  });
  return out;
}
