"""The gambler's-ruin chapter must keep matching its three classical closed forms: fair goal probability i/N,
expected duration i(N-i), and the biased-walk 24/31. Run as a subprocess so it stays the real example a reader
would run (its own assert_probability / assert checks pin the fractions)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "gamblers_ruin.py"


def test_example_runs_and_matches_the_closed_forms() -> None:
    proc = subprocess.run([sys.executable, str(_EXAMPLE)], capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr  # its internal exact-fraction asserts all held
    out = proc.stdout
    assert "start 2: 2/5" in out  # fair goal probability i/N (i=2, N=5)
    assert "start 2: 6" in out  # expected duration i(N-i) (2*3)
    assert "P(reach goal) = 24/31" in out  # the biased walk
