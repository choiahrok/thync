// The modal: node details (opened from the ⓘ buttons or by clicking an already focused node) and the
// hand-off confirmation in reflex.ts. Close with ×, a click outside, or Esc.
import { post } from "./api.ts";
import { refresh } from "./main.ts";
import { state } from "./state.ts";

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
    if (vv instanceof HTMLAnchorElement && /^https?:\/\//.test(v)) { vv.href = v; vv.target = "_blank"; vv.rel = "noopener"; }
    row.append(Object.assign(document.createElement("b"), { textContent: k }), vv);
    return row;
  }));
}
