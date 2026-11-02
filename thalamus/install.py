"""Install the routing rules and the MCP server into every AI tool on this machine.

One source (AGENTS.md in the repo, plus `python -m thalamus mcp`) written into each tool's own files.
Safe to re-run: files are only written when something drifted, every changed file is copied to
HOME/backups/<timestamp>/ first, and rules live between marker lines, so anything you wrote outside the
markers is never touched.

    thalamus install                apply
    thalamus install --check        report drift, change nothing (exit 1 if anything is out of date)
    thalamus install --dry-run      show what would change, change nothing
    thalamus install --only claude-code,codex
    thalamus install --skip cursor
    thalamus install --uninstall    remove what install added

Targets: claude-code, claude-desktop, codex, cursor, vscode, cline, grok, antigravity, agents.
`agents` writes a block into a project AGENTS.md you name with --agents-file PATH (opt-in).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import paths

SERVER_NAME = "thalamus"
MD_START, MD_END = "<!-- thalamus:start -->", "<!-- thalamus:end -->"
TOML_START, TOML_END = "# thalamus:start (managed by thalamus install)", "# thalamus:end"
MANAGED = "<!-- Managed by `thalamus install`. Edit AGENTS.md in the thalamus repo, then re-run it. -->"
TOOLS = ["council", "council_result", "ask_model", "list_seats", "doctor", "routing_rules", "route", "leaderboard",
         "feedback", "scout"]
TARGETS = ["claude-code", "claude-desktop", "codex", "cursor", "vscode", "cline", "grok", "antigravity", "agents"]
IS_WIN = os.name == "nt"
IS_MAC = sys.platform == "darwin"


def fwd(p) -> str:
    return str(p).replace("\\", "/")


def app_support(home: Path) -> Path:
    if IS_WIN:
        return Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
    if IS_MAC:
        return home / "Library" / "Application Support"
    return home / ".config"


def needs_pythonpath() -> bool:
    """A source checkout is not importable from another folder; an installed package is."""
    return "site-packages" not in Path(__file__).resolve().parts


def server_entry() -> dict:
    entry = {"command": fwd(sys.executable), "args": ["-m", "thalamus", "mcp"]}
    if needs_pythonpath():
        entry["env"] = {"PYTHONPATH": fwd(paths.REPO)}
    return entry


def indent_of(text: str) -> int:
    m = re.search(r"\n( +)\S", text)
    return len(m.group(1)) if m else 2


class Installer:
    def __init__(self, home: Path | None = None, state: Path | None = None, rules: str | None = None,
                 check: bool = False, dry_run: bool = False, uninstall: bool = False,
                 use_cli: bool = True, agents_file: Path | None = None):
        self.home = Path(home) if home else Path.home()
        self.state = Path(state) if state else paths.HOME
        self.check, self.dry_run, self.uninstall, self.use_cli = check, dry_run, uninstall, use_cli
        self.agents_file = Path(agents_file) if agents_file else None
        self._rules = rules
        self.results: list[tuple[str, str, str]] = []
        self.backup_dir = self.state / "backups" / time.strftime("%Y-%m-%d_%H%M%S")
        self.entry = server_entry()

    # ---------- plumbing ----------
    @property
    def rules(self) -> str:
        if self._rules is None:
            path = paths.REPO / "AGENTS.md"
            if not path.exists():
                raise FileNotFoundError(f"{path} not found")
            self._rules = path.read_text(encoding="utf-8")
        return self._rules

    def note(self, target: str, status: str, detail: str = "") -> None:
        self.results.append((target, status, detail))

    def backup(self, path: Path) -> None:
        if not path.exists():
            return
        dest = self.backup_dir / re.sub(r"[:\\/]+", "_", fwd(path)).strip("_")
        dest.parent.mkdir(parents=True, exist_ok=True)
        if path.is_dir():
            shutil.copytree(path, dest, symlinks=True)
        else:
            shutil.copy2(path, dest)

    def write(self, target: str, path: Path, new: str) -> None:
        old = path.read_text(encoding="utf-8-sig") if path.exists() else None
        if old == new:
            return self.note(target, "ok", fwd(path))
        if self.check:
            return self.note(target, "drift", fwd(path))
        if self.dry_run:
            return self.note(target, "would-update", fwd(path))
        self.backup(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(new, encoding="utf-8")
        self.note(target, "updated", fwd(path))

    def delete(self, target: str, path: Path) -> None:
        if not path.exists():
            return self.note(target, "ok", f"{fwd(path)} not present")
        if self.check:
            return self.note(target, "drift", f"{fwd(path)} still present")
        if self.dry_run:
            return self.note(target, "would-remove", fwd(path))
        self.backup(path)
        path.unlink()
        self.note(target, "removed", fwd(path))

    def guarded(self, target: str, fn, *args) -> None:
        try:
            fn(target, *args)
        except Exception as exc:  # one broken tool config must not stop the others
            self.note(target, "error", str(exc)[:200])

    # ---------- markdown rules block ----------
    def md_block(self) -> str:
        if MD_START in self.rules or MD_END in self.rules:
            raise ValueError("the rules text contains Thalamus's own block markers; refusing to install it")
        return f"{MD_START}\n{MANAGED}\n\n{self.rules.rstrip()}\n{MD_END}\n"

    @staticmethod
    def _splice(text: str, start: str, end: str, block: str | None) -> str:
        """Replace (block) or remove (None) the marked region; add it at the end if absent."""
        if start in text and end in text:
            before = text[: text.index(start)]
            rest = text[text.index(end) + len(end):].lstrip("\n")
            if block is None:
                joined = before.rstrip() + ("\n\n" if before.strip() and rest else "") + rest
                return joined + ("\n" if joined.strip() and not joined.endswith("\n") else "")
            return before + block + ("\n" + rest if rest else "")
        if block is None:
            return text
        return (text.rstrip() + "\n\n" if text.strip() else "") + block

    def md_block_file(self, target: str, path: Path, needs: Path) -> None:
        if not needs.exists():
            return self.note(target, "skipped", "tool not installed")
        text = path.read_text(encoding="utf-8-sig") if path.exists() else ""
        if self.uninstall:
            new = self._splice(text, MD_START, MD_END, None)
            if not path.exists() or new == text:
                return self.note(target, "ok", "no block present")
            return self.delete(target, path) if not new.strip() else self.write(target, path, new)
        self.write(target, path, self._splice(text, MD_START, MD_END, self.md_block()))

    def owned_file(self, target: str, path: Path, needs: Path, header: str = "") -> None:
        """A file only this tool reads and nobody else writes: the whole file is ours."""
        if not needs.exists():
            return self.note(target, "skipped", "tool not installed")
        if self.uninstall:
            return self.delete(target, path)
        self.write(target, path, f"{header}{MANAGED}\n\n{self.rules}")

    # ---------- JSON MCP configs ----------
    def json_server(self, target: str, path: Path, needs: Path, key: str = "mcpServers",
                    extra: dict | None = None) -> None:
        if not needs.exists():
            return self.note(target, "skipped", "tool not installed")
        text = path.read_text(encoding="utf-8-sig") if path.exists() else "{}"
        try:
            data = json.loads(text) if text.strip() else {}
        except json.JSONDecodeError as exc:
            return self.note(target, "error", f"{fwd(path)} is not plain JSON ({exc}); left untouched")
        servers = data.setdefault(key, {})
        current = servers.get(SERVER_NAME)
        if self.uninstall:
            if current is None:
                return self.note(target, "ok", "not registered")
            del servers[SERVER_NAME]
        else:
            want = {**(extra or {}), **self.entry}
            if current is not None and all(current.get(k) == v for k, v in want.items()):
                return self.note(target, "ok", fwd(path))
            servers[SERVER_NAME] = {**(current or {}), **want}
        self.write(target, path, json.dumps(data, indent=indent_of(text), ensure_ascii=False) + "\n")

    def allow_rule(self, target: str, path: Path, needs: Path, rule: str) -> None:
        """Pre-approves the tools where a headless run would auto-deny them."""
        if not needs.exists():
            return self.note(target, "skipped", "tool not installed")
        text = path.read_text(encoding="utf-8-sig") if path.exists() else "{}"
        try:
            data = json.loads(text) if text.strip() else {}
        except json.JSONDecodeError as exc:
            return self.note(target, "error", f"{fwd(path)} is not plain JSON ({exc}); left untouched")
        allow = data.setdefault("permissions", {}).setdefault("allow", [])
        if self.uninstall:
            if rule not in allow:
                return self.note(target, "ok", "rule not present")
            allow.remove(rule)
        else:
            if rule in allow:
                return self.note(target, "ok", f"{rule} in {fwd(path)}")
            allow.append(rule)
        self.write(target, path, json.dumps(data, indent=indent_of(text), ensure_ascii=False) + "\n")

    # ---------- per-tool installers ----------
    def _cli(self, name: str) -> str | None:
        return (shutil.which(name) or None) if self.use_cli else None

    def claude_code(self) -> None:
        claude_dir = self.home / ".claude"
        self.guarded("claude-code rules", self.md_block_file, claude_dir / "CLAUDE.md", claude_dir)
        self.guarded("claude-code mcp", self._claude_code_mcp)

    def _claude_code_mcp(self, target: str) -> None:
        cfg = self.home / ".claude.json"
        current = None
        if cfg.exists():
            try:
                current = (json.loads(cfg.read_text(encoding="utf-8-sig")).get("mcpServers") or {}).get(SERVER_NAME)
            except json.JSONDecodeError:
                return self.note(target, "error", "~/.claude.json is not valid JSON; left untouched")
        exe = self._cli("claude")
        same = bool(current) and all(current.get(k) == v for k, v in self.entry.items())
        if self.uninstall:
            if not current:
                return self.note(target, "ok", "not registered")
            if self.check or self.dry_run or not exe:
                return self.note(target, "drift" if self.check else ("would-remove" if self.dry_run else "error"),
                                 "registered at user scope" if exe or self.check or self.dry_run else "claude CLI not found")
            proc = subprocess.run([exe, "mcp", "remove", "--scope", "user", SERVER_NAME], capture_output=True, text=True, timeout=60)
            return self.note(target, "removed" if proc.returncode == 0 else "error", (proc.stderr or proc.stdout)[-200:])
        if same:
            return self.note(target, "ok", "user scope in ~/.claude.json")
        if self.check:
            return self.note(target, "drift", "not registered at user scope")
        if self.dry_run:
            return self.note(target, "would-update", "claude mcp add-json --scope user")
        if not exe:
            return self.note(target, "skipped", "claude CLI not found")
        # The CLI edits ~/.claude.json safely while sessions are running; never hand-edit that file.
        if current:
            subprocess.run([exe, "mcp", "remove", "--scope", "user", SERVER_NAME], capture_output=True, timeout=60)
        proc = subprocess.run([exe, "mcp", "add-json", "--scope", "user", SERVER_NAME,
                               json.dumps({"type": "stdio", **self.entry})], capture_output=True, text=True, timeout=60)
        self.note(target, "updated" if proc.returncode == 0 else "error",
                  "user scope" if proc.returncode == 0 else (proc.stderr or proc.stdout)[-200:])

    def claude_desktop(self) -> None:
        d = app_support(self.home) / "Claude"
        self.guarded("claude-desktop mcp", self.json_server, d / "claude_desktop_config.json", d)

    def codex(self) -> None:
        d = self.home / ".codex"
        self.guarded("codex rules", self.md_block_file, d / "AGENTS.md", d)
        self.guarded("codex mcp", self._codex_mcp)

    def _codex_mcp(self, target: str) -> None:
        d = self.home / ".codex"
        path = d / "config.toml"
        if not d.exists():
            return self.note(target, "skipped", "Codex not installed")
        text = path.read_text(encoding="utf-8-sig") if path.exists() else ""
        if self.uninstall:
            new = self._splice(text, TOML_START, TOML_END, None)
            if new == text:
                return self.note(target, "ok", "no block present")
            return self.write(target, path, new)
        env = ""
        if "env" in self.entry:
            pairs = ", ".join(f"{k} = '{v}'" for k, v in self.entry["env"].items())
            env = f"env = {{ {pairs} }}\n"
        args = ", ".join(f"'{a}'" for a in self.entry["args"])
        approvals = "".join(f'[mcp_servers.{SERVER_NAME}.tools.{t}]\napproval_mode = "approve"\n' for t in TOOLS)
        block = (f"{TOML_START}\n[mcp_servers.{SERVER_NAME}]\ncommand = '{self.entry['command']}'\nargs = [{args}]\n{env}"
                 f"startup_timeout_sec = 30\ntool_timeout_sec = 120\nenv_vars = ['THALAMUS_DEPTH']\n"
                 # Pre-approved, or `codex exec` auto-denies the tools (approval policy never).
                 f"{approvals}{TOML_END}\n")
        if TOML_START not in text and f"[mcp_servers.{SERVER_NAME}]" in text:
            return self.note(target, "error", f"{SERVER_NAME} already defined in config.toml outside the managed block")
        self.write(target, path, self._splice(text, TOML_START, TOML_END, block))

    def cursor(self) -> None:
        d = self.home / ".cursor"
        self.guarded("cursor mcp", self.json_server, d / "mcp.json", d)

    def _code_user(self) -> Path:
        return app_support(self.home) / "Code" / "User"

    def vscode(self) -> None:
        user = self._code_user()
        self.guarded("vscode mcp", self.json_server, user / "mcp.json", user, "servers", {"type": "stdio"})
        self.guarded("vscode chat rules", self.owned_file, user / "prompts" / "thalamus.instructions.md", user,
                     "---\napplyTo: \"**\"\ndescription: \"thalamus routing rules\"\n---\n")

    def cline(self) -> None:
        settings = self._code_user() / "globalStorage" / "saoudrizwan.claude-dev" / "settings"
        self.guarded("cline mcp", self.json_server, settings / "cline_mcp_settings.json", settings, "mcpServers",
                     {"disabled": False, "timeout": 120, "autoApprove": ["list_seats", "routing_rules", "doctor"]})
        self.guarded("cline rules", self.owned_file, self.home / "Documents" / "Cline" / "Rules" / "thalamus.md", settings)

    def grok(self) -> None:
        d = self.home / ".grok"
        self.guarded("grok rules", self.md_block_file, d / "AGENTS.md", d)
        self.guarded("grok mcp", self._grok_mcp)

    def _grok_mcp(self, target: str) -> None:
        d = self.home / ".grok"
        cfg = d / "config.toml"
        if not d.exists():
            return self.note(target, "skipped", "Grok Build not installed")
        text = cfg.read_text(encoding="utf-8-sig") if cfg.exists() else ""
        present = SERVER_NAME in text
        exe = self._cli("grok")
        if self.uninstall:
            if not present:
                return self.note(target, "ok", "not registered")
            if self.check or self.dry_run or not exe:
                return self.note(target, "drift" if self.check else "would-remove", "registered in ~/.grok/config.toml")
            self.backup(cfg)
            proc = subprocess.run([exe, "mcp", "remove", "--scope", "user", SERVER_NAME], capture_output=True, text=True, timeout=60)
            return self.note(target, "removed" if proc.returncode == 0 else "error", (proc.stderr or proc.stdout)[-200:])
        if present:
            return self.note(target, "ok", fwd(cfg))
        if self.check:
            return self.note(target, "drift", "not in ~/.grok/config.toml")
        if self.dry_run:
            return self.note(target, "would-update", "grok mcp add --scope user")
        if not exe:
            return self.note(target, "skipped", "grok CLI not found")
        self.backup(cfg)
        cmd = [exe, "mcp", "add", "--scope", "user"]
        for k, v in (self.entry.get("env") or {}).items():
            cmd += ["--env", f"{k}={v}"]
        proc = subprocess.run(cmd + [SERVER_NAME, self.entry["command"], "--", *self.entry["args"]],
                              capture_output=True, text=True, timeout=60)
        self.note(target, "updated" if proc.returncode == 0 else "error",
                  fwd(cfg) if proc.returncode == 0 else (proc.stderr or proc.stdout)[-200:])

    def antigravity(self) -> None:
        g = self.home / ".gemini"
        self.guarded("antigravity rules", self.md_block_file, g / "GEMINI.md", g)
        self.guarded("antigravity mcp (shared)", self.json_server, g / "config" / "mcp_config.json", g / "config")
        self.guarded("antigravity ide mcp", self.json_server, g / "antigravity-ide" / "mcp_config.json", g / "antigravity-ide")
        self.guarded("antigravity tool approval", self.allow_rule, g / "antigravity-cli" / "settings.json",
                     g / "antigravity-cli", f"mcp({SERVER_NAME}/*)")

    def agents(self) -> None:
        path = self.agents_file
        if path is None:
            return self.note("agents block", "skipped", "pass --agents-file PATH to add the rules to a project's AGENTS.md")
        if path.resolve() == (paths.REPO / "AGENTS.md").resolve():
            return self.note("agents block", "skipped", "that is this repo's own rules file, the source")
        if not path.exists() and not self.uninstall:
            return self.note("agents block", "skipped", f"{fwd(path)} does not exist (pass --agents-file to create one)")
        self.guarded("agents block", self.md_block_file, path, path.parent)

    def run(self, only: set[str] | None = None, skip: set[str] | None = None) -> None:
        for name in TARGETS:
            if (only and name not in only) or (skip and name in skip):
                continue
            try:
                getattr(self, name.replace("-", "_"))()
            except FileNotFoundError as exc:
                self.note(name, "error", str(exc))


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="thalamus install", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="report drift, change nothing")
    ap.add_argument("--dry-run", action="store_true", help="show what would change, change nothing")
    ap.add_argument("--only", help="comma-separated targets: " + ", ".join(TARGETS))
    ap.add_argument("--skip", help="comma-separated targets to leave alone")
    ap.add_argument("--uninstall", action="store_true", help="remove what install added")
    ap.add_argument("--agents-file", help="a project AGENTS.md to add the rules block to (opt-in)")
    ap.add_argument("--quiet", action="store_true", help="print only changes and problems")
    args = ap.parse_args(argv)
    split = lambda s: {x.strip() for x in s.split(",") if x.strip()} if s else None  # noqa: E731
    only, skip = split(args.only), split(args.skip)
    unknown = ((only or set()) | (skip or set())) - set(TARGETS)
    if unknown:
        print(f"Unknown target(s): {', '.join(sorted(unknown))}. Use: {', '.join(TARGETS)}", file=sys.stderr)
        return 2
    inst = Installer(check=args.check, dry_run=args.dry_run, uninstall=args.uninstall,
                     agents_file=Path(args.agents_file) if args.agents_file else None)
    inst.run(only, skip)
    shown = [r for r in inst.results if not args.quiet or r[1] not in ("ok", "skipped")]
    mode = " (check only)" if args.check else " (dry run)" if args.dry_run else ""
    print("thalamus install" + (" --uninstall" if args.uninstall else "") + mode)
    for target, status, detail in shown:
        print(f"  {status:13} {target:30} {detail}")
    if any(r[1] in ("updated", "removed") for r in inst.results):
        print(f"  backups: {fwd(inst.backup_dir)}")
    bad = ("drift", "error") if args.check else ("error",)
    return 1 if any(r[1] in bad for r in inst.results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
