"""Seats: one call() for every model lane.

A seat is a named model on a lane. Lanes:
    openrouter         OpenRouter HTTP API (key from OPENROUTER_API_KEY or HOME/env). Billed per token.
    codex              OpenAI Codex CLI on a ChatGPT plan.
    claude-cli         Claude Code headless (`claude -p`) on a Claude plan.
    grok               Grok Build CLI.
    agy                Antigravity CLI.
    ollama             Local Ollama server (http://localhost:11434 unless OLLAMA_HOST is set).
    openai-compatible  Any /chat/completions server: set base_url and api_key_env on the seat.

Seats come from default_seats.json in this package, merged with HOME/seats.json if it exists.
"""
from __future__ import annotations

import copy
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import paths

OPENROUTER_API = "https://openrouter.ai/api/v1"
EFFORTS = ["none", "minimal", "low", "medium", "high", "xhigh", "max"]
DEPTH_VAR = "THALAMUS_DEPTH"
METERED_LANES = {"openrouter", "openai-compatible"}
IS_WIN = os.name == "nt"

# Guess a family for a raw OpenRouter slug like "z-ai/glm-5.3".
SLUG_FAMILY = {"z-ai": "zhipu", "moonshotai": "moonshot", "deepseek": "deepseek", "qwen": "qwen",
               "mistralai": "mistral", "meta": "meta", "meta-llama": "meta", "google": "google",
               "x-ai": "xai", "openai": "openai", "anthropic": "anthropic"}


# ---------- registry ----------

def load_registry() -> dict[str, dict]:
    """Default seats merged with HOME/seats.json. A user entry updates the default of the same key;
    a null entry removes a seat."""
    base = json.loads((Path(__file__).resolve().parent / "default_seats.json").read_text(encoding="utf-8"))
    merged: dict[str, dict] = copy.deepcopy(base["seats"])
    user_file = paths.HOME / "seats.json"
    if user_file.exists():
        data = json.loads(user_file.read_text(encoding="utf-8-sig"))
        items = data.get("seats", data) if isinstance(data, dict) else {}
        for key, val in items.items():
            if key.startswith("_"):
                continue
            if val is None:
                merged.pop(key, None)
            elif isinstance(val, dict):
                merged[key] = {**merged.get(key, {}), **val}
    out = {}
    for key, seat in merged.items():
        entry = {"key": key, "label": key, "default_effort": None, "family": seat.get("lane", "other"),
                 "lab": "unknown", "country": "unknown", "open_weights": False, **seat}
        entry.setdefault("metered", entry["lane"] in METERED_LANES)
        out[key] = entry
    return out


# ---------- environment, keys, executables ----------

def depth() -> int:
    try:
        return int(os.environ.get(DEPTH_VAR, "0") or 0)
    except ValueError:
        return 0


# Only what a CLI needs to find itself, its own login files and the network. Everything else is dropped:
# API keys, tokens, database URLs, cloud profiles and backend switches (ANTHROPIC_BASE_URL,
# CLAUDE_CODE_USE_BEDROCK, OPENAI_BASE_URL and the like), so a seat runs on the plan login stored in the
# CLI's own credential files and can't read the parent's secrets.
SAFE_ENV = {
    "PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "TEMP", "TMP", "TMPDIR", "HOME",
    "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "PROGRAMFILES",
    "PROGRAMFILES(X86)", "PROGRAMW6432", "COMMONPROGRAMFILES", "USERNAME", "USER", "LOGNAME", "SHELL", "TERM",
    "LANG", "LANGUAGE", "TZ", "OS", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "SSL_CERT_FILE",
    "SSL_CERT_DIR", "NODE_EXTRA_CA_CERTS", "CODEX_HOME", "CLAUDE_CONFIG_DIR",
}
SAFE_PREFIXES = ("LC_", "XDG_")


