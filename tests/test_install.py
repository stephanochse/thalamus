import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _helpers import temp_home
from thalamus import install

RULES = "# Rules\n\nUse the council when asked.\n"


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.state = temp_home(self)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name) / "user"
        self.sup = self.home / "support"
        for d in (".claude", ".codex", ".cursor", ".gemini", ".grok"):
            (self.home / d).mkdir(parents=True)
        (self.sup / "Claude").mkdir(parents=True)
        (self.sup / "Code" / "User").mkdir(parents=True)
        p = mock.patch.object(install, "app_support", lambda home: self.sup)
        p.start()
        self.addCleanup(p.stop)

    def make(self, **kw):
        return install.Installer(home=self.home, state=self.state, rules=RULES, use_cli=False, **kw)

    def run_installer(self, **kw):
        inst = self.make(**kw)
        inst.run()
        return inst

    def statuses(self, inst):
        return {t: s for t, s, _ in inst.results}

    def test_second_run_changes_nothing(self):
        first = self.run_installer()
        self.assertIn("updated", self.statuses(first).values())
        snapshot = {p: p.read_text(encoding="utf-8") for p in self.home.rglob("*") if p.is_file()}
        second = self.run_installer()
        self.assertNotIn("updated", self.statuses(second).values())
        again = {p: p.read_text(encoding="utf-8") for p in self.home.rglob("*") if p.is_file()}
        self.assertEqual(snapshot, again)

    def test_markers_and_user_content_preserved(self):
        md = self.home / ".claude" / "CLAUDE.md"
        md.write_text("# My own notes\n\nKeep this.\n", encoding="utf-8")
        self.run_installer()
        text = md.read_text(encoding="utf-8")
        self.assertIn("Keep this.", text)
        self.assertEqual(text.count(install.MD_START), 1)
        # user edits above and below the block survive a rules change
        md.write_text("Top line\n\n" + text + "\nBottom line\n", encoding="utf-8")
        inst = install.Installer(home=self.home, state=self.state, rules=RULES + "\nNew rule.\n", use_cli=False)
        inst.run()
        new = md.read_text(encoding="utf-8")
        self.assertIn("Top line", new)
        self.assertIn("Bottom line", new)
        self.assertIn("New rule.", new)
        self.assertEqual(new.count(install.MD_START), 1)

    def test_json_configs_keep_other_servers(self):
        cursor = self.home / ".cursor" / "mcp.json"
        cursor.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}}, indent=2), encoding="utf-8")
        self.run_installer()
        data = json.loads(cursor.read_text(encoding="utf-8"))
        self.assertIn("other", data["mcpServers"])
        self.assertEqual(data["mcpServers"]["thalamus"]["args"], ["-m", "thalamus", "mcp"])
        vs = json.loads((self.sup / "Code" / "User" / "mcp.json").read_text(encoding="utf-8"))
        self.assertEqual(vs["servers"]["thalamus"]["type"], "stdio")

    def test_codex_toml_block(self):
        cfg = self.home / ".codex" / "config.toml"
        cfg.write_text("model = 'x'\n", encoding="utf-8")
        self.run_installer()
        text = cfg.read_text(encoding="utf-8")
        self.assertIn("model = 'x'", text)
        self.assertIn("[mcp_servers.thalamus]", text)
        self.assertEqual(text.count(install.TOML_START), 1)
        self.assertIn("THALAMUS_DEPTH", text)

    def test_check_reports_drift_then_ok_and_changes_nothing(self):
        before = self.make(check=True)
        before.run()
        self.assertIn("drift", self.statuses(before).values())
        self.assertFalse((self.home / ".claude" / "CLAUDE.md").exists())
        self.run_installer()
        after = self.make(check=True)
        after.run()
        bad = {t: s for t, s in self.statuses(after).items() if s in ("drift", "error")}
        # the only drift left is the claude and grok CLI registrations, which need the real CLIs
        self.assertEqual(set(bad), {"claude-code mcp", "grok mcp"})

    def test_dry_run_writes_nothing(self):
        inst = self.run_installer(dry_run=True)
        self.assertIn("would-update", self.statuses(inst).values())
        self.assertFalse((self.home / ".cursor" / "mcp.json").exists())
        self.assertFalse((self.state / "backups").exists())

    def test_backup_before_overwrite(self):
        md = self.home / ".codex" / "AGENTS.md"
        md.write_text("original\n", encoding="utf-8")
        inst = self.run_installer()
        backups = list((self.state / "backups").rglob("*AGENTS.md"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(encoding="utf-8"), "original\n")
        self.assertTrue(inst.backup_dir.exists())

    def test_uninstall_removes_only_our_content(self):
        md = self.home / ".claude" / "CLAUDE.md"
        md.write_text("# Mine\n", encoding="utf-8")
        cursor = self.home / ".cursor" / "mcp.json"
        cursor.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}}), encoding="utf-8")
        self.run_installer()
        self.run_installer(uninstall=True)
        self.assertEqual(md.read_text(encoding="utf-8").strip(), "# Mine")
        self.assertEqual(list(json.loads(cursor.read_text(encoding="utf-8"))["mcpServers"]), ["other"])
        self.assertFalse((self.home / ".codex" / "AGENTS.md").exists())
        self.assertNotIn("thalamus", (self.home / ".codex" / "config.toml").read_text(encoding="utf-8"))

    def test_jsonc_config_is_left_alone(self):
        vs = self.sup / "Code" / "User" / "mcp.json"
        vs.write_text('{\n  // my comment\n  "servers": {}\n}\n', encoding="utf-8")
        inst = self.run_installer()
        self.assertEqual(vs.read_text(encoding="utf-8"), '{\n  // my comment\n  "servers": {}\n}\n')
        self.assertEqual(self.statuses(inst)["vscode mcp"], "error")

    def test_only_and_skip(self):
        inst = self.make()
        inst.run(only={"cursor"})
        self.assertEqual([t for t, _, _ in inst.results], ["cursor mcp"])
        inst = self.make()
        inst.run(skip={name for name in install.TARGETS if name != "codex"})
        self.assertTrue(all(t.startswith("codex") for t, _, _ in inst.results))

    def test_generic_agents_file(self):
        target = self.home / "proj" / "AGENTS.md"
        target.parent.mkdir()
        target.write_text("# Project rules\n", encoding="utf-8")
        inst = self.make(agents_file=target)
        inst.run(only={"agents"})
        self.assertIn("Use the council", target.read_text(encoding="utf-8"))
        self.assertIn("# Project rules", target.read_text(encoding="utf-8"))

    def test_missing_tools_are_skipped(self):
        empty = self.home.parent / "empty"
        empty.mkdir()
        inst = install.Installer(home=empty, state=self.state, rules=RULES, use_cli=False)
        inst.run(only={"cursor", "codex"})
        self.assertTrue(all(s == "skipped" for _, s, _ in inst.results))


if __name__ == "__main__":
    unittest.main()
