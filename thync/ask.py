"""Answer a Claude Code question (AskUserQuestion) from thync.

The PreToolUse hook (`python3 -m thync.ask`) holds the question and polls the running thync server for an answer
picked in the page. The answer goes back as `updatedInput.answers`, so the session goes on without its own dialog.
When thync is down, or nobody answers within `ask_wait_sec`, the hook steps aside and the session asks as usual.
Register it in ~/.claude/settings.json (docs/usage.md).
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


def poll(qid: str) -> list[str] | None:
    """A hook asks for the answer to `qid`; returns it once, or None while there is none."""
    with _lock:
        now = time.time()
        for k in [k for k, t in _polled.items() if now - t > 60]:
            _polled.pop(k)
            _answers.pop(k, None)
        _polled[qid] = now
        return _answers.pop(qid, None)


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
