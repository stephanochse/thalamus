"""OpenRouter: the live catalog of callable models (ids, prices, context, modalities).

Public endpoint, no key: GET https://openrouter.ai/api/v1/models. This is the backbone of the
merged catalog: if a model has an OpenRouter id, any tool with an OpenRouter key can call it.
"""
from __future__ import annotations

from datetime import datetime, timezone

from . import get_json, num, record

NAME = "OpenRouter models"
URL = "https://openrouter.ai/api/v1/models"
ATTRIBUTION = "Model ids, prices and context windows from OpenRouter (openrouter.ai)."

SKIP_SUFFIXES = (":free", ":batch", ":extended", ":beta", ":thinking", ":online", ":nitro", ":floor")


def _kind(arch: dict) -> str | None:
    outs = arch.get("output_modalities") or []
    if "text" in outs:
        return "llm"
    if "image" in outs:
        return "t2i"
    if "audio" in outs:
        return "tts"
    return None


def fetch() -> list[dict]:
    rows = get_json(URL)["data"]
    out = []
    for m in rows:
        mid = m.get("id", "")
        if not mid or mid.endswith(SKIP_SUFFIXES) or mid.startswith("openrouter/"):
            continue
        arch = m.get("architecture") or {}
        kind = _kind(arch)
        if not kind:
            continue
        pricing = m.get("pricing") or {}
        p_in, p_out = num(pricing.get("prompt")), num(pricing.get("completion"))
        if p_in is not None and p_in < 0:  # variable-price routers report -1
            continue
        price = None
        if p_in is not None and p_out is not None:
            pin, pout = p_in * 1e6, p_out * 1e6
            price = {"input": round(pin, 4), "output": round(pout, 4), "blended": round((3 * pin + pout) / 4, 4),
                     "unit": "usd_per_mtok"}
        name = m.get("name", mid)
        lab = name.split(":", 1)[0].strip() if ":" in name else mid.split("/", 1)[0]
        created = m.get("created")
        out.append(record(
            "openrouter", mid, name.split(":", 1)[-1].strip(), lab=lab, kind=kind,
            price=price, context=m.get("context_length"),
            input=arch.get("input_modalities") or ["text"],
            open_weights=bool(m.get("hugging_face_id")),
            reasoning="reasoning" in (m.get("supported_parameters") or []),
            released=datetime.fromtimestamp(created, timezone.utc).strftime("%Y-%m-%d") if created else None,
            slug_hint=mid, hf_id=m.get("hugging_face_id"),
        ))
    return out
