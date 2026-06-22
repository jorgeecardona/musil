"""The `python -m musil` CLI, exercised through its testable main(argv)."""

from __future__ import annotations

from pathlib import Path

import pytest

from musil.__main__ import main

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def test_check_a_passing_model_returns_zero() -> None:
    assert main([str(EXAMPLES / "traffic_light.py")]) == 0


def test_check_a_violating_model_returns_one() -> None:
    assert main([str(EXAMPLES / "lost_update.py")]) == 1  # the race violates its invariant


def test_dot_flag_returns_zero(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([str(EXAMPLES / "traffic_light.py"), "--dot"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("digraph")


def test_no_args_is_usage_error() -> None:
    assert main([]) == 2


def test_bad_path_is_error() -> None:
    assert main(["does_not_exist_12345.py"]) == 2
