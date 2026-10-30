"""Claude Code session logs (~/.claude/projects/*/*.jsonl).

Logs can grow past 100 MB, so each Session keeps a byte offset and only reads lines appended since the
last call. Only the line types thync needs are parsed.
"""
import json
import re
import threading
from collections import deque
from pathlib import Path

from ..config import CLAUDE_LOGS, HOME
from ..util import epoch

FILE_TOOLS = {"Edit", "Write", "NotebookEdit", "MultiEdit"}
TS = re.compile(r'"timestamp":"([^"]+)"')
SLASH = re.compile(r"<command-name>(/[\w:-]+)</command-name>.*?(?:<command-args>(.*?)</command-args>|$)", re.S)


def describe_tool(block: dict) -> str:
    """A one-line summary of a tool call for the live activity feed."""
    name, inp = block.get("name", ""), block.get("input") or {}
    if inp.get("file_path"):
        return f"{name} {Path(inp['file_path']).name}"
    if name == "Bash":
        return f"Bash {inp.get('description') or ' '.join(str(inp.get('command', '')).split())[:60]}"
    for key in ("description", "skill", "pattern", "query", "url"):
        if inp.get(key):
            return f"{name} {str(inp[key])[:60]}"
    return name


class Session:
    """One session log, read incrementally."""

    def __init__(self, path: Path):
        self.path, self.id, self.offset = path, path.stem, 0
        self.cwd = self.branch = self.title = self.ai_title = ""
        self.prompts: list[tuple[str, str]] = []
        self.prs: dict[str, tuple] = {}
        self.files: dict[str, str] = {}
        self.events: deque = deque(maxlen=40)
        self.claude_turn = False
        # Time of the last prompt or reply. The file mtime is not enough: the app appends metadata to old logs.
        self.last_at = ""

    def update(self) -> None:
        with self.path.open("rb") as f:
            f.seek(self.offset)
            chunk = f.read()
        end = chunk.rfind(b"\n") + 1  # leave a half-written last line for next time
        self.offset += end
        for raw in chunk[:end].decode("utf-8", errors="replace").splitlines():
            try:
                self._line(raw)
            except (json.JSONDecodeError, AttributeError, TypeError):
                pass

    def _line(self, line: str) -> None:
        if '"type":"assistant"' in line:
            if '"isSidechain":true' in line:
                return
            m = TS.search(line)
            if m:
                self.last_at = max(self.last_at, m.group(1))
            # A reply that did not end with end_turn means Claude is still using tools.
            self.claude_turn = '"stop_reason":"end_turn"' not in line
            if '"tool_use"' in line:
                d = json.loads(line)
                for block in d.get("message", {}).get("content") or []:
                    if block.get("type") != "tool_use":
                        continue
                    self.events.append((d.get("timestamp", ""), "tool", describe_tool(block)))
                    fp = (block.get("input") or {}).get("file_path")
                    if block.get("name") in FILE_TOOLS and fp:
                        self.files[fp] = d.get("timestamp", "")
        elif '"type":"user"' in line:
            d = json.loads(line)
            if d.get("isSidechain"):
                return
            self.claude_turn = True  # a prompt or a tool result: Claude's turn next
            self.last_at = max(self.last_at, d.get("timestamp", ""))
            self.cwd = self.cwd or d.get("cwd") or ""  # the folder the session started in
            self.branch = d.get("gitBranch") or self.branch
            content = (d.get("message") or {}).get("content")
            command = SLASH.search(content) if isinstance(content, str) else None
            if command:
                # Slash commands with arguments count as prompts ('/name args'); bare ones like /clear do not.
                content = f"{command.group(1)} {command.group(2).strip()}" if (command.group(2) or "").strip() else ""
            if isinstance(content, str) and content.strip() and not content.lstrip().startswith(
                    ("<", "[", "Another Claude session")):
                text = " ".join(content.split())
                self.prompts.append((d.get("timestamp", ""), text))
                self.events.append((d.get("timestamp", ""), "prompt", text[:120]))
        elif '"type":"custom-title"' in line:
            self.title = json.loads(line).get("customTitle") or self.title
        elif '"type":"ai-title"' in line:
            self.ai_title = json.loads(line).get("aiTitle") or self.ai_title
        elif '"type":"pr-link"' in line:
            d = json.loads(line)
            if d.get("prUrl"):
                self.prs[d["prUrl"]] = (d.get("timestamp", ""), d.get("prRepository", ""), d.get("prNumber"))


_sessions: dict[str, tuple[float, Session]] = {}
_lock = threading.Lock()  # request threads share Session offsets; two readers would skip or repeat lines


def load_sessions(now: float, window: float) -> list[tuple[Session, float, int]]:
    """(session, last activity, running subagents) for sessions active within the window."""
    with _lock:
        return _load_sessions(now, window)


def _load_sessions(now: float, window: float) -> list[tuple[Session, float, int]]:
    out = []
    for path in CLAUDE_LOGS.glob("*/*.jsonl"):
        try:
            item = _load_one(path, now, window)
        except (OSError, ValueError):  # a log deleted or unreadable mid-scan
            continue
        if item:
            out.append(item)
    return out


def _load_one(path: Path, now: float, window: float) -> tuple[Session, float, int] | None:
    mtime = path.stat().st_mtime
    if now - mtime > window:
        return None
    key = str(path)
    seen_mtime, s = _sessions.get(key, (None, None))
    if s is None:
        s = Session(path)
    if seen_mtime != mtime:
        s.update()
        _sessions[key] = (mtime, s)
    sub = path.with_suffix("") / "subagents"
    subs = sum(1 for p in sub.glob("*.jsonl") if now - p.stat().st_mtime < 120) if sub.is_dir() else 0
    last = epoch(s.last_at)
    return (s, last, subs) if s.prompts and now - last <= window else None


def known_sessions() -> list[Session]:
    """Every session read so far, without touching the disk."""
    with _lock:
        return [s for _, s in _sessions.values()]


def repo_of(cwd: str) -> str:
    """Repository folder name for a session's working directory ('' for the home folder)."""
    root = cwd.split("/.claude/worktrees/")[0]
    return "" if root.rstrip("/") == str(HOME) else Path(root).name
