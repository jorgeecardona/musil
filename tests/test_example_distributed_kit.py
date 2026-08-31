"""The distributed-kit chapter must keep telling both halves: the controller's []<>converged holds under a
fair reconcile and fails without it, and the cluster keeps quorum through one crash but not two. Run as a
subprocess so it stays the real example a reader would run (its own asserts also check the verdicts)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "distributed_kit.py"


def test_example_runs_and_shows_convergence_and_quorum() -> None:
    proc = subprocess.run([sys.executable, str(_EXAMPLE)], capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "reconcile weak-fair : OK" in out  # convergence holds with the fair reconcile
    assert "no fairness          : BAD" in out  # and fails without it
    assert "<=1 crash         : OK" in out  # quorum survives one crash
    assert "<=2 crashes       : BAD" in out  # but not two
    assert "Convergence needs the reconcile to be fair" in out
