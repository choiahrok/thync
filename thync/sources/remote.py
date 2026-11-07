"""Sessions on other machines (config "remotes"), so one thync shows every dev server.

Each server runs its own thync, which reads its own session logs and serves them, already parsed, at
/sessions.json (thync/export.py). This thync, the hub, keeps one SSH tunnel per server, reads that endpoint every
POLL_SEC and puts the sessions on its own brain next to its local ones. Logs never cross the network, only the
parsed sessions, and only when they changed (ETag) and gzipped.

A tunnel that drops is opened again with backoff. While a server is unreachable its last sessions stay on the brain
but stop counting as working, so the brain does not show Claude busy on a machine it cannot see.
"""
import atexit
import gzip
import json
import socket
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request

from ..config import MAX_DAYS, REMOTES

POLL_SEC = 1.5
SSH_OPTS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-o", "ServerAliveInterval=10",
            "-o", "ServerAliveCountMax=3"]


class RemoteError(Exception):
    pass


class RemoteSession:
    """A session read on another machine: the attributes graph.build_graph uses, plus where it runs."""

    def __init__(self, host: str, d: dict):
        self.host = host
        self.id, self.source = str(d["id"]), str(d.get("source", "claude_code"))
        self.cwd, self.branch = str(d.get("cwd", "")), str(d.get("branch", ""))
        self.title, self.ai_title = str(d.get("title", "")), str(d.get("ai_title", ""))
        self.prompts = [(str(t), str(p)) for t, p in d.get("prompts", [])]
        self.prs = {str(u): tuple(v) for u, v in (d.get("prs") or {}).items()}
        self.files = {str(f): str(t) for f, t in (d.get("files") or {}).items()}
        self.events = [tuple(e) for e in d.get("events", [])]
        self.claude_turn = bool(d.get("claude_turn"))
        self.waiting = d.get("waiting") or None
        self.last_at = str(d.get("last_at", ""))
        # Worked out on the server, which knows its own folders, PR hand-offs and question hooks.
        self.profile, self.repo, self.reflex = str(d.get("profile", "")), str(d.get("repo", "")), str(d.get("reflex", ""))
        self.answerable = bool(d.get("answerable"))
        self.last, self.subs = float(d.get("last", 0)), int(d.get("subs", 0))


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Remote:
    def __init__(self, cfg: dict):
        self.name, self.ssh, self.port, self.home = cfg["name"], cfg["ssh"], cfg["port"], cfg["thync_home"]
        self.local_port = 0
        self.proc: subprocess.Popen | None = None
        self.token = self.etag = ""
        self.sessions: list[RemoteSession] = []
        self.reflexes: dict[str, dict] = {}
        self.ok, self.error, self.seen = False, "연결 중", 0.0
        self.lock = threading.Lock()

    # --- tunnel and token ---
    def tunnel(self) -> None:
        if self.proc and self.proc.poll() is None:
            return
        self.close()
        self.local_port = free_port()
        # A file, not a pipe: ssh keeps logging refused channels while the remote thync is down, and a full pipe
        # would stall the tunnel.
        errlog = tempfile.TemporaryFile()
        self.proc = subprocess.Popen(
            ["ssh", "-N", *SSH_OPTS, "-o", "ExitOnForwardFailure=yes",
             "-L", f"127.0.0.1:{self.local_port}:127.0.0.1:{self.port}", self.ssh],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=errlog)
        deadline = time.time() + 20
        while time.time() < deadline:
            if self.proc.poll() is not None:
                errlog.seek(0)
                err = errlog.read().decode(errors="replace").strip().splitlines()
                raise RemoteError(f"SSH 접속 실패: {err[-1] if err else self.proc.returncode}")
            try:
                socket.create_connection(("127.0.0.1", self.local_port), timeout=1).close()
                return
            except OSError:
                time.sleep(0.3)
        raise RemoteError("SSH 터널이 열리지 않음")

    def close(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None

    def read_token(self) -> None:
        if self.token:
            return
        try:
            out = subprocess.run(["ssh", *SSH_OPTS, self.ssh, f"cat {self.home}/token"],
                                 stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30)
        except (subprocess.SubprocessError, OSError) as e:
            raise RemoteError(f"토큰을 읽지 못함 ({e.__class__.__name__})") from e
        token = out.stdout.strip()
        if out.returncode != 0 or not token or len(token) > 200:
            raise RemoteError("토큰을 읽지 못함 (그 서버에서 thync 를 한 번 실행했는지 확인)")
        self.token = token

    # --- HTTP over the tunnel ---
    def request(self, path: str, body: dict | None = None, etag: str = "") -> tuple[int, bytes, dict]:
        # Marked so the far end never forwards it again (a hub listed as a remote of itself would loop).
        headers = {"X-Thync-Token": self.token, "Accept-Encoding": "gzip", "X-Thync-Forwarded": "1"}
        if etag:
            headers["If-None-Match"] = etag
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(f"http://127.0.0.1:{self.local_port}{path}", data=data, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                status, raw, hdrs = r.status, r.read(), dict(r.headers)
        except urllib.error.HTTPError as e:
            with e:
                status, raw, hdrs = e.code, e.read(), dict(e.headers)
        except (OSError, ValueError) as e:
            raise RemoteError("thync 가 응답하지 않음 (그 서버에서 thync 가 꺼져 있을 수 있음)") from e
        if hdrs.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        if status == 401:
            self.token = ""
            raise RemoteError("토큰이 맞지 않음")
        return status, raw, hdrs

    def fetch(self) -> None:
        status, raw, hdrs = self.request(f"/sessions.json?days={MAX_DAYS}", etag=self.etag)
        if status == 404:
            raise RemoteError("그 서버의 thync 가 오래된 버전 (/sessions.json 없음) · git pull 후 재시작 필요")
        if status == 304:
            with self.lock:
                self.ok, self.error, self.seen = True, "", time.time()
            return
        if status != 200:
            raise RemoteError(f"thync 응답 {status}")
        data = json.loads(raw)
        sessions = [RemoteSession(self.name, d) for d in data.get("sessions", []) if isinstance(d, dict) and d.get("id")]
        with self.lock:
            self.sessions, self.reflexes = sessions, dict(data.get("reflexes") or {})
            self.etag = hdrs.get("ETag", "")
            self.ok, self.error, self.seen = True, "", time.time()

    def down(self, error: str) -> None:
        with self.lock:
            self.ok, self.error, self.etag = False, error, ""
            for s in self.sessions:  # cannot see it, so do not claim it is working
                s.subs, s.claude_turn, s.answerable = 0, False, False

    def run(self) -> None:
        backoff = 2.0
        while True:
            try:
                self.tunnel()
                self.read_token()
                self.fetch()
                backoff = 2.0
                time.sleep(POLL_SEC)
            except RemoteError as e:
                self.down(str(e))
                if self.proc and self.proc.poll() is not None:
                    self.close()
                time.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
            except Exception as e:  # noqa: BLE001 - a bad reply must not stop the loop for good
                self.down(f"오류: {e.__class__.__name__}")
                time.sleep(backoff)
                backoff = min(backoff * 2, 30.0)

    def post(self, path: str, body: dict) -> tuple[int, dict]:
        """Forward a write to this server's thync. Returns (HTTP status, JSON body or {})."""
        if not self.ok:
            return 503, {"message": f"{self.name} 에 연결되어 있지 않아요 ({self.error})"}
        try:
            status, raw, _ = self.request(path, body)
        except RemoteError as e:
            return 502, {"message": f"{self.name}: {e}"}
        try:
            return status, json.loads(raw) if raw else {}
        except ValueError:
            return status, {}


_remotes: list[Remote] = []


def start() -> None:
    """Open a tunnel to every configured remote and keep reading it, each in its own thread."""
    if _remotes:
        return
    for cfg in REMOTES:
        r = Remote(cfg)
        _remotes.append(r)
        threading.Thread(target=r.run, name=f"remote-{r.name}", daemon=True).start()
    atexit.register(lambda: [r.close() for r in _remotes])


def sessions(now: float, window: float) -> list[tuple[RemoteSession, float, int]]:
    out = []
    for r in _remotes:
        with r.lock:
            out += [(s, s.last, s.subs) for s in r.sessions if now - s.last <= window]
    return out


def reflexes() -> dict[str, dict]:
    """PR hand-offs the remotes run: {url: record plus "host", "ssh" and, for tmux ones, "alive"}."""
    out = {}
    for r in _remotes:
        with r.lock:
            out.update({url: {**rec, "host": r.name, "ssh": r.ssh} for url, rec in r.reflexes.items()})
    return out


def by_name(name: str) -> Remote | None:
    return next((r for r in _remotes if r.name == name), None)


def owner_of_question(qid: str) -> Remote | None:
    for r in _remotes:
        with r.lock:
            if any(s.waiting and s.waiting.get("id") == qid for s in r.sessions):
                return r
    return None


def status() -> list[dict]:
    out = []
    for r in _remotes:
        with r.lock:
            out.append({"name": r.name, "ok": r.ok, "error": r.error, "seen": int(r.seen)})
    return out
