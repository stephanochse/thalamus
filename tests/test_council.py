import json
import os
import unittest
from unittest import mock

from _helpers import temp_home
from thalamus import council, seats


def fake_available(missing=()):
    """Every seat is usable except the lanes named in `missing`."""
    def available(entry):
        return f"{entry['lane']} unavailable" if entry["lane"] in missing else None
    return available


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.home = temp_home(self)
        patcher = mock.patch.object(seats, "available", fake_available())
        patcher.start()
        self.addCleanup(patcher.stop)

    def keys(self, plan):
        return [s["key"] for s in council.sitting(plan)]

    def test_harder_is_one_seat(self):
        self.assertEqual(len(council.sitting(council.plan_seats("harder", host="unknown"))), 1)

    def test_deep_skips_host_family(self):
        plan = council.plan_seats("deep", host="claude")
        self.assertEqual(self.keys(plan), ["gpt", "grok", "gemini"])
        skipped = [s for s in plan if s["skip"]]
        self.assertEqual([s["family"] for s in skipped], ["anthropic"])
        self.assertIn("host family", skipped[0]["skip"])

    def test_host_names_map_to_families(self):
        for host, gone in (("codex", "gpt"), ("gpt", "gpt"), ("grok", "grok"), ("agy", "gemini")):
            self.assertNotIn(gone, self.keys(council.plan_seats("max", host=host)))

    def test_max_adds_extras_when_key_exists(self):
        keys = self.keys(council.plan_seats("max", host="claude"))
        self.assertEqual(keys[:3], ["gpt", "grok", "gemini"])
        self.assertEqual(keys[3:], ["glm-5.3", "kimi-k3"])

    def test_max_extras_skipped_with_note_without_key(self):
        with mock.patch.object(seats, "available", fake_available(missing=("openrouter",))):
            plan = council.plan_seats("max", host="claude")
        extras = [s for s in plan if s.get("extra")]
        self.assertEqual(len(extras), 2)
        for s in extras:
            self.assertIn("openrouter unavailable", s["skip"])
        self.assertEqual(self.keys(plan), ["gpt", "grok", "gemini"])

    def test_unavailable_subscription_seat_is_skipped_and_reported(self):
        with mock.patch.object(seats, "available", fake_available(missing=("codex",))):
            plan = council.plan_seats("deep", host="unknown")
        self.assertEqual(self.keys(plan), ["claude", "grok", "gemini"])
        skip = [s for s in plan if s["skip"]]
        self.assertEqual(skip[0]["family"], "openai")

    def test_metered_seats_never_sit_in_private_context(self):
        plan = council.plan_seats("max", host="claude", context="private")
        self.assertNotIn("glm-5.3", self.keys(plan))
        reasons = [s["skip"] for s in plan if s.get("extra")]
        self.assertTrue(all("private" in r for r in reasons))
        explicit = council.plan_seats("harder", context="private", seats=["z-ai/glm-5.3"])
        self.assertIn("private", explicit[0]["skip"])

    def test_private_contexts_come_from_config(self):
        (self.home / "config.json").write_text(json.dumps({"private_contexts": ["secret-client"]}), encoding="utf-8")
        self.assertFalse(council.metered_allowed("secret-client"))
        self.assertTrue(council.metered_allowed("private"))

    def test_config_families_and_extras(self):
        (self.home / "config.json").write_text(json.dumps({"council": {
            "families": ["openai", "deepseek"], "extras": ["qwen-3.8"]}}), encoding="utf-8")
        self.assertEqual(self.keys(council.plan_seats("max", host="claude")), ["gpt", "deepseek-v4-pro", "qwen-3.8"])

    def test_diversity_prefers_new_lab_and_country(self):
        (self.home / "config.json").write_text(json.dumps({"council": {
            "families": ["openai", "xai", "deepseek", "mistral"]}}), encoding="utf-8")
        # openai first by order; then new lab+country beats a second US lab.
        picked = self.keys(council.plan_seats("deep", host="unknown"))
        self.assertEqual(picked[0], "gpt")
        self.assertEqual(set(picked[1:]), {"deepseek-v4-pro", "mistral-large"})

    def test_subscription_seat_preferred_within_family(self):
        (self.home / "seats.json").write_text(json.dumps({"seats": {
            "gpt-or": {"lane": "openrouter", "id": "openai/gpt-x", "family": "openai", "lab": "OpenAI", "country": "US"}}}),
            encoding="utf-8")
        self.assertEqual(self.keys(council.plan_seats("harder"))[0], "gpt")

    def test_bad_tier(self):
        with self.assertRaises(ValueError):
            council.plan_seats("nope")


