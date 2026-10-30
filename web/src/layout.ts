// Where nodes sit in the brain. Work units are laid out front to back by how focused I am on them,
// following which areas are active during focused work (prefrontal, parietal) and at rest (posterior midline):
//   tier 0  forehead           top workspace session's unit
//   tier 1  upper front, sides other workspace units
//   tier 2  temples, rear top   in progress but less focused, review requests
//   tier 3  back of the head    background (Claude working, I am not)
//   tier 4  cerebellum          units holding only my PRs waiting on review
//   spine                       sessions handed off to Claude
import { CHAOS, KIND_LABEL } from "../../vendor/brain-atlas/src/palette.ts";
import { LOBE_CENTERS, spinePoint } from "../../vendor/brain-atlas/src/shape.ts";
import type { BrainEdge, BrainGraph, BrainNode, LobeName, Vec3 } from "../../vendor/brain-atlas/src/types.ts";
import { isSource, shown, state } from "./state.ts";
import { ROLE_COLOR, ROLE_ORDER, colorOf, cut, isHub, palette, profileColor } from "./style.ts";
import type { ApiNode, ApiUnit } from "./types.ts";

const TIER_SPOTS: Vec3[][] = [
  [{ x: 0, y: 0.28, z: 0.82 }],
  [{ x: -0.46, y: 0.5, z: 0.36 }, { x: 0.46, y: 0.5, z: 0.36 }, { x: 0, y: 0.76, z: 0.05 }],
  [{ x: -0.66, y: -0.06, z: 0.12 }, { x: 0.66, y: -0.06, z: 0.12 }, { x: -0.46, y: 0.46, z: -0.42 }, { x: 0.46, y: 0.46, z: -0.42 },
    { x: -0.62, y: -0.22, z: -0.32 }, { x: 0.62, y: -0.22, z: -0.32 }],
  [{ x: 0, y: 0.12, z: -0.96 }, { x: -0.36, y: 0.16, z: -0.86 }, { x: 0.36, y: 0.16, z: -0.86 }, { x: 0, y: 0.46, z: -0.76 },
    { x: -0.3, y: -0.14, z: -0.86 }, { x: 0.3, y: -0.14, z: -0.86 }],
  [{ x: 0, y: -0.52, z: -0.8 }, { x: -0.3, y: -0.5, z: -0.72 }, { x: 0.3, y: -0.5, z: -0.72 },
    { x: -0.4, y: -0.32, z: -0.62 }, { x: 0.4, y: -0.32, z: -0.62 }, { x: 0, y: -0.3, z: -0.98 }]
];
const TIER_SPREAD = [0.2, 0.15, 0.12, 0.11, 0.1];          // front tiers spread wider
const TIER_NAME = ["", "", "", "백그라운드", "리뷰 기다리는 내 PR"];
const COLLECTION_UNITS = new Set(["sent", "review"]);      // collections of PRs: each PR gets its own spot

function hash(v: string): number {
  let h = 2166136261 >>> 0;
  for (let i = 0; i < v.length; i += 1) { h ^= v.charCodeAt(i); h = Math.imul(h, 16777619) >>> 0; }
  return h;
}

// Scatter around a spot deterministically by id, so a node keeps its place across refreshes.
function placeNear(id: string, at: Vec3, spread: number): Vec3 {
  const h = hash(id);
  const u = ((h & 0xffff) / 0xffff) * Math.PI * 2;
  const v = Math.acos(2 * (((h >>> 16) & 0xffff) / 0xffff) - 1);
  const r = spread * (0.35 + 0.65 * ((Math.imul(h, 31) >>> 0) % 1000) / 1000);
  return { x: at.x + r * Math.sin(v) * Math.cos(u), y: at.y + r * Math.sin(v) * Math.sin(u), z: at.z + r * Math.cos(v) };
}

function nearestLobe(p: Vec3): LobeName {
  let best: LobeName = "parietal", d = Infinity;
  for (const [name, c] of Object.entries(LOBE_CENTERS) as [LobeName, typeof LOBE_CENTERS[LobeName]][]) {
    const dd = (Math.abs(p.x) - Math.abs(c.c.x)) ** 2 + (p.y - c.c.y) ** 2 + (p.z - c.c.z) ** 2;
    if (dd < d) { d = dd; best = name; }
  }
  return best;
}

// When a tier runs out of spots, step around the same spots.
function tierSpot(tier: number, i: number): Vec3 {
  const spots = TIER_SPOTS[tier];
  const base = spots[i % spots.length];
  const lap = Math.floor(i / spots.length);
  if (!lap) return base;
  const a = lap * 2.1;
  return { x: base.x + 0.13 * Math.cos(a), y: base.y + 0.1 * Math.sin(a), z: base.z + 0.06 * lap };
}

// Title color of a unit: its strongest role, else its profile.
export function unitColor(unit: string, ns: ApiNode[]): string {
  const inUnit = ns.filter((n) => n.detail.unit === unit);
  const roles = new Set(inUnit.flatMap((n) => n.roles));
  const role = ROLE_ORDER.find((r) => roles.has(r));
  return role ? ROLE_COLOR[role] : profileColor(state.data.units.find((u) => u.id === unit)?.profile ?? inUnit[0]?.profile ?? "");
}

