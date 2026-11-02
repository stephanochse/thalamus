import unittest

from _helpers import temp_home
from thalamus import mcp_server


class McpTests(unittest.TestCase):
    def setUp(self):
        temp_home(self)

    def rpc(self, method, params=None, msg_id=1):
        return mcp_server.handle({"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params or {}})

    def test_initialize_and_list(self):
        init = self.rpc("initialize", {"protocolVersion": "2025-03-26"})
        self.assertEqual(init["result"]["serverInfo"]["name"], "thalamus")
        names = [t["name"] for t in self.rpc("tools/list")["result"]["tools"]]
        self.assertEqual(names, ["council", "council_result", "ask_model", "list_seats", "doctor",
                                 "routing_rules", "route", "leaderboard", "feedback", "scout"])

    def test_notification_gets_no_reply(self):
        self.assertIsNone(mcp_server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))

    def test_list_seats_tool(self):
        out = self.rpc("tools/call", {"name": "list_seats", "arguments": {}})["result"]
        self.assertFalse(out["isError"])
        self.assertIn("| gpt |", out["content"][0]["text"])

    def test_council_requires_host_draft(self):
        out = self.rpc("tools/call", {"name": "council", "arguments": {"task": "q", "host_draft": " "}})["result"]
        self.assertIn("host_draft", out["content"][0]["text"])

    def test_route_without_routes_module_is_a_clear_error(self):
        out = self.rpc("tools/call", {"name": "route", "arguments": {"task": "x"}})["result"]
        if out["isError"]:
            self.assertIn("routes", out["content"][0]["text"])

    def test_unknown_tool_and_method(self):
        self.assertIn("error", self.rpc("tools/call", {"name": "nope"}))
        self.assertEqual(self.rpc("bogus")["error"]["code"], -32601)

    def test_bad_arguments_are_a_tool_error(self):
        out = self.rpc("tools/call", {"name": "council_result", "arguments": {}})["result"]
        self.assertTrue(out["isError"])


if __name__ == "__main__":
    unittest.main()
