// The thync cloud: wanders the screen in its own small transparent window and shows what thync sees.
//   waiting  a session asks me something: stops, pushes its shades up, bounces, shows the question; notifies once
//   done     a long or background run just ended: stops, hops, shows which one; notifies once
//   working  Claude works on its own: lightning flickers, it moves faster, a count shows
//   focus    I am working: calm cyan glow
//   idle     nothing going on: shades on, slow drift
//   offline  the hub does not answer: grey, sinks, dozes; it starts the hub once
// Click opens thync (and its answer window when a question waits); drag moves it; hovering stops it.
const { invoke } = window.__TAURI__.core;
const tw = window.__TAURI__.window;
const dpi = window.__TAURI__.dpi || tw;
const win = tw.getCurrentWindow();

const W = 260, H = 200, CX = 130, CY = 132;           // canvas size and the cloud's center
const canvas = document.getElementById("pet");
const ctx = canvas.getContext("2d");
const ratio = window.devicePixelRatio || 1;
canvas.width = W * ratio;
canvas.height = H * ratio;
ctx.scale(ratio, ratio);

const LOOK = {
  idle: { aura: "#9fc4ff", speed: 22 },
  focus: { aura: "#5fe3ff", speed: 30 },
  working: { aura: "#8f7bff", speed: 70 },
  waiting: { aura: "#ffcf6b", speed: 0 },
  done: { aura: "#7ee08a", speed: 0 },
  offline: { aura: "#7a8290", speed: 0 },
};

let status = null;          // last /status.json
let mood = "offline";
let seenQuestions = new Set();
let primed = false;         // no notifications for questions already waiting when the app starts
let hubStarted = false;
let hovered = false, dragging = false, pausedUntil = 0;
let pos = null, target = null, area = null;
// Where the tail points: away from the way the cloud moves, eased so it swings instead of snapping.
let tailAngle = Math.PI * 0.92, tailWant = Math.PI * 0.92;
// The tail peeks out from behind only while the cloud travels on a slant, and fades otherwise.
let steppedAt = 0, tailShown = 0, slant = 0;
let blinkAt = performance.now() + 2500;

// A run counts as finished when a session goes from working to its turn ended. Short interactive turns end every
// minute or so, so only background runs or runs that worked for LONG_RUN_MS without a break are announced.
const LONG_RUN_MS = 2 * 60 * 1000, DONE_MS = 6000;
let working = new Map();    // session -> { since, background } while Claude works on it
let done = null;            // { session: last finished, more: how many others finished with it, until }

// --- status ---------------------------------------------------------------------------------------------
async function poll() {
  try {
    status = await invoke("status");
  } catch {
    status = null;
    if (!hubStarted) { hubStarted = true; invoke("start_hub").catch(() => {}); }
  }
  const before = mood;
  if (status) noticeFinished();
  mood = currentMood();
  if (status) {
    const ids = new Set(status.waiting.map((w) => w.session));
    for (const w of status.waiting) {
      if (primed && !seenQuestions.has(w.session)) {
        invoke("notify", { title: "thync · 선택을 기다려요", body: `${w.host || "이 Mac"} · ${w.title}\n${w.question}` }).catch(() => {});
      }
    }
    seenQuestions = ids;
    primed = true;
  }
  if (mood !== before) target = null;   // pick a new place to go for the new mood
}

function currentMood() {
  if (!status) return "offline";
  if (status.waiting.length) return "waiting";
  if (done && performance.now() < done.until) return "done";
  return status.working > 0 ? "working" : status.focus > 0 ? "focus" : "idle";
}

// Sessions that were working on the last poll and have ended their turn now. While the hub is down nothing changes.
function noticeFinished() {
  const now = Date.now(), next = new Map(), finished = [];
  for (const s of status.sessions || []) {
    const run = working.get(s.session);
    if (s.state === "working") {
      next.set(s.session, { since: run ? run.since : now, background: s.background || Boolean(run && run.background) });
    } else if (s.state === "ended" && run && (run.background || now - run.since >= LONG_RUN_MS)) {
      finished.push(s);
    }
  }
  working = next;
  for (const s of finished) {
    invoke("notify", { title: "thync · 끝났어요", body: `${s.host || "이 Mac"} · ${s.title}` }).catch(() => {});
  }
  if (finished.length) {
    done = { session: finished[finished.length - 1], more: finished.length - 1, until: performance.now() + DONE_MS };
  }
}

