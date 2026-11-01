"""Brain model and log parsing: python3 -m unittest discover tests"""
import json
import os
import tempfile
import unittest
from pathlib import Path

os.environ["THYNC_HOME"] = tempfile.mkdtemp()

from thync import model  # noqa: E402
from thync.config import WORKSPACE_SIZE  # noqa: E402
from thync.sources.claude_code import SLASH  # noqa: E402
from thync.sources.codex import CodexSession  # noqa: E402
from thync.sources.jira import clean  # noqa: E402


def session(i: int, now: float, unit: str) -> dict:
    return {"id": f"session:{i}", "kind": "workThread", "roles": [], "glow": 0.0, "status": "active",
            "detail": {"last_at": now - 60 * i, "unit": unit, "act": model.retention(60 * i)}}


class Model(unittest.TestCase):
    def test_retention_fades_from_one(self):
        self.assertAlmostEqual(model.retention(0), 1.0)
        self.assertGreater(model.retention(3600), model.retention(86400))
        self.assertGreater(model.retention(86400), 0.0)

    def test_workspace_holds_at_most_four(self):
        now = 1_000_000.0
        nodes = {f"session:{i}": session(i, now, f"u{i % 3}") for i in range(8)}
        level = model.think(now, nodes, set())
        focused = [n for n in nodes.values() if "focus" in n["roles"]]
        self.assertEqual(len(focused), WORKSPACE_SIZE)
        self.assertIn("focus", nodes["session:0"]["roles"])  # the most recent prompt always gets in
        self.assertGreater(level, 0.9)


class Parsing(unittest.TestCase):
    def test_codex_log(self):
        lines = [
            {"type": "session_meta", "timestamp": "t0",
             "payload": {"id": "abc", "cwd": "/w/repo", "git": {"branch": "feat-x"}, "source": "vscode"}},
            {"type": "event_msg", "timestamp": "t1", "payload": {"type": "task_started"}},
            {"type": "event_msg", "timestamp": "t1", "payload": {
                "type": "user_message", "message": "# Context from my IDE setup:\n## Open tabs:\n- a.py\n"
                                                   "## My request for Codex:\nfix the  bug\n"}},
            {"type": "response_item", "timestamp": "t2", "payload": {
                "type": "function_call", "name": "exec_command", "arguments": '{"cmd": "ls -la"}'}},
            {"type": "response_item", "timestamp": "t3", "payload": {
                "type": "custom_tool_call", "name": "apply_patch",
                "input": "*** Begin Patch\n*** Update File: src/a.py\n@@\n-x\n+y\n*** End Patch"}},
            {"type": "event_msg", "timestamp": "t4", "payload": {"type": "thread_name_updated", "thread_name": "Fix"}},
        ]
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
            f.write("".join(json.dumps(x) + "\n" for x in lines) + '{"type": "event_msg", "pay')  # half-written
        self.addCleanup(os.unlink, f.name)
        s = CodexSession(Path(f.name))
        s.update()
        self.assertEqual((s.id, s.cwd, s.branch, s.title), ("abc", "/w/repo", "feat-x", "Fix"))
        self.assertEqual(s.prompts, [("t1", "fix the bug")])
        self.assertEqual([e[2] for e in s.events if e[1] == "tool"], ["exec_command ls -la", "apply_patch a.py"])
        self.assertEqual(s.files, {"/w/repo/src/a.py": "t3"})
        self.assertTrue(s.claude_turn)
        self.assertEqual(s.last_at, "t3")

    def test_slash_command_with_args(self):
        m = SLASH.search("<command-message>x</command-message>\n<command-name>/pr-review-watch</command-name>\n"
                         "<command-args>https://github.com/o/r/pull/1</command-args>")
        self.assertEqual((m.group(1), m.group(2)), ("/pr-review-watch", "https://github.com/o/r/pull/1"))

    def test_clean_jira_summary(self):
        self.assertEqual(clean("[API][console] Audit log screen"), "Audit log screen")


if __name__ == "__main__":
    unittest.main()
