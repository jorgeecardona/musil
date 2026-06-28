"""The Alternating Bit Protocol example must keep telling its story: ABP is unsafe on musil's
unordered channel (it needs FIFO), the no-bit variant double-delivers, the real protocol is safe on a
FIFO link, and eventual delivery needs STRONG (not weak) fairness over a lossy link. Run it as a
subprocess so this stays a real end-to-end check of what a reader would run."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "alternating_bit.py"


def test_example_runs_and_reports_the_finding() -> None:
    proc = subprocess.run(
        [sys.executable, str(_EXAMPLE)],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "UNSAFE -- invariant 'in-order'" in out  # ABP on the unordered kit needs FIFO
    assert "BUG FOUND" in out  # no sequence bit -> the duplicate is delivered twice
    assert "in-order, no over-delivery: OK" in out  # real ABP on a FIFO link is safe
    assert "under WEAK fairness on delivery:   FAILS" in out  # the lossy link can drop forever
    assert "under STRONG fairness on delivery: OK" in out  # strong fairness forces delivery