// --- moving around --------------------------------------------------------------------------------------
async function screenArea() {
  const m = await tw.currentMonitor();
  if (!m) return { x0: 0, y0: 30, x1: 1200, y1: 700 };
  const s = m.scaleFactor;
  const x = m.position.x / s, y = m.position.y / s, w = m.size.width / s, h = m.size.height / s;
  // Keep clear of the menu bar on top and the Dock below.
  return { x0: x + 4, y0: y + 30, x1: x + w - W - 4, y1: y + h - H - 70 };
}

async function pickTarget(now) {
  area = await screenArea();
  target = {
    x: area.x0 + Math.random() * Math.max(1, area.x1 - area.x0),
    y: area.y0 + Math.random() * Math.max(1, area.y1 - area.y0),
  };
  pausedUntil = now + 800 + Math.random() * 3500;
}

let lastMove = 0;
async function move(now) {
  if (!pos || dragging || hovered || now < pausedUntil) return;
  const speed = LOOK[mood].speed;
  if (!speed) return;
  if (!target) { await pickTarget(now); return; }
  const dx = target.x - pos.x, dy = target.y - pos.y, d = Math.hypot(dx, dy);
  const dt = Math.min(0.1, (now - lastMove) / 1000);
  lastMove = now;
  if (d < 2) { target = null; pausedUntil = now + 1500 + Math.random() * 5000; return; }
  const step = Math.min(d, speed * dt);
  pos.x += (dx / d) * step;
  pos.y += (dy / d) * step;
  tailWant = Math.atan2(-dy * 0.6, -dx);
  steppedAt = now;
  slant = Math.abs(dx * dy) / (d * d) * 2;     // 1 at 45 degrees, 0 when going straight across or up and down
  await win.setPosition(new dpi.LogicalPosition(Math.round(pos.x), Math.round(pos.y)));
}

// --- drawing --------------------------------------------------------------------------------------------
const PUFFS = [[-40, 10, 25], [-16, -8, 33], [18, -12, 30], [44, 6, 24], [4, 14, 30], [-24, 18, 22], [30, 20, 20]];

function cloudPath(cx, cy, k = 1) {
  const p = new Path2D();
  for (const [x, y, r] of PUFFS) { p.moveTo(cx + x * k + r * k, cy + y * k); p.arc(cx + x * k, cy + y * k, r * k, 0, Math.PI * 2); }
  return p;
}

function drawCloud(t) {
  const look = LOOK[mood];
  const bob = mood === "waiting" ? -Math.abs(Math.sin(t / 180)) * 10 : mood === "done" ? -Math.abs(Math.sin(t / 130)) * 14
    : mood === "offline" ? 6 : Math.sin(t / 700) * 3;
  const cx = CX, cy = CY + bob;
  const grey = mood === "offline";

  // shadow on the "ground"
  ctx.fillStyle = "rgba(0,0,0,0.18)";
  ctx.beginPath(); ctx.ellipse(cx, CY + 52, 52 - bob, 7, 0, 0, Math.PI * 2); ctx.fill();

  drawTail(cx, cy, t, grey);

  // aura
  ctx.save();
  ctx.shadowColor = look.aura;
  ctx.shadowBlur = mood === "waiting" ? 26 + Math.sin(t / 150) * 8 : mood === "working" ? 22 : 14;
  const body = cloudPath(cx, cy);
  const g = ctx.createLinearGradient(0, cy - 45, 0, cy + 45);
  if (grey) { g.addColorStop(0, "#c9ced6"); g.addColorStop(1, "#8a919c"); }
  else { g.addColorStop(0, "#ffffff"); g.addColorStop(0.55, "#e8f1ff"); g.addColorStop(1, "#b9cff2"); }
  ctx.fillStyle = g;
  ctx.fill(body);
  ctx.restore();

  // rim light and inner sheen
  ctx.save();
  ctx.clip(body);
  const sheen = ctx.createLinearGradient(cx - 60, cy - 50, cx + 30, cy + 10);
  sheen.addColorStop(0, "rgba(255,255,255,0.65)"); sheen.addColorStop(0.5, "rgba(255,255,255,0)");
  ctx.fillStyle = sheen;
  ctx.fillRect(cx - 80, cy - 60, 160, 120);
  ctx.fillStyle = hexA(look.aura, 0.18);
  ctx.fillRect(cx - 80, cy + 18, 160, 40);
  ctx.restore();

  if (mood === "working") drawBolts(cx, cy, t);
  drawFace(cx, cy, t);
  if (mood === "offline") drawZzz(cx, cy, t);
  if (status && status.reviews > 0 && mood !== "offline") drawLetter(cx, cy, t);
  if (mood === "working" && status) badge(cx + 52, cy - 34, `⚡${status.working}`, look.aura);
  if (mood === "done") drawCheck(cx, cy, t);
  if (status && status.waiting.length > 1) badge(cx + 52, cy - 34, `${status.waiting.length}`, look.aura);
}

