"""The readers-writers chapter must keep telling its story: mutual exclusion holds, the
reader-preference policy can starve a waiting writer (a fair cycle), and writer-preference fixes it.
Run as a subprocess so it stays the real example a reader would run."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "readers_writers.py"


def test_example_runs_and_reports_the_finding() -> None:
    proc = subprocess.run([sys.executable, str(_EXAMPLE)], capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "WRITER CAN STARVE" in out  # reader-preference can starve a waiting writer
    assert "writer always eventually writes" in out  # writer-preference fixes it
