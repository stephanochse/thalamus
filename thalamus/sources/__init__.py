"""Leaderboard fetchers. Each module exposes fetch() -> list[record] and NAME / URL / ATTRIBUTION.

A record is one model as one source sees it:

    {"source": "aa", "key": "<source's own id>", "name": "GPT-6 (high)", "lab": "OpenAI",
     "kind": "llm" | "t2i" | "image-edit" | "t2v" | "i2v" | "tts" | "stt",
     "metrics": {"aa.intelligence": 71.2, ...}, "price": {"input": 1.25, "output": 10.0, "blended": 3.4},
     "speed": {"tps": 140, "ttft": 0.7}, "context": 1000000, "input": ["text", "image"],
     "open_weights": False, "released": "2026-10-01", "slug_hint": "openai/gpt-6"}

Fetchers never raise for a bad row; they skip it. They raise only when the whole source is
unreachable, and update.py then keeps last week's cached copy and says so in the report.
"""
from __future__ import annotations

import gzip
import json
import time
import urllib.error
import urllib.request

UA = "Mozilla/5.0 (compatible; thalamus-weekly-sync; +https://github.com/thalamus)"


def http_get(url: str, headers: dict | None = None, timeout: int = 45, retries: int = 2) -> bytes:
    last = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip", **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    body = gzip.decompress(body)
                return body
        except (urllib.error.URLError, TimeoutError) as err:
            last = err
            if isinstance(err, urllib.error.HTTPError) and err.code in (401, 403, 404):
                break
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"GET {url} failed: {last}")


def get_json(url: str, headers: dict | None = None, timeout: int = 45):
    return json.loads(http_get(url, headers, timeout).decode("utf-8"))


def num(value) -> float | None:
    """Float or None. Accepts strings like '71.2', '71.2%', '$3.40', '1,234'."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace("%", "").replace("$", "").replace(",", "").strip())
    except ValueError:
        return None


def record(source: str, key: str, name: str, **fields) -> dict:
    rec = {"source": source, "key": key, "name": name, "lab": None, "kind": "llm", "metrics": {}}
    rec.update({k: v for k, v in fields.items() if v is not None})
    rec["metrics"] = {k: v for k, v in rec.get("metrics", {}).items() if v is not None}
    return rec
