"""The co-simulation-master scaling benchmark (#37) must keep telling the same curve: the full interleaving
search is (k+1)**n, the sorting symmetry is C(n+k, n), and the symmetry is SOUND on every instance. Run as a
subprocess so it stays the real example a reader would run -- its own asserts pin the closed-form counts and
run symmetry_reduction_sound on each instance, so a zero exit IS the known-verdict guard; the output checks
below additionally pin the published curve so the "interchangeable components -> canonical_by_sorting" recipe
cannot silently rot."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "cosim_master_scaling.py"


def test_example_runs_and_prints_the_scaling_curve() -> None:
    proc = subprocess.run([sys.executable, str(_EXAMPLE)], capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr  # internal soundness + closed-form-count asserts all held
    out = proc.stdout
    # the full column is exponential (k+1)**n, k=3: 16, 64, 256, 1024 for n=2..5
    for full in ("16", "64", "256", "1,024"):
        assert full in out
    # the symmetry column is polynomial C(n+3, n): 10, 20, 35, 56
    for sym in ("10", "20", "35", "56"):
        assert sym in out
    assert "18.3x" in out  # the n=5 shrink, pinned so the curve cannot silently change
