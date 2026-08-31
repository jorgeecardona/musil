"""The K8s-scheduler chapter is an open-system check: the fragile service violates availability against pod
eviction, and the resilient one holds. Run as a subprocess so it stays the real example a reader would run."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "k8s_scheduler.py"


def test_example_runs_and_shows_the_open_system_violation() -> None:
    proc = subprocess.run([sys.executable, str(_EXAMPLE)], capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "Open-system model checking" in out
    assert "INVARIANT VIOLATED: always-responsive" in out  # the fragile model against eviction
