// The kanban board under the brain. Cards are dragged between columns (a hand-set column wins over the
// automatic one) and edited in place: double-click a title or a note. Each card is a Markdown file on the
// server. Also here: view modes (brain + board / brain / board), the resize handle, and "+ 카드".
import { post } from "./api.ts";
import { focus, refresh } from "./main.ts";
import { infoButton } from "./panel.ts";
import { openReflex, reflexTargets } from "./reflex.ts";
import { inProfile, recall, remember, state } from "./state.ts";
import { ago, epochMs, profileColor } from "./style.ts";
import type { ApiCard } from "./types.ts";

const boardEl = document.querySelector<HTMLDivElement>("#board")!;
const stageEl = document.querySelector<HTMLElement>("#stage")!;
const COLUMN_NAME: Record<string, string> = { todo: "Todo", doing: "진행 중", background: "백그라운드 진행 중", reflex: "맡긴 일", done: "완료" };
let busy = false; // while dragging or editing, the 2 s refresh must not redraw the cards

const saveCard = (body: Record<string, unknown>) => post("/board", body);

function cardView(c: ApiCard): HTMLDivElement {
  const el = Object.assign(document.createElement("div"), { className: "card", draggable: true });
  el.style.borderLeftColor = c.column === "done" ? "#6f6b75" : profileColor(c.profile);
  const title = Object.assign(document.createElement("div"), { className: "t", textContent: c.title, title: "두 번 눌러 제목 고치기" });
  const sub = Object.assign(document.createElement("div"), {
    className: "s", textContent: [c.sub, `${c.profile} · ${ago(epochMs(c.updated) / 1000)}`].filter(Boolean).join(" · ") });
  const note = Object.assign(document.createElement("div"), {
    className: c.note ? "note" : "note empty", textContent: c.note, title: "두 번 눌러 메모 고치기" });
  note.dataset.placeholder = "메모 추가";
  const tags = Object.assign(document.createElement("div"), { className: "tags" });
  tags.replaceChildren(...c.tags.map((x) => Object.assign(document.createElement("i"), { textContent: x })));
  if (c.moved) {
    const moved = Object.assign(document.createElement("i"), {
      className: "moved", textContent: `직접 옮김 · 자동은 ${COLUMN_NAME[c.auto_column]} ↺`, title: "눌러서 자동 칸으로 되돌리기" });
    moved.onclick = async (e) => { e.stopPropagation(); await saveCard({ id: c.id, reset: true }); await refresh(); };
    tags.append(moved);
  }
  el.append(title, sub, note, tags);
  if (c.focus) el.prepend(infoButton(c.focus));
  el.onclick = () => { if (c.focus) focus(c.focus); };
  title.ondblclick = (e) => { e.stopPropagation(); editInPlace(el, title, c.title, true, (v) => ({ id: c.id, title: v })); };
  el.ondblclick = () => editInPlace(el, note, c.note, false, (v) => ({ id: c.id, note: v }));
  el.ondragstart = (e) => { busy = true; el.classList.add("dragging"); e.dataTransfer!.setData("text/plain", c.id); };
  el.ondragend = () => { busy = false; el.classList.remove("dragging"); };
  return el;
}

// In-place editing. Title: Enter saves. Note: Ctrl/Cmd+Enter or clicking away saves. Esc cancels.
function editInPlace(card: HTMLDivElement, field: HTMLElement, original: string, singleLine: boolean,
  body: (value: string) => Record<string, unknown>): void {
  if (field.isContentEditable) return;
  busy = true;
  card.draggable = false;
  field.classList.remove("empty");
  field.classList.add("editing");
  field.contentEditable = "plaintext-only";
  field.focus();
  document.getSelection()?.selectAllChildren(field);
  let cancelled = false;
  field.onkeydown = (e) => {
    if (e.key === "Escape") { cancelled = true; field.blur(); }
    else if (e.key === "Enter" && (singleLine || e.ctrlKey || e.metaKey)) { e.preventDefault(); field.blur(); }
  };
  field.onblur = async () => {
    field.contentEditable = "false";
    const value = singleLine ? (field.textContent ?? "").replace(/\s+/g, " ").trim() : (field.innerText ?? "").trim();
    if (!cancelled && value !== original) await saveCard(body(value));
    busy = false;
    await refresh();
    renderBoard();
  };
}

