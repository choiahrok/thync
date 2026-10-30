// The live activity feed and the brain's reactions to change.
//   ignition: a session entering the workspace fires across its whole unit (Dehaene & Changeux 2011)
//   salience: a new review request, finished background work or a changed review state flashes (Menon & Uddin 2010)
//   replay: at rest, recent activity is replayed quickly in order (Carr, Jadhav & Frank 2011)
import { focus } from "./main.ts";
import { renderer } from "./renderer.ts";
import { inProfile, state } from "./state.ts";
import { ROLE_COLOR, clock, cut } from "./style.ts";

const liveList = document.querySelector<HTMLUListElement>("#live")!;
const SALIENCE_COOLDOWN_MS = 30_000;
let lastEventAt = "";
let primed = false;
let prevWorkspace = new Set<string>();
let prevReviews = new Set<string>();
let prevBackground = new Set<string>();
let prevSentState = new Map<string, string>();
const lastSalience = new Map<string, number>();

/** Forget which events were already seen, e.g. after switching tabs or periods. */
export function resetLive(): void {
  lastEventAt = "";
}

export function renderLive(): void {
  const events = state.data.activity.filter((e) => inProfile(e.profile));
  // Nothing bursts on the first load; afterwards each new event bursts from its session.
  if (lastEventAt) for (const e of events) if (e.at > lastEventAt) renderer.burst(e.session);
  lastEventAt = events[0]?.at ?? lastEventAt;
  liveList.replaceChildren(...events.slice(0, 5).map((e, i) => {
    const li = Object.assign(document.createElement("li"), { className: e.kind });
    li.style.opacity = String(1 - i * 0.15);
    li.append(Object.assign(document.createElement("time"), { textContent: clock(e.at) }),
      Object.assign(document.createElement("b"), { textContent: cut(e.title, 22) }),
      Object.assign(document.createElement("span"), { textContent: e.text }));
    li.onclick = () => focus(e.session);
    return li;
  }));
}

export function reactToChanges(): void {
  const nodes = state.data.nodes;
  const ids = (role: string) => new Set(nodes.filter((n) => n.roles.includes(role)).map((n) => n.id));
  const workspace = ids("focus"), reviews = ids("review"), background = ids("running");
  const sentState = new Map(nodes.filter((n) => n.roles.includes("sent")).map((n) => [n.id, String(n.detail.review_state)]));
  if (primed) {
    for (const id of workspace) {
      if (prevWorkspace.has(id)) continue;
      const unit = nodes.find((n) => n.id === id)?.detail.unit;
      for (const n of nodes) if (n.detail.unit === unit) renderer.burst(n.id, ROLE_COLOR.focus, 900);
    }
    const salient = [...reviews].filter((id) => !prevReviews.has(id))
      .concat([...prevBackground].filter((id) => !background.has(id)));
    for (const id of salient) {
      if (performance.now() - (lastSalience.get(id) ?? -Infinity) < SALIENCE_COOLDOWN_MS) continue;
      lastSalience.set(id, performance.now());
      renderer.burst(id, ROLE_COLOR.review, 1500);
    }
    for (const [id, st] of sentState) if (prevSentState.has(id) && prevSentState.get(id) !== st) renderer.burst(id, ROLE_COLOR.sent, 1500);
  }
  prevWorkspace = workspace; prevReviews = reviews; prevBackground = background; prevSentState = sentState; primed = true;
}

let replayAt = 0;
setInterval(() => {
  if (state.data.focus_level > 0.3 || !state.data.activity.length) return;
  const seq = [...state.data.activity].reverse();
  renderer.burst(seq[replayAt++ % seq.length].session, "#b9a6ff", 600);
}, 900);
