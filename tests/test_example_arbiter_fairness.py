"""The arbiter-fairness chapter demonstrates fair LTL + action-sequence liveness + probability_ltl and must
keep its verdicts: G(req_A -> F serve_A) fails unfair, holds under weak/strong fairness, and P(GF serve_A)=1
on the uniform DTMC. Run as a subprocess so it stays the real example a reader would run (its own asserts pin
the verdicts)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "arbiter_fairness.py"


def test_example_runs_and_shows_fairness_carrying_liveness() -> None:
    proc = subprocess.run([sys.executable, str(_EXAMPLE)], capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr  # its internal asserts (verdicts + probability) all held
    out = proc.stdout
    assert "no fairness    : BAD" in out  # the unfair arbiter starves A
    assert "weak-fair serve : OK" in out  # weak fairness carries the liveness
    assert "strong-fair     : OK" in out
    assert "P(GF serve_A), uniform-random arbiter  : 1" in out  # random arbiter serves A a.s.
