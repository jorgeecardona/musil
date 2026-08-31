"""The availability chapter demonstrates the steady-state and constrained probabilistic answers, and must
keep matching its closed forms: long-run availability 4/7, until-probability 1/2, recovery cost min 2 / max 3.
Run as a subprocess so it stays the real example a reader would run (its own asserts pin the fractions)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "availability.py"


def test_example_runs_and_matches_the_closed_forms() -> None:
    proc = subprocess.run([sys.executable, str(_EXAMPLE)], capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr  # its internal exact-fraction asserts all held
    out = proc.stdout
    assert "P(healthy) = 4/7" in out  # steady-state availability
    assert "P(failed before recovering)      = 1/2" in out  # the until-probability
    assert "min E[recovery cost]             = 2" in out
    assert "max E[recovery cost]             = 3" in out
