"""Regression tests for the issues an outside review found before the first public release."""
import json
import tempfile
import unittest
from pathlib import Path

from thalamus import merge, paths, routes, score, update


class EssentialSignals(unittest.TestCase):
    def test_job_without_its_essential_signal_is_not_ranked(self):
        job = {"id": "fast", "title": "Fast", "kinds": ["llm"], "essential": ["x.tps"],
               "metrics": [{"id": "x.tps", "w": 3}, {"id": "q.a", "w": 1}]}
        models = [{"id": "a", "name": "a", "kind": "llm", "metrics": {"q.a": 90}, "access": ["openrouter"]}]
        self.assertEqual(score.score_job(job, models), [])
        models[0]["metrics"]["x.tps"] = 200
        self.assertEqual(len(score.score_job(job, models)), 1)


class QualityFloor(unittest.TestCase):
    def test_price_cannot_carry_a_weak_model_into_budget(self):
        job = {"id": "bulk", "title": "Bulk", "kinds": ["llm"],
               "metrics": [{"id": "q.a", "w": 2}, {"id": "x.price", "w": 3, "higher": False, "log": True}]}
        mk = lambda i, q, p: {"id": i, "name": i, "kind": "llm", "metrics": {"q.a": q, "x.price": p},
                              "price": {"blended": p, "unit": "usd_per_mtok"}, "access": ["openrouter"]}
        rows = score.score_job(job, [mk("good", 90, 1.0), mk("ok", 80, 0.5), mk("weak", 10, 0.01), mk("floor", 5, 5)])
        picks = score.pick(rows)
        top_q = max(r["quality"] for r in rows)
        self.assertGreaterEqual(picks["budget"]["quality"], 0.75 * top_q)
        self.assertNotEqual(picks["budget"]["id"], "weak")

    def test_zero_is_a_real_price(self):
        self.assertEqual(score._price({"price": {"blended": 0.0}}), 0.0)


class VariantsStaySeparate(unittest.TestCase):
    def test_unmatched_effort_levels_do_not_share_scores(self):
        raw = {"openrouter": [],
               "arena": [{"source": "arena", "key": "x-high", "name": "Zeta 2 (High)", "lab": "acme", "kind": "llm",
                          "metrics": {"arena.coding": 1500}},
                         {"source": "arena", "key": "x-low", "name": "Zeta 2 (Low)", "lab": "acme", "kind": "llm",
                          "metrics": {"arena.text": 1300}}]}
        catalog, _ = merge.merge(raw)
        by = {m["id"]: m for m in catalog}
        low = next(m for i, m in by.items() if i.endswith("@low"))
        high = next(m for i, m in by.items() if i.endswith("@high"))
        self.assertNotIn("arena.coding", low["metrics"])
        self.assertNotIn("arena.text", high["metrics"])


class PublicBuildStaysClean(unittest.TestCase):
    def test_personal_only_sources_are_refused_in_public_builds(self):
        with self.assertRaises(SystemExit):
            update.run(extra=["aa"], offline=True, quiet=True)

    def test_personal_only_sources_are_not_default(self):
        self.assertNotIn("aa", update.SOURCES)
        self.assertNotIn("epoch_external", update.SOURCES)
        self.assertIn("aa.", update._closed_prefixes())
        self.assertIn("epochx.", update._closed_prefixes())

    def test_jobs_only_lean_on_public_or_declared_prefixes(self):
        known = ("aa.", "arena.", "llmstats.", "epoch.", "epochx.", "benchlm.", "eqbench.", "x.")
        for job in score.load_jobs():
            for m in job["metrics"]:
                self.assertTrue(m["id"].startswith(known), m["id"])


