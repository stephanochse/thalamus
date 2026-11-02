"""Map the weekly media picks onto the platforms you actually create on.

Creators rarely call image and video models directly. They use an aggregator that bundles many
models under one plan. This module lists what your platform offers (through its own CLI, on your
own login, locally) and intersects it with this week's rankings:

    thalamus media --platform higgsfield            image, edit, video, image-to-video, voice
    thalamus media --platform file --list mine.txt  any platform: one model name per line

Nothing here runs in CI. It needs your local login.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

from .merge import tokens

MEDIA_JOBS = {"image-gen": "image", "image-edit": "image", "video-gen": "video", "image-to-video": "video",
              "voice": "audio", "transcription": "data"}


def higgsfield_catalog() -> list[dict]:
    exe = shutil.which("higgsfield") or shutil.which("higgsfield.cmd")
    if not exe:
        raise RuntimeError("Higgsfield CLI not found (npm i -g @higgsfield/cli, then `higgsfield auth login`).")
    out = subprocess.run([exe, "model", "list", "--json"], capture_output=True, text=True, encoding="utf-8",
                         errors="replace", timeout=90)
    if out.returncode != 0:
        raise RuntimeError(f"higgsfield model list failed: {(out.stderr or out.stdout)[-300:]}")
    rows = json.loads(out.stdout[out.stdout.find("["):])
    return [{"name": r.get("display_name", ""), "id": r.get("job_type", ""), "type": r.get("type", "")} for r in rows]


def file_catalog(path: str) -> list[dict]:
    names = [ln.strip() for ln in Path(path).read_text(encoding="utf-8").splitlines() if ln.strip()]
    return [{"name": n, "id": n, "type": ""} for n in names]


def _match(model_name: str, catalog: list[dict], kind: str | None) -> dict | None:
    want = tokens(model_name)
    best, best_overlap = None, 0.0
    for item in catalog:
        if kind and item["type"] and item["type"] != kind:
            continue
        have = tokens(item["name"]) | tokens(item["id"].replace("_", "-"))
        if not want or not have:
            continue
        overlap = len(want & have) / len(want)
        if overlap > best_overlap:
            best, best_overlap = item, overlap
    return best if best_overlap >= 0.67 else None


def media_picks(catalog: list[dict], n: int = 10) -> dict:
    from . import routes
    out = {}
    for job, kind in MEDIA_JOBS.items():
        try:
            board = routes.leaderboard(job, n=n)
        except ValueError:
            continue
        available = []
        for r in board["rows"]:
            hit = _match(r["name"], catalog, kind)
            if hit:
                available.append({"rank": r["rank"], "model": r["name"], "score": r["score"], "use": hit["id"],
                                  "shown_as": hit["name"]})
        out[job] = {"title": board["title"], "best_overall": board["rows"][0]["name"] if board["rows"] else None,
                    "best_on_your_platform": available[0] if available else None, "on_platform": available}
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="thalamus media")
    ap.add_argument("--platform", default="higgsfield", choices=["higgsfield", "file"])
    ap.add_argument("--list", help="for --platform file: a text file with one model name per line")
    ap.add_argument("-n", type=int, default=10)
    a = ap.parse_args(argv)
    catalog = higgsfield_catalog() if a.platform == "higgsfield" else file_catalog(a.list)
    print(json.dumps(media_picks(catalog, a.n), indent=1, ensure_ascii=False))
    return 0
