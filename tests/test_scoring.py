import json
import os
import tempfile
import unittest
from pathlib import Path

from thalamus import merge, score


def model(mid, **kw):
    base = {"id": mid, "name": mid, "kind": "llm", "metrics": {}, "price": None, "access": ["openrouter"], "where": {}}
    base.update(kw)
    return base


JOB = {"id": "t", "title": "Test", "kinds": ["llm"], "min_coverage": 0.4,
       "metrics": [{"id": "q.a", "w": 3}, {"id": "q.b", "w": 1}, {"id": "x.price", "w": 1, "higher": False, "log": True}]}


class ScoreTests(unittest.TestCase):
    def setUp(self):
        self.models = [
            model("top", metrics={"q.a": 90, "q.b": 80, "x.price": 10}, price={"blended": 10, "unit": "usd_per_mtok"}),
            model("near", metrics={"q.a": 86, "q.b": 78, "x.price": 1}, price={"blended": 1, "unit": "usd_per_mtok"}),
            model("cheap", metrics={"q.a": 70, "q.b": 60, "x.price": 0.1}, price={"blended": 0.1, "unit": "usd_per_mtok"}),
            model("weak", metrics={"q.a": 20, "q.b": 20, "x.price": 0.05}, price={"blended": 0.05, "unit": "usd_per_mtok"}),
            model("priceonly", metrics={"x.price": 0.01}, price={"blended": 0.01, "unit": "usd_per_mtok"}),
            model("image", kind="t2i", metrics={"q.a": 99}),
        ]

    def test_price_alone_never_ranks(self):
        ids = [r["id"] for r in score.score_job(JOB, self.models)]
        self.assertNotIn("priceonly", ids)
        self.assertNotIn("image", ids)

    def test_picks_follow_the_bands(self):
        job = {**JOB, "metrics": [m for m in JOB["metrics"] if m["id"] != "x.price"]}
        rows = score.score_job(job, self.models)
        picks = score.pick(rows)
        self.assertEqual(picks["best"]["id"], rows[0]["id"])
        top_q = max(r["quality"] for r in rows)
        self.assertGreaterEqual(picks["value"]["quality"], 0.9 * top_q)
        self.assertGreaterEqual(picks["budget"]["quality"], 0.75 * top_q)
        self.assertLessEqual(picks["budget"]["price"], picks["value"]["price"])

    def test_mix_is_cheaper_than_all_best(self):
        job = {**JOB, "metrics": [m for m in JOB["metrics"] if m["id"] != "x.price"]}
        rows = score.score_job(job, self.models)
        mix = score.mix_savings(score.pick(rows))
        self.assertIsNotNone(mix)
        self.assertGreater(mix["saves_pct"], 0)

    def test_unreachable_models_are_never_picked(self):
        models = [dict(m, access=[]) if m["id"] == "top" else m for m in self.models]
        rows = score.score_job(JOB, models)
        self.assertIn("top", [r["id"] for r in rows])                  # still shown in the table
        self.assertNotIn("top", [p["id"] for p in score.pick(rows).values()])  # but never picked

    def test_missing_source_does_not_unrank_everyone(self):
        job = {**JOB, "metrics": JOB["metrics"] + [{"id": "never.reported", "w": 10}]}
        self.assertTrue(score.score_job(job, self.models))

    def test_jobs_file_is_valid(self):
        jobs = score.load_jobs()
        ids = [j["id"] for j in jobs]
        self.assertEqual(len(ids), len(set(ids)))
        for j in jobs:
            self.assertTrue(j["metrics"], j["id"])
            self.assertTrue(any(score._is_quality(m["id"]) for m in j["metrics"]), j["id"])


class MergeTests(unittest.TestCase):
    def test_names_match_across_sources(self):
        self.assertEqual(merge.tokens("Claude Sonnet 5"), merge.tokens("Claude 5 Sonnet (Thinking)"))
        self.assertEqual(merge.canon("GPT-6.1 Terra (high)"), merge.canon("GPT-6.1 Terra"))
        self.assertEqual(merge.variant_of("GPT-6.1 Terra (high)"), "high")
        self.assertEqual(merge.lab_id("Z.ai"), "zhipu")
        self.assertEqual(merge.lab_id("MoonshotAI"), "moonshot")

    def test_merge_attaches_metrics_and_variants(self):
        raw = {
            "openrouter": [{"source": "openrouter", "key": "acme/rocket-2", "name": "Rocket 2", "lab": "OpenAI",
                            "kind": "llm", "metrics": {}, "price": {"blended": 2.0, "unit": "usd_per_mtok"},
                            "context": 400000}],
            "aa": [{"source": "aa", "key": "rocket-2-high", "name": "Rocket 2 (high)", "lab": "OpenAI", "kind": "llm",
                    "metrics": {"aa.intelligence": 70}}],
            "arena": [{"source": "arena", "key": "rocket-2", "name": "rocket-2", "lab": "OpenAI", "kind": "llm",
                       "metrics": {"arena.text": 1400}}],
        }
        catalog, unmatched = merge.merge(raw)
        by_id = {m["id"]: m for m in catalog}
        self.assertIn("acme/rocket-2", by_id)
        self.assertIn("acme/rocket-2@high", by_id)
        self.assertEqual(by_id["acme/rocket-2@high"]["metrics"]["aa.intelligence"], 70)
        self.assertEqual(by_id["acme/rocket-2"]["metrics"]["arena.text"], 1400)
        self.assertEqual(by_id["acme/rocket-2@high"]["metrics"]["arena.text"], 1400)
        self.assertIn("openrouter", by_id["acme/rocket-2"]["access"])
        self.assertEqual(unmatched, [])


class LearnTests(unittest.TestCase):
    def test_three_verdicts_needed_to_overturn(self):
        with tempfile.TemporaryDirectory() as tmp:
            from thalamus import learn, paths
            old = paths.FEEDBACK
            paths.FEEDBACK = Path(tmp) / "feedback.jsonl"
            try:
                rows = [{"id": "a", "name": "a", "score": 90.0}, {"id": "b", "name": "b", "score": 85.0}]
                learn.record("t", "b", "good")
                self.assertEqual(learn.personalize("t", rows)[0]["id"], "a")
                for _ in range(6):
                    learn.record("t", "b", "good")
                    learn.record("t", "a", "bad")
                self.assertEqual(learn.personalize("t", rows)[0]["id"], "b")
                self.assertEqual([r["id"] for r in rows], ["a", "b"])  # input untouched
            finally:
                paths.FEEDBACK = old


if __name__ == "__main__":
    unittest.main()