def child_env(extra: dict | None = None) -> dict:
    """Env for a model CLI we spawn: an allowlist (SAFE_ENV), plus THALAMUS_DEPTH so the council and the MCP
    server refuse to fan out again from inside a seat."""
    base = {k: v for k, v in os.environ.items() if k.upper() in SAFE_ENV or k.upper().startswith(SAFE_PREFIXES)}
    return {**base, DEPTH_VAR: str(depth() + 1), **(extra or {})}


def env_value(name: str) -> str | None:
    """Look in the process environment, then in HOME/env (KEY=VALUE lines, optional `export `)."""
    val = os.environ.get(name, "").strip()
    if val:
        return val
    env_file = paths.HOME / "env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line.startswith("export "):
                line = line[len("export "):]
            if line.startswith(name + "="):
                return line.split("=", 1)[1].strip().strip('"').strip("'") or None
    return None


def api_key() -> str:
    key = env_value("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError(f"OPENROUTER_API_KEY not found in the environment or {paths.HOME / 'env'}")
    return key


def find_exe(name: str) -> str | None:
    """PATH first, then the places global installers usually put a CLI on each OS."""
    exe = shutil.which(name)
    if exe:
        return exe
    home = Path.home()
    dirs: list[Path] = [home / ".local" / "bin", home / f".{name}" / "bin", home / ".npm-global" / "bin",
                        home / ".bun" / "bin", home / ".cargo" / "bin"]
    if IS_WIN:
        appdata = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
        local = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
        dirs += [appdata / "npm", local / name / "bin", local / "Programs" / name / "bin"]
        names = [name + ext for ext in (".exe", ".cmd", ".bat")]
    else:
        dirs += [Path("/usr/local/bin"), Path("/opt/homebrew/bin"), Path("/usr/bin"), Path("/snap/bin")]
        names = [name]
    for d in dirs:
        for n in names:
            if (d / n).exists():
                return str(d / n)
    return None


# ---------- resolving a spec ----------

def resolve(spec: str) -> dict:
    """'gpt', 'gpt:high', or a raw OpenRouter slug like 'z-ai/glm-5.3' or 'z-ai/glm-5.3:online:high'."""
    base, effort = spec, None
    if ":" in spec:
        head, tail = spec.rsplit(":", 1)
        if tail in EFFORTS:
            base, effort = head, tail
    reg = load_registry()
    if base in reg:
        entry = dict(reg[base])
    elif "/" in base:
        prefix = base.split("/", 1)[0]
        entry = {"key": base, "label": base, "lane": "openrouter", "id": base, "default_effort": None,
                 "family": SLUG_FAMILY.get(prefix, prefix), "lab": prefix, "country": "unknown",
                 "open_weights": False, "metered": True}
    else:
        raise ValueError(f"Unknown seat '{base}'. Use a key from list_seats, or a raw OpenRouter slug like 'vendor/model'.")
    entry["effort"] = effort or entry.get("default_effort")
    return entry


def available(entry: dict) -> str | None:
    """None when the seat can be tried, otherwise the reason it cannot. Cheap checks only; the login
    itself is checked by doctor."""
    lane = entry["lane"]
    cli = {"codex": "codex", "claude-cli": "claude", "grok": "grok", "agy": "agy"}
    if lane in cli:
        return None if find_exe(cli[lane]) else f"{cli[lane]} CLI not found"
    if lane == "openrouter":
        return None if env_value("OPENROUTER_API_KEY") else "no OpenRouter key (OPENROUTER_API_KEY)"
    if lane == "ollama":
        base = _ollama_base()
        try:
            with urllib.request.urlopen(base + "/api/tags", timeout=2):
                return None
        except Exception:
            return f"Ollama not reachable at {base}"
    if lane == "openai-compatible":
        if not entry.get("base_url"):
            return "seat has no base_url"
        env = entry.get("api_key_env")
        if env and not env_value(env):
            return f"no key in {env}"
        return None
    return f"unknown lane '{lane}'"


# ---------- HTTP lanes ----------

def _post(url: str, payload: dict, headers: dict, timeout: float) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        raise RuntimeError(f"HTTP {err.code}: {err.read().decode('utf-8', 'replace')[:400]}")


def _messages(prompt: str, system: str | None) -> list[dict]:
    return ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]


