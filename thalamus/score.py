"""Score every model for every job, then pick the right one per budget.

Input: the merged catalog (list of model dicts, see merge.py) and jobs.json.
Output: per job, a ranked table plus five picks:

    best    highest score, price ignored
    value   cheapest model within 90% of the best score (and in the top 10)
    budget  cheapest model within 75% of the best score (bulk work)
    fast    fastest model within 85% of the best score
    open    best open-weights model (self-host or cheap providers)

Scores are relative. Each metric is scaled 0-100 inside the pool of models that report it
(floor at the 10th percentile, ceiling at the best), so Elo points, percentages and dollars
can be blended. A model needs enough of a job's metric weight (min_coverage) to be ranked,
and thin coverage costs up to 15% of its score, so one lucky benchmark can't top a table.
"""
from __future__ import annotations

import json
import math
from statistics import median

from .paths import PKG

VALUE_BAND, BUDGET_BAND, FAST_BAND = 0.90, 0.75, 0.85
DEFAULT_MIX = {"best": 0.10, "value": 0.30, "budget": 0.60}  # share of tokens per role in a mixed plan


def load_jobs() -> list[dict]:
    return json.loads((PKG / "jobs.json").read_text(encoding="utf-8"))["jobs"]


def _scale(values: dict[str, float], higher_better: bool = True) -> dict[str, float]:
    if not values:
        return {}
    signed = {k: (v if higher_better else -v) for k, v in values.items()}
    xs = sorted(signed.values())
    lo = xs[int(0.1 * (len(xs) - 1))]
    hi = xs[-1]
    span = hi - lo
    if span <= 0:
        return {k: 100.0 for k in signed}
    return {k: max(0.0, min(1.0, (x - lo) / span)) * 100 for k, x in signed.items()}


NON_QUALITY = ("x.", "aa.index_cost")


def _is_quality(metric_id: str) -> bool:
    return not metric_id.startswith(NON_QUALITY)


def _eligible(model: dict, job: dict) -> bool:
    if model.get("kind") not in job["kinds"]:
        return False
    need = job.get("requires", {})
    if need.get("min_context") and (model.get("context") or 0) < need["min_context"]:
        return False
    for modality in need.get("input", []):
        if modality not in (model.get("input") or []):
            return False
    if need.get("reasoning") is False and model.get("reasoning"):
        return False
    return True


def _price(model: dict) -> float | None:
    p = model.get("price") or {}
    return p.get("blended") if p.get("blended") is not None else p.get("unit_price")


def score_job(job: dict, models: list[dict]) -> list[dict]:
    pool = [m for m in models if _eligible(m, job)]
    metrics = job["metrics"]
    essential = set(job.get("essential", []))
    total_w = sum(mt["w"] for mt in metrics)
    scaled: dict[str, dict[str, float]] = {}
    for mt in metrics:
        vals = {}
        for m in pool:
            v = (m.get("metrics") or {}).get(mt["id"])
            if isinstance(v, (int, float)) and not math.isnan(v):
                if mt.get("log"):
                    if v < 0:
                        continue
                    v = math.log10(max(v, 1e-3))  # free (0) still counts, as the cheapest possible
                vals[m["id"]] = float(v)
        scaled[mt["id"]] = _scale(vals, mt.get("higher", True))
    # Coverage counts only metrics some source actually reported this week, so a source that is
    # down doesn't knock every model under min_coverage. "claim" metrics (benchmarks the labs report
    # about their own models) can add to a model's coverage but don't raise the bar for everyone else.
    total_w = sum(mt["w"] for mt in metrics if scaled[mt["id"]] and not mt.get("claim")) or total_w
    if essential and not any(scaled.get(e) for e in essential):
        return []  # e.g. "fast" without any speed data: better no ranking than a wrong one

    rows = []
    for m in pool:
        got = [(mt, scaled[mt["id"]][m["id"]]) for mt in metrics if m["id"] in scaled[mt["id"]]]
        if not any(_is_quality(mt["id"]) for mt, _ in got) and not essential:
            continue  # price, speed or popularity alone never earns a rank
        if essential and not essential & {mt["id"] for mt, _ in got}:
            continue
        w = sum(mt["w"] for mt, _ in got)
        coverage = min(1.0, w / total_w)
        # the bar is cleared on independent evidence only; vendor claims can add to the score, never qualify it
        independent = sum(mt["w"] for mt, _ in got if not mt.get("claim"))
        if independent / total_w < job.get("min_coverage", 0.5):
            continue
        quality = sum(mt["w"] * s for mt, s in got) / w
        q_only = [(mt, s) for mt, s in got if _is_quality(mt["id"])]
        q_w = sum(mt["w"] for mt, _ in q_only)
        rows.append({
            "quality": round(sum(mt["w"] * s for mt, s in q_only) / q_w, 1) if q_w else 0.0,
            "id": m["id"], "name": m["name"], "lab": m.get("lab"), "open_weights": bool(m.get("open_weights")),
            "score": round(quality * (0.85 + 0.15 * coverage), 1), "coverage": round(coverage, 2),
            "price": _price(m), "price_unit": (m.get("price") or {}).get("unit", "usd_per_mtok"),
            "tps": (m.get("speed") or {}).get("tps"), "context": m.get("context"),
            "openrouter": (m.get("where") or {}).get("openrouter"), "access": m.get("access", []),
            "basis": {mt["id"]: round(s) for mt, s in got},
            # a pick must be something you can run: released, and for text models reachable by API or plan
            "pickable": not m.get("unreleased") and (m.get("kind") != "llm" or bool(m.get("access"))),
            "unreleased": bool(m.get("unreleased")),
        })
    rows.sort(key=lambda r: (-r["score"], r["price"] if r["price"] is not None else 1e9))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows


