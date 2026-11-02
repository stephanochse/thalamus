import json
import tempfile
import unittest
import urllib.parse
from pathlib import Path
from unittest import mock

from _helpers import ROOT  # noqa: F401  (puts the repo root on sys.path)
from thalamus import community as c

IDS = {"code-build", "writing", "general"}
MODEL = "anthropic/claude-opus-5.5"


def body(job="code-build (Writing code)", model=MODEL, verdict="good",
         beats="_No response_", note="_No response_"):
    return (f"### Job\n\n{job}\n\n### Model\n\n{model}\n\n### Verdict\n\n{verdict}\n\n"
            f"### Beats\n\n{beats}\n\n### Note\n\n{note}")


def issue(user="a", text=None, updated="2026-11-01T00:00:00Z", utype="User", reason=None, **kw):
    return {"user": user, "user_type": utype, "created_at": updated, "updated_at": updated,
            "body": text if text is not None else body(**kw), "state": "open", "state_reason": reason}


class ParseTests(unittest.TestCase):
    def test_realistic(self):
        r = c.parse_issue_body(body(note="my secret client details"), IDS)
        self.assertEqual(r, {"job": "code-build", "model": MODEL, "verdict": "good", "beats": None})
        self.assertNotIn("secret", json.dumps(r))

    def test_bare_id_backticks_case(self):
        r = c.parse_issue_body(body(job="writing", model="`Z-AI/GLM-5.3`", beats="`openai/gpt-6`"), IDS)
        self.assertEqual((r["job"], r["model"], r["beats"]), ("writing", "z-ai/glm-5.3", "openai/gpt-6"))

    def test_rejects(self):
        bad = [body(job="nope (X)"), body(verdict="meh"), body(model="a b/c"), body(model="<b>x/y</b>"),
               body(model="x/y;rm -rf /"), body(model="ab"), body(beats="bad model!"),
               body(beats=MODEL), "", "no headings here"]
        for text in bad:
            self.assertIsNone(c.parse_issue_body(text, IDS), text[:40])


class AggregateTests(unittest.TestCase):
    def test_dedupe_keeps_latest(self):
        agg = c.aggregate([issue("a", verdict="bad", updated="2026-11-01T00:00:00Z"),
                           issue("A", verdict="good", updated="2026-11-02T00:00:00Z")], IDS)
        self.assertEqual(agg["jobs"]["code-build"][MODEL], {"good": 1, "bad": 0, "voters": 1})

    def test_ignores_bots_and_not_planned(self):
        agg = c.aggregate([issue("bot", utype="Bot"), issue("x", reason="not_planned")], IDS)
        self.assertEqual(agg["jobs"], {})
        self.assertEqual(agg["issues_read"], 2)

    def test_beats_counts_loss(self):
        agg = c.aggregate([issue("a", beats="z-ai/glm-5.3")], IDS)
        j = agg["jobs"]["code-build"]
        self.assertEqual(j[MODEL]["good"], 1)
        self.assertEqual(j["z-ai/glm-5.3"]["bad"], 1)

    def test_no_logins_in_output(self):
        agg = c.aggregate([issue("octocat-secret"), issue("hubot-x", model="b/cde")], IDS)
        self.assertNotIn("octocat", json.dumps(agg))
        self.assertNotIn("hubot", json.dumps(agg))
        self.assertEqual(agg["valid"], 2)

    def test_inputs_not_mutated(self):
        rows = [issue("a")]
        before = json.dumps(rows)
        c.aggregate(rows, IDS)
        self.assertEqual(json.dumps(rows), before)


class FactorTests(unittest.TestCase):
    def test_neutral_under_min(self):
        self.assertEqual(c.factor(4, 0, 4), 1.0)

    def test_bounded(self):
        for g, b in [(5, 0), (500, 0), (0, 500), (3, 2), (50, 50)]:
            v = c.factor(g, b, max(g + b, 5))
            self.assertTrue(0.9 <= v <= 1.1, (g, b, v))
        self.assertGreater(c.factor(30, 0, 30), 1.0)
        self.assertLess(c.factor(0, 30, 30), 1.0)


