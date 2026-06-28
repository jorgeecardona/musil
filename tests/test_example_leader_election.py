"""The leader-election example must keep telling its story: no quorum splits the brain, a quorum is
safe (at most one leader per term), and elections can split-vote livelock. Run as a subprocess."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "leader_election.py"


def test_example_runs_and_reports_the_finding() -> None:
    proc = subprocess.run([sys.executable, str(_EXAMPLE)], capture_output=True, text=True, timeout=180)
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "SPLIT BRAIN" in out  # no quorum -> two leaders in one term
    assert "at most one leader per term: OK" in out  # quorum is safe
    assert "SPLIT-VOTE LIVELOCK" in out  # liveness fails without randomized timeouts
