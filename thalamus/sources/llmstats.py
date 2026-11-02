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


def fetch() -> list[dict]:
    data = get_json(API)
    models: dict[str, dict] = {}
    for cat in CATEGORIES:
        board = (data.get(cat) or {}).get("models") or []
        if len(board) < MIN_MODELS:
            continue
        for m in board:
            score = num(m.get("conservative"))
            if score is None or not m.get("model_name"):
                continue
            rec = models.setdefault(m["model_id"], record(
                "llmstats", m["model_id"], m["model_name"], lab=m.get("organization_name") or m.get("organization_id")))
            rec["metrics"][f"llmstats.{cat}"] = score
    if not models:
        raise RuntimeError("llm-stats returned no usable categories")
    return list(models.values())
