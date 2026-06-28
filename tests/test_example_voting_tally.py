"""The vote-tally example must keep its story: a racy read-then-write count loses a vote, the atomic
count is clean. Run as a subprocess."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "voting_tally.py"


def test_example_runs_and_reports_the_finding() -> None:
    proc = subprocess.run([sys.executable, str(_EXAMPLE)], capture_output=True, text=True, timeout=180)
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "VOTE LOST" in out  # racy tally drops a counted ballot
    assert "tally matches, no overcount: OK" in out  # atomic tally is correct
