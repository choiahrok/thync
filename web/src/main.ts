// Entry point: build the graph, start the renderer, wire the controls, and poll the server every 2 s.
import { allLobesEnabled } from "../../vendor/brain-atlas/src/lobe-visibility.ts";
import { fetchGraph } from "./api.ts";
import { renderBoard } from "./board.ts";
import { isModalOpen, openDetail } from "./detail.ts";
import { toGraph } from "./layout.ts";
import { reactToChanges, renderLive, resetLive } from "./live.ts";
import { renderPanel, setStatus } from "./panel.ts";
import { openReflex } from "./reflex.ts";
import { renderer } from "./renderer.ts";
import { remember, state } from "./state.ts";
import { colorOf, isHub } from "./style.ts";

/** Redraw everything from state.data. The graph is rebuilt only when its shape changed, so nodes keep their places. */
export function apply(): void {
  const d = state.data;
  const sig = [state.profile, state.showAll, state.days, d.units.map((u) => u.id).join(","), d.nodes.map((n) => n.id).join(","), d.edges.length].join("|");
  if (sig !== state.signature) {
    state.signature = sig;
    state.graph = toGraph();
  } else {
    for (const n of d.nodes) {
      const g = state.graph.idx[n.id];
      if (!g) continue;
      g.glow = n.glow;
      g.status = n.status;
      g.hub = isHub(n);
      g.color = colorOf(n);
    }
  }
  renderPanel();
  renderBoard();
  renderLive();
  reactToChanges();
}

export async function poll(): Promise<void> {
  try {
    const data = await fetchGraph();
    if (!data) {
      setStatus("토큰이 필요해요 · 서버의 ~/.thync/token 내용을 주소 끝 #t= 뒤에 붙여 한 번 여세요");
      return;
    }
    state.data = data;
    apply();
  } catch {
    setStatus("서버에 연결할 수 없음");
  }
}

/** Rebuild from scratch after a change the server made (rename, card edit, ...). */
export async function refresh(): Promise<void> {
  state.signature = "";
  await poll();
}

let lastFocused: string | null = null;
/** Highlight a node on the brain. */
export function focus(id: string): void {
  renderer.setFocusForTest(id);
  lastFocused = id;
}

// --- Brain: a click highlights a node; clicking the highlighted node again opens its details. ---
const canvas = document.querySelector<HTMLCanvasElement>("#graph")!;
let pointerUpAt = -Infinity;
canvas.addEventListener("pointerup", () => { pointerUpAt = performance.now(); });
state.graph = toGraph();
renderer.onSpineDrop = openReflex;
renderer.start(canvas, () => state.graph, {
  idleAutoRotate: true,
  showLobeLabels: true,
  enabledLobes: allLobesEnabled(),
  onChange: () => {
    if (performance.now() - pointerUpAt > 50) return; // onChange also fires on hover; only react to a click
    const id = renderer.getFocusedNode()?.id ?? null;
    if (id !== lastFocused) { lastFocused = id; return; }
    if (id && !isModalOpen()) openDetail(id);
  }
});
renderer.setView({ zoom: 1.25 });

// --- Controls: profile tab, period, show past work. ---
for (const btn of document.querySelectorAll<HTMLButtonElement>("[data-profile]")) {
  btn.classList.toggle("on", btn.dataset.profile === state.profile);
  btn.onclick = () => {
    state.profile = btn.dataset.profile!;
    remember("profile", state.profile);
    document.querySelectorAll("[data-profile]").forEach((b) => b.classList.toggle("on", b === btn));
    resetLive();
    apply();
  };
}
for (const btn of document.querySelectorAll<HTMLButtonElement>("[data-days]")) {
  btn.classList.toggle("on", Number(btn.dataset.days) === state.days);
  btn.onclick = () => {
    state.days = Number(btn.dataset.days);
    remember("days", String(state.days));
    document.querySelectorAll("[data-days]").forEach((b) => b.classList.toggle("on", b === btn));
    resetLive();
    void poll();
  };
}
const showAll = document.querySelector<HTMLInputElement>("#show-all")!;
showAll.checked = state.showAll;
showAll.onchange = () => {
  state.showAll = showAll.checked;
  remember("showAll", state.showAll ? "1" : "0");
  apply();
};

void poll();
setInterval(poll, 2000);
