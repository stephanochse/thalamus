"""The learning loop: your verdicts bend the public rankings toward your own taste.

Public leaderboards say what's best on average. You care about what's best for your work.
Every verdict goes into ~/.thalamus/feedback.jsonl (never into the repo):

    thalamus feedback writing anthropic/claude-sonnet-5 good --note "kept my voice"
    thalamus feedback code-build z-ai/glm-5.3 bad --note "invented an API"
    thalamus feedback writing a-model --beats b-model         (a head-to-head pick)

Each (job, model) keeps a Beta(good+1, bad+1) belief. A model's personal factor is
1 + 0.5 * (belief - 0.5) * n / (n + 5): neutral with no data, up to +/-25% once you've
said enough. A personal verdict can only move a model past the public pick after three or
more verdicts (the "beat the baseline before you change the rule" gate), so one bad day
never rewrites routing.

Scouting: new models arrive every week. `thalamus scout <job>` picks an untried model from
the job's top list (Thompson sampling, weighted by its public score) for your next
low-stakes task of that kind, so the system keeps learning about new releases on your work.
"""
from __future__ import annotations

import argparse
import json
import random
import time

from . import paths

K, SWING, MIN_VERDICTS = 5, 0.5, 3


def _rows() -> list[dict]:
    if not paths.FEEDBACK.exists():
        return []
    out = []
    for line in paths.FEEDBACK.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def record(job: str, model: str, verdict: str, note: str = "", vs: str | None = None, source: str = "cli") -> dict:
    if verdict not in ("good", "bad"):
        raise ValueError("verdict must be 'good' or 'bad'")
    paths.ensure_home()
    row = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "job": job, "model": model, "verdict": verdict,
           "note": note[:500], "vs": vs, "source": source}
    with paths.FEEDBACK.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    if vs:  # a head-to-head pick is a win for one and a loss for the other
        loser = {**row, "model": vs, "verdict": "bad", "vs": model}
        with paths.FEEDBACK.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(loser, ensure_ascii=False) + "\n")
    return row


def beliefs() -> dict[tuple[str, str], dict]:
    table: dict[tuple[str, str], dict] = {}
    for r in _rows():
        b = table.setdefault((r["job"], r["model"]), {"good": 0, "bad": 0, "notes": []})
        b[r["verdict"]] += 1
        if r.get("note"):
            b["notes"].append(r["note"])
    for b in table.values():
        n = b["good"] + b["bad"]
        b["n"] = n
        b["mean"] = (b["good"] + 1) / (n + 2)
        b["factor"] = 1 + SWING * (b["mean"] - 0.5) * n / (n + K)
    return table


def personalize(job: str, rows: list[dict]) -> list[dict]:
    """Re-rank a job's public top list with your verdicts. Returns new dicts, input untouched."""
    table = beliefs()
    if not any(j == job for j, _ in table):
        return rows
    public_best = rows[0]["id"] if rows else None
    out = []
    for r in rows:
        b = table.get((job, r["id"])) or table.get((job, r["id"].split("@", 1)[0]))
        factor = b["factor"] if b else 1.0
        out.append({**r, "personal_score": round(r["score"] * factor, 1),
                    "your_verdicts": f"{b['good']} good / {b['bad']} bad" if b else None, "_n": b["n"] if b else 0})
    out.sort(key=lambda r: -r["personal_score"])
    if out and public_best and out[0]["id"] != public_best and out[0]["_n"] < MIN_VERDICTS:
        # not enough evidence to overturn the public pick yet
        keep = next(r for r in out if r["id"] == public_best)
        out.remove(keep)
        out.insert(0, keep)
    for r in out:
        r.pop("_n", None)
    return out


def scout(job: str, top: list[dict]) -> dict | None:
    """Thompson-sample an untried model from the top list, favoring strong public scores."""
    table = beliefs()
    untried = [r for r in top[:10] if (job, r["id"]) not in table]
    if not untried:
        return None
    draws = [(random.betavariate(1 + r["score"] / 20, 1 + (100 - r["score"]) / 20), r) for r in untried]
    return max(draws, key=lambda d: d[0])[1]


def report() -> str:
    table = beliefs()
    if not table:
        return "No feedback yet. Teach it with: thalamus feedback <job> <model> good|bad"
    lines = ["Your verdicts so far (job, model: good/bad, personal factor):"]
    for (job, model), b in sorted(table.items(), key=lambda kv: (kv[0][0], -kv[1]["factor"])):
        flag = "" if b["n"] >= MIN_VERDICTS else f"  (needs {MIN_VERDICTS - b['n']} more to move a pick)"
        lines.append(f"  {job:<14} {model:<40} {b['good']}/{b['bad']}  x{b['factor']:.2f}{flag}")
        if b["notes"]:
            lines.append(f"  {'':<14} last note: {b['notes'][-1][:100]}")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    cmd, rest = argv[0], argv[1:]
    if cmd == "feedback":
        ap = argparse.ArgumentParser(prog="thalamus feedback")
        ap.add_argument("job")
        ap.add_argument("model")
        ap.add_argument("verdict", nargs="?", choices=["good", "bad"])
        ap.add_argument("--beats", help="the model it beat in a head-to-head")
        ap.add_argument("--note", default="")
        a = ap.parse_args(rest)
        verdict = a.verdict or ("good" if a.beats else None)
        if not verdict:
            ap.error("give good, bad or --beats <model>")
        print(json.dumps(record(a.job, a.model, verdict, a.note, vs=a.beats)))
        return 0
    if cmd == "learn":
        print(report())
        return 0
    if cmd == "scout":
        ap = argparse.ArgumentParser(prog="thalamus scout")
        ap.add_argument("job")
        a = ap.parse_args(rest)
        from . import routes
        board = routes.leaderboard(a.job, n=10)
        pick = scout(a.job, board["rows"])
        print(json.dumps({"job": a.job, "try_next": pick and {"id": pick["id"], "name": pick["name"],
                                                              "public_score": pick["score"]}}, indent=1))
        return 0
    return 2
