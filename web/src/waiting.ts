// Sessions waiting for my answer (a choice, or a plan to approve) pop up once each, so I notice them even when
// the session is in another window. thync only shows the question; the answer goes to the session itself.
import { claimModal, closeDetail, detailBox, isModalOpen } from "./detail.ts";
import { focus } from "./main.ts";
import { recall, remember, state } from "./state.ts";
import { ago } from "./style.ts";
import type { ApiNode, Waiting } from "./types.ts";

const SOURCE: Record<string, string> = { claude_code: "Claude Code", codex: "Codex" };
const key = (n: ApiNode) => `${n.id}|${n.detail.waiting!.id}`;
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
  if (next && !isModalOpen()) show(next);
}

function markSeen(n: ApiNode): void {
  seen.add(key(n));
  remember("waitingSeen", [...seen].join("\n"));
}

function show(n: ApiNode): void {
  const w = n.detail.waiting!;
  markSeen(n); // shown once; it stays marked in the panel until answered
  claimModal(`선택을 기다리고 있어요: ${n.name}`);
  const where = [SOURCE[String(n.detail.source)] ?? "세션", n.profile, String(n.detail.branch || n.detail.cwd || ""),
    ago(Date.parse(w.at) / 1000)].filter(Boolean).join(" · ");
  const box = el("section", "reviews");
  box.append(el("p", "quiet", where));
  for (const q of w.questions) {
    const item = el("article", "review");
    item.append(el("header", "", q.question));
    if (q.options.length) item.append(el("p", "", q.options.map((o, i) => `${i + 1}. ${o}`).join("\n")));
    if (q.detail) item.append(el("p", "", q.detail));
    box.append(item);
  }
  box.append(el("p", "quiet", "답은 그 세션(터미널이나 Claude·Codex 앱)에서 해 주세요. thync 에서는 답할 수 없어요."));
  const row = el("div", "actions");
  const show = el("button", "", "뇌에서 보기"), ok = el("button", "primary", "확인");
  show.onclick = () => { closeDetail(); focus(n.id); };
  ok.onclick = closeDetail;
  row.append(show, ok);
  detailBox.replaceChildren(box, row);
}
