"""Work units that share a PR or a Jira key become one unit (graph.merge_units)."""
import os
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest import mock

os.environ["THYNC_HOME"] = tempfile.mkdtemp()

from thync import graph  # noqa: E402


def iso(ago: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - ago))


def session(sid: str, branch: str, title: str, prs: dict, ago: float = 60):
    return SimpleNamespace(id=sid, source="claude_code", cwd="/home/me/work/app", branch=branch, title=title,
                           ai_title="", prompts=[(iso(ago), title)], prs=prs, files={}, events=[],
                           claude_turn=False, waiting=None, last_at=iso(ago), ago=ago)


PR = "https://github.com/o/app/pull/411"


class MergeUnits(unittest.TestCase):
    def build(self, sessions):
        with mock.patch.multiple(graph, SESSIONS=True, SOURCES={"claude_code"}), \
                mock.patch.object(graph, "load_sessions", return_value=[(s, time.time() - s.ago, 0) for s in sessions]):
            return graph.build_graph(7)

    def test_sessions_on_two_branches_with_the_same_pr_are_one_unit(self):
        g = self.build([
            session("a", "feat-rotate", "키 로테이션", {PR: (iso(600), "o/app", 411)}, ago=600),
            session("b", "review-loop", "Code review loop", {PR: (iso(60), "o/app", 411)}, ago=60),
            session("c", "other", "다른 일", {}),
        ])
        units = {u["id"]: u for u in g["units"]}
        nodes = {n["id"]: n for n in g["nodes"]}
        self.assertEqual(nodes["session:a"]["detail"]["unit"], nodes["session:b"]["detail"]["unit"])
        kept = nodes["session:a"]["detail"]["unit"]
        self.assertEqual(units[kept]["sessions"], 2)
        self.assertEqual(units[kept]["title"], "Code review loop")  # the latest session titles the unit
        self.assertEqual(nodes[f"pr:{PR}"]["detail"]["unit"], kept)
        self.assertNotEqual(nodes["session:c"]["detail"]["unit"], kept)
        self.assertEqual(len([u for u in units if u.startswith("branch:")]), 2)

    def test_a_ticket_unit_absorbs_a_branch_unit(self):
        units = {"jira:ABC-1": {"updated": 1, "title": "t", "glow": 0.0, "sessions": 1, "keys": ["ABC-1"], "working": False},
                 "branch:app:x": {"updated": 5, "title": "x", "glow": 0.7, "sessions": 2, "keys": [], "working": True}}
        moved = graph.merge_units(units, {"jira:ABC-1": {"pr:p"}, "branch:app:x": {"pr:p"}})
        self.assertEqual(moved, {"branch:app:x": "jira:ABC-1"})
        self.assertEqual(units["jira:ABC-1"]["sessions"], 3)
        self.assertTrue(units["jira:ABC-1"]["working"])
        self.assertEqual(units["jira:ABC-1"]["title"], "x")


if __name__ == "__main__":
    unittest.main()
