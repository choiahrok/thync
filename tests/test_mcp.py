import unittest
from unittest import mock

from thync import mcp


class McpTest(unittest.TestCase):
    def test_protocol(self):
        init = mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}})
        self.assertEqual(init["result"]["protocolVersion"], "2025-03-26")
        self.assertIsNone(mcp.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        self.assertEqual(mcp.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"][0]["name"], "thync_now")
        self.assertEqual(mcp.handle({"jsonrpc": "2.0", "id": 3, "method": "nope"})["error"]["code"], -32601)

    def test_tool_error_is_reported_not_raised(self):
        with mock.patch.object(mcp, "build_graph", side_effect=OSError):
            out = mcp.handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "thync_now"}})
        self.assertTrue(out["result"]["isError"])

    def test_malformed_requests_get_errors(self):
        import json, subprocess, sys
        lines = ['nope', '{"jsonrpc":"2.0","id":5,"method":"tools/call","params":["x"]}', '{"jsonrpc":"2.0","id":6,"method":"ping"}']
        out = subprocess.run([sys.executable, "-m", "thync.mcp"], input="\n".join(lines) + "\n", capture_output=True,
                             text=True, timeout=30).stdout
        codes = [json.loads(line).get("error", {}).get("code") for line in out.splitlines()]
        self.assertEqual(codes, [-32700, -32603, None])

if __name__ == "__main__":
    unittest.main()
