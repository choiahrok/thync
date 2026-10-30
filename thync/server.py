"""HTTP server: static page from web/, data at /graph.json, writes at /rename, /board and /reflex.

Binds to 127.0.0.1 only. Data and writes also require the X-Thync-Token header, because on a shared
machine other local users can reach 127.0.0.1 too. The static page holds no data and needs no token.
"""
import hmac
import json
import os
import secrets
import subprocess
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse, urlsplit

from .config import (DEFAULT_DAYS, HANDOFF, HOST, MAX_DAYS, PORT, PROFILE_PERSONAL, PROFILE_WORK, SESSIONS, SOURCES,
                     STATE_DIR, WEB_DIR)
from .graph import build_graph
from .reflex import start_reflex
from .sources import github, jira, notion
from .sources.claude_code import load_sessions
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
        handler = {"/reflex": self.post_reflex, "/board": self.post_board, "/rename": self.post_rename}.get(
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

    def post_reflex(self):
        if not HANDOFF:
            self.send_json(503, {"message": "이 머신에는 claude CLI 나 세션 기록이 없어 PR 을 맡길 수 없어요"})
            return
        req = self.read_body(4096)
        nid, approve = str(req["id"]), req.get("approve") is True
        target = next((n for n in build_graph(MAX_DAYS)["nodes"] if n["id"] == nid), None)
        status, message = start_reflex(target, approve) if target else (404, "노드를 찾지 못했어요")
        self.send_json(status, {"message": message})

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


def main() -> None:
    global TOKEN
    os.umask(0o077)
    TOKEN = load_token()
    print(f"thync: http://{HOST}:{PORT}/  (first time: append #t=<contents of {STATE_DIR / 'token'}>)", flush=True)
    if "github" in SOURCES:
        threading.Thread(target=github.refresh_forever, daemon=True).start()
    if "notion" in SOURCES:
        threading.Thread(target=notion.refresh_forever, daemon=True).start()
    threading.Thread(target=jira.refresh_forever, daemon=True).start()  # summaries of keys seen anywhere
    if SESSIONS:
        load_sessions(time.time(), MAX_DAYS * 86400)  # read logs up front so the first page load does not wait
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
