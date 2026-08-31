"""The service-lifecycle chapter builds the model from the code's own transition table and must keep covering
all five declared states. Run as a subprocess so it stays the real example a reader would run."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "service_lifecycle.py"


def test_example_runs_and_covers_all_declared_states() -> None:
    proc = subprocess.run([sys.executable, str(_EXAMPLE)], capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "reached 5 of 5 declared states" in out
