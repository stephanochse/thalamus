"""Epoch AI benchmarking hub (benchmark_data.zip). Epoch's OWN data only: CC BY 4.0.

Uses the Epoch Capabilities Index and Epoch's own SWE-bench Verified runs. The zip also re-hosts results
from other publishers (Terminal-Bench, METR, ARC-AGI-2, HLE, Fiction.LiveBench, Aider). Epoch says those
keep their original licenses, so they live in the opt-in `epoch_external` source for personal builds.
"""
from __future__ import annotations

import csv
import io
import zipfile

from . import http_get, num, record

NAME = "Epoch AI benchmarking hub"
URL = "https://epoch.ai/data/benchmark_data.zip"
ATTRIBUTION = "Benchmark data from Epoch AI (epoch.ai), CC BY 4.0."
REDISTRIBUTE = True

# file stem -> (metric, value column(s)); the max across rows of one model version is kept
FILES = {
    "eci_scores": ("epoch.eci", ["eci"]),
    "swe_bench_verified": ("epoch.swebench", ["mean_score", "Best score (across scorers)"]),
}
NO_VARIANT = {"unknown", "none", "default", ""}


def _csv(z: zipfile.ZipFile, stem: str) -> list[dict]:
    name = next((n for n in z.namelist() if n.endswith(f"{stem}.csv")), None)
    if not name:
        return []
    return list(csv.DictReader(io.TextIOWrapper(z.open(name), encoding="utf-8")))


def _split(version: str) -> tuple[str, str | None]:
    base, _, variant = version.rpartition("_") if "_" in version else (version, "", "")
    return (base or version), (None if variant.lower() in NO_VARIANT else variant.lower())


def fetch(files: dict | None = None, source: str = "epoch") -> list[dict]:
    files = files or FILES
    z = zipfile.ZipFile(io.BytesIO(http_get(URL, timeout=120)))
    meta = {r["model_version"]: r for r in _csv(z, "model_metadata")}
    models: dict[str, dict] = {}

    def rec_for(version: str, row: dict) -> dict:
        info = meta.get(version, {})
        base, variant = _split(version)
        display = info.get("display_name") or row.get("Display name") or row.get("Name") or base
        if variant and "(" not in display:
            display = f"{display} ({variant})"
        access = (info.get("accessibility") or row.get("Model accessibility") or "").lower()
        return models.setdefault(version, record(
            source, version, display, lab=info.get("organization") or row.get("Organization"),
            open_weights="open weights" in access, unreleased="unreleased" in access,
            released=info.get("date") or row.get("date") or row.get("Release date")))

    for stem, (metric, cols) in files.items():
        for row in _csv(z, stem):
            version = row.get("Model version") or row.get("Model") or ""
            if not version:
                continue
            value = next((num(row.get(c)) for c in cols if num(row.get(c)) is not None), None)
            if value is None:
                continue
            rec = rec_for(version, row)
            old = rec["metrics"].get(metric)
            rec["metrics"][metric] = value if old is None else max(old, value)
    if not models:
        raise RuntimeError("Epoch zip had no readable benchmark files")
    return list(models.values())
