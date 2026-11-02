import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

import _helpers  # noqa: F401  (puts the repo root on sys.path)
from thalamus import brainmap
from thalamus.score import load_jobs

ROOT = Path(__file__).resolve().parent.parent
SVG_TEXT = "{http://www.w3.org/2000/svg}text"


def fake_payload():
    def job(title, group, best_lab=None):
        if best_lab is None:
            return {"title": title, "group": group, "picks": {}, "top": []}
        return {"title": title, "group": group, "picks": {"best": {"id": "m/x", "name": "Model X"}},
                "top": [{"id": "m/x", "name": "Model X", "lab": best_lab, "score": 90}]}
    return {"updated": "2026-11-02", "jobs": {
        "a": job("Writing, copy and voice", "Voice", "Anthropic"),
        "b": job("Math & <hard> reasoning", "Think", "OpenAI"),
        "c": job("Fast local transcription", "Make"),
    }}


META = [{"id": "b", "title": "x", "group": "Think"}, {"id": "a", "title": "x", "group": "Voice"},
        {"id": "c", "title": "x", "group": "Make"}]


def texts(svg):
    return ["".join(t.itertext()) for t in ET.fromstring(svg).iter(SVG_TEXT)]


class BrainmapTests(unittest.TestCase):
    def test_parses_and_has_titles(self):
        found = texts(brainmap.render_svg(fake_payload(), META))
        for j in fake_payload()["jobs"].values():
            self.assertIn(brainmap.shorten(j["title"], 28), found)
        self.assertIn("THALAMUS", found)
        self.assertIn("week of 2026-11-02", found)

    def test_themes_differ(self):
        p = fake_payload()
        self.assertNotEqual(brainmap.render_svg(p, META, "light"), brainmap.render_svg(p, META, "dark"))

    def test_no_picks_says_no_data(self):
        self.assertIn("no data yet", texts(brainmap.render_svg(fake_payload(), META)))

    def test_escaping(self):
        svg = brainmap.render_svg(fake_payload(), META)
        self.assertNotIn("<hard>", svg)
        self.assertIn("&amp;", svg)
        self.assertIn("Math & <hard> reasoning", texts(svg))

    def test_deterministic_and_inputs_untouched(self):
        p = fake_payload()
        before = json.dumps(p, sort_keys=True)
        self.assertEqual(brainmap.render_svg(p, META), brainmap.render_svg(p, META))
        self.assertEqual(before, json.dumps(p, sort_keys=True))

    def test_shorten(self):
        s = brainmap.shorten("Following instructions and structured output", 28)
        self.assertLessEqual(len(s), 28)
        self.assertTrue(s.endswith("..."))
        self.assertEqual(brainmap.shorten("Short", 28), "Short")
        self.assertLessEqual(len(brainmap.shorten("Supercalifragilisticexpialidocious_word", 20)), 20)

    def test_legend_counts_winning_labs_only(self):
        found = texts(brainmap.render_svg(fake_payload(), META))
        self.assertIn("Anthropic", found)
        self.assertIn("OpenAI", found)
        self.assertNotIn("Google", found)

    def test_write_both_themes(self):
        with tempfile.TemporaryDirectory() as d:
            paths = brainmap.write(fake_payload(), META, Path(d) / "assets")
            self.assertEqual([p.name for p in paths], ["brain-map-light.svg", "brain-map-dark.svg"])
            for p in paths:
                ET.parse(p)

    def test_real_data(self):
        payload = json.loads((ROOT / "data" / "routes.json").read_text(encoding="utf-8"))
        meta = load_jobs()
        for theme in ("light", "dark"):
            svg = brainmap.render_svg(payload, meta, theme)
            ET.fromstring(svg)
            self.assertLess(len(svg), 60_000)
            found = texts(svg)
            for j in payload["jobs"].values():
                self.assertIn(brainmap.shorten(j.get("short") or j["title"], 28), found)


if __name__ == "__main__":
    unittest.main()
