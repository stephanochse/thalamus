"""BenchLM composite category scores (static JSON downloads). OPT-IN.

BenchLM's data is licensed CC BY-NC 4.0: free for non-commercial use with credit, but not for
redistribution inside a commercial product. It's off by default; turn it on for a personal copy with
`--with benchlm` or "extra_sources": ["benchlm"] in ~/.thalamus/config.json.
"""
from __future__ import annotations

import re

from . import get_json, num, record

NAME = "BenchLM"
URL = "https://benchlm.ai/data/leaderboard.json"
ATTRIBUTION = "Data from BenchLM.ai (CC BY-NC 4.0)."
REDISTRIBUTE = False
OPT_IN = True
PREFIX = "benchlm."


def _snake(s: str) -> str:
    s = s.replace("Grounded", "")
    return re.sub(r"(?<!^)(?=[A-Z])", "_", s).lower()


def fetch() -> list[dict]:
    data = get_json(URL)
    models: dict[str, dict] = {}

    def add(row: dict, metric: str) -> None:
        score = num(row.get("displayScore"))
        if score is None or not row.get("slug"):
            return
        rec = models.setdefault(row["slug"], record("benchlm", row["slug"], row.get("model") or row["slug"],
                                                    lab=row.get("creator"),
                                                    open_weights=(row.get("sourceType") or "").lower().startswith("open")))
        rec["metrics"][metric] = score

    for row in data.get("items") or []:
        add(row, "benchlm.overall")
    for cat, rows in (data.get("categories") or {}).items():
        rows = rows.get("items") if isinstance(rows, dict) else rows
        for row in rows or []:
            add(row, f"benchlm.{_snake(cat)}")
    return list(models.values())
