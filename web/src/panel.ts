// The side panel: what I focus on, background work, review requests, my PRs under review.
// Clicking an item highlights it on the brain; only its ⓘ button opens the detail modal.
import { openDetail } from "./detail.ts";
import { focus } from "./main.ts";
import { isSource, shown, state } from "./state.ts";
import { ago, cut } from "./style.ts";
import type { ApiNode } from "./types.ts";

const focusList = document.querySelector<HTMLUListElement>("#focus")!;
const runningList = document.querySelector<HTMLUListElement>("#running")!;
const reviewList = document.querySelector<HTMLUListElement>("#reviews")!;
const sentList = document.querySelector<HTMLUListElement>("#sent")!;
const statusLine = document.querySelector<HTMLSpanElement>("#status")!;

export function setStatus(text: string): void {
  statusLine.textContent = text;
}

export function infoButton(id: string): HTMLButtonElement {
  const btn = Object.assign(document.createElement("button"), { className: "info", textContent: "ⓘ", title: "상세 보기" });
  btn.onclick = (e) => { e.stopPropagation(); focus(id); openDetail(id); };
  btn.ondblclick = (e) => e.stopPropagation();
  return btn;
}

function item(n: ApiNode, main: string, sub: string, role: string): HTMLLIElement {
  const li = Object.assign(document.createElement("li"), { className: role });
  li.append(Object.assign(document.createElement("div"), { className: "main", textContent: main }),
    Object.assign(document.createElement("div"), { className: "sub", textContent: sub }), infoButton(n.id));
  li.onclick = () => focus(n.id);
  return li;
}

function list(ul: HTMLUListElement, items: HTMLLIElement[], empty: string): void {
  ul.replaceChildren(...(items.length ? items : [Object.assign(document.createElement("li"), { className: "empty", textContent: empty })]));
}

const STATE_ORDER: Record<string, number> = { "수정 요청": 0, "승인됨": 1, "코멘트 있음": 2, "리뷰 대기": 3 };

export function renderPanel(): void {
  const visible = shown();
  const sources = visible.filter(isSource);
  const sub = (n: ApiNode): string => `${n.profile} · ${String(n.detail.branch || n.detail.kind_label)} · ${ago(Number(n.detail.updated))}`;
  // A session says how much I prompted; a branch, ticket or page says what its last activity was.
  const what = (n: ApiNode): string => n.kind === "workThread"
    ? `${n.detail.claude_working ? "Claude 작업 중 · " : ""}최근 1시간 프롬프트 ${n.detail.focus_prompts}개 · `
    : n.detail.text && n.detail.text !== n.name ? `${cut(String(n.detail.text), 60)} · ` : "";

  const focused = sources.filter((n) => n.roles.includes("focus"))
    .sort((x, y) => Number(y.detail.last_at) - Number(x.detail.last_at));
  list(focusList, focused.map((n) => item(n, n.name, `${what(n)}${sub(n)}`, "focus")), "최근에 손댄 일 없음");

  const running = sources.filter((n) => n.roles.includes("running"))
    .sort((x, y) => Number(y.detail.updated) - Number(x.detail.updated));
  list(runningList, running.map((n) => item(n, n.name,
    `${Number(n.detail.subagents) ? `subagent ${n.detail.subagents}개 · ` : ""}${n.kind === "workThread" ? "" : `${String(n.detail.jira_status)} · `}${sub(n)}`, "running")),
    "백그라운드 작업 없음");

  const reviews = visible.filter((n) => n.roles.includes("review"))
    .sort((x, y) => String(y.detail.updated).localeCompare(String(x.detail.updated)));
  list(reviewList, reviews.map((n) => item(n, `${n.name} ${String(n.detail.text)}`,
    `${String(n.detail.author)} · ${ago(Date.parse(String(n.detail.updated)) / 1000)}`, "review")),
    "리뷰 요청 없음");

  const sent = visible.filter((n) => n.roles.includes("sent"))
    .sort((x, y) => (STATE_ORDER[String(x.detail.review_state)] ?? 9) - (STATE_ORDER[String(y.detail.review_state)] ?? 9)
      || String(y.detail.updated).localeCompare(String(x.detail.updated)));
  list(sentList, sent.map((n) => item(n, `${n.name} ${String(n.detail.text)}`,
    `${String(n.detail.review_state)}${n.detail.reviewers ? ` · 대기: ${n.detail.reviewers}` : ""} · ${ago(Date.parse(String(n.detail.updated)) / 1000)}`, "sent")),
    "리뷰를 기다리는 내 PR 없음");

  setStatus(`몰입 ${Math.round(state.data.focus_level * 100)}% · 작업공간 ${focused.length}/4 · 백그라운드 ${running.length} · 리뷰 ${reviews.length} · ${new Date(state.data.generated * 1000).toLocaleTimeString()}`);
}
