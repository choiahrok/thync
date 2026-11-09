"""HTTP server: static page from web/, data at /graph.json, writes at /rename, /board and /reflex.

/sessions.json serves this machine's parsed sessions to a hub thync on another machine (export.py). On a hub,
answers to a remote session's question and, with `reflex_host`, PR hand-offs are forwarded to that machine.

Binds to 127.0.0.1 only. Data and writes also require the X-Thync-Token header, because on a shared
machine other local users can reach 127.0.0.1 too. The static page holds no data and needs no token.
"""
import gzip
import hmac
import json
import os
import re
import secrets
import signal
import subprocess
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse, urlsplit

from . import ask
from .config import (DEFAULT_DAYS, HANDOFF, HOST, MAX_DAYS, PORT, PROFILE_PERSONAL, PROFILE_WORK, REFLEX_HOST, REMOTES,
                     SESSIONS, SOURCES, STATE_DIR, WEB_DIR)
from .export import snapshot
from .graph import build_graph
from .reflex import start_reflex
from .sources import github, jira, notion, remote
from .sources.claude_code import load_sessions, questions_of
from .store import BOARD_COLUMNS, load_token, save_card, save_name

TOKEN = ""


LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
SECURITY_HEADERS = {
    "X-Frame-Options": "SAMEORIGIN",
    "Content-Security-Policy": "default-src 'self'; style-src 'self' 'unsafe-inline'; frame-ancestors 'self'",
    "X-Content-Type-Options": "nosniff",
}


