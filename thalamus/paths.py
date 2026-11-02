"""Where things live. Everything personal stays in THALAMUS_HOME (default ~/.thalamus), never in the repo."""
import os
from pathlib import Path

PKG = Path(__file__).resolve().parent
REPO = PKG.parent
DATA = Path(os.environ.get("THALAMUS_DATA", REPO / "data"))
HOME = Path(os.environ.get("THALAMUS_HOME", Path.home() / ".thalamus"))
RUNS = HOME / "runs"
FEEDBACK = HOME / "feedback.jsonl"
CONFIG = HOME / "config.json"
PERSONAL_DATA = HOME / "data"  # `thalamus update --personal` writes here; never published


def ensure_home() -> Path:
    HOME.mkdir(parents=True, exist_ok=True)
    return HOME
