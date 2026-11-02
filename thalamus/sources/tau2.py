"""tau2-bench (Sierra): agents that use tools under a written policy, over many turns with a simulated user.

Results are published as one submission.json per run in github.com/sierra-research/tau2-bench (MIT),
listed in a manifest. Two metrics, because the headline task changed in 2026 and the scores don't mix:
  tau2.banking  pass^1 on banking_knowledge (2026 runs: retrieval plus tools)
  tau2.classic  mean pass^1 over airline, retail and telecom (earlier runs)
Only standard text submissions whose prompts and questions weren't modified are used.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from . import get_json, num, record

NAME = "tau2-bench (Sierra)"
BASE = "https://raw.githubusercontent.com/sierra-research/tau2-bench/main/web/leaderboard/public/submissions"
URL = "https://taubench.com"
ATTRIBUTION = "Agent results from tau2-bench by Sierra (github.com/sierra-research/tau2-bench), MIT."
REDISTRIBUTE = True
EFFORTS = {"minimal", "low", "medium", "high", "xhigh", "max"}


def _pass1(results: dict, domain: str) -> float | None:
    return num(((results or {}).get(domain) or {}).get("pass_1"))


def to_record(folder: str, sub: dict) -> dict | None:
    name = sub.get("model_name")
    if not name or "voice" in folder.lower() or sub.get("submission_type", "standard") != "standard":
        return None
    check = (sub.get("methodology") or {}).get("verification") or {}
    if check.get("modified_prompts") or check.get("omitted_questions"):
        return None
    res = sub.get("results") or {}
    classic = [_pass1(res, d) for d in ("airline", "retail", "telecom")]
    metrics = {"tau2.banking": _pass1(res, "banking_knowledge"),
               "tau2.classic": round(sum(classic) / 3, 2) if all(v is not None for v in classic) else None}
    if not any(v is not None for v in metrics.values()):
        return None
    effort = str(sub.get("reasoning_effort") or "").lower()
    label = f"{name} ({effort.capitalize() if effort != 'xhigh' else 'xHigh'})" if effort in EFFORTS else name
    released = (sub.get("model_release") or {}).get("release_date")
    return record("tau2", folder, label, lab=sub.get("model_organization"), released=released, metrics=metrics,
                  date=sub.get("submission_date"))


def latest(records: list[dict]) -> list[dict]:
    """One row per model and effort: the most recent submission."""
    best: dict[str, dict] = {}
    for r in records:
        key = r["name"].lower()
        if key not in best or (r.get("date") or "") > (best[key].get("date") or ""):
            best[key] = r
    return list(best.values())


def fetch() -> list[dict]:
    folders = [f for f in get_json(f"{BASE}/manifest.json").get("submissions", []) if not f.startswith("A_EXAMPLE")]
    if not folders:
        raise RuntimeError("tau2-bench manifest lists no submissions")

    def one(folder: str) -> dict | None:
        try:
            return to_record(folder, get_json(f"{BASE}/{folder}/submission.json", timeout=30))
        except Exception:  # one broken submission file must not sink the source
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        rows = [r for r in pool.map(one, folders) if r]
    return latest(rows)