def _call_openrouter(entry, prompt, system, timeout, max_tokens):
    if max_tokens is None:
        max_tokens = 16000 if entry["effort"] in ("high", "xhigh", "max") else 6000
    payload = {"model": entry["id"], "messages": _messages(prompt, system), "max_tokens": max_tokens,
               "usage": {"include": True}}
    # Reasoning models can spend the whole budget thinking and return an empty message, so always set an effort.
    if entry["effort"]:
        payload["reasoning"] = {"effort": entry["effort"]}
    out = _post(OPENROUTER_API + "/chat/completions", payload, {"Authorization": "Bearer " + api_key()}, timeout)
    if "choices" not in out:
        raise RuntimeError(f"Unexpected response: {json.dumps(out)[:400]}")
    text = out["choices"][0]["message"].get("content") or ""
    if not text.strip():
        raise RuntimeError("Empty answer: the model spent the budget reasoning. Raise max_tokens or lower effort.")
    usage = out.get("usage", {})
    return text, usage.get("cost"), usage.get("prompt_tokens"), usage.get("completion_tokens"), out.get("model")


def _call_openai_compatible(entry, prompt, system, timeout, max_tokens):
    payload = {"model": entry["id"], "messages": _messages(prompt, system)}
    if max_tokens:
        payload["max_tokens"] = max_tokens
    if entry.get("send_effort") and entry["effort"]:
        payload["reasoning_effort"] = entry["effort"]
    headers = {}
    if entry.get("api_key_env"):
        key = env_value(entry["api_key_env"])
        if not key:
            raise RuntimeError(f"No key in {entry['api_key_env']}")
        headers["Authorization"] = "Bearer " + key
    out = _post(entry["base_url"].rstrip("/") + "/chat/completions", payload, headers, timeout)
    text = (out.get("choices") or [{}])[0].get("message", {}).get("content") or ""
    if not text.strip():
        raise RuntimeError(f"Empty answer: {json.dumps(out)[:300]}")
    usage = out.get("usage", {})
    return text, usage.get("cost"), usage.get("prompt_tokens"), usage.get("completion_tokens"), out.get("model")


def _ollama_base() -> str:
    host = os.environ.get("OLLAMA_HOST", "").strip() or "localhost:11434"
    return host.rstrip("/") if "://" in host else "http://" + host


def _call_ollama(entry, prompt, system, timeout, max_tokens):
    payload = {"model": entry["id"], "messages": _messages(prompt, system), "stream": False}
    if max_tokens:
        payload["options"] = {"num_predict": max_tokens}
    out = _post(_ollama_base() + "/api/chat", payload, {}, timeout)
    text = (out.get("message") or {}).get("content") or ""
    if not text.strip():
        raise RuntimeError(f"Empty answer: {json.dumps(out)[:300]}")
    return text, 0.0, out.get("prompt_eval_count"), out.get("eval_count"), entry["id"]


# ---------- CLI lanes ----------

def _require(name: str, hint: str) -> str:
    exe = find_exe(name)
    if not exe:
        raise RuntimeError(f"{name} CLI not found. {hint}")
    return exe


def _parse_cli_json(stdout: str) -> tuple[str, dict]:
    """Grok Build and Antigravity print one JSON object in headless json mode. Pull the answer text out."""
    raw = (stdout or "").strip()
    start = raw.find("{")
    if start < 0:
        return raw, {}
    try:
        obj = json.loads(raw[start:])
    except json.JSONDecodeError:
        return raw, {}
    for key in ("response", "result", "text", "content", "message", "output"):
        val = obj.get(key)
        if isinstance(val, str) and val.strip():
            return val, obj
    return "", obj


