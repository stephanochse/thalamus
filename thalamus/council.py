"""Council: let any AI tool consult other model families, and go deeper on demand.

    thalamus council run --tier deep --file task.md --draft my_answer.md --host claude
    thalamus council run --tier harder --mode review --file task.md --draft draft.md --host gpt
    thalamus council ask --model gpt:high --file task.md
    thalamus council seats --tier max --host claude        (dry run: who would sit)
    thalamus council show <run_id>
    thalamus council doctor [--live]

Tiers:
    harder  one outside family, high effort
    deep    three outside families, blind first round, high effort
    max     every outside family at top effort, blind, then an anonymized cross-review round,
            plus the configured extras (default: open-weights models from non-US labs on OpenRouter)

Seat choice: one seat per model family, never the host's own family. When a tier has fewer slots than
candidate families, the panel is picked for diversity: minds from different labs and countries come before
a second mind from the same place. Subscription seats come before metered (pay per token) seats.

Patterns used: the host commits its own answer before the panel speaks, seats from vendors other than the
host, anonymized peer review in round 2, adversarial review stances, independent first answers with
dissent kept visible.

Config (HOME/config.json), all optional:
    {"private_contexts": ["private"],
     "council": {"families": ["openai", "anthropic", "xai", "google"], "extras": ["glm-5.3", "kimi-k3"]}}
Metered seats never run in a private context.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import string
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait
from pathlib import Path

from . import paths, seats as seatlib
from .scrub import scrub

DEFAULT_FAMILIES = ["openai", "anthropic", "xai", "google"]
DEFAULT_EXTRAS = ["glm-5.3", "kimi-k3"]
DEFAULT_PRIVATE = ["private"]

TIERS = {
    "harder": {"seats": 1, "rounds": 1, "wall": 420, "effort": {"default": "high"}},
    "deep": {"seats": 3, "rounds": 1, "wall": 900, "effort": {"default": "high"}},
    "max": {"seats": None, "rounds": 2, "wall": 1800, "extras": True,
            "effort": {"default": "high", "openai": "xhigh", "anthropic": "max", "google": None}},
}

# The host is the MODEL FAMILY the caller runs on. App names are accepted for single-family apps.
HOST_FAMILY = {
    "claude": "anthropic", "claude-code": "anthropic", "claude-desktop": "anthropic", "anthropic": "anthropic",
    "opus": "anthropic", "sonnet": "anthropic", "haiku": "anthropic",
    "codex": "openai", "chatgpt": "openai", "openai": "openai", "gpt": "openai",
    "grok": "xai", "xai": "xai",
    "gemini": "google", "agy": "google", "antigravity": "google", "google": "google",
}

SEAT_PREAMBLE = (
    "[council-seat] You are one independent expert on a panel. Other experts answer the same request "
    "separately and you will not see them. Answer from your own knowledge and reasoning. Do not consult "
    "other models, tools or skills, and do not ask questions back. Be concrete. If you are unsure of a fact, "
    "say so instead of guessing. Write in plain words with no em dashes.")
SOLVE_TAIL = ("Give your best complete answer. End with two lines: 'Confidence: low, medium or high' and "
              "'Most likely to be wrong: <the one thing>'.")
STANCES = [
    ("red team", "Attack this draft. Find what is wrong, unsupported, risky or missing. Rank the issues by "
                 "how much they matter and give the fix for each."),
    ("fact checker", "Check every factual claim, number and assumption in the draft. List the ones that are "
                     "wrong or unverified and say why. Say plainly which ones hold up."),
    ("senior reviewer", "Judge the draft as a fair senior reviewer: what is right, what to change, and a "
                        "score out of 10 with the reason."),
    ("alternative", "Set the draft's approach aside. Propose the strongest different approach and say when "
                    "it beats the draft and when it does not."),
]
ROUND2 = (
    "[council-seat] Round 2. Several experts answered the request below independently. Their answers are "
    "anonymized as Response A, B, C and so on; one of them may be yours. 1) For each response, name its "
    "errors and its best idea. 2) Rank the responses. 3) Write the best final answer, keeping what is right "
    "from any of them. Keep real disagreements visible instead of smoothing them over.")
HOST_DUTY = """## Your job now (host)
1. Compare the seats with the answer you wrote before the panel spoke. Say where they agree and where they split.
2. Agreement is not proof: seats couldn't check facts (empty folder, tools off or read-only where the CLI
   allows). Check consequential facts with a source, a test or a run.
