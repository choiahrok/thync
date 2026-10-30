"""Sources other than session logs, with stubbed HTTP and gh responses."""
import io
import json
import os
import tempfile
import time
import unittest
import urllib.parse
from unittest import mock

os.environ["THYNC_HOME"] = tempfile.mkdtemp()

from thync import graph  # noqa: E402
from thync.sources import github, jira, notion  # noqa: E402


def reply(body) -> io.BytesIO:
    return io.BytesIO(json.dumps(body).encode())


class GitHub(unittest.TestCase):
    def test_search_items_become_default_branch_commits(self):
        items = [{"html_url": "https://github.com/o/r/commit/1", "repository": {"full_name": "o/r"},
                  "commit": {"message": "[API] Fix ABC-7\n\nbody", "author": {"date": "2026-10-29T14:04:33.000+09:00"}}}]
        self.assertEqual(github.parse_search(items), [{"slug": "o/r", "branch": "", "at": "2026-10-29T14:04:33.000+09:00",
                                                       "message": "[API] Fix ABC-7\n\nbody",
                                                       "url": "https://github.com/o/r/commit/1"}])

    def test_pushes_keep_the_newest_per_branch(self):
        events = [
            {"type": "PushEvent", "repo": {"name": "o/r"}, "created_at": "2026-10-29T02:00:00Z",
             "payload": {"ref": "refs/heads/abc-7-audit", "head": "b"}},
            {"type": "PushEvent", "repo": {"name": "o/r"}, "created_at": "2026-10-28T02:00:00Z",
             "payload": {"ref": "refs/heads/abc-7-audit", "head": "a"}},
            {"type": "PushEvent", "repo": {"name": "o/r"}, "created_at": "2026-10-28T01:00:00Z",
             "payload": {"ref": "refs/tags/v1", "head": "t"}},
            {"type": "WatchEvent", "repo": {"name": "o/x"}, "created_at": "2026-10-28T00:00:00Z", "payload": {}},
        ]
        got = github.parse_pushes(events)
        self.assertEqual([(p["branch"], p["head"], p["at"]) for p in got], [("abc-7-audit", "b", "2026-10-29T02:00:00Z")])
        self.assertEqual(got[0]["url"], "https://github.com/o/r/tree/abc-7-audit")


class JiraMine(unittest.TestCase):
    def test_search_mine_reads_assigned_tickets(self):
        body = {"issues": [{"key": "ABC-9", "fields": {
            "summary": "감사 로그", "status": {"name": "진행 중"}, "updated": "2026-10-29T14:04:33.000+0900",
            "parent": {"key": "ABC-1", "fields": {"summary": "콘솔"}}}}]}
        with mock.patch.object(jira, "_open", return_value=reply(body)) as op:
            got = jira.search_mine("https://x.atlassian.net", "Basic abc")
        self.assertEqual(got, {"ABC-9": {"summary": "감사 로그", "status": "진행 중", "epic": "ABC-1",
                                         "epic_summary": "콘솔", "updated": "2026-10-29T14:04:33.000+0900"}})
        req = op.call_args[0][0]
        url = urllib.parse.urlsplit(req.full_url)
        self.assertEqual(url.path, "/rest/api/3/search/jql")
        self.assertIn("assignee = currentUser()", urllib.parse.parse_qs(url.query)["jql"][0])
        self.assertEqual(req.get_method(), "GET")


class Notion(unittest.TestCase):
    PAGE = {"object": "page", "id": "p1", "url": "https://www.notion.so/p1", "last_edited_time": "2026-10-29T05:00:00.000Z",
            "last_edited_by": {"id": "u1"},
            "properties": {"Tags": {"type": "multi_select"}, "Name": {"type": "title", "title": [
                {"plain_text": "ABC-9 "}, {"plain_text": "설계"}]}}}

    def test_parse_takes_the_title_property(self):
        self.assertEqual(notion.parse([self.PAGE, {"object": "database", "id": "d"}]),
                         [{"id": "p1", "title": "ABC-9 설계", "url": "https://www.notion.so/p1",
                           "at": "2026-10-29T05:00:00.000Z"}])

    def test_parse_filters_by_last_editor(self):
        self.assertEqual(notion.parse([self.PAGE], "someone-else"), [])

    def test_search_only_posts_to_search(self):
        with mock.patch.object(notion, "_open", return_value=reply({"results": [self.PAGE]})) as op:
            got = notion.search("secret")
        req = op.call_args[0][0]
        self.assertEqual((req.full_url, req.get_method()), ("https://api.notion.com/v1/search", "POST"))
        self.assertEqual(req.get_header("Notion-version"), notion.VERSION)
        self.assertNotIn("secret", req.full_url)
        self.assertEqual(got, [self.PAGE])


