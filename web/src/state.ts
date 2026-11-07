// Shared page state. Small view preferences are remembered in localStorage; every access may fail
// (private windows, blocked storage), so they fall back to defaults.
import type { BrainGraph } from "../../vendor/brain-atlas/src/types.ts";
import type { ApiGraph, ApiNode } from "./types.ts";

export function remember(key: string, value: string | null): void {
  try {
    if (value === null) localStorage.removeItem(`thync.${key}`);
    else localStorage.setItem(`thync.${key}`, value);
  } catch { /* keep it for this tab only */ }
}

export function recall(key: string): string | null {
  try { return localStorage.getItem(`thync.${key}`); } catch { return null; }
}

export const state = {
  data: { schema: 1, board: [], generated: 0, focus_level: 0, handoff: false, received: [], units: [], nodes: [], edges: [], activity: [] } as ApiGraph,
  graph: undefined as unknown as BrainGraph, // built by main before the renderer starts
  signature: "",                             // when it changes, the graph is rebuilt from scratch
  days: Number(recall("days")) || 3,          // a short period keeps old work off the brain
  showAll: recall("showAll") === "1",        // also show work that is not in progress
  profile: recall("profile") || "전체",       // 전체 / 회사 / 개인 tab
};

/** Activity sources (sessions, branches, tickets, pages) carry the time of their last activity. */
export const isSource = (n: ApiNode): boolean => n.detail.last_at !== undefined;

export const inProfile = (profile: string): boolean => state.profile === "전체" || profile === state.profile;

/** Units worth a name on the brain: something I focus on, a question waiting on me, or work running without me
 * (background or handed off). Everything else stays a dim dot that shows its name on hover. */
export function notableUnits(nodes: ApiNode[]): Set<string> {
  return new Set(nodes.filter((n) => n.roles.includes("focus") || n.roles.includes("running") || n.detail.waiting
    || (n.kind === "workThread" && n.detail.reflex)).map((n) => String(n.detail.unit)));
}

// Nodes that go on the brain: in-progress work of the selected tab. Repositories shared by several
// work units ("common") are left out.
export const shown = (): ApiNode[] =>
  state.data.nodes.filter((n) => n.detail.unit !== "common" && inProfile(n.profile) && (state.showAll || n.detail.live));
