"""Third-party benchmark results that Epoch AI re-hosts in benchmark_data.zip. OPT-IN, PERSONAL BUILDS.

Terminal-Bench, METR time horizons, ARC-AGI-2, Humanity's Last Exam, Fiction.LiveBench and Aider Polyglot.
Epoch notes that externally sourced data keeps its original licensing, so the public build leaves these
out. For your own use: thalamus update --personal --with epoch_external
"""
from __future__ import annotations

from . import epoch

NAME = "Epoch AI (re-hosted external benchmarks)"
URL = epoch.URL
ATTRIBUTION = "Third-party benchmark results collected by Epoch AI; each keeps its original license."
REDISTRIBUTE = False
OPT_IN = True
PREFIX = "epochx."

FILES = {
    "terminalbench_external": ("epochx.terminalbench", ["Accuracy mean"]),
    "metr_time_horizons_external": ("epochx.metr_horizon", ["Time horizon"]),
    "arc_agi_2_external": ("epochx.arc_agi2", ["Score"]),
    "hle_external": ("epochx.hle", ["Accuracy"]),
    "fictionlivebench_external": ("epochx.fictionlive", ["120k token score", "60k token score"]),
    "aider_polyglot_external": ("epochx.aider", ["Percent correct"]),
}


def fetch() -> list[dict]:
    return epoch.fetch(FILES, source="epoch_external")
