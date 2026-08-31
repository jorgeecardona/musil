"""The lost-update chapter must keep finding the race: two non-atomic increments where one is silently lost.
Run as a subprocess so it stays the real example a reader would run."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "lost_update.py"


def test_example_runs_and_finds_the_lost_update() -> None:
    proc = subprocess.run([sys.executable, str(_EXAMPLE)], capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "INVARIANT VIOLATED: both-increments-counted" in out
