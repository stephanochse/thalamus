"""EQ-Bench Creative Writing v3 (Elo from an LLM judge, plus a "slop" score). OPT-IN.

The site publishes no license or terms for its data, so this is off by default. Turn it on for a
personal copy with `--with eqbench` or "extra_sources": ["eqbench"] in ~/.thalamus/config.json.
"""
from __future__ import annotations

import csv
import io
import re

from . import http_get, num, record

NAME = "EQ-Bench Creative Writing v3"
URL = "https://eqbench.com/creative_writing.html"
ATTRIBUTION = "Creative writing scores from EQ-Bench (eqbench.com)."
REDISTRIBUTE = False
OPT_IN = True
PREFIX = "eqbench."
DATA = "https://eqbench.com/creative_writing.js"


def fetch() -> list[dict]:
    js = http_get(DATA, timeout=60).decode("utf-8", errors="replace")
    m = re.search(r"leaderboardDataCreativeWritingV3\s*=\s*`(.*?)`", js, flags=re.S)
    if not m:
        raise RuntimeError("creative writing table not found in creative_writing.js")
    out = []
    for row in csv.DictReader(io.StringIO(m.group(1).strip())):
        name = (row.get("model_name") or "").lstrip("*").strip()
        elo = num(row.get("elo_score"))
        if not name or elo is None:
            continue
        out.append(record("eqbench", name, name, metrics={"eqbench.creative": elo,
                                                          "eqbench.slop": num(row.get("slop_score"))}))
    return out
