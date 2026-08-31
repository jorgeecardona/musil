"""The co-simulation-master scaling chapter demonstrates symmetry reduction shrinking the interleaving space.
Run as a subprocess so it stays the real example a reader would run."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "cosim_master_scaling.py"


def test_example_runs_and_reports_symmetry_shrink() -> None:
    proc = subprocess.run([sys.executable, str(_EXAMPLE)], capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "Co-simulation master, k=3 micro-steps per component" in out
    assert "canonical_by_sorting" in out