def _cheapest(rows: list[dict], floor: float, top: int | None = None) -> dict | None:
    """Cheapest model whose quality (price and speed left out) clears the floor."""
    pool = sorted(rows, key=lambda r: -r["quality"])[:top] if top else rows
    cands = [r for r in pool if r["quality"] >= floor and r["price"] is not None]
    return min(cands, key=lambda r: (r["price"], -r["quality"])) if cands else None


def pick(rows: list[dict]) -> dict:
    rows = [r for r in rows if r.get("pickable", True)]
    if not rows:
        return {}
    best = rows[0]
    # value and budget are always judged on quality with price and speed left out, so a job that also
    # rewards low prices (bulk, structured output) can't push a weak model through on price alone
    top_q = max(r["quality"] for r in rows)
    picks = {
        "best": best,
        "value": _cheapest(rows, VALUE_BAND * top_q, top=10),
        "budget": _cheapest(rows, BUDGET_BAND * top_q),
    }
    fast = [r for r in rows if r["quality"] >= FAST_BAND * top_q and r.get("tps")]
    picks["fast"] = max(fast, key=lambda r: r["tps"]) if fast else None
    picks["open"] = next((r for r in rows if r["open_weights"]), None)
    return {k: v for k, v in picks.items() if v}


def mix_savings(picks: dict, mix: dict | None = None) -> dict | None:
    """Cost of a mixed plan (top model for the hard 10%, value pick for 30%, budget pick for 60%)
    against sending everything to the top model. Only for jobs priced per token."""
    mix = mix or DEFAULT_MIX
    best = picks.get("best")
    if not best or best.get("price") in (None, 0) or best.get("price_unit") != "usd_per_mtok":
        return None
    if any(k.startswith("x.price") for k in best.get("basis", {})):
        return None  # price is already part of this job's score; a mixed plan adds nothing
    cost = 0.0
    for role, share in mix.items():
        r = picks.get(role) or best
        if r.get("price") is None:
            return None
        cost += share * r["price"]
    return {"mixed_per_mtok": round(cost, 3), "all_best_per_mtok": round(best["price"], 3),
            "saves_pct": round(100 * (1 - cost / best["price"]))}


PICK_FIELDS = ("id", "name", "lab", "score", "price", "price_unit", "tps", "openrouter", "access", "held")


def build_routes(models: list[dict], jobs: list[dict] | None = None, top_n: int = 40,
                 previous: dict | None = None, community: dict | None = None) -> dict:
    """previous: last week's routes payload (keeps near-tie best picks steady).
    community: data/community.json (verdicts filed as GitHub issues)."""
    from . import brain
    jobs = jobs or load_jobs()
    prev_jobs = (previous or {}).get("jobs", {})
    votes = (community or {}).get("jobs", {})
    out = {}
    for job in jobs:
        public_rows = score_job(job, models)
        rows = brain.apply_community(public_rows, votes.get(job["id"], {}))
        prev_best = ((prev_jobs.get(job["id"], {}).get("picks") or {}).get("best") or {}).get("id")
        # community verdicts shift ranks, value and budget, but the best pick always comes from the public
        # evidence alone, so a handful of accounts can never decide what everyone uses for the hardest work
        public_best = brain.steady(pick(public_rows), public_rows, prev_best).get("best")
        picks = pick(rows)
        if public_best:
            shown = next((r for r in rows if r["id"] == public_best["id"]), public_best)
            picks = {**picks, "best": {**shown, **({"held": public_best["held"]} if public_best.get("held") else {})}}
        other = brain.rival(rows, picks.get("best"))
        if other:
            picks = {**picks, "rival": other}
        out[job["id"]] = {
            "title": job["title"], "short": job.get("short", job["title"]), "group": job.get("group"),
            "kinds": job["kinds"],
            "needs": job.get("essential", []) if not rows else [],
            "about": job.get("about", ""), "metrics": [mt["id"] for mt in job["metrics"]],
            "weights": {mt["id"]: mt["w"] for mt in job["metrics"]},
            "ranked": len(rows), "top": rows[:top_n], "labs": brain.lab_champions(rows),
            "picks": {k: {kk: v.get(kk) for kk in PICK_FIELDS if v.get(kk) is not None or kk in ("price", "tps")}
                      for k, v in picks.items()},
            "mix": mix_savings(picks),
            "median_price": median([r["price"] for r in rows if r["price"] is not None]) if any(
                r["price"] is not None for r in rows) else None,
        }
    return out