class PersonalPicks(unittest.TestCase):
    def setUp(self):
        self.entry = {"top": [
            {"id": "anthropic/claude-opus-9", "name": "Opus", "score": 90, "quality": 90, "price": 10,
             "access": ["openrouter"], "pickable": True},
            {"id": "google/gemini-9-pro", "name": "Gemini Pro", "score": 89, "quality": 89, "price": 4,
             "access": ["openrouter"], "pickable": True},
            {"id": "lab/unreleased", "name": "Secret", "score": 99, "quality": 99, "price": None,
             "access": [], "pickable": False}]}

    def test_subscription_needs_a_served_pattern(self):
        picks = routes.your_picks(self.entry, ["claude-cli", "agy"])
        self.assertEqual(picks, {})  # no openrouter access and nothing declared as served
        picks = routes.your_picks(self.entry, ["claude-cli", "agy"],
                                  served={"claude-cli": "^anthropic/claude-opus"})
        self.assertEqual(picks["best"]["id"], "anthropic/claude-opus-9")
        self.assertEqual(picks["best"]["via"], ["claude-cli"])

    def test_unpickable_models_never_appear(self):
        picks = routes.your_picks(self.entry, ["openrouter"])
        self.assertNotIn("lab/unreleased", [p["id"] for p in picks.values()])

    def test_personal_build_wins_only_when_fresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_data, old_personal = paths.DATA, paths.PERSONAL_DATA
            paths.DATA, paths.PERSONAL_DATA = Path(tmp) / "pub", Path(tmp) / "mine"
            try:
                for d, day in ((paths.DATA, "2026-11-02"), (paths.PERSONAL_DATA, "2026-10-26")):
                    d.mkdir(parents=True)
                    (d / "routes.json").write_text(json.dumps({"updated": day, "jobs": {}, "who": d.name}))
                self.assertEqual(routes._routes()["who"], "pub")
                (paths.PERSONAL_DATA / "routes.json").write_text(json.dumps({"updated": "2026-11-02", "jobs": {}, "who": "mine"}))
                self.assertEqual(routes._routes()["who"], "mine")
            finally:
                paths.DATA, paths.PERSONAL_DATA = old_data, old_personal


if __name__ == "__main__":
    unittest.main()


