"""Optional fallback for route(): a decision model picks the job when the keywords are weak.

Keyword matching is cheap and explainable, but a task described in other words, or a long brief whose
words point at several jobs, can leave no clear winner. Then this asks a decision model (a model that
answers typed questions with probabilities instead of writing prose) which job fits.

Off by default: it sends the task text to OpenRouter and bills your key, about $0.00002 a call.
Turn it on with "classifier": true in HOME/config.json (or {"model": "<decision model>"}), with
THALAMUS_CLASSIFIER=1, or with `thalamus route --classify`. The text is scrubbed first (keys, emails,
ids and HOME/private-terms.txt). The endpoint is OpenRouter's Decisions API, not chat completions.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from . import scrub as scrubber
from .seats import env_value

URL = "https://openrouter.ai/api/alpha/decisions"
MODEL = "typesafe/jev-1.13"
FLOOR = 0.5  # below this the model isn't sure, and the keyword result stands
MAX_CHARS = 8000
INSTRUCTIONS = ("Which kind of work is this task mostly? Pick the job for the main deliverable, "
                "not for a side part of it.")


def enabled(cfg: dict) -> bool:
    """THALAMUS_CLASSIFIER (1/0) wins over the config's "classifier" setting."""
    env = os.environ.get("THALAMUS_CLASSIFIER", "").strip().lower()
    if env in ("0", "false", "no", "off"):
        return False
    if env in ("1", "true", "yes", "on"):
        return True
    return bool(cfg.get("classifier"))


def model_from(cfg: dict) -> str:
    setting = cfg.get("classifier")
    return (setting.get("model") if isinstance(setting, dict) else None) or MODEL


def _post(body: dict, key: str, timeout: int) -> dict:
    req = urllib.request.Request(URL, data=json.dumps(body).encode("utf-8"),
                                 headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def parse(data: dict, labels: dict[str, str]) -> dict | None:
    """The chosen label and its probability, or None when the answer is missing, unknown or unsure."""
    ans = (data.get("answers") or {}).get("job") or {}
    choice = ans.get("choice")
    prob = (ans.get("probabilities") or {}).get(choice)
    if choice not in labels or not isinstance(prob, (int, float)) or prob < FLOOR:
        return None
    return {"choice": choice, "probability": round(float(prob), 3), "model": data.get("model"),
            "cost": (data.get("usage") or {}).get("cost")}


def choose(task: str, labels: dict[str, str], model: str = MODEL, timeout: int = 20) -> dict | None:
    """Ask the decision model which label fits the task. None when there's no key, the call fails, or the
    model is unsure. Never raises: routing must work without it."""
    key = env_value("OPENROUTER_API_KEY")
    if not key or not labels:
        return None
    body = {"model": model, "state": scrubber.scrub(task).text[:MAX_CHARS],
            "questions": {"job": {"type": "choice", "instructions": INSTRUCTIONS, "criteria": labels}}}
    try:
        return parse(_post(body, key, timeout), labels)
    except (OSError, urllib.error.URLError, ValueError, json.JSONDecodeError):
        return None
