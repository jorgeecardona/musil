"""The composed-open-system chapter checks a service against K8s + AWS + etcd faults in a single BFS, surfacing
an invariant violation. Run as a subprocess so it stays the real example a reader would run."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "open_system_composed.py"


def test_example_runs_and_composes_the_environments() -> None:
    proc = subprocess.run([sys.executable, str(_EXAMPLE)], capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "Invariant violated!" in out
    assert "k8s:evict-pod" in out  # a composed-environment fault appears in the counterexample
