// Hand a PR off to Claude. Dropping a PR node on the spine, or a card on the "맡긴 일" column, asks for
// confirmation. My PR: the server starts Claude Code in tmux with /pr-review-watch. Someone else's PR: the
// server fetches it, has Claude review it read-only, and posts the review (approving only if asked and clean).
import { post } from "./api.ts";
import { claimModal, closeDetail, detailBox, modalTitle } from "./detail.ts";
import { apply } from "./main.ts";
import { renderer } from "./renderer.ts";
import { state } from "./state.ts";
import { ROLE_COLOR, cut } from "./style.ts";
import type { ApiNode } from "./types.ts";

const REFLEX_TEXT: Record<string, [string, string, string]> = {
  sent: ["pr-review-watch", "이 서버의 tmux 에서 Claude Code 가 auto 권한으로 리뷰 지적 사항을 고치고 push 한 뒤 스레드에 답글을 달고, 새 리뷰를 계속 지켜봐요.",
    "force push 와 main 직접 push 는 하지 않아요. 띄운 세션은 '맡긴 일'에 하늘색으로 보여요."],
  review: ["리뷰", "thync 가 PR 내용과 변경 사항을 받아 두면 Claude 는 그 파일만 읽고 리뷰를 써요. 명령 실행, 파일 수정, 네트워크 접근은 할 수 없어요.",
    "리뷰는 thync 가 COMMENT 로 한 번에 올려요. 진행 상황은 '맡긴 일' 카드에 보여요."] };

const isPR = (n: ApiNode) => n.roles.includes("sent") || n.roles.includes("review");

/** PRs that can be handed off from a node or card: the PR itself, or the PRs inside its work unit. */
export function reflexTargets(id: string): ApiNode[] {
  const self = state.data.nodes.find((x) => x.id === id);
  if (self && isPR(self)) return [self];
  const unit = self && self.kind !== "workThread" ? id : String(self?.detail.unit ?? id);
  return state.data.nodes.filter((n) => isPR(n) && n.detail.unit === unit);
}

const p = (text: string) => Object.assign(document.createElement("p"), { textContent: text });
const button = (text: string, primary = false) =>
  Object.assign(document.createElement("button"), { textContent: text, className: primary ? "primary" : "" });
const radio = (name: string, value: string, label: string, checked: boolean) => {
  const l = document.createElement("label");
  l.append(Object.assign(document.createElement("input"), { type: "radio", name, value, checked }), ` ${label}`);
  return l;
};

export function openReflex(id: string): void {
  const targets = reflexTargets(id);
  state.signature = ""; // put a dragged node back in its place
  apply();
  if (!state.data.handoff) return; // no claude CLI or session logs on the server
  if (!targets.length) {
    claimModal("맡길 PR 이 없어요");
    const close = button("닫기");
    close.onclick = closeDetail;
    const row = Object.assign(document.createElement("div"), { className: "actions" });
    row.append(close);
    detailBox.replaceChildren(
      p("'맡긴 일'은 PR 에 리뷰 감시(내 PR)나 리뷰(남의 PR)를 Claude 에게 맡기는 칸이에요."),
      p("이 작업에는 리뷰를 기다리는 내 PR 이나 나에게 온 리뷰 요청이 없어요."), row);
    return;
  }
  claimModal("");
  // With several PRs, pick which one to hand off.
  const pick = Object.assign(document.createElement("fieldset"), { className: "choice" });
  pick.append(Object.assign(document.createElement("legend"), { textContent: "맡길 PR" }),
    ...targets.map((n, i) => radio("reflex-target", n.id,
      `${n.name} · ${n.roles.includes("review") ? "리뷰 요청" : String(n.detail.review_state ?? "보낸 리뷰")} — ${cut(String(n.detail.text ?? ""), 48)}`, i === 0)));
  // For someone else's PR, choose whether to approve when the review finds nothing.
  const choice = Object.assign(document.createElement("fieldset"), { className: "choice" });
  choice.append(Object.assign(document.createElement("legend"), { textContent: "남의 PR 이면, 리뷰 뒤에" }),
    radio("reflex-approve", "comment", "리뷰만 남기기 (COMMENT)", true),
    radio("reflex-approve", "approve", "🔴·🟡 지적이 없으면 approve (내 계정으로 승인)", false));
  const what = p(""), note = p("");
  const ok = button("시작", true), cancel = button("취소");
  const row = Object.assign(document.createElement("div"), { className: "actions" });
  row.append(cancel, ok);
  const selected = () => targets.find((n) => n.id === pick.querySelector<HTMLInputElement>("input:checked")?.value) ?? targets[0];
  const update = () => {
    const n = selected();
    const role = n.roles.includes("review") ? "review" : "sent";
    const [skill, text, after] = REFLEX_TEXT[role];
    modalTitle.textContent = `${n.name}에 ${skill} 를 시작할까요?`;
    what.textContent = text;
    note.textContent = after;
    choice.hidden = role !== "review";
  };
  pick.onchange = update;
  detailBox.replaceChildren(...(targets.length > 1 ? [pick] : [p(String(targets[0].detail.text ?? ""))]), what, choice,
    note, row);
  update();
  cancel.onclick = closeDetail;
  ok.onclick = async () => {
    ok.disabled = true;
    const n = selected();
    const approve = !choice.hidden && choice.querySelector<HTMLInputElement>("input[value=approve]")?.checked === true;
    const res = await post("/reflex", { id: n.id, approve });
    const { message } = await res.json().catch(() => ({ message: `실패 (${res.status})` }));
    detailBox.replaceChildren(p(message));
    if (res.ok) renderer.burst(n.id, ROLE_COLOR.running, 1500);
  };
}
