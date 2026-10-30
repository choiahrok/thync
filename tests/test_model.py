"""Brain model and log parsing: python3 -m unittest discover tests"""
import os
import tempfile
import unittest

os.environ["THYNC_HOME"] = tempfile.mkdtemp()

from thync import model  # noqa: E402
from thync.config import WORKSPACE_SIZE  # noqa: E402
from thync.sources.claude_code import SLASH  # noqa: E402
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
    def test_slash_command_with_args(self):
        m = SLASH.search("<command-message>x</command-message>\n<command-name>/pr-review-watch</command-name>\n"
                         "<command-args>https://github.com/o/r/pull/1</command-args>")
        self.assertEqual((m.group(1), m.group(2)), ("/pr-review-watch", "https://github.com/o/r/pull/1"))

    def test_clean_jira_summary(self):
        self.assertEqual(clean("[API][console] Audit log screen"), "Audit log screen")


if __name__ == "__main__":
    unittest.main()