class SecondReview(unittest.TestCase):
    def test_seat_env_is_an_allowlist(self):
        import os
        from unittest import mock
        from thalamus import seats
        fake = {"PATH": "/bin", "DATABASE_URL": "postgres://u:p@h/db", "AWS_PROFILE": "prod",
                "ANTHROPIC_API_KEY": "x", "ANTHROPIC_BASE_URL": "https://proxy", "CLAUDE_CODE_USE_BEDROCK": "1",
                "LC_ALL": "C"}
        with mock.patch.dict(os.environ, fake, clear=True):
            env = seats.child_env()
        self.assertEqual(env["PATH"], "/bin")
        self.assertIn("LC_ALL", env)
        for gone in ("DATABASE_URL", "AWS_PROFILE", "ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "CLAUDE_CODE_USE_BEDROCK"):
            self.assertNotIn(gone, env)

    def test_free_models_keep_their_price_signal(self):
        job = {"id": "bulk", "title": "Bulk", "kinds": ["llm"],
               "metrics": [{"id": "q.a", "w": 1}, {"id": "x.price", "w": 1, "higher": False, "log": True}]}
        mk = lambda i, p: {"id": i, "name": i, "kind": "llm", "metrics": {"q.a": 80, "x.price": p},
                           "price": {"blended": p}, "access": ["openrouter"]}
        rows = {r["id"]: r for r in score.score_job(job, [mk("free", 0.0), mk("paid", 2.0), mk("mid", 0.5)])}
        self.assertIn("x.price", rows["free"]["basis"])
        self.assertGreater(rows["free"]["score"], rows["paid"]["score"])

    def test_personal_data_judged_by_source_freshness(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_data, old_personal = paths.DATA, paths.PERSONAL_DATA
            paths.DATA, paths.PERSONAL_DATA = Path(tmp) / "pub", Path(tmp) / "mine"
            try:
                paths.DATA.mkdir(parents=True); paths.PERSONAL_DATA.mkdir(parents=True)
                (paths.DATA / "routes.json").write_text(json.dumps(
                    {"updated": "2026-11-02", "jobs": {}, "who": "pub",
                     "sources": {"arena": {"rows": 5, "fetched": "2026-11-02"}}}))
                # rebuilt today offline, but from data fetched two weeks ago
                (paths.PERSONAL_DATA / "routes.json").write_text(json.dumps(
                    {"updated": "2026-11-03", "jobs": {}, "who": "mine",
                     "sources": {"arena": {"rows": 5, "fetched": "2026-10-19"}}}))
                self.assertEqual(routes._routes()["who"], "pub")
            finally:
                paths.DATA, paths.PERSONAL_DATA = old_data, old_personal

    def test_served_pattern_rescues_a_model_with_no_public_api(self):
        entry = {"top": [{"id": "google/gemini-sub-only", "name": "Sub only", "score": 95, "quality": 95, "price": None,
                          "access": [], "pickable": False, "unreleased": False}]}
        picks = routes.your_picks(entry, ["agy"], served={"agy": "^google/gemini-sub"})
        self.assertEqual(picks["best"]["via"], ["agy"])

    def test_opt_in_sources_need_personal_even_benchlm(self):
        for name in ("benchlm", "eqbench", "aa", "epoch_external"):
            with self.assertRaises(SystemExit):
                update.run(extra=[name], offline=True, quiet=True)

    def test_epoch_external_parses_its_files(self):
        import io
        import zipfile
        from unittest import mock
        from thalamus.sources import epoch_external
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("data/model_metadata.csv", "model_version,display_name,organization,date,accessibility\n"
                                                  "zeta-2_high,Zeta 2 (high),Acme,2026-10-01,API access\n")
            z.writestr("data/terminalbench_external.csv", "Model version,Accuracy mean\nzeta-2_high,0.5\nzeta-2_high,0.7\n")
        with mock.patch("thalamus.sources.epoch.http_get", return_value=buf.getvalue()):
            recs = epoch_external.fetch()
        self.assertEqual(recs[0]["source"], "epoch_external")
        self.assertEqual(recs[0]["metrics"]["epochx.terminalbench"], 0.7)

    def test_arena_with_no_fresh_board_fails(self):
        from unittest import mock
        from thalamus.sources import arena
        with tempfile.TemporaryDirectory() as tmp:
            arena.CACHE_DIR = Path(tmp)
            (Path(tmp) / "arena_text.json").write_text(json.dumps(
                [{"model_name": "m", "category": "overall", "rating": 1300}]))
            try:
                with mock.patch.object(arena, "_load", side_effect=RuntimeError("down")):
                    with self.assertRaises(RuntimeError):
                        arena.fetch()
            finally:
                arena.CACHE_DIR = None

    def test_personal_build_writes_outside_the_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_personal, old_data = paths.PERSONAL_DATA, update.DATA
            paths.PERSONAL_DATA = Path(tmp) / "mine"
            cache = paths.PERSONAL_DATA / "cache"
            cache.mkdir(parents=True)
            (cache / "openrouter.json").write_text(json.dumps({"fetched": "2026-11-02", "records": [
                {"source": "openrouter", "key": "acme/zeta-2", "name": "Zeta 2", "lab": "Acme", "kind": "llm",
                 "metrics": {}, "price": {"blended": 1.0, "unit": "usd_per_mtok"}, "context": 300000}]}))
            (cache / "arena.json").write_text(json.dumps({"fetched": "2026-11-02", "records": [
                {"source": "arena", "key": "llm:Zeta 2", "name": "Zeta 2", "lab": "Acme", "kind": "llm",
                 "metrics": {"arena.text": 1400}}]}))
            repo_routes = (paths.DATA / "routes.json").read_text(encoding="utf-8")
            try:
                update.run(offline=True, quiet=True, personal=True, extra=[])
                self.assertTrue((paths.PERSONAL_DATA / "routes.json").exists())
                self.assertEqual((paths.DATA / "routes.json").read_text(encoding="utf-8"), repo_routes)
            finally:
                paths.PERSONAL_DATA = old_personal