// A round, fluffy pompom on the cloud's back, like a bunny tail: it sits on the side away from where the cloud
// goes, wiggles faster while moving, and sags a little when the hub is down.
const POM = [[0, 0, 13], [-8, -7, 7], [8, -7, 7], [-10, 3, 6.5], [10, 3, 6.5], [-5, 10, 6.5], [5, 10, 6.5], [0, -11, 6]];
function drawTail(cx, cy, t, grey) {
  tailShown += ((t - steppedAt < 400 && slant > 0.55 ? 1 : 0) - tailShown) * 0.06;
  if (tailShown < 0.02) return;
  let diff = tailWant - tailAngle;
  diff = Math.atan2(Math.sin(diff), Math.cos(diff));
  tailAngle += diff * 0.05;
  const wiggle = grey ? 0 : LOOK[mood].speed ? Math.sin(t / 110) * 2.5 : Math.sin(t / 450) * 1.5;
  const side = Math.cos(tailAngle) < 0 ? -1 : 1;           // left or right of the body
  const x = cx + side * 62 + wiggle, y = cy + 18 + (grey ? 6 : 0) + Math.sin(tailAngle) * 6;   // half tucked behind
  ctx.save();
  ctx.shadowColor = LOOK[mood].aura;
  ctx.shadowBlur = 8;
  ctx.globalAlpha = tailShown;
  // One shape, one fill: a soft round ball with a fluffy edge, no seams between the puffs.
  const ball = new Path2D();
  for (const [dx, dy, r] of POM) { ball.moveTo(x + dx + r, y + dy); ball.arc(x + dx, y + dy, r, 0, Math.PI * 2); }
  const g = ctx.createRadialGradient(x - 5, y - 6, 2, x, y, 17);
  if (grey) { g.addColorStop(0, "#dde0e6"); g.addColorStop(1, "#8f96a1"); }
  else { g.addColorStop(0, "#ffffff"); g.addColorStop(0.6, "#f1f6ff"); g.addColorStop(1, "#c9daf5"); }
  ctx.fillStyle = g;
  ctx.fill(ball, "nonzero");
  ctx.restore();
}

function drawFace(cx, cy, t) {
  const eyesY = cy - 2;
  if (mood === "waiting") {
    // shades pushed up, eyes wide
    shades(cx, cy - 34, 0.85, -0.08);
    const blink = t > blinkAt && t < blinkAt + 120;
    if (t > blinkAt + 120) blinkAt = t + 2000 + Math.random() * 3000;
    ctx.fillStyle = "#1d2433";
    for (const dx of [-15, 15]) {
      ctx.beginPath(); ctx.ellipse(cx + dx, eyesY, 6, blink ? 1 : 8, 0, 0, Math.PI * 2); ctx.fill();
      if (!blink) { ctx.fillStyle = "#fff"; ctx.beginPath(); ctx.arc(cx + dx + 2, eyesY - 3, 2.2, 0, Math.PI * 2); ctx.fill(); ctx.fillStyle = "#1d2433"; }
    }
    ctx.beginPath(); ctx.ellipse(cx, cy + 16, 5, 6, 0, 0, Math.PI * 2); ctx.fill();   // a small "o"
    return;
  }
  if (mood === "offline") {
    shades(cx, eyesY, 1, 0.18);            // shades slipped
    ctx.strokeStyle = "#4b5260"; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.moveTo(cx - 8, cy + 16); ctx.lineTo(cx + 8, cy + 16); ctx.stroke();
    return;
  }
  shades(cx, eyesY, 1, 0);
  if (mood === "done") {   // a wide grin
    ctx.strokeStyle = "#1d2433"; ctx.lineWidth = 2.4; ctx.lineCap = "round";
    ctx.beginPath(); ctx.arc(cx, cy + 6, 13, 0.15 * Math.PI, 0.85 * Math.PI); ctx.stroke();
    return;
  }
  // a small confident smile
  ctx.strokeStyle = "#1d2433"; ctx.lineWidth = 2.2; ctx.lineCap = "round";
  ctx.beginPath(); ctx.arc(cx + 4, cy + 10, 9, 0.25 * Math.PI, 0.7 * Math.PI); ctx.stroke();
}

