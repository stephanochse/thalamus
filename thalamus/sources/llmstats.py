"""llm-stats.com category indexes (open JSON API at api.llm-stats.com, reuse allowed with attribution).

Each category index is a TrueSkill-style rating built from many benchmarks; we use the conservative
estimate. Many underlying scores are self-reported by model vendors, so jobs give these small weights,
and categories with fewer than 20 rated models are skipped as noise.
"""
from __future__ import annotations

from . import get_json, num, record

NAME = "llm-stats"
URL = "https://llm-stats.com"
ATTRIBUTION = "Category indexes from llm-stats.com."
REDISTRIBUTE = True
API = "https://api.llm-stats.com/leaderboard/indexes/compact"
MIN_MODELS = 20
CATEGORIES = ["general", "agents", "code", "reasoning", "legal", "finance", "economics", "long_context",
              "tool_calling", "vision", "structured_output", "search", "frontend_development", "factuality",
              "instruction_following", "math", "writing", "creativity", "healthcare", "language", "multimodal"]


# Individual benchmarks, as the labs reported them at launch (llm-stats marks almost every score
# self_reported). They reach new models weeks before independent boards do, so jobs use them as "claim"
# signals: small weights that can lift a score but never count against a model that lacks them.
TOP = "https://api.llm-stats.com/leaderboard/benchmarks/top/providers"
DETAILS = "https://api.llm-stats.com/leaderboard/benchmarks/{id}/details"
BENCHMARKS = {  # llm-stats benchmark id -> metric
    "gpqa": "llmstats.gpqa", "aime-2025": "llmstats.aime", "swe-bench-verified": "llmstats.swe_verified",
    "swe-bench-pro": "llmstats.swe_pro", "humanity's-last-exam": "llmstats.hle", "mmmu-pro": "llmstats.mmmu_pro",
    "browsecomp": "llmstats.browsecomp", "ifeval": "llmstats.ifeval", "livecodebench-v6": "llmstats.livecodebench",
}
DETAIL_BENCHMARKS = {
    "terminal-bench-2.1": "llmstats.terminal_bench", "toolathlon": "llmstats.toolathlon",
    "mcp-atlas": "llmstats.mcp_atlas", "osworld-verified": "llmstats.osworld", "simpleqa": "llmstats.simpleqa",
    "ifbench": "llmstats.ifbench", "aa-lcr": "llmstats.lcr", "mrcr-v2-(8-needle)": "llmstats.mrcr",
    "finance-agent-v2": "llmstats.finance_agent", "charxiv-r": "llmstats.charxiv", "deepswe-1.1": "llmstats.deepswe",
}


def _rec(models: dict, model_id: str, name: str, lab: str | None) -> dict:
    return models.setdefault(model_id, record("llmstats", model_id, name, lab=lab))


def _add_indexes(models: dict) -> None:
    data = get_json(API)
    for cat in CATEGORIES:
        board = (data.get(cat) or {}).get("models") or []
        if len(board) < MIN_MODELS:
            continue
        for m in board:
            score = num(m.get("conservative"))
            if score is None or not m.get("model_name"):
                continue
            rec = _rec(models, m["model_id"], m["model_name"], m.get("organization_name") or m.get("organization_id"))
            rec["metrics"][f"llmstats.{cat}"] = score


def _add_benchmarks(models: dict) -> list[str]:
    """Benchmark scores in 0-100. Returns the benchmarks that couldn't be read (the indexes still count)."""
    missing = []
    try:
        for m in get_json(TOP).get("models", []):
            for bid, metric in BENCHMARKS.items():
                score = num(((m.get("benchmark_scores") or {}).get(bid) or {}).get("score"))
                if score is not None and m.get("model_id") and m.get("model_name"):
                    _rec(models, m["model_id"], m["model_name"], m.get("organization_name"))["metrics"][metric] = \
                        round(100 * score, 2)
    except Exception:  # benchmarks are extra: a bad payload must not cost the indexes
        missing.append("top benchmarks")
    for bid, metric in DETAIL_BENCHMARKS.items():
        try:
            rows = get_json(DETAILS.format(id=bid), timeout=30).get("models", []) or []
        except Exception:
            missing.append(bid)
            continue
        for m in rows:
            score = num(m.get("score"))
            if score is not None and m.get("model_id") and m.get("model_name"):
                _rec(models, m["model_id"], m["model_name"], m.get("organization_name"))["metrics"][metric] = \
                    round(100 * score, 2)
    return missing


PARTIAL: list[str] = []


def fetch() -> list[dict]:
    models: dict[str, dict] = {}
    _add_indexes(models)
    if not models:
        raise RuntimeError("llm-stats returned no usable categories")
    PARTIAL[:] = [f"{m} (missing)" for m in _add_benchmarks(models)]
    return list(models.values())
