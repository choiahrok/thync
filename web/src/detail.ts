// The modal: node details (opened from the 상세 buttons or by clicking an already focused node) and the
// hand-off confirmation in reflex.ts. Close with ×, a click outside, or Esc.
import { api, post } from "./api.ts";
import { refresh } from "./main.ts";
import { state } from "./state.ts";
import { ago } from "./style.ts";

export const modalEl = document.querySelector<HTMLDivElement>("#modal")!;
export const modalTitle = document.querySelector<HTMLHeadingElement>("#modal-title")!;
export const detailBox = document.querySelector<HTMLDivElement>("#detail")!;

const DETAIL_LABEL: Record<string, string> = {
  text: "내용", last_prompt: "마지막 입력", author: "작성자", reviewers: "리뷰 대기", review_state: "리뷰 상태",
  jira_status: "Jira 상태", cwd: "작업 폴더", branch: "브랜치", url: "링크" };

let shownId: string | null = null;

export function closeDetail(): void {
  modalEl.hidden = true;
  shownId = null;
}
document.querySelector<HTMLButtonElement>("#modal-close")!.onclick = closeDetail;
modalEl.onclick = (e) => { if (e.target === modalEl) closeDetail(); };
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !modalEl.hidden) closeDetail(); });

/** Use the modal for something other than node details (it then ignores repeated showDetail calls). */
export function claimModal(title: string): void {
  shownId = "custom";
  modalTitle.textContent = title;
  modalEl.hidden = false;
}

export function isModalOpen(): boolean {
  return !modalEl.hidden;
}

export async function rename(id: string, name: string): Promise<void> {
  await post("/rename", { id, name });
  await refresh();
}

// Name field: Enter saves; clearing it and pressing Enter restores the automatic name.
function nameField(label: string, id: string, current: string, auto: string, isCard = false): HTMLDivElement {
  const row = document.createElement("div");
  const k = Object.assign(document.createElement("b"), { textContent: label });
  const input = Object.assign(document.createElement("input"), { value: current, placeholder: auto, title: `Enter로 저장 · 비우면 원래 이름(${auto})` });
  input.onkeydown = (e) => {
    if (e.key !== "Enter") return;
    const name = input.value.trim() === auto ? "" : input.value.trim();
    // A work unit's name is the title in its kanban card file.
    void (isCard ? post("/board", { id, title: name }).then(refresh) : rename(id, name));
    input.blur();
  };
  row.append(k, input);
  return row;
}

// A link opens one tab per URL: clicking it again brings that tab forward instead of opening another.
// ponytail: only tabs opened since this page loaded are remembered; after a reload the named window is reused instead.
const openedTabs = new Map<string, Window>();
function openOnce(url: string): void {
  const prev = openedTabs.get(url);
  if (prev && !prev.closed) { prev.focus(); return; }
  const w = window.open(url, `thync:${url}`);
  if (!w) return;
  w.opener = null; // the opened page must not reach back into thync
  openedTabs.set(url, w);
}

export function openDetail(id: string): void {
  shownId = null;
  showDetail(id);
}