// Wraparound shades: two dark lenses on a bar, with a light streak.
function shades(cx, y, k, tilt) {
  ctx.save();
  ctx.translate(cx, y);
  ctx.rotate(tilt);
  ctx.scale(k, k);
  ctx.fillStyle = "#121722";
  ctx.beginPath(); ctx.roundRect(-34, -6, 68, 4, 2); ctx.fill();
  for (const dx of [-17, 17]) {
    ctx.beginPath();
    ctx.moveTo(dx - 15, -5); ctx.lineTo(dx + 15, -5); ctx.quadraticCurveTo(dx + 14, 10, dx, 11); ctx.quadraticCurveTo(dx - 14, 10, dx - 15, -5);
    ctx.fill();
  }
  const streak = ctx.createLinearGradient(-30, -4, 30, 8);
  streak.addColorStop(0, "rgba(140,200,255,0)"); streak.addColorStop(0.45, "rgba(140,200,255,0.55)"); streak.addColorStop(0.6, "rgba(140,200,255,0)");
  ctx.fillStyle = streak;
  for (const dx of [-17, 17]) { ctx.beginPath(); ctx.moveTo(dx - 9, -3); ctx.lineTo(dx - 3, -3); ctx.lineTo(dx - 10, 8); ctx.lineTo(dx - 14, 8); ctx.fill(); }
  ctx.restore();
}

function drawBolts(cx, cy, t) {
  const phase = Math.floor(t / 140) % 6;
  if (phase > 2) return;
  ctx.save();
  ctx.strokeStyle = "#ffe66b"; ctx.shadowColor = "#ffe66b"; ctx.shadowBlur = 10; ctx.lineWidth = 2.5; ctx.lineJoin = "round";
  const side = phase === 1 ? -1 : 1;
  const x = cx + side * 58, y = cy + 6;
  ctx.beginPath(); ctx.moveTo(x, y - 14); ctx.lineTo(x - 5 * side, y); ctx.lineTo(x + 3 * side, y); ctx.lineTo(x - 3 * side, y + 16); ctx.stroke();
  ctx.restore();
}

// A check mark that pops in beside the cloud.
function drawCheck(cx, cy, t) {
  const k = Math.min(1, (DONE_MS - (done.until - t)) / 250);
  ctx.save();
  ctx.translate(cx + 56, cy - 30);
  ctx.scale(k, k);
  ctx.fillStyle = LOOK.done.aura;
  ctx.beginPath(); ctx.arc(0, 0, 12, 0, Math.PI * 2); ctx.fill();
  ctx.strokeStyle = "#10301a"; ctx.lineWidth = 3; ctx.lineCap = "round"; ctx.lineJoin = "round";
  ctx.beginPath(); ctx.moveTo(-5, 0); ctx.lineTo(-1, 4); ctx.lineTo(6, -4); ctx.stroke();
  ctx.restore();
}

function drawZzz(cx, cy, t) {
  ctx.fillStyle = "rgba(220,226,235,0.8)";
  ctx.font = "600 13px -apple-system, sans-serif";
  for (let i = 0; i < 3; i += 1) {
    const p = ((t / 1600) + i / 3) % 1;
    ctx.globalAlpha = 1 - p;
    ctx.fillText("z", cx + 40 + p * 18, cy - 30 - p * 30);
  }
  ctx.globalAlpha = 1;
}

function drawLetter(cx, cy, t) {
  const a = t / 900;
  const x = cx + Math.cos(a) * 70, y = cy - 20 + Math.sin(a) * 18;
  ctx.fillStyle = "#ff8a70"; ctx.strokeStyle = "#fff"; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.roundRect(x - 8, y - 6, 16, 12, 2); ctx.fill();
  ctx.beginPath(); ctx.moveTo(x - 8, y - 6); ctx.lineTo(x, y + 1); ctx.lineTo(x + 8, y - 6); ctx.stroke();
}

function badge(x, y, text, color) {
  ctx.font = "700 11px -apple-system, sans-serif";
  const w = ctx.measureText(text).width + 10;
  ctx.fillStyle = color;
  ctx.beginPath(); ctx.roundRect(x - w / 2, y - 9, w, 18, 9); ctx.fill();
  ctx.fillStyle = "#111";
  ctx.textAlign = "center"; ctx.textBaseline = "middle";
  ctx.fillText(text, x, y + 0.5);
  ctx.textAlign = "start"; ctx.textBaseline = "alphabetic";
}

