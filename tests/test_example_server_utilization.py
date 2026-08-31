"""The server-utilisation chapter demonstrates the reward-RATE capabilities (long_run_reward,
transient_distribution, long_run_reward_mdp) and must keep its exact verdicts: steady-state utilisation 2/3,
revenue 19/3, and best/worst-policy utilisation 2/3 / 1/2. Run as a subprocess (its own asserts pin them)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "server_utilization.py"


def test_example_runs_and_shows_the_rates() -> None:
    proc = subprocess.run([sys.executable, str(_EXAMPLE)], capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr  # its exact-fraction asserts all held
    out = proc.stdout
    assert "utilisation (fraction BUSY) = 2/3" in out  # steady-state
    assert "revenue rate per step       = 19/3" in out
    assert "best-policy utilisation  (ECO)           = 2/3" in out
    assert "worst-policy utilisation (TURBO)         = 1/2" in out
