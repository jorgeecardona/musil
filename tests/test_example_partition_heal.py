"""The partition-heal chapter must keep telling its VOPR-style liveness story: a partitioned
fire-and-forget push wedges, a re-pushing source converges once the link heals, and a cold restart
loses an un-retried write. Run as a subprocess so it stays the real example a reader would run."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "partition_heal.py"


def test_example_runs_and_reports_the_finding() -> None:
    proc = subprocess.run([sys.executable, str(_EXAMPLE)], capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "WEDGED" in out  # partition + fire-and-forget never converges
    assert "CONVERGES" in out  # partition + re-push catches up after the heal
    assert "LOST ON RESTART" in out  # cold restart drops an un-retried, already-acked write
