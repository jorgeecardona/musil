"""The traffic-light chapter must keep confirming the three-state cycle is safe and emit its DOT rendering.
Run as a subprocess so it stays the real example a reader would run."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "traffic_light.py"


def test_example_runs_and_is_safe() -> None:
    proc = subprocess.run([sys.executable, str(_EXAMPLE)], capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "3 states, no violations" in out
    assert "digraph musil" in out  # the DOT rendering
