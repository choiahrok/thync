// Colors and small text helpers.
import { PALETTES } from "../../vendor/brain-atlas/src/palette.ts";
import type { ApiNode } from "./types.ts";

export const palette = PALETTES.graphite;
// A node takes the color of its strongest role (focus > background > review request > my PR), else its profile.
export const ROLE_COLOR: Record<string, string> = { focus: "#ffcf6b", running: "#6be3ff", review: "#ff8a70", sent: "#c9a7ff" };
export const ROLE_ORDER = ["focus", "running", "review", "sent"];
const PROFILE_COLOR: Record<string, string> = { 회사: "#7fa7d6", 개인: "#8fd19a" };

export const profileColor = (profile: string): string => PROFILE_COLOR[profile] ?? "#bcc4cc";
export const colorOf = (n: ApiNode): string =>
  ROLE_COLOR[ROLE_ORDER.find((r) => n.roles.includes(r)) ?? ""] ?? profileColor(n.profile);
export const isHub = (n: ApiNode): boolean => n.glow >= 0.5;

export const cut = (t: string, n = 30): string => (t.length > n ? t.slice(0, n - 1) + "…" : t);
export const clock = (iso: string): string => new Date(iso).toLocaleTimeString([], { hour12: false });
export const epochMs = (v: string | number): number => (typeof v === "number" ? v * 1000 : Date.parse(v));
export const ago = (sec: number): string => {
  const m = Math.round((Date.now() / 1000 - sec) / 60);
  return m < 1 ? "방금" : m < 60 ? `${m}분 전` : m < 1440 ? `${Math.round(m / 60)}시간 전` : `${Math.round(m / 1440)}일 전`;
};
