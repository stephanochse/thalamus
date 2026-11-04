"""MCP server (stdio, JSON-RPC 2.0, no third-party packages).

Run with `python -m thalamus mcp`. Gives any MCP client the council engine and the routing tools.
Messages are newline-delimited JSON on stdin and stdout; logs go to stderr only.
"""
from __future__ import annotations

import json
import sys

from . import council as engine, doctor as health, paths, seats as seatlib

SERVER_NAME = "thalamus"
PROTOCOL = "2025-03-26"
MAX_WAIT = 50  # most MCP clients cut a tool call at about 60 s; longer runs continue as a background job

INSTRUCTIONS = """A council of model families, plus routing tools.
Effort ladder, read from the user's own current message only: "think harder" or "second opinion" -> tier harder;
"go deep" or "think much harder" -> tier deep; "ultrathink", "maximum effort" or "all hands" -> tier max.
"Be careful" and "make sure" mean check your own work, no council. Climb one tier on your own only right
before an irreversible step. Write your own answer first and pass it as host_draft. Set host to the model
family you run on (claude, gpt, grok, gemini, other) so the panel does not echo you. Outside models advise;
you decide, verify and name who caught what. If your own prompt starts with [council-seat], you are a seat:
answer directly and never call these tools. Full rules: call routing_rules."""

TOOLS = [
    {"name": "council",
     "description": ("Convene a blind panel of other model families and return their answers. Tiers: harder = one "
                     "other family (1 call); deep = three families, blind; max = every other family, then an "
                     "anonymized cross-review, plus configured extras. task must stand alone (seats see nothing "
                     "else). host_draft is YOUR OWN answer written before you see the panel. mode: solve for open "
                     "questions, review for a finished draft. Returns the report, or a run_id for council_result."),
     "inputSchema": {"type": "object", "required": ["task", "host_draft"], "properties": {
         "task": {"type": "string"}, "host_draft": {"type": "string"},
         "tier": {"type": "string", "enum": ["harder", "deep", "max"], "default": "deep"},
         "mode": {"type": "string", "enum": ["solve", "review"], "default": "solve"},
         "host": {"type": "string", "default": "unknown"},
         "context": {"type": "string", "default": "general"},
         "seats": {"type": "array", "items": {"type": "string"}, "description": "optional seat keys to override the tier"},
         "wait_seconds": {"type": "integer", "default": 50}}}},
    {"name": "council_result",
     "description": "Collect a council or ask_model run that was still going. Waits up to 50 s per call; call again until done.",
     "inputSchema": {"type": "object", "required": ["run_id"], "properties": {
         "run_id": {"type": "string"}, "wait_seconds": {"type": "integer", "default": 50}}}},
    {"name": "ask_model",
     "description": "Ask one seat one question. model is a key from list_seats (optionally with an effort suffix like gpt:high) or a raw OpenRouter slug.",
     "inputSchema": {"type": "object", "required": ["model", "prompt"], "properties": {
         "model": {"type": "string"}, "prompt": {"type": "string"},
         "context": {"type": "string", "default": "general"}, "wait_seconds": {"type": "integer", "default": 50}}}},
    {"name": "list_seats", "description": "Every seat the council can reach: key, lane, lab, country, open weights, metered.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "doctor", "description": "Check every lane (CLIs, logins, keys). live=true also sends a one-word test to each subscription seat.",
     "inputSchema": {"type": "object", "properties": {"live": {"type": "boolean", "default": False}}}},
    {"name": "routing_rules", "description": "The routing rules (AGENTS.md of this repo).",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "route",
     "description": "Recommend a model for a task: best, value, budget, fast, open and other-lab picks, every "
                    "lab's best model for the job (other_labs) and, if configured, where the user's favourite "
                    "model families stand. Optional job (task category) and budget. Says how sure the job match "
                    "is (confidence: pass job yourself on low or none) and which other jobs the task touches "
                    "(also). A job with no public scores says so and lists local_options instead.",
     "inputSchema": {"type": "object", "required": ["task"], "properties": {
         "task": {"type": "string"}, "job": {"type": "string"}, "budget": {"type": "string"}}}},
    {"name": "leaderboard",
     "description": "Top models for a job, plus every lab's best model (every_lab). Optional n and kind.",
     "inputSchema": {"type": "object", "required": ["job"], "properties": {
         "job": {"type": "string"}, "n": {"type": "integer", "default": 10}, "kind": {"type": "string"}}}},
    {"name": "feedback",
     "description": "Record how a model did on a job (good or bad, or which model beat which). Stays on this "
                    "machine and bends future routing toward the user's taste. Call it when the user accepts, "
                    "rejects or corrects a model's work.",
     "inputSchema": {"type": "object", "required": ["job", "model"], "properties": {
         "job": {"type": "string"}, "model": {"type": "string", "description": "model id from route/leaderboard"},
         "verdict": {"type": "string", "enum": ["good", "bad"]}, "note": {"type": "string"},
         "beats": {"type": "string", "description": "the model it beat in a head-to-head, if any"}}}},
    {"name": "scout",
     "description": "Suggest an untried, strong model for the next low-stakes task of this job, so new "
                    "releases get tested on real work.",
     "inputSchema": {"type": "object", "required": ["job"], "properties": {"job": {"type": "string"}}}},
]
TOOL_NAMES = [t["name"] for t in TOOLS]