class Handler(SimpleHTTPRequestHandler):
    timeout = 10  # a client that stops sending cannot hold a thread forever

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def local_host(self) -> bool:
        """Reject other Host names (DNS rebinding). The port is free because SSH may forward from any port."""
        if urlsplit("//" + self.headers.get("Host", "")).hostname in LOCAL_HOSTS:
            return True
        self.send_error(403, "bad host")
        return False

    def authorized(self) -> bool:
        sent = self.headers.get("X-Thync-Token", "").encode()
        if TOKEN and hmac.compare_digest(sent, TOKEN.encode()):
            return True
        self.send_error(401, "token required")
        return False

    def forwarded(self) -> bool:
        """Sent on by a hub thync (sources/remote.py): handle it here, never forward it again."""
        return self.headers.get("X-Thync-Forwarded") == "1"

    def read_body(self, limit: int) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 <= length <= limit:
            raise ValueError("bad length")
        body = json.loads(self.rfile.read(length))
        if not isinstance(body, dict):
            raise ValueError("not an object")
        return body

    def fail(self, code: int) -> None:
        """send_error, unless a response is already on the wire (a second status line would corrupt it)."""
        if not self.wfile.closed and not getattr(self, "_headers_buffer", None) and not getattr(self, "_started", False):
            self.send_error(code)

    def send_response(self, code, message=None):
        self._started = True
        super().send_response(code, message)

    def list_directory(self, path):
        self.send_error(404)
        return None

    def send_json(self, status: int, data) -> None:
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_HEAD(self):
        self.send_error(405)

    def do_GET(self):
        if not self.local_host():
            return
        try:
            self.get()
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            return  # the client went away; nothing left to answer
        except Exception:  # noqa: BLE001 - answer 500 instead of dropping the connection
            self.fail(500)

    def get(self):
        url = urlparse(self.path)
        if url.path == "/answer":
            if self.authorized():
                picked = ask.poll(parse_qs(url.query).get("id", [""])[0])
                if picked:
                    self.send_json(200, picked)
                else:
                    self.send_response(204)
                    self.end_headers()
            return
        if url.path == "/reviews":
            self.get_reviews(parse_qs(url.query).get("url", [""])[0])
            return
        if url.path == "/status.json":
            if self.authorized():
                self.send_json(200, status_of(build_graph(DEFAULT_DAYS)))
            return
        if url.path == "/sessions.json":
            if self.authorized():
                self.get_sessions(parse_qs(url.query).get("days", [str(MAX_DAYS)])[0])
            return
        if url.path != "/graph.json":
            super().do_GET()
            return
        if not self.authorized():
            return
        try:
            days = int(parse_qs(url.query).get("days", [DEFAULT_DAYS])[0])
        except ValueError:
            days = DEFAULT_DAYS
        self.send_json(200, build_graph(max(1, min(MAX_DAYS, days))))

    def do_POST(self):
        if not self.local_host() or not self.authorized():
            return
        handler = {"/reflex": self.post_reflex, "/board": self.post_board, "/rename": self.post_rename,
                   "/answer": self.post_answer, "/ask": self.post_ask}.get(
            urlparse(self.path).path)
        if not handler:
            self.send_error(404)
            return
        try:
            handler()
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            return
        except (ValueError, KeyError, TypeError, AttributeError, RecursionError):
            self.fail(400)
        except (OSError, subprocess.SubprocessError, RuntimeError):
            self.fail(500)

    def get_sessions(self, days: str):
        try:
            n = max(1, min(MAX_DAYS, int(days)))
        except ValueError:
            n = MAX_DAYS
        body, etag = snapshot(n)
        if self.headers.get("If-None-Match") == etag:
            self.send_response(304)
            self.send_header("ETag", etag)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("ETag", etag)
        if "gzip" in self.headers.get("Accept-Encoding", ""):
            body = gzip.compress(body, compresslevel=5)
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def get_reviews(self, pr: str):
        if not self.authorized():
            return
        if not re.fullmatch(r"https://github\.com/[\w.-]+/[\w.-]+/pull/\d+", pr):
            self.send_json(400, {"message": "PR 주소가 아니에요"})
            return
        try:
            self.send_json(200, github.pr_reviews(pr, time.time()))
        except (subprocess.SubprocessError, OSError, ValueError, KeyError, TypeError):
            self.send_json(502, {"message": "GitHub 에서 리뷰를 가져오지 못했어요"})

    def post_reflex(self):
        req = self.read_body(16384)
        approve = req.get("approve") is True
        if isinstance(req.get("node"), dict):
            # A hub forwarding a hand-off: it sends the PR node, which this machine's graph may not have.
            target = req["node"]
            if not isinstance(target.get("roles"), list) or not isinstance(target.get("detail"), dict):
                raise ValueError("bad node")
        else:
            nid = str(req["id"])
            target = next((n for n in build_graph(MAX_DAYS)["nodes"] if n["id"] == nid), None)
        if not target:
            self.send_json(404, {"message": "노드를 찾지 못했어요"})
            return
        if REFLEX_HOST and not self.forwarded():
            status, reply = remote.by_name(REFLEX_HOST).post("/reflex", {"node": target, "approve": approve})
            message = str(reply.get("message", "")) or f"{REFLEX_HOST} 응답 {status}"
            self.send_json(status, {"message": f"{REFLEX_HOST}: {message}" if status < 400 else message})
            return
        if not HANDOFF or REFLEX_HOST:
            self.send_json(503, {"message": "이 머신에는 claude CLI 나 세션 기록이 없어 PR 을 맡길 수 없어요"})
            return
        status, message = start_reflex(target, approve)
        self.send_json(status, {"message": message})

    def post_ask(self):
        """The question hook announces the question it holds (ask.py), since the session log has it only later."""
        body = self.read_body(32768)
        qid, session = str(body["id"])[:200], str(body["session"])[:200]
        if not qid or not session or not isinstance(body.get("questions"), list):
            raise ValueError("bad question")
        at = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
        ask.hold(qid, session, {"id": qid, "at": at, "tool": "AskUserQuestion",
                                "questions": questions_of("AskUserQuestion", {"questions": body["questions"]})})
        self.send_response(204)
        self.end_headers()

    def post_answer(self):
        body = self.read_body(8192)
        answers = [" ".join(str(a).split())[:500] for a in body["answers"]][:4]
        owner = None if self.forwarded() else remote.owner_of_question(str(body["id"]))
        if owner:  # the session runs on another machine, whose question hook polls its own thync
            status, reply = owner.post("/answer", {"id": str(body["id"]), "answers": answers})
            if status == 204:
                self.send_response(204)
                self.end_headers()
            else:
                self.send_json(status, reply or {"message": f"{owner.name} 응답 {status}"})
            return
        if not ask.answer(str(body["id"]), answers):
            self.send_json(409, {"message": "이 질문은 thync 에서 답할 수 없어요. 세션에서 답해 주세요"})
            return
        self.send_response(204)
        self.end_headers()

    def post_board(self):
        body = self.read_body(8192)
        # A new card gets a fresh id and is saved as a hand-made card.
        cid = f"manual:{int(time.time() * 1000)}{secrets.token_hex(2)}" if body.get("new") else " ".join(str(body["id"]).split())
        if not cid or len(cid) > 500:
            raise ValueError("bad id")
        change = {"reset": bool(body.get("reset"))}
        if "column" in body:
            if body["column"] not in BOARD_COLUMNS:
                raise ValueError("bad column")
            change["column"] = body["column"]
        if "note" in body:
            change["note"] = str(body["note"]).strip()[:4000]
        if "title" in body:
            change["title"] = " ".join(str(body["title"]).split())[:200]
        if body.get("new"):
            profile = body.get("profile") if body.get("profile") in (PROFILE_WORK, PROFILE_PERSONAL) else PROFILE_PERSONAL
            change.update(manual="true", profile=profile, column=change.get("column", "todo"))
        save_card(cid, change)
        self.send_response(204)
        self.end_headers()

    def post_rename(self):
        body = self.read_body(4096)
        nid, name = " ".join(str(body["id"]).split()), " ".join(str(body.get("name", "")).split())
        if not nid or len(nid) > 500 or len(name) > 120:
            raise ValueError("bad id or name")
        save_name(nid, name)
        self.send_response(204)
        self.end_headers()

    def end_headers(self):
        for name, value in SECURITY_HEADERS.items():
            self.send_header(name, value)
        # Make browsers revalidate page files so an edited app.js is never served from cache.
        if "Cache-Control" not in "".join(h.decode("latin-1") for h in getattr(self, "_headers_buffer", [])):
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def log_message(self, fmt, *args):
        pass


