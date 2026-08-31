"""The TCAS II chapter is an open-system verification of RA coordination across several real-world scenarios.
Run as a subprocess so it stays the real example a reader would run."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "tcas.py"


def test_example_runs_the_tcas_scenarios() -> None:
    proc = subprocess.run([sys.executable, str(_EXAMPLE)], capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "TCAS II RA coordination" in out