def _wait(seconds) -> int:
    try:
        return max(0, min(int(seconds), MAX_WAIT))
    except (TypeError, ValueError):
        return MAX_WAIT


def _format(result: dict, run_id: str) -> str:
    if result["status"] in ("done", "failed"):
        return result["report"]
    progress = "\n".join(result.get("progress", []))
    return (f"Still running. run_id: {run_id}\n{progress}\n\n"
            f"Call council_result with run_id '{run_id}' to collect it (it keeps running in the background).")


def _seat_refusal() -> str | None:
    if seatlib.depth() >= 1:
        return "Refused: you are running as a council seat. Answer the request directly without consulting other models."
    return None


def _routes():
    try:
        from . import routes  # written separately; imported lazily so the server runs without it
    except ImportError as exc:
        raise RuntimeError(f"The routes module is not available ({exc}). Add thalamus/routes.py to enable route and leaderboard.")
    return routes


def tool_council(task, host_draft, tier="deep", mode="solve", host="unknown", context="general", seats=None,
                 wait_seconds=50) -> str:
    refusal = _seat_refusal()
    if refusal:
        return refusal
    if not (host_draft or "").strip():
        return "Write your own answer first and pass it as host_draft. The panel checks your thinking, it does not replace it."
    if tier not in engine.TIERS or mode not in ("solve", "review"):
        return f"Invalid input. tier: {list(engine.TIERS)}; mode: solve or review."
    try:
        run_id = engine.start_job(task=task, draft=host_draft, tier=tier, mode=mode, host=host,
                                  context=context, seats=seats)
    except Exception as exc:
        return f"Could not start the council: {exc}"
    return _format(engine.job_result(run_id, _wait(wait_seconds)), run_id)


def tool_council_result(run_id, wait_seconds=50) -> str:
    return _format(engine.job_result(run_id, _wait(wait_seconds)), run_id)


def tool_ask_model(model, prompt, context="general", wait_seconds=50) -> str:
    refusal = _seat_refusal()
    if refusal:
        return refusal
    try:
        entry = seatlib.resolve(model)
    except ValueError as exc:
        return str(exc)
    if entry.get("metered") and not engine.metered_allowed(context):
        return (f"{entry['label']} is a metered seat (billed per token) and context '{context}' is private. "
                f"Pick a subscription or local seat.")
    try:
        run_id = engine.start_job(task=prompt, tier="harder", mode="raw", context=context, seats=[model])
    except Exception as exc:
        return f"Could not start: {exc}"
    return _format(engine.job_result(run_id, _wait(wait_seconds)), run_id)


def tool_list_seats() -> str:
    rows = ["| Key | Model | Lane | Family | Lab | Country | Open weights | Metered |", "|---|---|---|---|---|---|---|---|"]
    for key, s in seatlib.load_registry().items():
        rows.append(f"| {key} | {s['label']} | {s['lane']} | {s.get('family')} | {s.get('lab')} | "
                    f"{s.get('country')} | {'yes' if s.get('open_weights') else 'no'} | {'yes' if s.get('metered') else 'no'} |")
    return "\n".join(rows)


