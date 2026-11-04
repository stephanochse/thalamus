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
import math
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


GROUP_SUPPORT = 0.25  # share of the weight from the job's group-mates that backs it (a build brief's parts)
CLOSE = 0.8  # a single-word winner with a rival this close is a guess, not a match
ALSO_MIN = 0.75  # weight another job needs to be listed as a part of the task


def _rarity(meta: list[dict]) -> dict[str, float]:
    """A keyword several jobs share ('script', 'transcript') says less than one only one job uses."""
    df: dict[str, int] = {}
    for job in meta:
        for k in set(job.get("keywords", [])):
            df[k] = df.get(k, 0) + 1
    n = max(len(meta), 1)
    return {k: math.log(1 + n / c) / math.log(1 + n) for k, c in df.items()}


def _spans(text: str, keyword: str) -> list[tuple[int, int]]:
    return [m.span() for m in re.finditer(r"(?<![a-z])" + re.escape(keyword) + r"(?![a-z])", text)]


def _found(text: str, meta: list[dict]) -> set[str]:
    """Keywords in the text, minus any that only appear inside a longer keyword that also matched:
    'voice note' is not a vote for 'voice', and 'landing page copy' is not one for 'landing page'."""
    spans = {k: s for k in {k for job in meta for k in job.get("keywords", [])} if (s := _spans(text, k))}

    def inside(a: int, b: int, k: str) -> bool:
        return any(len(o) > len(k) and x <= a and b <= y for o, ss in spans.items() for x, y in ss)
    return {k for k, ss in spans.items() if not all(inside(a, b, k) for a, b in ss)}


def _scored(task: str, meta: list[dict]) -> list[dict]:
    """Every job with a hit: phrases count double, shared keywords count less, and a job gets a little
    backing from hits on the other jobs in its group. Sorted best first; file order breaks ties."""
    text, rare = task.lower(), _rarity(meta)
    found = _found(text, meta)
    rows = []
    for order, job in enumerate(meta):
        hits = [k for k in job.get("keywords", []) if k in found]
        if hits:
            weight = sum((2 if " " in h else 1) * rare.get(h, 1.0) for h in hits)
            rows.append({"job": job["id"], "group": job.get("group"), "hits": hits, "weight": round(weight, 2),
                         "order": order})
    mass: dict[str | None, float] = {}
    for r in rows:
        mass[r["group"]] = mass.get(r["group"], 0.0) + r["weight"]
    for r in rows:
        r["total"] = round(r["weight"] + GROUP_SUPPORT * (mass[r["group"]] - r["weight"]), 2)
    return sorted(rows, key=lambda r: (-r["total"], r["order"]))


def _labels(meta: list[dict]) -> dict[str, str]:
    return {j["id"]: f"{j['title']} (e.g. {', '.join(j.get('keywords', [])[:6])})" for j in meta}


def classify_detail(task: str, classifier=None) -> dict:
    """Which job a task is, how sure the match is, and the other jobs it touches.

    confidence: high (two keywords or a phrase), medium (one word, nothing close), low (one word with a
    close rival), none (no keyword). On low or none, `classifier(task, labels)` gets a say when given:
    it returns {"choice", "probability", ...} or None, and None keeps the keyword result."""
    meta = _jobs_meta()
    rows = _scored(task, meta)
    if rows:
        top = rows[0]
        strong = len(top["hits"]) >= 2 or any(" " in h for h in top["hits"])
        close = any(r["weight"] >= CLOSE * top["weight"] for r in rows[1:])
        confidence = "high" if strong else ("low" if close else "medium")
        out = {"job": top["job"], "matched": top["hits"], "confidence": confidence, "method": "keywords"}
    else:
        out = {"job": "general", "matched": [], "confidence": "none", "method": "default"}
    if out["confidence"] in ("low", "none") and classifier:
        pick = classifier(task, _labels(meta))
        if pick and pick.get("choice") in {j["id"] for j in meta}:
            out.update(job=pick["choice"], method="classifier",
                       matched=next((r["hits"] for r in rows if r["job"] == pick["choice"]), []),
                       classifier={k: pick.get(k) for k in ("model", "probability", "cost")})
    out["also"] = [{"job": r["job"], "matched": r["hits"]} for r in rows
                   if r["job"] != out["job"] and r["weight"] >= ALSO_MIN][:4]
    return out


def classify(task: str) -> tuple[str, list[str]]:
    """Keyword match against jobs.json. Returns (job_id, matched words). Cheap and explainable;
    an agent can always override by passing job= explicitly. classify_detail says how sure it is."""
    detail = classify_detail(task)
    return detail["job"], detail["matched"]


def _classifier(setting, cfg: dict):
    """route()'s classifier argument: a callable, True/False, or None for the config and environment."""
    if callable(setting):
        return setting
    from . import classifier as clf
    if setting is False or (setting is None and not clf.enabled(cfg)):
        return None
    model = clf.model_from(cfg)
    return lambda task, labels: clf.choose(task, labels, model=model)


def local_options(job: str) -> list[dict]:
    """Tools that do the job on your own machine (jobs.json "local"), with whether each is installed."""
    import importlib.util
    import shutil
    meta = next((j for j in _jobs_meta() if j["id"] == job), {})
    out = []
    for opt in meta.get("local", []):
        installed = bool((opt.get("module") and importlib.util.find_spec(opt["module"]))
                         or (opt.get("command") and shutil.which(opt["command"])))
        out.append({**{k: v for k, v in opt.items() if k not in ("module", "command")}, "installed": installed})
    return sorted(out, key=lambda o: not o["installed"])


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


def route(task: str, job: str | None = None, budget: str | None = None, classifier=None) -> dict:
    """classifier: None follows config/THALAMUS_CLASSIFIER, True/False forces it, or pass a callable
    (task, labels) -> {"choice", "probability"} | None to use your own decision model."""
    data = _routes()
    jobs = data["jobs"]
    cfg = _config()
    matched: list[str] = []
    detail = None
    if not job:
        detail = classify_detail(task, classifier=_classifier(classifier, cfg))
        job, matched = detail["job"], detail["matched"]
    if job not in jobs:
        job = "general" if "general" in jobs else next(iter(jobs))
    entry = dict(jobs[job])
    from . import learn
    entry["top"] = learn.personalize(job, entry.get("top", []))
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
    if detail:
        result["confidence"], result["method"] = detail["confidence"], detail["method"]
        if detail.get("classifier"):
            result["classifier"] = detail["classifier"]
        if detail["also"]:
            result["also"] = detail["also"]  # other parts of the task: route them on their own
        if detail["confidence"] in ("low", "none") and detail["method"] != "classifier":
            result["match_note"] = ("Weak keyword match. Pass job= if this is wrong (see `thalamus jobs`), or turn on "
                                    "the classifier fallback (--classify, or \"classifier\": true in the config).")
    if not entry.get("picks"):
        local = local_options(job)
        result["no_public_scores"] = True
        result["note"] = (f"No model has public scores for '{entry['title']}' this week, so there are no picks. "
                          "Say so rather than borrowing a pick from another job."
                          + (" A local tool can do it: see local_options." if local else ""))
        if local:
            result["local_options"] = local
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
