"""Answer "which model for this?" from the weekly data.

    route("refactor this TypeScript service")        -> job "code-build" with picks and reasons
    route("anything", job="image-gen", budget="value")
    leaderboard("long-context", n=10)

Picks come from data/routes.json (rebuilt every week). "Your picks" re-ranks them for the
channels you actually have, set in ~/.thalamus/config.json:

    {"access": ["claude-cli", "codex", "openrouter"], "prefer_subscriptions": true}

Subscription channels (claude-cli, codex, grok, agy) cost nothing extra per token, so when
prefer_subscriptions is on, a model you already pay for wins ties against a metered one.
"""
from __future__ import annotations

import json
import random
import re

from . import paths

SUBSCRIPTION_CHANNELS = {"claude-cli", "codex", "grok", "agy", "ollama"}
BUDGETS = ["best", "value", "budget", "fast", "open"]


def _load(path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _data_date(payload: dict) -> str:
    """The oldest fetch date among sources that delivered rows: an offline rebuild of old data stays old."""
    dates = [s.get("fetched") for s in (payload.get("sources") or {}).values() if s.get("rows") and s.get("fetched")]
    return min(dates) if dates else payload.get("updated", "")


def _routes() -> dict:
    """Your personal build (~/.thalamus/data) when it's at least as fresh as the public weekly data,
    otherwise the public data that ships with the repo."""
    public = _load(paths.DATA / "routes.json")
    personal = _load(paths.PERSONAL_DATA / "routes.json")
    if personal and (not public or _data_date(personal) >= _data_date(public)):
        return personal
    if public:
        return public
    raise FileNotFoundError(f"{paths.DATA / 'routes.json'} is missing. Run `thalamus update` first.")


def _config() -> dict:
    try:
        return json.loads(paths.CONFIG.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _jobs_meta() -> list[dict]:
    from .score import load_jobs
    return load_jobs()


def classify(task: str) -> tuple[str, list[str]]:
    """Keyword match against jobs.json. Returns (job_id, matched words). Cheap and explainable;
    an agent can always override by passing job= explicitly."""
    text = task.lower()
    best, best_hits = "general", []
    for job in _jobs_meta():
        hits = [k for k in job.get("keywords", []) if re.search(r"(?<![a-z])" + re.escape(k) + r"(?![a-z])", text)]
        weight = sum(2 if " " in h else 1 for h in hits)
        if weight > sum(2 if " " in h else 1 for h in best_hits):
            best, best_hits = job["id"], hits
    return best, best_hits


def _served(served: dict | None) -> dict:
    """{channel: regex} of the model ids each subscription CLI serves on YOUR plan, e.g.
    {"claude-cli": "^anthropic/claude-(opus|sonnet|haiku)", "codex": "^openai/gpt-6"}. Lab alone doesn't
    tell us: plans serve some models and not others."""
    out = {}
    for ch, pat in (served or {}).items():
        out[ch] = pat if hasattr(pat, "search") else re.compile(pat)
    return out


def _reachable(row: dict, access: list[str], served: dict | None = None) -> list[str]:
    via = [c for c in (row.get("access") or []) if c in access]
    base = row["id"].split("@", 1)[0]
    via += [ch for ch, pat in _served(served).items() if ch in access and ch not in via and pat.search(base)]
    return via


def your_picks(entry: dict, access: list[str], prefer_subscriptions: bool = True,
               served: dict | None = None) -> dict:
    """For each budget, the best model in the job's top list that you can actually call."""
    if not access:
        return {}
    # released models only; one with no public API can still be yours if a served pattern covers it
    top = [r for r in entry.get("top", []) if not r.get("unreleased")]
    out = {}
    reachable = [{**r, "access": _reachable(r, access, served)} for r in top]
    reachable = [r for r in reachable if r["access"]]
    if not reachable:
        return {}
    best = reachable[0]
    out["best"] = best
    if prefer_subscriptions:
        subs = [r for r in reachable if set(r["access"]) & SUBSCRIPTION_CHANNELS]
        if subs and subs[0]["score"] >= 0.9 * best["score"]:
            out["included"] = subs[0]  # good enough and already paid for
    priced = [r for r in reachable if r.get("price") is not None]
    top_q = max((r.get("quality", r["score"]) for r in reachable), default=0)
    if priced:
        within = [r for r in priced if r.get("quality", r["score"]) >= 0.9 * top_q]
        if within:
            out["value"] = min(within, key=lambda r: r["price"])
        within = [r for r in priced if r.get("quality", r["score"]) >= 0.75 * top_q]
        if within:
            out["budget"] = min(within, key=lambda r: r["price"])
    return {k: {"id": v["id"], "name": v["name"], "score": v["score"], "price": v.get("price"),
                "via": v["access"]} for k, v in out.items()}


def _matches(pattern: str, model_id: str) -> bool:
    try:
        return re.match(pattern, model_id) is not None
    except re.error:
        return model_id.startswith(pattern)


def your_favourites(entry: dict, patterns: list[str]) -> list[dict]:
    """Where each model family you like stands for this job: its best model, rank and share of the top
    score. Looks through the job's top list, then its lab champions (which cover every ranked model)."""
    rows = [r for r in entry.get("top", []) if r.get("pickable", True)]  # models you can call
    top_score = max((r["score"] for r in rows), default=None)
    pool = rows + [c for c in entry.get("labs", []) if c["id"] not in {r["id"] for r in rows}]
    out = []
    for p in patterns or []:
        hit = next(((i, r) for i, r in enumerate(pool, 1) if _matches(p, r["id"])), None)
        if not hit:
            continue
        i, r = hit
        out.append({"pattern": p, "id": r["id"], "name": r["name"], "rank": r.get("rank", i), "score": r["score"],
                    "of_best": round(100 * r["score"] / top_score) if top_score else None, "price": r.get("price")})
    seen, unique = set(), []
    for f in sorted(out, key=lambda f: -f["score"]):
        if f["id"] not in seen:
            seen.add(f["id"])
            unique.append(f)
    return unique


def route(task: str, job: str | None = None, budget: str | None = None) -> dict:
    data = _routes()
    jobs = data["jobs"]
    matched: list[str] = []
    if not job:
        job, matched = classify(task)
    if job not in jobs:
        job = "general" if "general" in jobs else next(iter(jobs))
    entry = dict(jobs[job])
    from . import learn
    entry["top"] = learn.personalize(job, entry.get("top", []))
    cfg = _config()
    scout_pick = learn.scout(job, entry["top"]) if cfg.get("scout", True) and random.random() < cfg.get(
        "scout_rate", 0.1) else None
    result = {
        "job": job, "title": entry["title"], "matched_words": matched,
        "updated": data.get("updated"), "picks": entry["picks"], "mix": entry.get("mix"),
        "based_on": entry["metrics"],
        "your_picks": your_picks(entry, cfg.get("access", []), cfg.get("prefer_subscriptions", True),
                                 cfg.get("served")),
        "how_to_use": ("Use 'best' for the hard, high-stakes part (plan, final review, decisions), 'value' for "
                       "most of the work, 'budget' for bulk and first drafts, 'fast' when latency matters. "
                       "Picks are relative to this week's public leaderboards; check your own results. "
                       "Record how it went with the feedback tool so routing learns your taste."),
    }
    if entry.get("labs"):
        result["other_labs"] = [{k: c[k] for k in ("lab", "name", "id", "rank", "of_best", "price")}
                                for c in entry["labs"][:8]]
    if cfg.get("favourites") or cfg.get("favorites"):
        result["your_favourites"] = your_favourites(entry, cfg.get("favourites") or cfg.get("favorites"))
    if any(r.get("your_verdicts") for r in entry["top"]):
        result["personal_top"] = [{"id": r["id"], "name": r["name"], "public": r["score"],
                                   "yours": r.get("personal_score"), "verdicts": r.get("your_verdicts")}
                                  for r in entry["top"][:5]]
        from .score import pick
        mine = pick([{**r, "score": r.get("personal_score", r["score"])} for r in entry["top"]])
        result["personal_picks"] = {k: {"id": v["id"], "name": v["name"], "score": v["score"], "price": v.get("price")}
                                    for k, v in mine.items()}
    if scout_pick:
        result["scout"] = {"id": scout_pick["id"], "name": scout_pick["name"],
                           "why": "Untried on your work and strong on the public board. Use it for a low-stakes "
                                  "task of this kind, then record a verdict."}
    if budget:
        if budget not in BUDGETS:
            raise ValueError(f"budget must be one of {BUDGETS}")
        mine = result.get("personal_picks") or {}
        result["pick"] = mine.get(budget) or entry["picks"].get(budget) or entry["picks"].get("best")
    return result


def leaderboard(job: str, n: int = 10, kind: str | None = None) -> dict:
    data = _routes()
    if job not in data["jobs"]:
        raise ValueError(f"Unknown job '{job}'. Known: {', '.join(sorted(data['jobs']))}")
    entry = data["jobs"][job]
    rows = entry["top"]
    if kind:
        rows = [r for r in rows if kind in (r.get("kinds") or entry["kinds"])]
    return {"job": job, "title": entry["title"], "updated": data.get("updated"), "rows": rows[:n],
            "every_lab": entry.get("labs", [])[:16], "based_on": entry["metrics"]}


def jobs() -> list[dict]:
    return [{"id": j["id"], "title": j["title"], "group": j.get("group"), "about": j.get("about", "")}
            for j in _jobs_meta()]