class GraphWithoutSessions(unittest.TestCase):
    def test_commits_tickets_and_pages_make_a_graph(self):
        now = time.time()
        iso = lambda ago: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - ago))  # noqa: E731
        commits = [{"slug": "o/r", "branch": "abc-9-audit", "at": iso(600), "message": "Add audit log",
                    "url": "https://github.com/o/r/tree/abc-9-audit", "personal": False},
                   {"slug": "me/tool", "branch": "main", "at": iso(7200), "message": "Fix typo",
                    "url": "https://github.com/me/tool/commit/1", "personal": True}]
        tickets = {"ABC-9": {"summary": "감사 로그", "status": "진행 중", "updated": iso(3600), "mine": True},
                   "ABC-5": {"summary": "키 회전", "status": "In Progress", "updated": iso(5 * 86400), "mine": True}}
        pages = [{"id": "p1", "title": "ABC-9 설계", "url": "https://www.notion.so/p1", "at": iso(1800)}]
        with mock.patch.multiple(graph, SESSIONS=False, SOURCES={"github", "jira", "notion"}), \
                mock.patch.object(github, "my_commits", return_value=commits), \
                mock.patch.object(github, "review_requests", return_value=[]), \
                mock.patch.object(github, "sent_reviews", return_value=[]), \
                mock.patch.object(notion, "recent_pages", return_value=pages), \
                mock.patch.object(jira, "read_json", return_value=tickets):
            g = graph.build_graph(7)
        nodes = {n["id"]: n for n in g["nodes"]}
        self.assertEqual(nodes["branch:r:abc-9-audit"]["detail"]["unit"], "jira:ABC-9")
        self.assertEqual(nodes["notion:p1"]["detail"]["unit"], "jira:ABC-9")
        self.assertIn("focus", nodes["branch:r:abc-9-audit"]["roles"])
        self.assertEqual(nodes["repo:tool"]["profile"], "개인")
        self.assertIn("running", nodes["jira:ABC-5"]["roles"])  # in progress, outside the workspace
        cards = {c["id"]: c["column"] for c in g["board"]}
        self.assertEqual((cards["jira:ABC-9"], cards["jira:ABC-5"]), ("doing", "background"))
        self.assertTrue(g["activity"])

    def test_with_session_logs_only_sessions_compete_for_focus(self):
        commits = [{"slug": "o/r", "branch": "feat", "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "message": "x", "url": "https://github.com/o/r/tree/feat", "personal": False}]
        with mock.patch.multiple(graph, SESSIONS=True, SOURCES={"claude_code", "github"}), \
                mock.patch.object(graph, "load_sessions", return_value=[]), \
                mock.patch.object(github, "my_commits", return_value=commits), \
                mock.patch.object(github, "review_requests", return_value=[]), \
                mock.patch.object(github, "sent_reviews", return_value=[]):
            g = graph.build_graph(7)
        branch = next(n for n in g["nodes"] if n["id"] == "branch:r:feat")
        self.assertNotIn("last_at", branch["detail"])
        self.assertNotIn("focus", branch["roles"])
        self.assertEqual(next(u for u in g["units"] if u["id"] == "branch:r:feat")["updated"], 0)


class EpochTest(unittest.TestCase):
    def test_offsets_without_colon_parse_on_every_supported_python(self):
        from thync.util import epoch
        self.assertEqual(epoch("2026-10-29T10:04:48.123+0900"), epoch("2026-10-29T01:04:48.123Z"))
        self.assertEqual(epoch("2026-10-29T10:04:48+09:00"), epoch("2026-10-29T01:04:48Z"))


if __name__ == "__main__":
    unittest.main()
