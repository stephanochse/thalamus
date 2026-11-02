"""Arena (formerly LMArena) human-preference leaderboards, from Arena's own open dataset on
Hugging Face: lmarena-ai/leaderboard-dataset, CC BY 4.0. The arena.ai website itself blocks bots and
its terms forbid automated access, so this reads only the published dataset.

Reads parquet files with pyarrow when it's installed (the GitHub Action installs it). Without pyarrow
it falls back to Hugging Face's rows API, slowly, to stay under its rate limit.
"""
from __future__ import annotations

import io
import json
import time
import urllib.parse
from pathlib import Path

from . import http_get, num, record

NAME = "Arena (lmarena-ai/leaderboard-dataset)"
URL = "https://huggingface.co/datasets/lmarena-ai/leaderboard-dataset"
ATTRIBUTION = "Human-preference ratings from Arena (arena.ai), dataset CC BY 4.0."
REDISTRIBUTE = True
CACHE_DIR: Path | None = None  # set by update.py; each board is cached on its own
PARTIAL: list[str] = []        # boards that fell back to last week's copy in this run
PARQUET = "https://huggingface.co/datasets/lmarena-ai/leaderboard-dataset/resolve/main/{cfg}/latest-00000-of-00001.parquet"
ROWS = "https://datasets-server.huggingface.co/rows"

TEXT_CATEGORIES = {
    "overall": "arena.text", "coding": "arena.coding", "hard_prompts": "arena.hard",
    "creative_writing": "arena.creative", "math": "arena.math", "instruction_following": "arena.if",
    "multi_turn": "arena.multiturn", "longer_query": "arena.longer", "expert": "arena.expert",
    "non_english": "arena.multilingual",
    "industry_legal_and_government": "arena.legal",
    "industry_business_and_management_and_financial_operations": "arena.business",
    "industry_software_and_it_services": "arena.software",
    "industry_writing_and_literature_and_language": "arena.writing",
    "industry_medicine_and_healthcare": "arena.health",
}
# config -> (kind, {category: metric})
CONFIGS = {
    "text_style_control": ("llm", TEXT_CATEGORIES),
    "text": ("llm", TEXT_CATEGORIES),  # fills categories the style-controlled board lacks
    "text_factuality": ("llm", {"overall": "arena.factuality"}),
    "webdev": ("llm", {"overall": "arena.webdev", "image_to_webdev": "arena.image_to_webdev"}),
    "vision": ("llm", {"overall": "arena.vision", "ocr": "arena.ocr", "diagram": "arena.diagram"}),
    "document": ("llm", {"overall": "arena.document"}),
    "search": ("llm", {"overall": "arena.search"}),
    "agent": ("llm", {"overall": "arena.agent"}),
    "text_to_image": ("t2i", {"overall": "arena.t2i", "text_rendering": "arena.t2i_text",
                              "photorealistic": "arena.t2i_photo", "commercial_design": "arena.t2i_design"}),
    "image_edit": ("image-edit", {"overall": "arena.image_edit"}),
    "text_to_video": ("t2v", {"overall": "arena.t2v"}),
    "image_to_video": ("i2v", {"overall": "arena.i2v"}),
    "video_edit": ("video-edit", {"overall": "arena.video_edit"}),
}


def _rows_parquet(cfg: str) -> list[dict]:
    import pyarrow.parquet as pq  # optional dependency
    table = pq.read_table(io.BytesIO(http_get(PARQUET.format(cfg=cfg), timeout=90)))
    return table.to_pylist()


def _rows_api(cfg: str) -> list[dict]:
    rows, offset = [], 0
    while True:
        qs = urllib.parse.urlencode({"dataset": "lmarena-ai/leaderboard-dataset", "config": cfg, "split": "latest",
                                     "offset": offset, "length": 100})
        for attempt in range(5):
            try:
                body = json.loads(http_get(f"{ROWS}?{qs}", timeout=60, retries=0))
                break
            except RuntimeError as err:
                if "429" not in str(err) or attempt == 4:
                    raise
                time.sleep(20 * (attempt + 1))
        batch = [r["row"] for r in body.get("rows", [])]
        rows += batch
        offset += 100
        if not batch or offset >= body.get("num_rows_total", 0):
            return rows
        time.sleep(1.5)


def _load(cfg: str) -> list[dict]:
    try:
        return _rows_parquet(cfg)
    except ImportError:
        return _rows_api(cfg)


def _board(cfg: str) -> list[dict]:
    """One board, fresh if possible, else last good copy. Raises only if neither exists."""
    cache = (CACHE_DIR / f"arena_{cfg}.json") if CACHE_DIR else None
    try:
        rows = _load(cfg)
        if not rows:
            raise RuntimeError("empty board")
        if cache:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(rows, default=str), encoding="utf-8")
        return rows
    except Exception:
        if cache and cache.exists():
            PARTIAL.append(cfg)
            return json.loads(cache.read_text(encoding="utf-8"))
        raise


def fetch() -> list[dict]:
    PARTIAL.clear()
    models: dict[tuple[str, str], dict] = {}
    loaded = 0
    for cfg, (kind, cats) in CONFIGS.items():
        try:
            rows = _board(cfg)
        except Exception:  # a board with no fresh or cached copy is skipped; the run says which (PARTIAL)
            PARTIAL.append(f"{cfg} (missing)")
            continue
        loaded += 1
        for r in rows:
            metric = cats.get(r.get("category"))
            value = num(r.get("rating") if r.get("rating") is not None else r.get("score"))
            name = r.get("model_name")
            if not metric or value is None or not name:
                continue
            rec = models.setdefault((kind, name), record(
                "arena", f"{kind}:{name}", name, lab=r.get("organization"), kind=kind,
                open_weights=(r.get("license") or "").lower() not in ("proprietary", ""),
                released=str(r.get("leaderboard_publish_date") or "")[:10] or None))
            rec["metrics"].setdefault(metric, value)  # style-controlled board wins (loaded first)
    if not loaded:
        raise RuntimeError("no Arena board could be loaded")
    if len(PARTIAL) >= len(CONFIGS):  # no board came back fresh
        raise RuntimeError("every Arena board failed this week; only cached copies were available")
    return list(models.values())
