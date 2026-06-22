"""The dining-philosophers chapter must keep telling its story: the naive left-first protocol
deadlocks (a circular wait musil finds), while the resource-ordered protocol has no reachable
deadlock. Run as a subprocess so it stays the real example a reader would run."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "dining_philosophers.py"


def test_example_runs_and_reports_the_finding() -> None:
    proc = subprocess.run([sys.executable, str(_EXAMPLE)], capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "DEADLOCK" in out  # the naive left-first protocol wedges in a circular wait
    assert "OK —" in out  # the resource-ordered protocol has no reachable deadlock
