"""Vectara hallucination leaderboard: how often a model invents facts when it summarises a document.

The table lives in the README of github.com/vectara/hallucination-leaderboard (Apache-2.0), scored with
Vectara's HHEM model and updated about monthly. It measures staying on source, not closed-book knowledge,
so it feeds research, legal, health, long documents and structured output, at a modest weight.
"""
from __future__ import annotations

import re

from . import http_get, num, record

NAME = "Vectara hallucination leaderboard"
URL = "https://raw.githubusercontent.com/vectara/hallucination-leaderboard/main/README.md"
ATTRIBUTION = "Hallucination rates from Vectara's HHEM leaderboard (github.com/vectara/hallucination-leaderboard), Apache-2.0."
REDISTRIBUTE = True

# Hugging Face org -> (lab label, OpenRouter org) so ids like "deepseek-ai/DeepSeek-V4-Pro" find their model
ORGS = {
    "openai": ("OpenAI", "openai"), "anthropic": ("Anthropic", "anthropic"), "google": ("Google", "google"),
    "deepseek-ai": ("DeepSeek", "deepseek"), "xai-org": ("xAI", "x-ai"), "x-ai": ("xAI", "x-ai"),
    "moonshotai": ("Moonshot AI", "moonshotai"), "zai-org": ("Zhipu (Z.ai)", "z-ai"), "thudm": ("Zhipu (Z.ai)", "z-ai"),
    "qwen": ("Alibaba (Qwen)", "qwen"), "meta-llama": ("Meta", "meta-llama"), "meta": ("Meta", "meta"),
    "mistralai": ("Mistral", "mistralai"), "minimaxai": ("MiniMax", "minimax"), "xiaomimimo": ("Xiaomi", "xiaomi"),
    "xiaomi": ("Xiaomi", "xiaomi"), "baidu": ("Baidu", "baidu"), "ibm-granite": ("IBM", "ibm-granite"),
    "microsoft": ("Microsoft", "microsoft"), "amazon": ("Amazon", "amazon"), "cohere": ("Cohere", "cohere"),
    "cohereforai": ("Cohere", "cohere"), "coherelabs": ("Cohere", "cohere"), "nvidia": ("NVIDIA", "nvidia"),
    "ai21labs": ("AI21", "ai21"),
}
DATE = r"[-_]?(20\d\d[-_]?\d\d[-_]?\d\d|\d{4})$"


def _model_name(org: str, raw: str) -> str:
    name = re.sub(r":\d+$", "", raw.strip())  # Bedrock-style "nova-pro-v1:0"
    name = re.sub(r"[-_]\d\d[-_]20\d\d$", "", name)  # "command-a-03-2025"
    name = re.sub(DATE, "", name)
    if org == "anthropic":  # "claude-opus-5-5" -> "claude-opus-5.5"
        name = re.sub(r"(?<=\d)-(\d)$", r".\1", name)
    return name


def parse(markdown: str) -> list[dict]:
    rows = []
    start = markdown.find("LEADERBOARD_START")
    end = markdown.find("LEADERBOARD_END", max(start, 0))
    for line in markdown[start if start >= 0 else 0:end if end > 0 else None].splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3 or "/" not in cells[0] or cells[0].lower().startswith("model"):
            continue
        org, _, raw = cells[0].partition("/")
        rate = num(cells[1])
        if rate is None or not raw:
            continue
        lab, or_org = ORGS.get(org.lower(), (org, org.lower()))
        name = _model_name(org.lower(), raw)
        rows.append(record("vectara", cells[0], name, lab=lab, slug_hint=f"{or_org}/{name.lower()}",
                           metrics={"vectara.hallucination": rate, "vectara.answer_rate": num(cells[3]) if len(cells) > 3 else None}))
    return rows


def fetch() -> list[dict]:
    rows = parse(http_get(URL).decode("utf-8"))
    if len(rows) < 20:
        raise RuntimeError(f"Vectara table parsed to {len(rows)} rows; the README layout probably changed")
    return rows
