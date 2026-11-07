"""GET /sessions.json: this machine's sessions, parsed, for a hub thync on another machine (sources/remote.py).

Only what graph.build_graph reads goes out, cut to the windows it uses, so a busy server sends kilobytes, not logs.
What only this machine can tell (profile from its company folders, repository, PR hand-off, whether a question
hook is waiting for an answer) is worked out here.
"""
import hashlib
import json
import time

from . import ask
from .config import ACTIVITY_SEC, FILES_SEC, FOCUS_SEC, HANDOFF, SESSIONS
from .graph import profile_of, reflex_of
from .reflex import tmux_alive
from .sources.claude_code import load_sessions, repo_of
from .store import load_reflexes
from .util import epoch

TEXT_MAX = 300


def session_dict(s, last: float, subs: int, now: float, reflexes: dict) -> dict:
    waiting = s.waiting or ask.held_for(s.id)  # a question hook holds it before the log has it
    keep = [p for p in s.prompts[1:-1] if epoch(p[0]) > now - FOCUS_SEC]
    prompts = [s.prompts[0], *keep, s.prompts[-1]] if len(s.prompts) > 1 else list(s.prompts)
    return {
        "id": s.id, "source": s.source, "cwd": s.cwd, "branch": s.branch, "title": s.title, "ai_title": s.ai_title,
        "prompts": [(t, p[:TEXT_MAX]) for t, p in prompts],
        "prs": s.prs,
        "files": {f: t for f, t in s.files.items() if epoch(t) > now - FILES_SEC},
        "events": [e for e in s.events if epoch(e[0]) > now - ACTIVITY_SEC],
        "claude_turn": s.claude_turn, "waiting": waiting, "last_at": s.last_at,
        "last": last, "subs": subs,
        "profile": profile_of(s.cwd), "repo": repo_of(s.cwd), "reflex": reflex_of(s, reflexes),
        "answerable": bool(waiting) and ask.answerable(waiting["id"]),
    }


def snapshot(days: int) -> tuple[bytes, str]:
    """(JSON body, ETag). The ETag lets the hub skip a body that did not change since its last read."""
    now = time.time()
    reflexes = load_reflexes() if HANDOFF else {}
    sessions = load_sessions(now, days * 86400) if SESSIONS else []
    data = {
        "sessions": [session_dict(s, last, subs, now, reflexes) for s, last, subs in sessions],
        # Hand-offs this machine runs, so the hub's board can show them; tmux only exists here.
        "reflexes": {url: {**r, "alive": tmux_alive(r["tmux"])} if "tmux" in r else r for url, r in reflexes.items()},
    }
    body = json.dumps(data, ensure_ascii=False, sort_keys=True).encode()
    return body, '"' + hashlib.sha256(body).hexdigest()[:32] + '"'
