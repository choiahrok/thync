// Sessions waiting for my answer (a choice, or a plan to approve) pop up once each, so I notice them even when
// the session is in another window. While thync's AskUserQuestion hook holds the question (`answerable`), it can be
// answered here: pick an option or type an answer. Otherwise the answer goes to the session itself.
import { post } from "./api.ts";
import { claimModal, closeDetail, detailBox, isModalOpen, modalTitle } from "./detail.ts";
import { focus, refresh } from "./main.ts";
import { recall, remember, state } from "./state.ts";
import { ago } from "./style.ts";
import type { ApiNode, Waiting } from "./types.ts";

const SOURCE: Record<string, string> = { claude_code: "Claude Code", codex: "Codex" };
const key = (n: ApiNode) => `${n.id}|${n.detail.waiting!.id}`;
let shown: { key: string; title: string; answerable: boolean } | null = null; // the question in the modal now
let seen = new Set((recall("waitingSeen") ?? "").split("\n").filter(Boolean));

const el = <K extends keyof HTMLElementTagNameMap>(tag: K, className: string, text = "") =>
  Object.assign(document.createElement(tag), { className, textContent: text });

export function checkWaiting(): void {
  const waiting = state.data.nodes.filter((n) => n.detail.waiting);
  const now = new Set(waiting.map(key));
  const kept = [...seen].filter((k) => now.has(k)); // forget answered questions so the list stays small
  if (kept.length !== seen.size) { seen = new Set(kept); remember("waitingSeen", kept.join("\n") || null); }
  document.title = waiting.length ? `(${waiting.length}) 선택 대기 · thync` : "thync";
  const next = waiting.find((n) => !seen.has(key(n)));
  if (next && !isModalOpen()) showWaiting(next);
  // The hook starts holding the question a moment after the log shows it: turn a shown question answerable.
  const open = shown && isModalOpen() && modalTitle.textContent === shown.title && waiting.find((n) => key(n) === shown!.key);
  if (open && !shown!.answerable && open.detail.waiting!.answerable) showWaiting(open);
}

function markSeen(n: ApiNode): void {
  seen.add(key(n));
  remember("waitingSeen", [...seen].join("\n"));
}

export function showWaiting(n: ApiNode): void {
  const w = n.detail.waiting!;
  markSeen(n); // shown once; it stays marked in the panel until answered
  const title = `선택을 기다리고 있어요: ${n.name}`;
  claimModal(title, true);
  shown = { key: key(n), title, answerable: !!w.answerable };
  const where = [SOURCE[String(n.detail.source)] ?? "세션", n.profile, String(n.detail.branch || n.detail.cwd || ""),
    ago(Date.parse(w.at) / 1000)].filter(Boolean).join(" · ");
  const box = el("section", "reviews");
  box.append(el("p", "quiet", where));
  const picks: (() => string)[] = [];
  w.questions.forEach((q, qi) => {
    const item = el("article", "review");
    item.append(el("header", "", q.question));
    if (q.detail) item.append(el("p", "", q.detail));
    if (!w.answerable) {
      if (q.options.length) item.append(el("p", "", q.options.map((o, i) => `${i + 1}. ${o}`).join("\n")));
      box.append(item);
      return;
    }
    // One option, or a typed answer instead.
    const radios = q.options.map((o) => {
      const label = el("label", "choice");
      const r = Object.assign(document.createElement("input"), { type: "radio", name: `q${qi}`, value: o });
      label.append(r, ` ${o}`);
      item.append(label);
      return r;
    });
    const typed = Object.assign(document.createElement("input"), { type: "text", placeholder: "직접 입력" });
    typed.oninput = () => radios.forEach((r) => { r.checked = false; });
    radios.forEach((r) => { r.onchange = () => { typed.value = ""; }; });
    item.append(typed);
    picks.push(() => typed.value.trim() || radios.find((r) => r.checked)?.value || "");
    box.append(item);
  });
  const note = el("p", "quiet", w.answerable ? "" : "답은 그 세션(터미널이나 Claude·Codex 앱)에서 해 주세요. 이 질문은 thync 에서 답할 수 없어요.");
  box.append(note);
  const row = el("div", "actions");
  const show = el("button", "", "뇌에서 보기"), ok = el("button", "primary", w.answerable ? "보내기" : "확인");
  show.onclick = () => { closeDetail(); focus(n.id); };
  ok.onclick = !w.answerable ? closeDetail : async () => {
    const answers = picks.map((p) => p());
    if (answers.some((a) => !a)) { note.textContent = "모든 질문에 답을 골라 주세요."; return; }
    ok.disabled = true;
    const r = await post("/answer", { id: w.id, answers });
    if (r.ok) { closeDetail(); await refresh(); return; }
    ok.disabled = false;
    note.textContent = r.status === 409 ? "세션이 더 이상 thync 의 답을 기다리지 않아요. 세션에서 답해 주세요." : "보내지 못했어요.";
  };
  row.append(show, ok);
  detailBox.replaceChildren(box, row);
}