def tool_doctor(live=False) -> str:
    return health.render(health.check(live=bool(live)))


def tool_routing_rules() -> str:
    path = paths.REPO / "AGENTS.md"
    return path.read_text(encoding="utf-8") if path.exists() else f"Rules file missing: {path}"


def tool_route(task, job=None, budget=None) -> str:
    return json.dumps(_routes().route(task, job=job, budget=budget), indent=2, ensure_ascii=False, default=str)


def tool_leaderboard(job, n=10, kind=None) -> str:
    return json.dumps(_routes().leaderboard(job, n=n, kind=kind), indent=2, ensure_ascii=False, default=str)


def tool_feedback(job, model, verdict=None, note="", beats=None) -> str:
    from . import learn
    if not verdict and not beats:
        raise ValueError("Give verdict (good or bad) or beats (the model it beat).")
    row = learn.record(job, model, "good" if beats else verdict, note=note, vs=beats, source="mcp")
    from . import community
    try:
        share = community.share_url(job, model, "good" if beats else verdict, beats)
    except ValueError:
        share = None
    return json.dumps({"saved": row, "now": learn.report(),
                       "share": share and {"url": share, "note": "Only if the user wants this verdict in the public "
                                                                "rankings: it opens a public GitHub issue they submit "
                                                                "themselves. Never open or submit it for them."}},
                      indent=2, ensure_ascii=False)


def tool_scout(job) -> str:
    from . import learn
    board = _routes().leaderboard(job, n=10)
    pick = learn.scout(job, board["rows"])
    return json.dumps({"job": job, "try_next": pick and {"id": pick["id"], "name": pick["name"],
                                                         "public_score": pick["score"]}}, indent=2)


HANDLERS = {"council": tool_council, "council_result": tool_council_result, "ask_model": tool_ask_model,
            "list_seats": tool_list_seats, "doctor": tool_doctor, "routing_rules": tool_routing_rules,
            "route": tool_route, "leaderboard": tool_leaderboard, "feedback": tool_feedback, "scout": tool_scout}


# ---------- JSON-RPC plumbing ----------

def _ok(msg_id, result) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _err(msg_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def handle(msg: dict) -> dict | None:
    """One JSON-RPC message in, one response out (None for notifications)."""
    method = msg.get("method")
    msg_id = msg.get("id")
    if method is None:
        return None  # a response from the client; nothing to do
    if msg_id is None:
        return None  # notification (notifications/initialized and friends)
    if method == "initialize":
        want = (msg.get("params") or {}).get("protocolVersion") or PROTOCOL
        return _ok(msg_id, {"protocolVersion": want, "capabilities": {"tools": {}},
                            "serverInfo": {"name": SERVER_NAME, "version": "0.1.0"}, "instructions": INSTRUCTIONS})
    if method == "ping":
        return _ok(msg_id, {})
    if method == "tools/list":
        return _ok(msg_id, {"tools": TOOLS})
    if method == "tools/call":
        params = msg.get("params") or {}
        fn = HANDLERS.get(params.get("name"))
        if fn is None:
            return _err(msg_id, -32602, f"Unknown tool '{params.get('name')}'")
        try:
            text = fn(**(params.get("arguments") or {}))
            return _ok(msg_id, {"content": [{"type": "text", "text": str(text)}], "isError": False})
        except TypeError as exc:
            return _ok(msg_id, {"content": [{"type": "text", "text": f"Bad arguments: {exc}"}], "isError": True})
        except Exception as exc:  # a tool failure is a tool result, not a protocol error
            return _ok(msg_id, {"content": [{"type": "text", "text": f"Error: {exc}"}], "isError": True})
    return _err(msg_id, -32601, f"Method not found: {method}")


def main() -> None:
    for stream in (sys.stdin, sys.stdout):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError as exc:
            sys.stdout.write(json.dumps(_err(None, -32700, f"Parse error: {exc}")) + "\n")
            sys.stdout.flush()
            continue
        replies = [handle(m) for m in msg] if isinstance(msg, list) else [handle(msg)]
        for reply in replies:
            if reply is not None:
                sys.stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
                sys.stdout.flush()


if __name__ == "__main__":
    main()
