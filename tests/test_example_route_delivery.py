"""The worked example must keep running and keep telling the right story (design verified, the
fire-and-forget bug found, re-push converges). Run it as a subprocess so this stays a real end-to-end
check of the example a reader would run."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "route_delivery.py"


def test_example_runs_and_reports_the_finding() -> None:
    proc = subprocess.run(
        [sys.executable, str(_EXAMPLE)],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "safety (no stale/invented version, no deadlock): OK" in out
    assert "liveness (converges under fair delivery):        OK" in out
    assert "BUG FOUND" in out  # the fire-and-forget push loses an update under loss
    assert "converged AND refined the model on all 300 seeds" in out  # the re-push fix