export function toGraph(): BrainGraph {
  const keep = shown();
  const present = new Set(keep.map((n) => String(n.detail.unit)));
  const units = state.data.units.filter((u) => present.has(u.id));
  const sessionsOf = (u: ApiUnit) => keep.filter((n) => isSource(n) && n.detail.unit === u.id && !n.detail.reflex);
  const lastPrompt = (u: ApiUnit) => Math.max(0, ...sessionsOf(u).map((n) => Number(n.detail.last_at) || 0));
  const tierOf = (u: ApiUnit): number => {
    const ss = sessionsOf(u);
    if (ss.some((n) => n.roles.includes("focus"))) return 1; // split into tiers 0 and 1 by recency below
    if (ss.some((n) => n.roles.includes("running"))) return 3;
    if (u.id === "sent" || (!ss.length && keep.filter((n) => n.detail.unit === u.id).every((n) => n.roles.includes("sent") || n.kind === "repo"))) return 4;
    return 2;
  };
  const tiers = new Map<string, number>();
  units.filter((u) => tierOf(u) === 1).sort((a, b) => lastPrompt(b) - lastPrompt(a))
    .forEach((u, i) => tiers.set(u.id, i === 0 ? 0 : 1));
  for (const u of units) if (!tiers.has(u.id)) tiers.set(u.id, tierOf(u));
  const anchorOf = new Map<string, Vec3>();
  const counter = [0, 0, 0, 0, 0];
  for (const u of units) { const t = tiers.get(u.id)!; anchorOf.set(u.id, tierSpot(t, counter[t]++)); }

  // Handed-off sessions line up along the spine, top to bottom.
  const reflexes = keep.filter((n) => n.kind === "workThread" && n.detail.reflex);
  const spineAt = new Map(reflexes.map((n, i) => [n.id, spinePoint(0.15 + (0.8 * i) / Math.max(1, reflexes.length))]));

  const nodes: BrainNode[] = keep.map((n) => {
    const unit = String(n.detail.unit);
    const tier = tiers.get(unit) ?? 2;
    const hubLike = n.id === unit || isSource(n);
    const spread = TIER_SPREAD[tier] * (hubLike ? 0.45 : 1);
    const own = COLLECTION_UNITS.has(unit) ? tierSpot(tier, hash(n.id) % (TIER_SPOTS[tier].length * 2)) : undefined;
    const p = spineAt.get(n.id) ?? placeNear(n.id, own ?? anchorOf.get(unit) ?? TIER_SPOTS[2][0], own ? 0.05 : spread);
    return {
      id: n.id, name: n.name, title: n.name, kind: n.kind,
      kindLabel: String(n.detail.kind_label ?? KIND_LABEL[n.kind]),
      status: n.status, hub: isHub(n), degree: 0, color: colorOf(n),
      path: `${unit}/${n.name}`, classificationSource: "default", glow: n.glow,
      _3dLobe: p, _lobeName: nearestLobe(p)
    };
  });
  const idx: Record<string, BrainNode> = {};
  const adj: Record<string, string[]> = {};
  for (const n of nodes) { idx[n.id] = n; adj[n.id] = []; }
  const edges: BrainEdge[] = state.data.edges.filter(([a, b]) => idx[a] && idx[b]).map(([a, b]) => ({ a, b }));
  for (const e of edges) { adj[e.a].push(e.b); adj[e.b].push(e.a); }
  for (const n of nodes) n.degree = adj[n.id].length;

  const titled = units.filter((u) => tiers.get(u.id)! <= 3);
  const auto = units.filter((u) => tiers.get(u.id) === 4);
  const clusterTitles = [
    ...titled.map((u) => {
      const t = tiers.get(u.id)!;
      const spot = anchorOf.get(u.id)!;
      return {
        title: cut(u.name, 24),
        sub: cut([TIER_NAME[t], u.name !== u.title ? u.title : u.sessions ? `세션 ${u.sessions}개` : ""].filter(Boolean).join(" · ")),
        at: { x: spot.x, y: spot.y + 0.2, z: spot.z },
        color: unitColor(u.id, keep)
      };
    }),
    ...(auto.length ? [{ title: TIER_NAME[4], sub: cut(auto.map((u) => u.name).join(", "), 40),
      at: { ...TIER_SPOTS[4][0], x: 0.3, y: TIER_SPOTS[4][0].y + 0.12 }, color: ROLE_COLOR.sent }] : []),
    ...(reflexes.length ? [{ title: `맡긴 일 ${reflexes.length}`, sub: cut(reflexes.map((n) => n.name).join(", ")),
      at: { ...spinePoint(0.5), x: 0.12 }, color: ROLE_COLOR.running }] : [])
  ];
  return { nodes, edges, idx, adj, KIND_LABEL, activePalette: palette, activePaletteName: "graphite", CHAOS, clusterTitles };
}
