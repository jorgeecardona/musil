"""The bank-transfer chapter must keep telling its story: the naive source-first locking deadlocks,
while ordered locking has no reachable deadlock and conserves the total. Run as a subprocess so it
stays the real example a reader would run."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "bank_transfer.py"


def test_example_runs_and_reports_the_finding() -> None:
    proc = subprocess.run([sys.executable, str(_EXAMPLE)], capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "DEADLOCK" in out  # naive source-first locking crosses and wedges
    assert "OK —" in out  # ordered locking: no deadlock, and conservation holds
