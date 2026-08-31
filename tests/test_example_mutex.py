"""The mutual-exclusion (Peterson) chapter must keep proving the invariant across every interleaving. Run as a
subprocess so it stays the real example a reader would run."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "mutex.py"


def test_example_runs_and_proves_mutual_exclusion() -> None:
    proc = subprocess.run([sys.executable, str(_EXAMPLE)], capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "20 states, no violations" in out
    assert "mutual exclusion holds across every interleaving" in out
