"""Checks that every model lane the council can use is installed and signed in.

    thalamus council doctor          fast: CLIs found, logins present, OpenRouter key check
    thalamus council doctor --live   also sends "Reply OK" to one seat per subscription lane
                                     (plan usage only; metered seats are never tested live)
"""
from __future__ import annotations

import json
import subprocess
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import seats as seatlib


def _run(args: list[str], timeout: int = 40) -> tuple[int, str]:
    try:
        proc = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=timeout, stdin=subprocess.DEVNULL)
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)


def _row(name: str, ok: bool, detail: str = "", fix: str | None = None, **more) -> dict:
    return {"name": name, "ok": ok, "detail": detail, "fix": fix, "live": None, **more}


def check_codex() -> dict:
    name = "ChatGPT (Codex CLI)"
    exe = seatlib.find_exe("codex")
    if not exe:
        return _row(name, False, "Codex CLI not installed", "npm i -g @openai/codex")
    code, out = _run([exe, "login", "status"])
    ok = code == 0 and "logged in" in out.lower()
    last = out.strip().splitlines()[-1] if out.strip() else f"exit {code}"
    return _row(name, ok, last, None if ok else "codex login", lane="codex")


def check_claude() -> dict:
    name = "Claude (claude -p)"
    exe = seatlib.find_exe("claude")
    if not exe:
        return _row(name, False, "Claude Code CLI not installed", "npm i -g @anthropic-ai/claude-code")
    code, out = _run([exe, "auth", "status"])
    try:
        data = json.loads(out[out.find("{"):])
    except (ValueError, json.JSONDecodeError):
        data = {}
    # An API-key login would bill per token; the plan login is what this lane is for.
    ok = bool(data.get("loggedIn")) and data.get("authMethod") != "api-key"
    detail = f"{data.get('authMethod', 'unknown')} login" if data else out.strip()[:120]
    return _row(name, ok, detail, None if ok else "run `claude`, then /login with your plan account", lane="claude-cli")


def check_grok() -> dict:
    name = "Grok (Grok Build)"
    exe = seatlib.find_exe("grok")
    if not exe:
        return _row(name, False, "Grok Build CLI not installed", "install Grok Build, then `grok login --oauth`")
    auth = Path.home() / ".grok" / "auth.json"
    ok = auth.exists() and auth.stat().st_size > 20
    return _row(name, ok, "auth.json present" if ok else "no login", None if ok else "grok login --oauth", lane="grok")


def check_agy() -> dict:
    name = "Gemini (Antigravity agy)"
    exe = seatlib.find_exe("agy")
    if not exe:
        return _row(name, False, "Antigravity CLI not installed", "install the Antigravity CLI from Google")
    code, out = _run([exe, "--version"])
    return _row(name, code == 0, f"agy {out.strip()[:60]} (login checked by --live only)",
                None if code == 0 else "run agy once in a terminal", lane="agy")


def check_openrouter() -> dict:
    name = "OpenRouter (metered)"
    key = seatlib.env_value("OPENROUTER_API_KEY")
    if not key:
        return _row(name, False, "no OPENROUTER_API_KEY in the environment or HOME/env",
                    "optional: only needed for OpenRouter seats")
    req = urllib.request.Request(seatlib.OPENROUTER_API + "/key", headers={"Authorization": "Bearer " + key})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8")).get("data", {})
    except Exception as exc:  # network or auth failure is a finding, not a crash
        return _row(name, False, f"key check failed: {exc}", lane="openrouter")
    left = data.get("limit_remaining")
    detail = f"used ${data.get('usage', 0):.2f}" + (f", ${left:.2f} left on key limit" if left is not None else "")
    return _row(name, left is None or left > 1, detail, lane="openrouter")


def check_ollama() -> dict:
    name = "Ollama (local)"
    base = seatlib._ollama_base()
    try:
        with urllib.request.urlopen(base + "/api/tags", timeout=3) as resp:
            models = [m.get("name") for m in json.loads(resp.read().decode("utf-8")).get("models", [])]
    except Exception:
        return _row(name, False, f"not reachable at {base}", "optional: install Ollama and run it", lane="ollama")
    return _row(name, True, f"{len(models)} model(s) pulled", lane="ollama")


def check_compatible() -> list[dict]:
    rows = []
    for entry in seatlib.load_registry().values():
        if entry["lane"] == "openai-compatible":
            why = seatlib.available(entry)
            rows.append(_row(f"{entry['label']} (openai-compatible)", why is None, why or entry.get("base_url", ""),
                             None if why is None else "set the key env var named in the seat", lane="openai-compatible"))
    return rows


CHECKS = [check_codex, check_claude, check_grok, check_agy, check_openrouter, check_ollama]


def check(live: bool = False) -> list[dict]:
    with ThreadPoolExecutor(max_workers=len(CHECKS)) as pool:
        rows = [f.result() for f in [pool.submit(fn) for fn in CHECKS]]
    rows += check_compatible()
    if live:
        prompt = "[council-seat] Health check. Reply with the single word OK."
        registry = seatlib.load_registry()
        targets: dict[str, str] = {}  # lane -> first non-metered seat key on that lane
        for key, entry in registry.items():
            if not entry.get("metered") and entry["lane"] in ("codex", "claude-cli", "grok", "agy", "ollama"):
                targets.setdefault(entry["lane"], key)
        with ThreadPoolExecutor(max_workers=max(1, len(targets))) as pool:
            futures = {lane: pool.submit(seatlib.call, key, prompt, None, 300) for lane, key in targets.items()}
            results = {lane: f.result() for lane, f in futures.items()}
        for row in rows:
            r = results.get(row.get("lane"))
            if r is None:
                continue
            answered = not r["error"] and "ok" in r["text"].lower()
            row["live"] = f"answered in {r['seconds']}s" if answered else f"FAILED: {(r['error'] or r['text'])[:160]}"
            row["ok"] = row["ok"] and answered
    return rows


def render(rows: list[dict]) -> str:
    lines = ["| Lane | OK | Detail | Live test | Fix |", "|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['name']} | {'yes' if r['ok'] else 'NO'} | {r.get('detail', '')} | "
                     f"{r.get('live') or '-'} | {r.get('fix') or ''} |")
    return "\n".join(lines)