def _run(args: list[str], stdin: str, timeout: float, extra_env: dict | None = None,
         files: dict | None = None) -> subprocess.CompletedProcess:
    """Runs a CLI in an empty scratch folder, so its agent has no project files to read or change.
    `files` ({name: text}) are the only files placed in that folder."""
    work = tempfile.mkdtemp(prefix="thalamus-seat-")
    for name, content in (files or {}).items():
        (Path(work) / name).write_text(content, encoding="utf-8")
    try:
        return subprocess.run(args, input=stdin, text=True, encoding="utf-8", errors="replace",
                              capture_output=True, timeout=timeout, cwd=work, env=child_env(extra_env))
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _call_codex(entry, prompt, system, timeout, max_tokens):
    exe = _require("codex", "Install: npm i -g @openai/codex, then `codex login`.")
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as fh:
        out_file = Path(fh.name)
    # --ignore-user-config skips ~/.codex/config.toml: no MCP servers or plugins start, so a call is faster
    # and the seat cannot reach this council again. Auth still comes from CODEX_HOME.
    # Model and effort are always passed explicitly.
    args = [exe, "exec", "--ignore-user-config", "--skip-git-repo-check", "-s", "read-only", "--color", "never",
            "-m", entry["id"], "-c", f"model_reasoning_effort={entry['effort'] or 'medium'}",
            "-o", str(out_file), "Complete the task given on stdin. Reply with the finished answer only."]
    task = (system.strip() + "\n\n" if system else "") + prompt
    try:
        proc = _run(args, task, timeout)
        text = out_file.read_text(encoding="utf-8", errors="replace") if out_file.exists() else ""
    finally:
        out_file.unlink(missing_ok=True)
    if proc.returncode != 0 or not text.strip():
        raise RuntimeError(f"Codex exit {proc.returncode}: {(proc.stderr or proc.stdout or '')[-600:]}")
    return text, None, None, None, entry["id"]


def _call_cli_json(label: str, args: list[str], stdin: str, timeout: float, extra_env=None, files=None):
    proc = _run(args, stdin, timeout, extra_env, files)
    text, obj = _parse_cli_json(proc.stdout)
    if proc.returncode != 0 or not text.strip():
        raise RuntimeError(f"{label} exit {proc.returncode}: {(proc.stderr or proc.stdout or '')[-600:]}")
    usage = obj.get("usage") if isinstance(obj.get("usage"), dict) else {}
    return text, usage.get("input_tokens") or usage.get("prompt_tokens"), usage.get("output_tokens") or usage.get("completion_tokens")


def _call_grok(entry, prompt, system, timeout, max_tokens):
    exe = _require("grok", "Install Grok Build, then `grok login --oauth`.")
    task = (system.strip() + "\n\n" if system else "") + prompt
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as fh:
        fh.write(task)
        prompt_file = Path(fh.name)
    args = [exe, "--prompt-file", str(prompt_file), "-m", entry["id"], "--output-format", "json",
            # Plan mode made Grok hunt for a skill first and hit max turns. Default mode with no tools,
            # headless (nobody to approve) and an empty folder is just as safe and answers directly.
            "--permission-mode", "default", "--no-subagents", "--max-turns", "4", "--tools", "",
            "--disable-web-search", "--system-prompt-override",
            "You are Grok, an expert advisor. Answer the request directly and completely. Plain text only."]
    if entry["effort"]:
        args += ["--reasoning-effort", entry["effort"]]
    # Grok Build reads Claude Code's and Cursor's files by default: CLAUDE.md, skills, hooks and the MCP servers
    # in ~/.claude.json (some with write tokens). Switch all of that off for seat calls.
    no_claude = {f"GROK_{vendor}_{cell}_ENABLED": "false"
                 for vendor in ("CLAUDE", "CURSOR") for cell in ("AGENTS", "SKILLS", "RULES", "MCPS", "HOOKS")}
    try:
        text, tin, tout = _call_cli_json("Grok Build", args, "", timeout, no_claude)
    finally:
        prompt_file.unlink(missing_ok=True)
    return text, None, tin, tout, entry["id"]


