// brain-atlas renderer with thync behavior: signal cascades, bursts, and dropping a node on the spine.
import { BrainRenderer } from "../../vendor/brain-atlas/src/renderer.ts";
import { Brain3D, spinePoint } from "../../vendor/brain-atlas/src/shape.ts";
import type { BrainEdge, BrainGraph } from "../../vendor/brain-atlas/src/types.ts";
import { state } from "./state.ts";

const SPINE_HIT_PX = 34;

class ThyncRenderer extends BrainRenderer {
  /** Called with the node id when a node is dragged and dropped near the spine. */
  onSpineDrop: (id: string) => void = () => {};
  private lastGlowSpawn = 0;
  // Keep the parent's pointerup handler (an instance field) before overriding it below.
  private baseUp = (this as unknown as { onPointerUp: (e: PointerEvent) => void }).onPointerUp;

  protected onPointerUp = (event: PointerEvent): void => {
    const drag = this.drag;
    const dropped = drag?.mode === "node" && drag.moved ? drag.nodeId : null;
    const point = this.localPoint(event);
    this.baseUp(event);
    if (dropped && this.nearSpine(point.x, point.y)) this.onSpineDrop(dropped);
  };

  // Project the spine's center line with the same camera as render-core and measure the drop distance.
  private nearSpine(x: number, y: number): boolean {
    const scale = Math.min(this.width, this.height) * 0.32 * this.zoom;
    const project = Brain3D.makeProjector({
      rotX: this.rot.x, rotY: this.rot.y, scale, cx: this.width / 2, cy: this.height / 2 - this.height * 0.04, dist: 3.4 });
    for (let t = 0; t <= 1.0001; t += 0.05) {
      const p = project(spinePoint(t));
      if (Math.hypot(p.sx - x, p.sy - y) < SPINE_HIT_PX) return true;
    }
    return false;
  }

  /** Send a burst of signals from a node to its neighbors. */
  burst(id: string, color = "#ffffff", dur = 1100): void {
    const graph = state.graph;
    const a = graph.idx[id];
    if (!a) return;
    const now = performance.now();
    for (const nb of (graph.adj[id] ?? []).slice(0, 10)) {
      const b = graph.idx[nb];
      if (b) this.signals.push({ id: Math.random(), a, b, born: now, dur, colA: color, colB: a.color });
    }
  }

  protected spawnSignals(now: number, graph: BrainGraph, interLobeEdges: BrainEdge[]): void {
    // Like nerve impulses, an arriving signal may continue to another neighbor; more likely near active work.
    for (const sig of this.signals) {
      if (now - sig.born <= sig.dur || (sig as { relayed?: boolean }).relayed) continue;
      (sig as { relayed?: boolean }).relayed = true;
      const heat = Math.max(sig.a.glow ?? 0, sig.b.glow ?? 0);
      if (Math.random() > 0.25 + heat * 0.5 || this.signals.length > 160) continue;
      const next = (graph.adj[sig.b.id] ?? []).filter((id) => id !== sig.a.id);
      const c = graph.idx[next[Math.floor(Math.random() * next.length)]];
      if (c) this.signals.push({ id: Math.random(), a: sig.b, b: c, born: now, dur: 900 + Math.random() * 700, colA: sig.colB, colB: c.color });
    }
    // Quiet areas still fire now and then.
    if (graph.edges.length && Math.random() < 0.08) {
      const e = graph.edges[Math.floor(Math.random() * graph.edges.length)];
      const a = graph.idx[e.a], b = graph.idx[e.b];
      if (a && b) this.signals.push({ id: Math.random(), a, b, born: now, dur: 1400 + Math.random() * 900, colA: a.color, colB: b.color });
    }
    super.spawnSignals(now, graph, interLobeEdges);
    // Edges touching glowing nodes carry signals more often.
    if (now - this.lastGlowSpawn < 280) return;
    this.lastGlowSpawn = now;
    const hot = graph.edges.filter((e) => (graph.idx[e.a]?.glow ?? 0) >= 0.7 || (graph.idx[e.b]?.glow ?? 0) >= 0.7);
    if (!hot.length) return;
    const e = hot[Math.floor(Math.random() * hot.length)];
    const fromHot = (graph.idx[e.a].glow ?? 0) >= (graph.idx[e.b].glow ?? 0);
    const a = graph.idx[fromHot ? e.a : e.b];
    const b = graph.idx[fromHot ? e.b : e.a];
    this.signals.push({ id: Math.random(), a, b, born: now, dur: 1600, colA: a.color, colB: b.color });
  }
}

export const renderer = new ThyncRenderer();