function showDetail(id: string): void {
  if (id === shownId) return; // re-rendering on hover would wipe a name being typed
  shownId = id;
  const n = state.data.nodes.find((x) => x.id === id);
  if (!n) { closeDetail(); return; }
  modalTitle.textContent = String(n.detail.text ?? n.name);
  modalEl.hidden = false;
  const unit = state.data.units.find((u) => u.id === n.detail.unit);
  const fields = [nameField("이름", n.id, n.name, String(n.detail.auto_name ?? n.name))];
  if (unit && unit.id !== n.id) fields.push(nameField("작업 단위", unit.id, unit.name, unit.auto_name ?? unit.name, true));
  const rows: [string, string][] = [["종류", String(n.detail.kind_label)], ["프로필", n.profile]];
  for (const k of Object.keys(DETAIL_LABEL)) {
    // Skip the content line when it repeats the title.
    if (n.detail[k] && !(k === "text" && String(n.detail[k]) === modalTitle.textContent)) rows.push([DETAIL_LABEL[k], String(n.detail[k])]);
  }
  const linked = (state.graph.adj[n.id] ?? []).map((x) => state.graph.idx[x]).filter(Boolean);
  rows.push(["연결", linked.map((x) => `${x.kindLabel}: ${x.name}`).join("\n")]);
  detailBox.replaceChildren(...fields, ...rows.map(([k, v]) => {
    const row = document.createElement("div");
    const vv = document.createElement(k === "링크" ? "a" : "span");
    vv.textContent = v;
    if (vv instanceof HTMLAnchorElement && /^https?:\/\//.test(v)) {
      vv.href = v; // kept so middle-click and "copy link" still work
      vv.onclick = (e) => { if (!e.ctrlKey && !e.metaKey && !e.shiftKey) { e.preventDefault(); openOnce(v); } };
    }
    row.append(Object.assign(document.createElement("b"), { textContent: k }), vv);
    return row;
  }));
  if (n.roles.includes("sent") && typeof n.detail.url === "string") void showReviews(id, n.detail.url);
}

const REVIEW_STATE: Record<string, string> = {
  APPROVED: "승인", CHANGES_REQUESTED: "수정 요청", COMMENTED: "코멘트", DISMISSED: "철회됨" };

interface Comment { author: string; body: string; at: string; url: string }
interface Thread { path: string; line: number | null; resolved: boolean; outdated: boolean; comments: Comment[] }
interface Reviews { reviews: (Comment & { state: string })[]; threads: Thread[] }

const el = <K extends keyof HTMLElementTagNameMap>(tag: K, className: string, text = "") =>
  Object.assign(document.createElement(tag), { className, textContent: text });

function entry(head: string, body: string, url: string): HTMLElement {
  const item = el("article", "review");
  const h = el("header", "", head);
  if (/^https?:\/\//.test(url)) {
    const a = el("a", "", "GitHub 에서 보기");
    a.href = url;
    a.onclick = (e) => { if (!e.ctrlKey && !e.metaKey && !e.shiftKey) { e.preventDefault(); openOnce(url); } };
    h.append(" · ", a);
  }
  item.append(h);
  if (body.trim()) item.append(el("p", "", body.length > 800 ? `${body.slice(0, 800)}…` : body));
  return item;
}

// Reviews others left on my PR, fetched when its details open. Text is shown as plain text, never as HTML.
async function showReviews(id: string, url: string): Promise<void> {
  const box = el("section", "reviews");
  box.append(el("h4", "", "받은 리뷰"), el("p", "quiet", "불러오는 중…"));
  detailBox.append(box);
  const res = await api(`/reviews?url=${encodeURIComponent(url)}`).catch(() => null);
  if (shownId !== id) return; // another node was opened meanwhile
  const data: Reviews | null = res?.ok ? await res.json() : null;
  box.lastElementChild!.remove();
  if (!data) { box.append(el("p", "quiet", "리뷰를 가져오지 못했어요")); return; }
  const open = data.threads.filter((t) => !t.resolved);
  if (!data.reviews.length && !data.threads.length) box.append(el("p", "quiet", "아직 받은 리뷰가 없어요"));
  for (const r of data.reviews) box.append(entry(`${r.author} · ${REVIEW_STATE[r.state] ?? r.state} · ${ago(Date.parse(r.at) / 1000)}`, r.body, r.url));
  if (open.length) box.append(el("h4", "", `해결 안 된 코멘트 ${open.length}`));
  for (const t of open) {
    const [first, ...replies] = t.comments;
    if (!first) continue;
    const where = `${t.path}${t.line ? `:${t.line}` : ""}${t.outdated ? " (바뀐 코드)" : ""}`;
    box.append(entry(`${where} · ${first.author}${replies.length ? ` · 답글 ${replies.length}` : ""}`, first.body, first.url));
  }
  const done = data.threads.length - open.length;
  if (done) box.append(el("p", "quiet", `해결된 코멘트 ${done}개는 접어 두었어요`));
}
