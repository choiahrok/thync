"""OpenAI Codex CLI session logs (~/.codex/sessions/YYYY/MM/DD/*.jsonl), read like Claude Code's.

Each line is {timestamp, type, payload}. The first line (session_meta) holds the id, cwd and git branch.
"""
import json
import re
from pathlib import Path

from .claude_code import Session

PATCH_FILE = re.compile(r"^\*\*\* (?:Add|Update) File: (.+)$", re.M)


class CodexSession(Session):
    source = "codex"

    def __init__(self, path: Path):
        super().__init__(path)
        self.subagent = False

    def _line(self, line: str) -> None:
        d = json.loads(line)
        ts, kind, p = d.get("timestamp", ""), d.get("type"), d.get("payload") or {}
        if kind == "session_meta":
            self.id = p.get("id") or self.id
            self.cwd = p.get("cwd") or ""
            self.branch = (p.get("git") or {}).get("branch") or ""
            self.subagent = isinstance(p.get("source"), dict)  # spawned by another Codex thread, like a sidechain
            return
        if self.subagent:
            return
        t = p.get("type")
        if kind == "event_msg" and t == "user_message":
            # The IDE extension prepends its context; the prompt follows the last '## My request' heading.
            text = re.split(r"^## My request[^\n]*\n", p.get("message") or "", flags=re.M)[-1]
            text = " ".join(text.split())
            if text:
                self.prompts.append((ts, text))
                self.events.append((ts, "prompt", text[:120]))
                self.last_at = max(self.last_at, ts)
        elif kind == "event_msg" and t == "agent_message":
            self.last_at = max(self.last_at, ts)
        elif kind == "event_msg" and t in ("task_started", "task_complete", "turn_aborted"):
            self.claude_turn = t == "task_started"
        elif kind == "event_msg" and t == "thread_name_updated":
            self.title = p.get("thread_name") or self.title
        elif kind == "response_item" and t in ("function_call", "custom_tool_call"):
            self.last_at = max(self.last_at, ts)
            name, raw = p.get("name", ""), p.get("arguments") or p.get("input") or ""
            if name == "apply_patch":
                paths = PATCH_FILE.findall(raw)
                for fp in paths:
                    self.files[str(Path(self.cwd, fp.strip()))] = ts
                self.events.append((ts, "tool", f"apply_patch {', '.join(Path(f).name for f in paths)}"[:80]))
                return
            try:
                args = json.loads(raw) if t == "function_call" else {}
            except json.JSONDecodeError:
                args = {}
            desc = next((str(args[k]) for k in ("cmd", "query", "path") if args.get(k)), "")
            self.events.append((ts, "tool", f"{name} {' '.join(desc.split())[:60]}".strip()))
