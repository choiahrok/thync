"""Answer a Claude Code question (AskUserQuestion) from thync.

The PreToolUse hook (`python3 -m thync.ask`) holds the question and polls the running thync server for an answer
picked in the page. The answer goes back as `updatedInput.answers`, so the session goes on without its own dialog.
When thync is down, or nobody answers within `ask_wait_sec`, the hook steps aside and the session asks as usual.
Register it in ~/.claude/settings.json (docs/usage.md).

Claude Code writes the question to the session log only after this hook returns, so the log cannot tell thync a
question is waiting. The hook therefore hands it to the server first (POST /ask), and the server shows it on the
session while the hook keeps polling.
"""
import json
import sys
import threading
import time
import urllib.parse
import urllib.request

from .config import ASK_WAIT_SEC, HOST, PORT, STATE_DIR

# Server side: questions a hook is polling for, and answers picked in the page but not yet collected.
_lock = threading.Lock()
_polled: dict[str, float] = {}
_answers: dict[str, list[str]] = {}
_held: dict[str, dict] = {}  # question id -> {"session": session id, "waiting": what graph shows as detail.waiting}


def hold(qid: str, session: str, waiting: dict) -> None:
    """A hook started holding this question for `session`; show it until the hook stops polling."""
    with _lock:
        _held[qid] = {"session": session, "waiting": waiting}
        _polled[qid] = time.time()


def held_for(session: str) -> dict | None:
    """The question a live hook holds for this session, as detail.waiting, or None."""
    with _lock:
        now = time.time()
        return next((h["waiting"] for q, h in _held.items() if h["session"] == session and now - _polled.get(q, 0) < 5),
                    None)


def poll(qid: str) -> list[str] | None:
    """A hook asks for the answer to `qid`; returns it once, or None while there is none."""
    with _lock:
        now = time.time()
        for k in [k for k, t in _polled.items() if now - t > 60]:
            _polled.pop(k)
            _answers.pop(k, None)
            _held.pop(k, None)
        _polled[qid] = now
        picked = _answers.pop(qid, None)
        if picked:
            _held.pop(qid, None)
        return picked


def answerable(qid: str) -> bool:
    """A hook is holding this question right now."""
    with _lock:
        return time.time() - _polled.get(qid, 0) < 5


def answer(qid: str, answers: list[str]) -> bool:
    with _lock:
        if time.time() - _polled.get(qid, 0) >= 5:
            return False
        _answers[qid] = answers
        return True


def main() -> None:
    try:
        event = json.load(sys.stdin)
        token = (STATE_DIR / "token").read_text().strip()
    except (OSError, ValueError):
        return
    questions = (event.get("tool_input") or {}).get("questions") or []
    qid = str(event.get("tool_use_id") or "")
    if event.get("tool_name") != "AskUserQuestion" or not qid or not questions:
        return
    headers = {"X-Thync-Token": token, "Content-Type": "application/json"}
    body = {"id": qid, "session": str(event.get("session_id") or ""), "questions": questions}
    try:  # show the question in thync now; an older server without /ask still answers through polling
        urllib.request.urlopen(urllib.request.Request(f"http://{HOST}:{PORT}/ask", headers=headers,
                                                      data=json.dumps(body, ensure_ascii=False).encode()), timeout=3).close()
    except (OSError, ValueError):
        pass
    url = f"http://{HOST}:{PORT}/answer?" + urllib.parse.urlencode({"id": qid})
    deadline = time.time() + ASK_WAIT_SEC
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"X-Thync-Token": token}), timeout=3) as r:
                picked = json.load(r) if r.status == 200 else None
        except (OSError, ValueError):
            return  # thync is not running: the session asks as usual
        if picked:
            sys.stdout.reconfigure(encoding="utf-8")
            answers = {q.get("question", ""): str(a) for q, a in zip(questions, picked) if str(a).strip()}
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "PreToolUse", "permissionDecision": "allow",
                "updatedInput": {**event["tool_input"], "answers": answers}}}, ensure_ascii=False))
            return
        time.sleep(1)


if __name__ == "__main__":
    main()
