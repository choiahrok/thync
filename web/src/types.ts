// Shapes of GET /graph.json (schema 1). See docs/architecture.md.
import type { BrainNode, NodeKind } from "../../vendor/brain-atlas/src/types.ts";

export interface ApiNode {
  id: string;
  name: string;
  kind: NodeKind;
  profile: string;
  glow: number;
  roles: string[];
  status: BrainNode["status"];
  detail: Record<string, string | number | boolean>;
}
export interface ApiEvent { at: string; kind: string; text: string; session: string; title: string; profile: string }
export interface ApiUnit {
  id: string; name: string; auto_name?: string; title: string; profile: string; sessions: number; working: boolean; count: number;
}
export interface ApiCard {
  id: string; title: string; sub?: string; column: string; auto_column: string; moved: boolean; note: string; file: string;
  profile: string; updated: string | number; focus: string; tags: string[];
}
export interface ApiGraph {
  schema: number; board: ApiCard[]; generated: number; focus_level: number; handoff: boolean; units: ApiUnit[]; nodes: ApiNode[];
  edges: [string, string][]; activity: ApiEvent[];
}
