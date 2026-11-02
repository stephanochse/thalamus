"""Shared test setup: repo root on sys.path and a temp HOME for thalamus."""
import sys
import tempfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from thalamus import paths  # noqa: E402


def temp_home(testcase):
    """Point thalamus's HOME at a throwaway folder for one test and return it."""
    tmp = tempfile.TemporaryDirectory()
    testcase.addCleanup(tmp.cleanup)
    home = Path(tmp.name) / "thalamus-home"
    home.mkdir()
    patcher = mock.patch.object(paths, "HOME", home)
    patcher.start()
    testcase.addCleanup(patcher.stop)
    return home
