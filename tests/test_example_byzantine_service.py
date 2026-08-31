"""The Byzantine-service chapter must keep detecting both wrong answers and wire corruption via AdversarialNode
and NetworkModel.mutate. Run as a subprocess so it stays the real example a reader would run."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "byzantine_service.py"


def test_example_runs_and_detects_byzantine_faults() -> None:
    proc = subprocess.run([sys.executable, str(_EXAMPLE)], capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "Byzantine fault injection" in out
    assert "wrong answers and wire corruption both detectable" in out