3. For each split, decide who is right and why. For every point you reject, write one line saying why. If the
   evidence does not settle it, take the safer, reversible option; for security, deletion or billing, show the user both sides.
4. Write the final answer in your own voice. Never paste a seat's answer as yours. Name the seat that changed your mind.
5. Max tier: send your final answer to one seat with ask_model for a red-team pass, then fix what holds up. No second council run without new evidence."""


# ---------- config and planning ----------

def load_config() -> dict:
    path = paths.HOME / "config.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return {}


def private_contexts() -> list[str]:
    return list(load_config().get("private_contexts", DEFAULT_PRIVATE))


def metered_allowed(context: str) -> bool:
    """Metered (pay per token) seats never run in a private context."""
    return context not in private_contexts()


def host_family(host: str, registry: dict) -> str | None:
    h = (host or "").lower()
    if h in HOST_FAMILY:
        return HOST_FAMILY[h]
    if any(s.get("family") == h for s in registry.values()):
        return h
    return None


def _run_id(tier: str) -> str:
    tag = "".join(random.choices(string.ascii_lowercase + string.digits, k=4))
    return f"{time.strftime('%Y%m%d-%H%M%S')}-{tier}-{tag}"


def _tier_effort(tier: str, family: str | None, extra: bool = False) -> str | None:
    eff = TIERS[tier]["effort"]
    key = family if family in eff else "default"
    return eff[key]


def _entry_row(entry: dict, effort: str | None, **more) -> dict:
    return {"key": entry["key"], "label": entry["label"], "lane": entry["lane"], "family": entry.get("family"),
            "lab": entry.get("lab"), "country": entry.get("country"), "metered": bool(entry.get("metered")),
            "effort": effort, "skip": None, **more}


def _usable(entry: dict, context: str) -> str | None:
    """Reason a seat cannot sit, or None."""
    if entry.get("metered") and not metered_allowed(context):
        return f"metered seat, and context '{context}' is private"
    return seatlib.available(entry)


def _diverse_pick(candidates: list[dict], n: int | None) -> list[dict]:
    """Greedy: next seat is the one adding a new lab (+2) and a new country (+1). Ties keep the given order."""
    if n is None or n >= len(candidates):
        return list(candidates)
    chosen: list[dict] = []
    pool = list(candidates)
    while pool and len(chosen) < n:
        labs = {c.get("lab") for c in chosen}
        countries = {c.get("country") for c in chosen}
        best = max(range(len(pool)), key=lambda i: (2 * (pool[i].get("lab") not in labs)
                                                    + (pool[i].get("country") not in countries), -i))
        chosen.append(pool.pop(best))
    return chosen


def plan_seats(tier: str, host: str = "unknown", context: str = "general",
               seats: list[str] | None = None) -> list[dict]:
    """Rows [{key, label, lane, family, lab, country, metered, effort, skip, extra}]. Rows with a `skip` reason
    will not be called and are listed in the report. Rows without one will sit."""
    registry = seatlib.load_registry()
    plan: list[dict] = []
    if seats:
        for spec in seats:
            entry = seatlib.resolve(spec)
            row = _entry_row(entry, entry["effort"])
            row["skip"] = _usable(entry, context)
            plan.append(row)
        return plan
    if tier not in TIERS:
        raise ValueError(f"Unknown tier '{tier}'. Use one of {list(TIERS)}.")
    cfg = load_config().get("council", {})
    families = cfg.get("families") or DEFAULT_FAMILIES
    skipped: list[dict] = []
    candidates: list[dict] = []
    hostfam = host_family(host, registry)
    for fam in families:
        members = [e for e in registry.values() if e.get("family") == fam]
        # Subscription seats first, then registry order.
        members.sort(key=lambda e: bool(e.get("metered")))
        if not members:
            skipped.append({"key": fam, "label": fam, "lane": "-", "family": fam, "skip": "no seat configured for this family"})
            continue
        if fam == hostfam:
            skipped.append(_entry_row(members[0], None, skip=f"host family ({fam})"))
            continue
        reasons = []
        for entry in members:
            why = _usable(entry, context)
            if why is None:
                candidates.append(_entry_row(entry, _tier_effort(tier, fam)))
                break
            reasons.append(f"{entry['key']}: {why}")
        else:
            skipped.append(_entry_row(members[0], None, skip="; ".join(reasons)))
    plan = _diverse_pick(candidates, TIERS[tier]["seats"])
    if TIERS[tier].get("extras"):
        for key in cfg.get("extras", DEFAULT_EXTRAS):
            if key not in registry:
                skipped.append({"key": key, "label": key, "lane": "-", "family": None, "skip": "extra seat not in the registry", "extra": True})
                continue
            entry = registry[key]
            if hostfam and entry.get("family") == hostfam:
                skipped.append(_entry_row(entry, None, skip=f"host family ({hostfam})", extra=True))
            elif any(p["key"] == key for p in plan):
                continue
            elif (why := _usable(entry, context)):
                skipped.append(_entry_row(entry, None, skip=why, extra=True))
            else:
                plan.append(_entry_row(entry, _tier_effort(tier, entry.get("family")), extra=True))
    return plan + skipped


def sitting(plan: list[dict]) -> list[dict]:
    return [s for s in plan if not s.get("skip")]


def _spec(seat: dict) -> str:
    return f"{seat['key']}:{seat['effort']}" if seat.get("effort") else seat["key"]


def _seat_prompt(task: str, mode: str, draft: str | None, index: int) -> tuple[str, str]:
    if mode == "review":
        stance, brief = STANCES[index % len(STANCES)]
        return stance, f"{SEAT_PREAMBLE}\n\nYour role: {stance}. {brief}\n\n## Request\n{task}\n\n## Draft to review\n{draft}"
    if mode == "raw":
        return "direct", f"[council-seat] Answer directly. Do not consult other models or tools.\n\n{task}"
    return "independent", f"{SEAT_PREAMBLE}\n\n## Request\n{task}\n\n## Your answer\n{SOLVE_TAIL}"


# ---------- runs on disk ----------

RUN_ID = re.compile(r"\d{8}-\d{6}-[a-z]+-[a-z0-9]{4}")


class Run:
    """One council run on disk: HOME/runs/<id>/ holds task.md, draft.md, meta.json, seatN.md and report.md."""

    def __init__(self, run_id: str):
        if not RUN_ID.fullmatch(run_id or ""):
            raise ValueError(f"Not a run id: {run_id!r}")
        runs = (paths.HOME / "runs").resolve()
        self.id = run_id
        self.dir = (runs / run_id).resolve()
        if runs not in self.dir.parents:
            raise ValueError(f"Run id escapes the runs folder: {run_id!r}")
        self.lock = threading.RLock()

    def write(self, name: str, text: str) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / name).write_text(text, encoding="utf-8")

    def save_meta(self, meta: dict) -> None:
        with self.lock:
            self.write("meta.json", json.dumps(meta, indent=2, ensure_ascii=False))

    def meta(self) -> dict:
        path = self.dir / "meta.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def report(self) -> str:
        path = self.dir / "report.md"
        return path.read_text(encoding="utf-8") if path.exists() else ""


def _call_seat(seat: dict, prompt: str, timeout: int) -> dict:
    return seatlib.call(_spec(seat), prompt, timeout=timeout)


def run_council(task: str, draft: str | None = None, tier: str = "deep", mode: str = "solve",
                host: str = "unknown", context: str = "general", seats: list[str] | None = None,
                keep_emails: bool = False, run_id: str | None = None) -> Run:
    if seatlib.depth() >= 1:
        raise RuntimeError(f"Refused: this process is itself a council seat ({seatlib.DEPTH_VAR} is set). Answer directly.")
    if mode not in ("solve", "review", "raw"):
        raise ValueError("mode must be solve, review or raw")
    if mode == "review" and not (draft or "").strip():
        raise ValueError("Review mode needs the draft to review.")
    cfg = TIERS.get(tier, TIERS["harder"])
    full_plan = plan_seats(tier, host, context, seats)
    plan = sitting(full_plan)
    skipped = [s for s in full_plan if s.get("skip")]
    if not plan:
        raise RuntimeError("No seat can sit: " + "; ".join(f"{s['label']} ({s['skip']})" for s in skipped))
    run = Run(run_id or _run_id(tier if not seats else "ask"))

    clean_task = scrub(task, keep_emails=keep_emails)
    clean_draft = scrub(draft, keep_emails=keep_emails) if draft else None
    redactions = {k: clean_task.counts.get(k, 0) + (clean_draft.counts.get(k, 0) if clean_draft else 0)
                  for k in clean_task.counts}
    names = {**clean_task.names, **(clean_draft.names if clean_draft else {})}
    run.write("task.md", clean_task.text)
    if draft:
        run.write("draft.md", draft)

    started = time.time()
    meta = {"id": run.id, "status": "running", "tier": tier, "mode": mode, "host": host, "context": context,
            "started": time.strftime("%Y-%m-%d %H:%M:%S"), "redacted": redactions, "names": names,
            "host_draft_committed": bool((draft or "").strip()), "seats": [], "round2": [],
            "skipped": [{"label": s["label"], "key": s["key"], "reason": s["skip"]} for s in skipped]}
    for i, seat in enumerate(plan):
        stance, _ = _seat_prompt("", mode, "", i)
        meta["seats"].append({**seat, "stance": stance, "status": "waiting"})
    run.save_meta(meta)

    def one(i: int, seat: dict) -> None:
        _, prompt = _seat_prompt(clean_task.text, mode, clean_draft.text if clean_draft else None, i)
        with run.lock:
            meta["seats"][i]["status"] = "running"
            run.save_meta(meta)
        remaining = max(30, int(cfg["wall"] - (time.time() - started)))
        r = _call_seat(seat, prompt, remaining)
        run.write(f"seat{i + 1}.md", r["text"] or f"(no answer: {r['error']})")
        with run.lock:
            meta["seats"][i].update(status="error" if r["error"] else "done", seconds=r.get("seconds"),
                                    cost=r.get("cost"), error=r["error"], file=f"seat{i + 1}.md")
            run.save_meta(meta)

    with ThreadPoolExecutor(max_workers=max(1, len(plan))) as pool:
        futures = [pool.submit(one, i, s) for i, s in enumerate(plan)]
        wait(futures, timeout=cfg["wall"] + 60)

    if cfg["rounds"] >= 2 and not seats and mode != "raw":
        answered = [(i, s) for i, s in enumerate(meta["seats"]) if s["status"] == "done"]
        if len(answered) >= 2:
            labels = [chr(65 + n) for n in range(len(answered))]
            shuffled = random.sample(answered, len(answered))
            bundle = "\n\n".join(f"## Response {lab}\n{(run.dir / s['file']).read_text(encoding='utf-8')}"
                                 for lab, (_, s) in zip(labels, shuffled))
            meta["round2_key"] = {lab: s["label"] for lab, (_, s) in zip(labels, shuffled)}
            prompt2 = f"{ROUND2}\n\n## Request\n{clean_task.text}\n\n{bundle}"

            def two(i: int, seat: dict) -> None:
                remaining = max(30, int(cfg["wall"] - (time.time() - started)))
                r = _call_seat(seat, prompt2, remaining)
                run.write(f"round2-seat{i + 1}.md", r["text"] or f"(no answer: {r['error']})")
                with run.lock:
                    meta["round2"].append({"label": seat["label"], "seconds": r.get("seconds"),
                                           "error": r["error"], "file": f"round2-seat{i + 1}.md"})
                    run.save_meta(meta)

            with ThreadPoolExecutor(max_workers=len(answered)) as pool:
                futures = [pool.submit(two, i, plan[i]) for i, _ in answered]
                wait(futures, timeout=max(60, cfg["wall"] - (time.time() - started)))

    for seat in meta["seats"]:
        if seat["status"] in ("waiting", "running"):
            seat["status"] = "timed out"
    meta["status"] = "done"
    meta["seconds"] = round(time.time() - started, 1)
    run.save_meta(meta)
    run.write("report.md", render_report(run))
    return run


def render_report(run: Run) -> str:
    meta = run.meta()
    seats = meta.get("seats", [])
    ok = sum(1 for s in seats if s["status"] == "done")
    money = sum(s.get("cost") or 0 for s in seats)
    lines = [f"# Council report ({meta['tier']}, {meta['mode']}) run {meta['id']}",
             f"Host {meta['host']} | context {meta['context']} | {ok} of {len(seats)} seats answered | "
             f"{meta.get('seconds', 0)}s | metered cost ${money:.4f}"]
    red = ", ".join(f"{n} {k}" for k, n in meta.get("redacted", {}).items() if n)
    lines.append(f"Removed before sending: {red or 'nothing'}"
                 + (f" | placeholders: {meta['names']}" if meta.get("names") else ""))
    if meta.get("skipped"):
        lines.append("Skipped (not called): " + "; ".join(f"{s['label']}: {s['reason']}" for s in meta["skipped"]))
    if meta.get("mode") != "raw" and not meta.get("host_draft_committed"):
        lines.append("WARNING: no host draft was written before the panel. Write your own answer first next time.")
    if meta.get("mode") != "raw" and str(meta.get("host", "unknown")).lower() in ("unknown", ""):
        lines.append("NOTE: host family unknown, so no family was skipped. Pass host so the panel is not echoing you.")
    for i, s in enumerate(seats):
        head = f"## Seat {i + 1}: {s['label']} ({s['lane']}, effort {s.get('effort') or 'default'}, {s.get('seconds', 0)}s"
        head += f", role: {s['stance']})" if s.get("stance") not in (None, "independent", "direct") else ")"
        body = (run.dir / s["file"]).read_text(encoding="utf-8") if s.get("file") and (run.dir / s["file"]).exists() \
            else f"(no answer: {s.get('error') or s['status']})"
        lines += ["", head, body.strip()]
    if meta.get("round2"):
        lines += ["", "# Round 2: anonymized cross-review",
                  f"Response key (for you only): {meta.get('round2_key')}"]
        for r in meta["round2"]:
            body = (run.dir / r["file"]).read_text(encoding="utf-8")
            lines += ["", f"## {r['label']} reviews the others ({r.get('seconds', 0)}s)", body.strip()]
    if meta["mode"] != "raw":
        lines += ["", HOST_DUTY]
    return "\n".join(lines) + "\n"


# ---------- background jobs (MCP clients time out long tool calls) ----------

_JOBS: dict[str, threading.Thread] = {}


def start_job(**kwargs) -> str:
    tier = kwargs.get("tier", "deep")
    run_id = _run_id(tier if not kwargs.get("seats") else "ask")
    plan = plan_seats(tier, kwargs.get("host", "unknown"), kwargs.get("context", "general"), kwargs.get("seats"))
    if not sitting(plan):
        raise RuntimeError("No seat can sit: " + "; ".join(f"{s['label']} ({s['skip']})" for s in plan))

    def target() -> None:
        try:
            run_council(run_id=run_id, **kwargs)
        except Exception as exc:  # recorded for the caller instead of lost in a thread
            Run(run_id).save_meta({"id": run_id, "status": "failed", "error": str(exc)})

    thread = threading.Thread(target=target, daemon=True)
    _JOBS[run_id] = thread
    thread.start()
    return run_id


def job_result(run_id: str, wait_seconds: float = 0) -> dict:
    run = Run(run_id)
    deadline = time.time() + max(0, wait_seconds)
    while True:
        meta = run.meta()
        if meta.get("status") in ("done", "failed"):
            return {"status": meta["status"], "report": run.report() or meta.get("error", ""), "dir": str(run.dir)}
        if time.time() >= deadline:
            progress = [f"{s['label']}: {s['status']}" for s in meta.get("seats", [])]
            return {"status": meta.get("status", "starting"), "progress": progress, "dir": str(run.dir)}
        time.sleep(1)


# ---------- CLI ----------

def _read(path_or_text: str | None) -> str | None:
    if not path_or_text:
        return None
    p = Path(path_or_text)
    try:
        return p.read_text(encoding="utf-8") if p.exists() else path_or_text
    except OSError:
        return path_or_text


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="thalamus council", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="convene the council")
    r.add_argument("--tier", default="deep", choices=list(TIERS))
    r.add_argument("--mode", default="solve", choices=["solve", "review"])
    r.add_argument("--file", "--prompt", dest="task", required=True, help="task text or a file path")
    r.add_argument("--draft", help="your own committed answer (text or file path)")
    r.add_argument("--host", default="unknown", help="model family you run on: claude, gpt, grok, gemini, ...")
    r.add_argument("--context", default="general")
    r.add_argument("--seats", help="comma-separated seat keys to override the tier's seats")
    r.add_argument("--keep-emails", action="store_true")
    a = sub.add_parser("ask", help="one seat, one answer")
    a.add_argument("--model", required=True)
    a.add_argument("--file", "--prompt", dest="task", required=True)
    a.add_argument("--context", default="general")
    a.add_argument("--keep-emails", action="store_true")
    s = sub.add_parser("seats", help="show who would sit, without calling anyone")
    s.add_argument("--tier", default="deep", choices=list(TIERS))
    s.add_argument("--host", default="unknown")
    s.add_argument("--context", default="general")
    sh = sub.add_parser("show", help="print a saved run report")
    sh.add_argument("run_id")
    d = sub.add_parser("doctor", help="check every login")
    d.add_argument("--live", action="store_true", help="also send a one-word test prompt to each subscription seat")
    args = ap.parse_args(argv)

    try:
        if args.cmd == "doctor":
            from . import doctor
            print(doctor.render(doctor.check(live=args.live)))
        elif args.cmd == "seats":
            for seat in plan_seats(args.tier, args.host, args.context):
                flag = f"  SKIPPED: {seat['skip']}" if seat.get("skip") else ""
                print(f"{seat['label']:44} {seat['lane']:12} effort {seat.get('effort') or 'default'}{flag}")
        elif args.cmd == "show":
            run = Run(args.run_id)
            print(run.report() or json.dumps(run.meta(), indent=2))
        elif args.cmd == "ask":
            run = run_council(_read(args.task), tier="harder", mode="raw", context=args.context,
                              seats=[args.model], keep_emails=args.keep_emails)
            print(run.report())
        else:
            chosen = [x.strip() for x in args.seats.split(",")] if args.seats else None
            run = run_council(_read(args.task), draft=_read(args.draft), tier=args.tier, mode=args.mode,
                              host=args.host, context=args.context, seats=chosen, keep_emails=args.keep_emails)
            print(run.report())
            print(f"[saved in {run.dir}]", file=sys.stderr)
    except (ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
