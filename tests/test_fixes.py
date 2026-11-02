import contextlib
import io
import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from thync import graph, review, store, util
from thync.sources import github, jira


class FixesTest(unittest.TestCase):
    def test_card_keeps_quotes_inside_a_title(self):
        meta, _ = store.parse_card('---\ntitle: "Fix" the "retry" path\nid: "a:1"\n---\nnote')
        self.assertEqual((meta["title"], meta["id"]), ('"Fix" the "retry" path', "a:1"))

    def test_write_text_ignores_a_planted_temp_symlink(self):
        with tempfile.TemporaryDirectory() as d:
            target, victim = Path(d, "card.md"), Path(d, "victim")
            victim.write_text("keep")
            Path(d, "card.tmp").symlink_to(victim)  # the old, predictable temp name
            util.write_text(target, "new")
            self.assertEqual((target.read_text(), victim.read_text()), ("new", "keep"))
            self.assertEqual(sorted(p.name for p in Path(d).iterdir()), ["card.md", "card.tmp", "victim"])

    def test_token_file_readable_by_others_warns(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d, "jira_token")
            path.write_text("secret\n")
            os.chmod(path, 0o644)
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                self.assertEqual(util.read_secret(path), "secret")
            self.assertIn("chmod 600", err.getvalue())

    def test_failed_slug_lookup_is_retried(self):
        fail = subprocess.CompletedProcess([], 1, "", "boom")
        ok = subprocess.CompletedProcess([], 0, "New/Name\n", "")
        with mock.patch.object(github.subprocess, "run", side_effect=[fail, ok]):
            self.assertEqual(github.canonical_slug("Old/Repo-x"), "old/repo-x")
            self.assertEqual(github.canonical_slug("Old/Repo-x"), "new/name")

    def test_same_commit_is_not_reviewed_twice(self):
        calls = []

        def gh(*args, stdin=None):
            calls.append(args[:2])
            return json.dumps({"title": "t", "body": "", "author": "a", "base": "main", "head": "f", "sha": "abc"})

        saved = {}
        with mock.patch.object(review, "gh", gh), mock.patch.object(review, "save_reflex", lambda u, r: saved.update(r)):
            review.review("https://github.com/o/r/pull/1", {"approve": False, "reviewed": "abc:False"})
        self.assertEqual((saved["status"], saved["reviewed"]), ("same", "abc:False"))  # kept for the next drop
        self.assertEqual(calls, [("api", "repos/o/r/pulls/1")])  # no diff fetched, nothing posted

    def test_reviewed_mark_survives_restarts_of_the_record(self):
        with mock.patch.object(review, "threading") as th, \
                mock.patch.object(review, "load_reflexes", return_value={"u": {"status": "failed", "reviewed": "abc:False"}}), \
                mock.patch.object(review, "save_reflex"):
            review.start_review("u", True)
        self.assertEqual(th.Thread.call_args.kwargs["args"][1]["reviewed"], "abc:False")

    def test_write_text_keeps_the_existing_mode(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d, "card.md")
            path.write_text("old")
            os.chmod(path, 0o644)
            util.write_text(path, "new")
            self.assertEqual(path.stat().st_mode & 0o777, 0o644)

    def test_jira_search_follows_next_page(self):
        pages = [{"issues": [{"key": "A-1", "fields": {"summary": "s", "status": {"name": "x"}}}], "nextPageToken": "p2",
                  "isLast": False},
                 {"issues": [{"key": "A-2", "fields": {"summary": "t", "status": {"name": "y"}}}], "isLast": True}]
        with mock.patch.object(jira, "_open", side_effect=[io.BytesIO(json.dumps(p).encode()) for p in pages]) as op:
            got = jira.search_mine("https://x.atlassian.net", "Basic a")
        self.assertEqual(sorted(got), ["A-1", "A-2"])
        self.assertIn("nextPageToken=p2", op.call_args_list[1][0][0].full_url)

    def test_my_tickets_follow_the_selected_period(self):
        old = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 10 * 86400))
        tickets = {"A-9": {"summary": "old", "status": "In Progress", "updated": old, "mine": True}}
        with mock.patch.multiple(graph, SESSIONS=False, SOURCES={"jira"}), \
                mock.patch.object(jira, "read_json", return_value=tickets):
            nodes = {n["id"] for n in graph.build_graph(7)["nodes"]}
        self.assertNotIn("jira:A-9", nodes)

    def test_unanswered_question_is_waiting_until_answered(self):
        from thync.sources.claude_code import Session
        from thync.sources.codex import CodexSession
        ask = {"questions": [{"question": "Which?", "header": "h", "options": [{"label": "A"}, {"label": "B"}]}]}
        claude = [
            {"type": "assistant", "timestamp": "t1", "message": {"content": [
                {"type": "tool_use", "id": "q1", "name": "AskUserQuestion", "input": ask}]}},
            {"type": "user", "timestamp": "t2", "message": {"content": [{"type": "tool_result", "tool_use_id": "q1"}]}}]
        codex = [
            {"type": "session_meta", "payload": {"id": "c", "cwd": "/w"}},
            {"type": "response_item", "timestamp": "t1", "payload": {
                "type": "function_call", "name": "request_user_input", "call_id": "k1", "arguments": json.dumps(ask)}},
            {"type": "response_item", "timestamp": "t2", "payload": {"type": "function_call_output", "call_id": "k1"}}]
        for cls, lines in ((Session, claude), (CodexSession, codex)):
            with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
                f.write("".join(json.dumps(x, separators=(",", ":")) + "\n" for x in lines[:-1]))
            self.addCleanup(os.unlink, f.name)
            s = cls(Path(f.name))
            s.update()
            self.assertEqual(s.waiting["questions"], [{"question": "Which?", "options": ["A", "B"]}], cls.__name__)
            with open(f.name, "a") as f2:
                f2.write(json.dumps(lines[-1], separators=(",", ":")) + "\n")
            s.update()
            self.assertIsNone(s.waiting, cls.__name__)


if __name__ == "__main__":
    unittest.main()