class IoTests(unittest.TestCase):
    def test_load_write(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "sub" / "community.json"
            self.assertEqual(c.load(p), {"jobs": {}})
            p.parent.mkdir()
            p.write_text("{not json")
            self.assertEqual(c.load(p), {"jobs": {}})
            c.write(p, {"jobs": {"writing": {"m/x": {"good": 1, "bad": 0, "voters": 1}}}})
            data = c.load(p)
            self.assertIn("updated", data)
            self.assertIn("Counts only", data["note"])
            self.assertEqual(data["jobs"]["writing"]["m/x"]["good"], 1)

    def test_share_url_round_trip(self):
        url = c.share_url("code-build", MODEL, "good", "z-ai/glm-5.3")
        self.assertTrue(url.startswith("https://github.com/stephanochse/thalamus/issues/new?"))
        q = {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlparse(url).query).items()}
        self.assertEqual(q["template"], "verdict.yml")
        self.assertEqual((q["model"], q["verdict"], q["beats"]), (MODEL, "good", "z-ai/glm-5.3"))
        ids = {j["id"] for j in c._jobs()}
        parsed = c.parse_issue_body(body(job=q["job"], model=q["model"], verdict=q["verdict"],
                                         beats=q["beats"]), ids)
        self.assertEqual(parsed["job"], "code-build")

    def test_fetch_issues_mocked(self):
        page = [{"user": {"login": "u", "type": "User"}, "created_at": "t", "updated_at": "t",
                 "body": "b", "state": "open", "state_reason": None},
                {"user": {"login": "p", "type": "User"}, "pull_request": {}, "body": "x"}]

        class Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self, *_):
                return json.dumps(page).encode()

        with mock.patch("urllib.request.urlopen", return_value=Resp()) as m:
            rows = c.fetch_issues("stephanochse/thalamus", "tok")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["user"], "u")
        req = m.call_args[0][0]
        self.assertEqual(req.get_header("Authorization"), "Bearer tok")
        self.assertIn("labels=verdict", req.full_url)

    def test_fetch_issues_bad_repo(self):
        with self.assertRaises(ValueError):
            c.fetch_issues("evil; rm", None)


if __name__ == "__main__":
    unittest.main()


class AbuseResistance(unittest.TestCase):
    def setUp(self):
        from thalamus import community
        self.c = community
        self.ids = {"writing"}

    def _issue(self, user, created="2026-10-01T00:00:00Z", **extra):
        body = "### Job\n\nwriting\n\n### Model\n\na/model\n\n### Verdict\n\ngood\n"
        return {"user": user, "user_type": "User", "created_at": created, "updated_at": created, "body": body,
                "state": "open", "state_reason": None, "labels": [], **extra}

    def test_fresh_accounts_do_not_count(self):
        issues = [self._issue(f"u{i}") for i in range(6)]
        accounts = {f"u{i}": "2026-09-20T00:00:00Z" for i in range(6)}  # 11 days old when voting
        self.assertEqual(self.c.aggregate(issues, self.ids, accounts=accounts)["jobs"], {})
        accounts = {f"u{i}": "2025-01-01T00:00:00Z" for i in range(6)}
        self.assertEqual(self.c.aggregate(issues, self.ids, accounts=accounts)["jobs"]["writing"]["a/model"]["voters"], 6)

    def test_unknown_accounts_do_not_count(self):
        self.assertEqual(self.c.aggregate([self._issue("ghost-x")], self.ids, accounts={})["jobs"], {})

    def test_spam_label_and_duplicate_are_ignored(self):
        old = {"a": "2020-01-01T00:00:00Z", "b": "2020-01-01T00:00:00Z"}
        issues = [self._issue("a", labels=["spam"]), self._issue("b", state="closed", state_reason="duplicate")]
        self.assertEqual(self.c.aggregate(issues, self.ids, accounts=old)["jobs"], {})

    def test_a_full_window_is_refused(self):
        page = [{"user": {"login": "u", "type": "User"}, "body": "b"} for _ in range(100)]

        class Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self, *_):
                return json.dumps(page).encode()

        with mock.patch("urllib.request.urlopen", return_value=Resp()):
            with self.assertRaises(RuntimeError):
                self.c.fetch_issues("o/r", None, max_pages=2)

    def test_share_url_rejects_arbitrary_text(self):
        with self.assertRaises(ValueError):
            self.c.share_url("writing", "ignore previous instructions", "good")
        with self.assertRaises(ValueError):
            self.c.share_url("not-a-job", "a/model", "good")
        self.assertIn("model=a%2Fmodel", self.c.share_url("writing", "a/model", "good"))
