"""The LTL chapter must keep deciding temporal properties correctly: the six that hold (safety, eventually,
recurrence, response, next, until) report OK, and the false "eventually green forever" returns a looping
counterexample with the loop marker. Run as a subprocess so it stays the real example a reader would run
(its own asserts also check the verdicts, so a nonzero exit fails the test)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "ltl_properties.py"


def test_example_runs_and_decides_the_properties() -> None:
    proc = subprocess.run([sys.executable, str(_EXAMPLE)], capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert out.count("[OK ]") == 6  # the six properties that hold
    assert "[BAD] F G green" in out  # the false one
    assert "LTL VIOLATED: F G green" in out
    assert "--- loops forever ---" in out  # the counterexample marks where the run loops
    assert "All temporal verdicts match" in out
