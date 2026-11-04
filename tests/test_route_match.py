"""Job matching in route(): one generic word must not decide a multi-part task (regressions from 5 Nov 2026)."""
import json
import os
import unittest
from unittest import mock

from _helpers import temp_home  # noqa: F401  (puts the repo on sys.path)
from thalamus import classifier, routes

TELEGRAM_BRIEF = ("build a Telegram bot personal assistant: morning brief from a dashboard JSON, two-way replies, "
                  "voice note transcription, queued tasks executed by an agent on a Windows PC")
BUILD_JOBS = {j["id"] for j in routes._jobs_meta() if j.get("group") == "Build"}


def _never(*_):
    raise AssertionError("the classifier must not be called on a strong keyword match")


class Matching(unittest.TestCase):
    def test_multi_part_build_brief_is_not_decided_by_json(self):
        d = routes.classify_detail(TELEGRAM_BRIEF)
        self.assertNotEqual(d["job"], "extraction")
        self.assertIn(d["job"], BUILD_JOBS)
        self.assertEqual(d["confidence"], "high")

    def test_parts_of_a_brief_are_listed(self):
        also = [a["job"] for a in routes.classify_detail(TELEGRAM_BRIEF)["also"]]
        self.assertIn("transcription", also)

    def test_keyword_inside_a_longer_keyword_counts_once(self):
        d = routes.classify_detail("turn my voice note into a task")
        self.assertEqual(d["job"], "transcription")
        self.assertNotIn("voice", [a["job"] for a in d["also"]])
        d = routes.classify_detail("write landing page copy")
        self.assertEqual(d["job"], "writing")
        self.assertNotIn("landing page", d["matched"])

    def test_one_word_with_a_close_rival_is_low_confidence(self):
        d = routes.classify_detail("json voice agent")
        self.assertEqual(d["confidence"], "low")

    def test_one_clear_word_is_medium(self):
        self.assertEqual(routes.classify_detail("convert this json")["confidence"], "medium")

    def test_no_keyword_falls_back_to_general(self):
        d = routes.classify_detail("hello there")
        self.assertEqual((d["job"], d["confidence"], d["method"]), ("general", "none", "default"))

    def test_classify_keeps_its_old_shape(self):
        job, matched = routes.classify("fix the flaky checkout test")
        self.assertEqual(job, "code-build")
        self.assertIsInstance(matched, list)


class ClassifierFallback(unittest.TestCase):
    def test_used_only_when_weak(self):
        routes.classify_detail(TELEGRAM_BRIEF, classifier=_never)  # strong: never asked
        pick = lambda task, labels: {"choice": "code-agent", "probability": 0.9, "model": "m"}
        d = routes.classify_detail("json voice agent", classifier=pick)
        self.assertEqual((d["job"], d["method"]), ("code-agent", "classifier"))
        self.assertEqual(d["classifier"]["probability"], 0.9)

    def test_unsure_or_unknown_answer_keeps_the_keyword_result(self):
        for answer in (None, {"choice": "not-a-job", "probability": 0.99}):
            d = routes.classify_detail("json voice agent", classifier=lambda t, l, a=answer: a)
            self.assertEqual((d["job"], d["method"]), ("extraction", "keywords"))

    def test_labels_cover_every_job(self):
        seen = {}
        routes.classify_detail("hello there", classifier=lambda t, labels: seen.update(labels))
        self.assertEqual(set(seen), {j["id"] for j in routes._jobs_meta()})

    def test_parse_applies_the_floor(self):
        labels = {"a": "A", "b": "B"}
        ok = {"model": "m", "answers": {"job": {"choice": "a", "probabilities": {"a": 0.8, "b": 0.2}}}}
        self.assertEqual(classifier.parse(ok, labels)["choice"], "a")
        unsure = {"answers": {"job": {"choice": "a", "probabilities": {"a": 0.4, "b": 0.35}}}}
        self.assertIsNone(classifier.parse(unsure, labels))
        self.assertIsNone(classifier.parse({}, labels))

    def test_choose_scrubs_the_text_and_never_raises(self):
        sent = {}

        def fake_post(body, key, timeout):
            sent.update(body)
            return {"answers": {"job": {"choice": "a", "probabilities": {"a": 1}}}}
        with mock.patch.object(classifier, "env_value", return_value="k"), \
                mock.patch.object(classifier, "_post", fake_post):
            self.assertEqual(classifier.choose("mail jane@example.com about it", {"a": "A"})["choice"], "a")
        self.assertNotIn("jane@example.com", sent["state"])
        self.assertEqual(sent["questions"]["job"]["type"], "choice")
        with mock.patch.object(classifier, "env_value", return_value="k"), \
                mock.patch.object(classifier, "_post", side_effect=OSError("down")):
            self.assertIsNone(classifier.choose("x", {"a": "A"}))
        with mock.patch.object(classifier, "env_value", return_value=None):
            self.assertIsNone(classifier.choose("x", {"a": "A"}))

    def test_off_unless_asked(self):
        with mock.patch.dict(os.environ, {"THALAMUS_CLASSIFIER": ""}):
            self.assertFalse(classifier.enabled({}))
            self.assertTrue(classifier.enabled({"classifier": True}))
        with mock.patch.dict(os.environ, {"THALAMUS_CLASSIFIER": "0"}):
            self.assertFalse(classifier.enabled({"classifier": True}))
        self.assertIsNone(routes._classifier(False, {"classifier": True}))
        self.assertEqual(classifier.model_from({"classifier": {"model": "x/y"}}), "x/y")


class NoPublicScores(unittest.TestCase):
    def setUp(self):
        temp_home(self)
        payload = {"updated": "2026-11-02", "jobs": {"transcription": {
            "title": "Transcription and speech-to-text", "kinds": ["stt"], "metrics": [], "top": [], "picks": {}},
            "general": {"title": "General", "kinds": ["llm"], "metrics": [], "top": [], "picks": {"best": {"id": "a"}}}}}
        patcher = mock.patch.object(routes, "_routes", return_value=json.loads(json.dumps(payload)))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_empty_job_says_so_and_offers_a_local_tool(self):
        r = routes.route("transcribe this voice note", job="transcription", classifier=False)
        self.assertEqual(r["picks"], {})
        self.assertTrue(r["no_public_scores"])
        self.assertIn("no picks", r["note"])
        names = [o["name"] for o in r["local_options"]]
        self.assertIn("faster-whisper", names)
        self.assertTrue(all(isinstance(o["installed"], bool) for o in r["local_options"]))

    def test_job_with_picks_has_no_such_note(self):
        r = routes.route("hello", job="general", classifier=False)
        self.assertNotIn("no_public_scores", r)


if __name__ == "__main__":
    unittest.main()
