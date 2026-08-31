"""The Needham-Schroeder chapter must keep exhibiting Lowe's attack on the original protocol and proving the
fix clean. Run as a subprocess so it stays the real example a reader would run (its own asserts pin both
verdicts: authentication fails on the original, holds on Lowe's fix)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "needham_schroeder.py"


def test_example_runs_and_shows_the_attack_then_the_fix() -> None:
    proc = subprocess.run([sys.executable, str(_EXAMPLE)], capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr  # its internal asserts (attack found, fix clean) held
    out = proc.stdout
    assert "authentication FAILS" in out  # the original protocol
    assert "A initiates with I" in out  # the attack trace's first step
    assert "authentication HOLDS" in out  # Lowe's fix