// Speech bubble: the waiting question, or on hover what the cloud is showing.
function drawBubble() {
  let lines = null;
  if (mood === "waiting") {
    const w = status.waiting[0];
    lines = [`? ${w.host || "이 Mac"} · ${w.title}`, w.question, w.answerable ? "눌러서 답하기" : "세션에서 답해 주세요"];
  } else if (mood === "done") {
    const s = done.session;
    lines = [`✓ ${s.host || "이 Mac"} · ${s.title}`, done.more ? `외 ${done.more}개도 끝났어요` : "Claude 가 일을 마쳤어요",
      "눌러서 thync 열기"];
  } else if (hovered) {
    lines = mood === "offline" ? ["thync 허브가 꺼져 있어요", "메뉴 막대에서 켤 수 있어요"]
      : [`집중 ${status.focus} · Claude 작업 ${status.working} · 리뷰 ${status.reviews}`,
        ...(status.hosts || []).map((h) => `${h.name} ${h.ok ? "연결됨" : "끊김"}`), "눌러서 thync 열기"];
  }
  if (!lines) return;
  ctx.font = "12px -apple-system, sans-serif";
  const wrapped = lines.flatMap((l, i) => (i === 1 && mood === "waiting" ? wrap(l, 228, 2) : [cut(l, 228)]));
  const h = wrapped.length * 16 + 12;
  ctx.fillStyle = "rgba(18,22,32,0.92)";
  ctx.strokeStyle = hexA(LOOK[mood].aura, 0.8);
  ctx.lineWidth = 1;
  ctx.beginPath(); ctx.roundRect(8, 6, 244, h, 10); ctx.fill(); ctx.stroke();
  wrapped.forEach((l, i) => {
    ctx.fillStyle = i === 0 ? LOOK[mood].aura : i === wrapped.length - 1 && wrapped.length > 1 ? "#9aa3b2" : "#e9eef6";
    ctx.font = i === 0 ? "600 12px -apple-system, sans-serif" : "12px -apple-system, sans-serif";
    ctx.fillText(l, 16, 22 + i * 16);
  });
}

function cut(text, max) {
  if (ctx.measureText(text).width <= max) return text;
  while (text.length && ctx.measureText(text + "…").width > max) text = text.slice(0, -1);
  return text + "…";
}

function wrap(text, max, maxLines) {
  const out = [];
  let line = "";
  for (const ch of text) {
    if (ctx.measureText(line + ch).width > max) { out.push(line); line = ""; if (out.length === maxLines) break; }
    line += ch;
  }
  if (out.length < maxLines && line) out.push(line);
  if (out.length === maxLines && text.length > out.join("").length) out[maxLines - 1] = cut(out[maxLines - 1] + "…", max);
  return out;
}

function hexA(hex, a) {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${n >> 16},${(n >> 8) & 255},${n & 255},${a})`;
}

// --- input ----------------------------------------------------------------------------------------------
let down = null;
canvas.addEventListener("pointerenter", () => { hovered = true; });
canvas.addEventListener("pointerleave", () => { hovered = false; });
canvas.addEventListener("pointerdown", (e) => { down = { x: e.screenX, y: e.screenY }; });
canvas.addEventListener("pointermove", async (e) => {
  if (!down || dragging || Math.hypot(e.screenX - down.x, e.screenY - down.y) < 4) return;
  dragging = true;
  down = null;
  try { await win.startDragging(); } finally {
    const p = await win.outerPosition(), s = await win.scaleFactor();
    pos = { x: p.x / s, y: p.y / s };
    target = null;
    pausedUntil = performance.now() + 4000;
    dragging = false;
  }
});
canvas.addEventListener("pointerup", () => {
  if (down) invoke("open_thync").catch(() => {});
  down = null;
});

// --- loop -----------------------------------------------------------------------------------------------
async function start() {
  const p = await win.outerPosition(), s = await win.scaleFactor();
  pos = { x: p.x / s, y: p.y / s };
  if (pos.x === 0 && pos.y === 0) {             // first launch: start near the bottom right
    const a = await screenArea();
    pos = { x: a.x1 - 40, y: a.y1 - 10 };
    await win.setPosition(new dpi.LogicalPosition(Math.round(pos.x), Math.round(pos.y)));
  }
  await poll();
  setInterval(poll, 2000);
  let moving = false;
  const frame = (t) => {
    if (mood === "done" && t >= done.until) { mood = currentMood(); target = null; }
    ctx.clearRect(0, 0, W, H);
    drawCloud(t);
    drawBubble();
    if (!moving && t - lastMove > 33) {
      moving = true;
      if (t - lastMove > 200) lastMove = t;      // after a pause, do not jump
      move(t).catch(() => {}).finally(() => { moving = false; });
    }
    requestAnimationFrame(frame);
  };
  requestAnimationFrame(frame);
}
start();
