"""Artificial Analysis, through its official API. OPT-IN, PERSONAL BUILDS ONLY.

Free key (100 requests a day; a run uses about 10): Intelligence Index, six capability indexes (strategy
and ops, finance and accounting, legal, healthcare, engineering, economics), cost to run the index, prices,
median speed and latency, plus Elo for image, image editing, video, image-to-video, speech and
transcription models.

Why opt-in: AA's terms require attribution on every tier, don't grant redistribution of the data on the
free tier, and ask for written consent before their data powers a public model-selection product. So the
public weekly build never uses it. Use it for yourself:

    set ARTIFICIAL_ANALYSIS_API_KEY (or put it in ~/.thalamus/env), then
    thalamus update --personal --with aa      -> ~/.thalamus/data, never published

Scraping AA's website instead of using the API is against their terms of use; don't.
"""
from __future__ import annotations

import os
import time

from . import get_json, num, record

NAME = "Artificial Analysis"
URL = "https://artificialanalysis.ai"
ATTRIBUTION = "Intelligence, capability, speed and media Elo data from Artificial Analysis (artificialanalysis.ai)."
REDISTRIBUTE = False
OPT_IN = True
PREFIX = "aa."
API = "https://artificialanalysis.ai/api/v2"

EVALS = {
    "artificial_analysis_intelligence_index": "aa.intelligence",
    "artificial_analysis_strategy_and_ops_index": "aa.strategy",
    "artificial_analysis_finance_and_accounting_index": "aa.finance",
    "artificial_analysis_legal_index": "aa.legal",
    "artificial_analysis_healthcare_and_medical_index": "aa.healthcare",
    "artificial_analysis_engineering_index": "aa.engineering",
    "artificial_analysis_economics_index": "aa.economics",
    "artificial_analysis_coding_index": "aa.coding",      # retired by AA, kept in case it returns
    "artificial_analysis_agentic_index": "aa.agentic",    # retired by AA, kept in case it returns
}
MEDIA = {"text-to-image": ("t2i", "aa.t2i"), "image-editing": ("image-edit", "aa.image_edit"),
         "text-to-video": ("t2v", "aa.t2v"), "image-to-video": ("i2v", "aa.i2v"),
         "text-to-speech": ("tts", "aa.tts"), "speech-to-text": ("stt", "aa.stt")}


def api_key() -> str | None:
    for var in ("ARTIFICIAL_ANALYSIS_API_KEY", "AA_API_KEY"):
        if os.environ.get(var, "").strip():
            return os.environ[var].strip()
    from ..paths import HOME
    env = HOME / "env"
    if env.exists():
        for line in env.read_text(encoding="utf-8-sig").splitlines():
            k, _, v = line.strip().removeprefix("export ").partition("=")
            if k in ("ARTIFICIAL_ANALYSIS_API_KEY", "AA_API_KEY") and v.strip():
                return v.strip().strip('"').strip("'")
    return None


def _pages(path: str, key: str, max_pages: int = 10) -> list[dict]:
    rows, page = [], 1
    while page <= max_pages:
        body = get_json(f"{API}{path}?page={page}", headers={"x-api-key": key, "Accept": "application/json"})
        rows += body.get("data") or []
        if not (body.get("pagination") or {}).get("has_more"):
            break
        page += 1
        time.sleep(0.5)
    return rows


def _creator(m: dict) -> str | None:
    c = m.get("model_creator") or m.get("creator") or {}
    return c.get("name") if isinstance(c, dict) else None


def fetch() -> list[dict]:
    key = api_key()
    if not key:
        raise RuntimeError("no ARTIFICIAL_ANALYSIS_API_KEY set (free key at artificialanalysis.ai); skipped")
    out = []
    for m in _pages("/language/models/free", key):
        ev = m.get("evaluations") or {}
        metrics = {mid: num(ev.get(field)) for field, mid in EVALS.items()}
        cost = m.get("artificial_analysis_intelligence_index_cost") or {}
        per_task = (cost.get("cost_per_task") or {}).get("total_cost") if isinstance(cost, dict) else None
        metrics["aa.index_cost"] = num(per_task if per_task is not None else (cost or {}).get("total_cost"))
        pricing = m.get("pricing") or {}
        pin, pout = num(pricing.get("price_1m_input_tokens")), num(pricing.get("price_1m_output_tokens"))
        price = ({"input": pin, "output": pout, "blended": round((3 * pin + pout) / 4, 4), "unit": "usd_per_mtok"}
                 if pin is not None and pout is not None else None)
        perf = m.get("performance") or {}
        speed = {"tps": num(perf.get("median_output_tokens_per_second")),
                 "ttft": num(perf.get("median_time_to_first_answer_token_seconds")
                             or perf.get("median_time_to_first_token_seconds"))}
        out.append(record("aa", m.get("slug") or m.get("id"), m.get("name", ""), lab=_creator(m), kind="llm",
                          metrics=metrics, price=price, speed=speed if any(speed.values()) else None,
                          released=m.get("release_date")))
    for media, (kind, metric) in MEDIA.items():
        try:
            rows = _pages(f"/media/{media}/models/free", key, max_pages=5)
        except RuntimeError:
            continue  # one media board missing must not lose the language data
        for m in rows:
            metrics = {}
            elo = num(m.get("elo"))
            if elo is not None:
                metrics[metric] = elo
            for wer_field in ("word_error_rate", "wer", "aa_wer_index"):
                if num(m.get(wer_field)) is not None:
                    metrics["aa.stt_wer"] = num(m.get(wer_field))
            if not metrics:
                continue
            out.append(record("aa", f"{media}:{m.get('slug') or m.get('id')}", m.get("name", ""), lab=_creator(m),
                              kind=kind, metrics=metrics, released=m.get("release_date")))
    return out
