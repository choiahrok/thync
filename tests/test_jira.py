import io
import json
import unittest
import urllib.request
from unittest import mock

from thync.sources import jira


class JiraTest(unittest.TestCase):
    def test_fetch_reads_summary_status_and_parent(self):
        body = {"fields": {"summary": "[API] 감사 로그", "status": {"name": "진행 중"},
                           "parent": {"key": "ABC-1", "fields": {"summary": "콘솔"}}}}
        with mock.patch.object(jira, "_open", return_value=io.BytesIO(json.dumps(body).encode())) as op:
            got = jira.fetch("https://x.atlassian.net", "Basic abc", "ABC-9")
        self.assertEqual(got, {"summary": "[API] 감사 로그", "status": "진행 중", "epic": "ABC-1", "epic_summary": "콘솔"})
        self.assertEqual(op.call_args[0][0].full_url, "https://x.atlassian.net/rest/api/3/issue/ABC-9?fields=summary,status,parent")

    def test_redirects_are_not_followed(self):
        req = urllib.request.Request("https://x.atlassian.net/a", headers={"Authorization": "Basic abc"})
        self.assertIsNone(jira._NoRedirect().redirect_request(req, None, 302, "Found", {}, "https://evil.example/"))

    def test_graph_lookups_record_only_jira_shaped_keys(self):
        jira._seen.clear()
        j = jira.Jira()
        j.name("ABC-12"), j.status("feat-3"), j.unit_of("ABC-1")
        self.assertEqual(jira._seen, {"ABC-12", "ABC-1"})


if __name__ == "__main__":
    unittest.main()
