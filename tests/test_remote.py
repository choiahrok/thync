"""A hub thync showing sessions another machine's thync serves at /sessions.json (export.py, sources/remote.py)."""
import json
import os
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

os.environ["THYNC_HOME"] = tempfile.mkdtemp()

from thync import ask, export, graph, server  # noqa: E402
from thync.sources import remote  # noqa: E402
from thync.sources.claude_code import Session  # noqa: E402


def iso(ago: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(time.time() - ago))


def session_log(folder: Path, sid: str, cwd: str, ask_id: str = "") -> Session:
    lines = [
        {"type": "user", "timestamp": iso(7200), "cwd": cwd, "gitBranch": "abc-12-audit",
         "message": {"content": "첫 요청"}},
        {"type": "user", "timestamp": iso(600), "cwd": cwd, "message": {"content": "감사 로그 고쳐줘"}},
        {"type": "assistant", "timestamp": iso(60), "message": {"stop_reason": "tool_use", "content": [
            {"type": "tool_use", "id": "t1", "name": "Edit", "input": {"file_path": f"{cwd}/audit.py"}}]}},
    ]
    if ask_id:
        lines.append({"type": "assistant", "timestamp": iso(30), "message": {"stop_reason": "tool_use", "content": [
            {"type": "tool_use", "id": ask_id, "name": "AskUserQuestion",
             "input": {"questions": [{"question": "어느 쪽?", "options": [{"label": "A"}, {"label": "B"}]}]}}]}})
    path = folder / f"{sid}.jsonl"
    path.write_text("".join(json.dumps(x, ensure_ascii=False, separators=(",", ":")) + "\n" for x in lines))
    s = Session(path)
    s.update()
    return s