export function renderBoard(): void {
  if (busy) return;
  const cards = state.data.board.filter((c) => inProfile(c.profile)).sort((a, b) => epochMs(b.updated) - epochMs(a.updated));
  for (const section of boardEl.querySelectorAll<HTMLElement>("section")) {
    if (section.dataset.col === "reflex") section.hidden = !state.data.handoff;
    const mine = cards.filter((c) => c.column === section.dataset.col);
    const h3 = section.querySelector("h3")!;
    const label = (h3.dataset.label ??= h3.textContent ?? "");
    h3.replaceChildren(label, Object.assign(document.createElement("span"), { textContent: String(mine.length) }));
    section.querySelector("div")!.replaceChildren(...mine.map(cardView));
  }
}

for (const section of boardEl.querySelectorAll<HTMLElement>("section")) {
  section.ondragover = (e) => { e.preventDefault(); section.classList.add("over"); };
  section.ondragleave = () => section.classList.remove("over");
  section.ondrop = async (e) => {
    e.preventDefault();
    section.classList.remove("over");
    const id = e.dataTransfer!.getData("text/plain");
    const card = state.data.board.find((c) => c.id === id);
    if (!card || card.column === section.dataset.col) return;
    // Dropping on "맡긴 일" does not move the card: it asks to hand the work's PR off to Claude.
    if (section.dataset.col === "reflex") {
      busy = false;
      openReflex(card.focus && reflexTargets(card.focus).length ? card.focus : card.id);
      return;
    }
    if (card.column === "reflex") return; // handed-off cards are session records and stay put
    card.column = section.dataset.col!;   // move it right away instead of waiting for the server
    card.moved = card.column !== card.auto_column;
    busy = false;
    renderBoard();
    await saveCard(card.moved ? { id, column: card.column } : { id, reset: true });
  };
}

// View modes. #board in the URL opens the board only, #brain the brain only.
function setMode(mode: string): void {
  stageEl.dataset.mode = mode;
  document.querySelectorAll<HTMLButtonElement>("[data-mode]").forEach((b) => b.classList.toggle("on", b.dataset.mode === mode));
  remember("mode", mode);
}
for (const btn of document.querySelectorAll<HTMLButtonElement>("[data-mode]")) btn.onclick = () => setMode(btn.dataset.mode!);
{
  const mode = ({ "#board": "board", "#brain": "brain" } as Record<string, string>)[location.hash] ?? recall("mode") ?? "";
  setMode(["both", "brain", "board"].includes(mode) ? mode : "both");
}

// Drag the handle between brain and board to resize the board; double-click to reset.
const splitter = document.querySelector<HTMLDivElement>("#splitter")!;
const BOARD_MIN = 140, BRAIN_MIN = 160;
function setBoardHeight(px: number | null): void {
  if (px === null) { boardEl.style.flexBasis = ""; return; }
  boardEl.style.flexBasis = `${Math.round(Math.max(BOARD_MIN, Math.min(stageEl.clientHeight - BRAIN_MIN, px)))}px`;
}
splitter.onpointerdown = (e) => {
  e.preventDefault();
  try { splitter.setPointerCapture(e.pointerId); } catch { /* dragging still works without capture */ }
  splitter.classList.add("dragging");
  stageEl.classList.add("resizing");
  const bar = document.querySelector<HTMLElement>("#boardbar")!;
  splitter.onpointermove = (m) => {
    setBoardHeight(stageEl.getBoundingClientRect().bottom - m.clientY - bar.offsetHeight - splitter.offsetHeight);
  };
  splitter.onpointerup = () => {
    splitter.onpointermove = null;
    splitter.classList.remove("dragging");
    stageEl.classList.remove("resizing");
    remember("boardHeight", String(boardEl.getBoundingClientRect().height));
  };
};
splitter.ondblclick = () => { setBoardHeight(null); remember("boardHeight", null); };
if (Number(recall("boardHeight"))) setBoardHeight(Number(recall("boardHeight")));

document.querySelector<HTMLButtonElement>("#add-card")!.onclick = async () => {
  const title = window.prompt("새 카드 제목");
  if (!title?.trim()) return;
  await saveCard({ new: true, title: title.trim(), column: "todo", profile: state.profile === "전체" ? "개인" : state.profile });
  await refresh();
};
