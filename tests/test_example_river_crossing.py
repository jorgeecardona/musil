"""The river-crossing chapter must keep finding the classic solution: 10 reachable safe states, the goal
reachable in exactly 7 crossings. Run as a subprocess so it stays the real example a reader would run (its own
asserts pin the state count and plan length)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "river_crossing.py"


def test_example_runs_and_finds_the_seven_crossing_plan() -> None:
    proc = subprocess.run([sys.executable, str(_EXAMPLE)], capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr  # its internal asserts (7 crossings, all states safe) held
    out = proc.stdout
    assert "reachable (safe) states: 10" in out
    assert "the goal is reachable in 7 crossings" in out
