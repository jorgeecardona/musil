"""The lossy-retry chapter must keep giving the exact quantitative answers: almost-sure delivery, the
geometric within-k law, expected attempts 1/p, and the min expected cost where a cost-minimising sender
picks the fast link. Run as a subprocess so it stays the real example a reader would run (its own asserts
also check the closed forms, so a nonzero exit fails the test)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "lossy_retry.py"


def test_example_runs_and_reports_the_exact_answers() -> None:
    proc = subprocess.run([sys.executable, str(_EXAMPLE)], capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "P(eventually delivered)      = 1" in out  # almost-sure delivery
    assert "['1/2', '3/4', '7/8', '15/16']" in out  # 1 - (1/2)^k, exact
    assert "E[attempts to deliver]       = 2" in out  # 1/p
    assert "min E[cost] over strategies  = 2" in out  # the fast link wins
    assert "match their closed forms" in out