def status_of(g: dict) -> dict:
    """GET /status.json: the few numbers and questions the desktop character shows (desktop/)."""
    nodes = g["nodes"]
    waiting = [{"session": n["id"], "title": n["name"], "host": n["detail"].get("host", ""),
                "question": (n["detail"]["waiting"].get("questions") or [{}])[0].get("question", ""),
                "answerable": bool(n["detail"]["waiting"].get("answerable"))}
               for n in nodes if n["kind"] == "workThread" and n["detail"].get("waiting")]
    return {"generated": g["generated"], "waiting": waiting,
            "running": sum(1 for n in nodes if n["kind"] == "workThread" and "running" in n["roles"]),
            "working": sum(1 for n in nodes if n["kind"] == "workThread" and n["detail"].get("claude_working")),
            "focus": sum(1 for n in nodes if "focus" in n["roles"] and "last_at" in n["detail"]),
            "reviews": sum(1 for n in nodes if "review" in n["roles"]),
            "sessions": [session_state(n) for n in nodes if n["kind"] == "workThread"],
            "hosts": g.get("hosts", [])}


def session_state(n: dict) -> dict:
    """One session for the desktop character, which notices a long or background run ending (desktop/ui/pet.js)."""
    d = n["detail"]
    state = ("waiting" if d.get("waiting") else "working" if d.get("claude_working")
             else "ended" if d.get("turn_ended") else "stalled")  # stalled: Claude's turn, but the log went quiet
    return {"session": n["id"], "title": n["name"], "host": d.get("host", ""), "state": state,
            "background": "running" in n["roles"]}


def main() -> None:
    global TOKEN
    os.umask(0o077)
    TOKEN = load_token()
    print(f"thync: http://{HOST}:{PORT}/  (first time: append #t=<contents of {STATE_DIR / 'token'}>)", flush=True)
    # Exit through atexit on kill/pkill too, so the SSH tunnels to remotes close with the server.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    if REMOTES:
        print(f"thync: showing sessions from {', '.join(r['name'] for r in REMOTES)} too", flush=True)
        remote.start()
    if "github" in SOURCES:
        threading.Thread(target=github.refresh_forever, daemon=True).start()
    if "notion" in SOURCES:
        threading.Thread(target=notion.refresh_forever, daemon=True).start()
    threading.Thread(target=jira.refresh_forever, daemon=True).start()  # summaries of keys seen anywhere
    if SESSIONS:
        load_sessions(time.time(), MAX_DAYS * 86400)  # read logs up front so the first page load does not wait
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