class RunTests(unittest.TestCase):
    def setUp(self):
        self.home = temp_home(self)
        p = mock.patch.object(seats, "available", fake_available(missing=("grok",)))
        p.start()
        self.addCleanup(p.stop)
        self.calls = []

        def fake_call(spec, prompt, system=None, timeout=600, max_tokens=None):
            self.calls.append((spec, prompt))
            return {"text": f"answer from {spec}", "error": None, "seconds": 0.1, "cost": None,
                    "model": spec, "label": spec}

        p = mock.patch.object(seats, "call", fake_call)
        p.start()
        self.addCleanup(p.stop)

    def test_deep_solve_report(self):
        run = council.run_council("Pick a database. Contact me at bob@example.com.", draft="my draft",
                                  tier="deep", host="claude")
        meta = run.meta()
        self.assertEqual(meta["status"], "done")
        self.assertEqual([s["key"] for s in meta["seats"]], ["gpt", "gemini"])
        self.assertEqual(len(self.calls), len(meta["seats"]))
        # scrubbed before sending, and the host draft never goes out in solve mode
        for _, prompt in self.calls:
            self.assertNotIn("bob@example.com", prompt)
            self.assertNotIn("my draft", prompt)
        report = run.report()
        self.assertIn("Skipped (not called):", report)
        self.assertIn("host family (anthropic)", report)
        self.assertIn("grok unavailable", report)
        self.assertIn("## Your job now (host)", report)
        for seat in meta["seats"]:
            self.assertEqual(seat["status"], "done")

    def test_review_mode_sends_draft_with_stances(self):
        council.run_council("Is this right?", draft="the draft text", tier="deep", mode="review", host="claude")
        self.assertTrue(all("the draft text" in p for _, p in self.calls))
        self.assertIn("red team", self.calls[0][1])

    def test_review_needs_draft(self):
        with self.assertRaises(ValueError):
            council.run_council("x", tier="harder", mode="review")

    def test_failed_seat_is_reported_not_faked(self):
        def failing(spec, prompt, system=None, timeout=600, max_tokens=None):
            return {"text": "", "error": "boom", "seconds": 0, "cost": None, "model": None, "label": spec}

        with mock.patch.object(seats, "call", failing):
            run = council.run_council("q", draft="d", tier="harder", host="unknown")
        self.assertEqual(run.meta()["seats"][0]["status"], "error")
        self.assertIn("(no answer: boom)", run.report())
        self.assertIn("0 of 1 seats answered", run.report())

    def test_max_runs_round_two_anonymized(self):
        run = council.run_council("q", draft="d", tier="max", host="claude")
        meta = run.meta()
        self.assertEqual(len(meta["round2"]), len(meta["seats"]))
        round2 = [p for _, p in self.calls if "Round 2" in p]
        self.assertTrue(round2)
        self.assertIn("Response A", round2[0])

    def test_no_seat_available(self):
        with mock.patch.object(seats, "available", fake_available(missing=("codex", "claude-cli", "grok", "agy"))):
            with self.assertRaises(RuntimeError):
                council.run_council("q", draft="d", tier="deep")

    def test_refuses_inside_a_seat(self):
        with mock.patch.dict(os.environ, {seats.DEPTH_VAR: "1"}):
            with self.assertRaises(RuntimeError):
                council.run_council("q", draft="d")

    def test_background_job(self):
        run_id = council.start_job(task="q", draft="d", tier="harder", host="claude")
        result = council.job_result(run_id, wait_seconds=20)
        self.assertEqual(result["status"], "done")
        self.assertIn("Council report", result["report"])

    def test_job_result_unknown_run_reports_progress(self):
        self.assertEqual(council.job_result("20260101-000000-deep-abcd")["status"], "starting")

    def test_run_ids_cannot_escape_the_runs_folder(self):
        for bad in ("../../etc", "..", "20260101-000000-deep-abcd/../../x", "a/b"):
            with self.assertRaises(ValueError):
                council.job_result(bad)


if __name__ == "__main__":
    unittest.main()