class RemoteThync:
    """A real thync HTTP server standing in for the one on the remote machine (the tunnel's far end)."""

    def __init__(self, sessions):
        self.sessions = sessions
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.port = self.httpd.server_address[1]

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class HubTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.remote_session = session_log(self.dir, "aaaa-remote", "/home/me/work/app", ask_id="q-remote")
        sessions = [(self.remote_session, time.time() - 30, 1)]
        self.patches = [
            mock.patch.object(server, "TOKEN", "secret"),
            mock.patch.object(export, "load_sessions", return_value=sessions),
            mock.patch.object(export, "SESSIONS", True),
            mock.patch.object(export, "profile_of", return_value="회사"),
        ]
        for p in self.patches:
            p.start()
        self.far = RemoteThync(sessions)
        self.r = remote.Remote({"name": "devbox1", "ssh": "devbox1", "port": 8765, "thync_home": "~/.thync"})
        self.r.local_port, self.r.token = self.far.port, "secret"
        remote._remotes[:] = [self.r]

    def tearDown(self):
        remote._remotes.clear()
        self.far.close()
        for p in self.patches:
            p.stop()

    def test_fetch_reads_sessions_then_skips_an_unchanged_body(self):
        self.r.fetch()
        self.assertTrue(self.r.ok)
        [s] = self.r.sessions
        self.assertEqual((s.host, s.id, s.repo, s.profile, s.subs), ("devbox1", "aaaa-remote", "app", "회사", 1))
        self.assertEqual(s.waiting["id"], "q-remote")
        etag = self.r.etag
        self.assertTrue(etag)
        status, _, _ = self.r.request("/sessions.json?days=30", etag=etag)
        self.assertEqual(status, 304)
        self.r.fetch()  # 304 keeps what it had
        self.assertEqual(len(self.r.sessions), 1)

    def test_wrong_token_is_reported_and_dropped(self):
        self.r.token = "wrong"
        with self.assertRaises(remote.RemoteError):
            self.r.fetch()
        self.assertEqual(self.r.token, "")

    def test_remote_sessions_join_the_hub_brain(self):
        self.r.fetch()
        local = session_log(self.dir, "bbbb-local", "/Users/me/tool/thync")
        with mock.patch.multiple(graph, SESSIONS=True, SOURCES={"claude_code"}), \
                mock.patch.object(graph, "load_sessions", return_value=[(local, time.time() - 30, 0)]):
            g = graph.build_graph(7)
        nodes = {n["id"]: n for n in g["nodes"]}
        far, near = nodes["session:aaaa-remote"], nodes["session:bbbb-local"]
        self.assertEqual((far["detail"]["host"], far["profile"], far["detail"]["repo"]), ("devbox1", "회사", "app"))
        self.assertEqual(near["detail"]["host"], "")
        # Files are per machine; the remote's live subagent keeps its session working.
        self.assertIn("file:devbox1:/home/me/work/app/audit.py", nodes)
        self.assertIn("file:/Users/me/tool/thync/audit.py", nodes)
        self.assertTrue(far["detail"]["claude_working"] is False)  # waiting on my answer is my turn
        self.assertEqual(far["detail"]["waiting"]["id"], "q-remote")
        self.assertEqual(g["hosts"], [{"name": "devbox1", "ok": True, "error": "", "seen": int(self.r.seen)}])
        self.assertTrue(any(a.get("host") == "devbox1" for a in g["activity"]))

    def test_unreachable_remote_keeps_sessions_but_not_as_working(self):
        self.r.fetch()
        self.r.down("thync 가 응답하지 않음")
        [s] = self.r.sessions
        self.assertEqual((s.subs, s.claude_turn, s.answerable), (0, False, False))
        self.assertEqual(remote.status()[0]["ok"], False)

    def test_answer_reaches_the_machine_whose_hook_holds_the_question(self):
        self.r.fetch()
        ask.poll("q-remote")  # the remote's question hook is polling its own thync for this id
        self.assertIs(remote.owner_of_question("q-remote"), self.r)
        status, _ = self.r.post("/answer", {"id": "q-remote", "answers": ["A"]})
        self.assertEqual(status, 204)
        self.assertEqual(ask.poll("q-remote"), ["A"])

    def test_a_question_only_the_hook_knows_reaches_the_hub_and_gets_its_answer(self):
        # Claude Code logs the question only after the hook returns; the hook announces it with POST /ask.
        quiet = session_log(self.dir, "dddd-quiet", "/home/me/work/app")
        with mock.patch.object(export, "load_sessions", return_value=[(quiet, time.time() - 5, 0)]):
            self.r.fetch()
            self.assertIsNone(self.r.sessions[0].waiting)  # the log alone shows nothing
            status, _ = self.r.post("/ask", {"id": "q-hook", "session": "dddd-quiet",
                                             "questions": [{"question": "어느 색?", "options": [{"label": "빨강"}]}]})
            self.assertEqual(status, 204)
            self.r.fetch()
        [s] = self.r.sessions
        self.assertEqual((s.waiting["id"], s.waiting["questions"][0]["options"], s.answerable), ("q-hook", ["빨강"], True))
        self.assertIs(remote.owner_of_question("q-hook"), self.r)
        status, _ = self.r.post("/answer", {"id": "q-hook", "answers": ["빨강"]})
        self.assertEqual(status, 204)
        self.assertEqual(ask.poll("q-hook"), ["빨강"])  # what the hook on that machine collects
        self.assertIsNone(ask.held_for("dddd-quiet"))  # answered: no longer shown as waiting

    def test_forwarded_handoff_uses_the_node_it_is_sent(self):
        self.r.fetch()
        node = {"id": "pr:https://github.com/o/r/pull/3", "roles": ["sent"],
                "detail": {"url": "https://github.com/o/r/pull/3", "repo": "r"}}
        with mock.patch.object(server, "HANDOFF", True), mock.patch.object(server, "REFLEX_HOST", ""), \
                mock.patch.object(server, "start_reflex", return_value=(202, "시작했어요")) as start:
            status, reply = self.r.post("/reflex", {"node": node, "approve": False})
        self.assertEqual((status, reply["message"]), (202, "시작했어요"))
        self.assertEqual(start.call_args.args[0]["detail"]["url"], node["detail"]["url"])


class ExportTest(unittest.TestCase):
    def test_only_what_the_graph_reads_goes_out(self):
        folder = Path(tempfile.mkdtemp())
        s = session_log(folder, "cccc", "/home/me/x")
        s.prompts = [(iso(9 * 3600 + i), f"old {i}") for i in range(50)] + s.prompts
        d = export.session_dict(s, time.time(), 0, time.time(), {})
        texts = [p for _, p in d["prompts"]]
        self.assertEqual(texts[0], "old 0")          # the first prompt (hand-off skill and PR)
        self.assertEqual(texts[-1], "감사 로그 고쳐줘")  # the last prompt
        self.assertNotIn("old 10", texts)             # older than the focus window
        rs = remote.RemoteSession("devbox1", json.loads(json.dumps(d)))
        self.assertEqual(rs.prompts[-1][1], "감사 로그 고쳐줘")


if __name__ == "__main__":
    unittest.main()
