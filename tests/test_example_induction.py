"""The induction chapter must keep demonstrating the counterexample-to-induction workflow: a green bounded
check, a non-inductive 'x <= 8' whose CTI is the unreachable Counter(7) -> Counter(9), and the strengthened
'x <= 8 and even' proven at unbounded depth. Run as a subprocess so it stays the real example a reader runs."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "induction.py"


def test_example_runs_and_shows_the_cti_then_the_strengthened_proof() -> None:
    proc = subprocess.run([sys.executable, str(_EXAMPLE)], capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr  # its internal asserts (CTI shape, proven) held
    out = proc.stdout
    assert "proven = False" in out  # 'x <= 8' is not inductive
    assert "Counter(x=7) --step--> Counter(x=9)" in out  # the counterexample-to-induction
    assert "proven = True" in out  # the strengthened invariant
