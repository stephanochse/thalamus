import json
import os
import unittest
from unittest import mock

from _helpers import temp_home
from thalamus import seats


class SeatTests(unittest.TestCase):
    def setUp(self):
        self.home = temp_home(self)

    def test_default_registry_has_expected_lanes(self):
        reg = seats.load_registry()
        for key, lane in (("gpt", "codex"), ("claude", "claude-cli"), ("grok", "grok"), ("gemini", "agy"),
                          ("local", "ollama"), ("glm-5.3", "openrouter")):
            self.assertEqual(reg[key]["lane"], lane)
        self.assertFalse(reg["gpt"]["metered"])
        self.assertTrue(reg["glm-5.3"]["metered"])
        for entry in reg.values():
            for field in ("label", "id", "family", "lab", "country", "open_weights", "metered"):
                self.assertIn(field, entry)

    def test_resolve_key_and_effort(self):
        e = seats.resolve("gpt:xhigh")
        self.assertEqual((e["key"], e["effort"], e["id"]), ("gpt", "xhigh", "gpt-6-astra"))
        self.assertEqual(seats.resolve("gpt")["effort"], "high")

    def test_resolve_raw_slug(self):
        e = seats.resolve("z-ai/glm-5.3")
        self.assertEqual((e["lane"], e["id"], e["family"], e["metered"]), ("openrouter", "z-ai/glm-5.3", "zhipu", True))
        self.assertIsNone(e["effort"])
        online = seats.resolve("z-ai/glm-5.3:online:high")
        self.assertEqual((online["id"], online["effort"]), ("z-ai/glm-5.3:online", "high"))

    def test_resolve_unknown(self):
        with self.assertRaises(ValueError):
            seats.resolve("nonsense")

    def test_user_overrides_add_change_remove(self):
        (self.home / "seats.json").write_text(json.dumps({"seats": {
            "gpt": {"id": "gpt-custom"},
            "mine": {"lane": "openai-compatible", "id": "m1", "base_url": "http://localhost:9/v1", "family": "custom"},
            "grok": None}}), encoding="utf-8")
        reg = seats.load_registry()
        self.assertEqual(reg["gpt"]["id"], "gpt-custom")
        self.assertEqual(reg["gpt"]["lane"], "codex")
        self.assertTrue(reg["mine"]["metered"])
        self.assertNotIn("grok", reg)

    def test_key_from_env_file(self):
        (self.home / "env").write_text('# x\nexport OPENROUTER_API_KEY="sk-or-test"\n', encoding="utf-8")
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENROUTER_API_KEY", None)
            self.assertEqual(seats.api_key(), "sk-or-test")
        with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "from-env"}):
            self.assertEqual(seats.api_key(), "from-env")

    def test_available_reports_missing_key_and_cli(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENROUTER_API_KEY", None)
            self.assertIn("no OpenRouter key", seats.available(seats.resolve("glm-5.3")))
        with mock.patch.object(seats, "find_exe", return_value=None):
            self.assertIn("codex CLI not found", seats.available(seats.resolve("gpt")))

    def test_child_env_depth(self):
        with mock.patch.dict(os.environ, {seats.DEPTH_VAR: "1"}):
            self.assertEqual(seats.depth(), 1)
            self.assertEqual(seats.child_env()[seats.DEPTH_VAR], "2")

    def test_call_never_raises(self):
        r = seats.call("nonsense", "hi")
        self.assertTrue(r["error"])
        self.assertEqual(r["text"], "")
        for k in ("text", "error", "seconds", "cost", "model", "label"):
            self.assertIn(k, r)

    def test_call_openrouter_payload(self):
        sent = {}

        def fake_post(url, payload, headers, timeout):
            sent.update(url=url, payload=payload, headers=headers)
            return {"choices": [{"message": {"content": "hello"}}],
                    "usage": {"cost": 0.01, "prompt_tokens": 3, "completion_tokens": 1}, "model": "z-ai/glm-5.3"}

        with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "k"}), mock.patch.object(seats, "_post", fake_post):
            r = seats.call("glm-5.3:low", "q", system="s", timeout=5)
        self.assertEqual((r["text"], r["cost"], r["error"]), ("hello", 0.01, None))
        self.assertEqual(sent["payload"]["reasoning"], {"effort": "low"})
        self.assertEqual(sent["payload"]["messages"][0]["role"], "system")
        self.assertEqual(sent["headers"]["Authorization"], "Bearer k")


if __name__ == "__main__":
    unittest.main()
