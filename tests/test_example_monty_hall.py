"""The Monty Hall chapter must keep matching its exact fractions: switching wins 2/3, staying 1/3. Run as a
subprocess so it stays the real example a reader would run (its own assert_probability calls pin the fractions)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "monty_hall.py"


def test_example_runs_and_matches_the_exact_fractions() -> None:
    proc = subprocess.run([sys.executable, str(_EXAMPLE)], capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr  # its internal assert_probability checks all held
    out = proc.stdout
    assert "P(win | stay)   = 1/3" in out
    assert "P(win | switch) = 2/3" in out
