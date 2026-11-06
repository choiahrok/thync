/**
 * Shared brain-cloud point construction.
 *
 * Both the Canvas2D renderer (renderer.ts) and the WebGL2 renderer
 * (gl/brain-gl-renderer.ts) build their point cloud from this single pure
 * function so the two renderers operate on byte-identical points (same counts,
 * same generation order, same twPhase/twFreq). No WebGL context, no DOM, no
 * `obsidian` import — importable under node --test and by either renderer.
 *
 * The construction (4200 surface + 360 cerebellum + 28 stem, plus thync's 90-point spine) is
 * the exact body that previously lived in BrainRenderer.buildCloud(); do not
 * change the math, indices, or constants — the Canvas2D A/B self-check guards
 * that the rendered output is unchanged.
 */

import { Brain3D, spinePoint } from "./shape.ts";
import type { SurfacePoint } from "./shape.ts";

/** Build the full brain point cloud (4200 surface + 360 cerebellum + 28 stem + 90 spine). */
export function buildBrainCloud(): SurfacePoint[] {
  const surface = Brain3D.generateSurface(4200, 0.026).map((p, index) => ({
    ...p,
    lobe: Brain3D.lobeFor(p),
    twPhase: (index * 0.731) % (Math.PI * 2),
    twFreq: 0.4 + (index % 9) / 12
  }));
  const cerebellum: SurfacePoint[] = [];
  const golden = Math.PI * (3 - Math.sqrt(5));
  for (let index = 0; index < 360; index += 1) {
    const t = (index + 0.5) / 360;
    const phi = Math.asin(2 * t - 1);
    const theta = (golden * index) % (Math.PI * 2);
    cerebellum.push({
      ...Brain3D.cerebellumPoint(theta, phi),
      lobe: "cerebellum",
      twPhase: (index * 0.91) % (Math.PI * 2),
      twFreq: 0.5 + (index % 5) / 8
    });
  }
  const stem: SurfacePoint[] = [];
  for (let index = 0; index < 28; index += 1) {
    const t = (index / 28) * 0.6;
    const a = ((index * 1.31) % 1) - 0.5;
    stem.push({ ...Brain3D.stemPoint(t, a), lobe: "stem", twPhase: index * 0.55, twFreq: 0.3 });
  }
  // thync: a short spinal cord below the brain stem; work handed off to Claude is placed on it
  const spine: SurfacePoint[] = [];
  for (let index = 0; index < 90; index += 1) {
    const t = index / 90;
    const a = index * 2.399;
    spine.push({ ...spinePoint(t), x: Math.cos(a) * 0.035, lobe: "stem", twPhase: index * 0.37, twFreq: 0.6 });
    spine[index].z += Math.sin(a) * 0.035;
  }
  return [...surface, ...cerebellum, ...stem, ...spine];
}
