"""The producer-consumer chapter must keep telling its story: the naive check-then-commit buffer
overflows past capacity (a race musil finds), while the atomic test-and-insert stays within capacity
and converges. Run as a subprocess so it stays a real end-to-end check of the example a reader runs."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "producer_consumer.py"


def test_example_runs_and_reports_the_finding() -> None:
    proc = subprocess.run(
        [sys.executable, str(_EXAMPLE)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "INVARIANT VIOLATED: within-capacity" in out  # the naive buffer overflows
    assert "OK —" in out  # the atomic buffer is safe (no overflow, no deadlock)
    assert "liveness (every item eventually consumed): OK" in out
