"""The coverage chapter must keep showing that a green check can hide a dead action and a vacuous invariant:
`check` reports OK, yet `coverage` flags `thaw` as dead and `invariant_coverage` flags `status-known` as
candidate-vacuous while `non-negative-balance` is load-bearing. Run as a subprocess so it stays the real
example a reader would run (its own asserts also check the verdicts, so a nonzero exit fails the test)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "coverage_vacuity.py"


def test_example_runs_and_surfaces_the_hidden_gaps() -> None:
    proc = subprocess.run([sys.executable, str(_EXAMPLE)], capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "OK — 4 states, no violations" in out  # the check is green
    assert "never enabled (dead): thaw" in out  # yet thaw can never fire
    assert "candidate-vacuous" in out and "status-known" in out  # and status-known passes for nothing
    assert "non-negative-balance: guarded off by withdraw" in out  # while this one is genuinely load-bearing
    assert "one dead action (thaw) and one vacuous invariant (status-known)" in out