def _call_agy(entry, prompt, system, timeout, max_tokens):
    exe = _require("agy", "Install the Antigravity CLI from Google and sign in once.")
    task = (system.strip() + "\n\n" if system else "") + prompt
    # agy ignores piped stdin in print mode. Short tasks go inline; long ones go in task.md inside the empty
    # scratch workspace, the only folder the agent sees. Plan mode keeps it read-only.
    files = None
    if len(task) <= 8000:
        prompt_arg = task
    else:
        files = {"task.md": task}
        prompt_arg = "Read task.md in your workspace and complete the task in it. Reply with the finished answer only."
    args = [exe, "-p", prompt_arg, "--output-format", "json", "--model", entry["id"], "--mode", "plan",
            "--disable-slash-commands", "--print-timeout", f"{int(timeout)}s"]
    if entry["effort"]:
        args += ["--effort", entry["effort"]]
    text, tin, tout = _call_cli_json("Antigravity", args, "", timeout + 30, files=files)
    return text, None, tin, tout, entry["id"]


CLAUDE_SEAT_SYSTEM = ("You are Claude, an expert advisor answering one request on its own. Answer directly and "
                      "completely in plain text. Do not ask follow-up questions.")


def _call_claude_cli(entry, prompt, system, timeout, max_tokens):
    """Claude through Claude Code headless (`claude -p`). Lean by design: no CLAUDE.md or settings
    (--setting-sources ""), no MCP servers, no tools, no saved session, empty scratch folder. Meant for hosts
    that are not Claude Code; inside Claude Code a subagent is the better route."""
    exe = _require("claude", "Install: npm i -g @anthropic-ai/claude-code, then run `claude` once to sign in.")
    args = [exe, "-p", "--model", entry["id"], "--output-format", "json", "--setting-sources", "",
            "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}', "--tools", "",
            "--no-session-persistence", "--system-prompt", (system or CLAUDE_SEAT_SYSTEM)]
    if entry["effort"]:
        args += ["--effort", entry["effort"]]
    proc = _run(args, prompt, timeout)
    raw = (proc.stdout or "").strip()
    try:
        obj = json.loads(raw[raw.find("{"):]) if "{" in raw else {}
    except json.JSONDecodeError:
        obj = {}
    text = obj.get("result") if isinstance(obj.get("result"), str) else ""
    if proc.returncode != 0 or obj.get("is_error") or not text.strip():
        raise RuntimeError(f"Claude CLI exit {proc.returncode}: {(proc.stderr or proc.stdout or '')[-600:]}")
    usage = obj.get("usage") or {}
    tin = sum(usage.get(k) or 0 for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
    return text, None, tin, usage.get("output_tokens"), entry["id"]


LANES = {"openrouter": _call_openrouter, "openai-compatible": _call_openai_compatible, "ollama": _call_ollama,
         "codex": _call_codex, "claude-cli": _call_claude_cli, "grok": _call_grok, "agy": _call_agy}


def call(spec: str, prompt: str, system: str | None = None, timeout: float = 600,
         max_tokens: int | None = None) -> dict:
    """Ask one seat. Never raises: failures land in result['error']."""
    started = time.time()
    result = {"spec": spec, "label": spec, "text": "", "error": None, "cost": None, "model": None,
              "in_tokens": None, "out_tokens": None}
    try:
        entry = resolve(spec)
        result.update(key=entry["key"], label=entry["label"], lane=entry["lane"], effort=entry["effort"],
                      family=entry.get("family"))
        fn = LANES.get(entry["lane"])
        if fn is None:
            raise RuntimeError(f"Unknown lane '{entry['lane']}'")
        text, cost, tin, tout, model = fn(entry, prompt, system, timeout, max_tokens)
        result.update(text=text, cost=cost, in_tokens=tin, out_tokens=tout, model=model)
    except subprocess.TimeoutExpired:
        result["error"] = f"timed out after {int(timeout)}s"
    except Exception as exc:
        result["error"] = str(exc)
    result["seconds"] = round(time.time() - started, 1)
    return result


def python_exe() -> str:
    return sys.executable
