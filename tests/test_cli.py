"""The `python -m musil` CLI: the `doctor` subcommand scans for hand-rolled patterns, the `citations`
subcommand gates on dangling model references, and the original model-check path still works (both
subcommands are backward-compatible additions)."""

from __future__ import annotations

from pathlib import Path

import pytest

from musil.__main__ import main


def test_doctor_subcommand_reports_findings(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text(
        "def test_it():\n    r = check(m)\n    assert r.ok, str(r)\n    assert not check(bad).ok\n",
        encoding="utf-8",
    )
    rc = main(["doctor", str(tmp_path)])
    assert rc == 0  # advisory: never fails the build
    out = capsys.readouterr().out
    assert "sample.py:3:4: assert-ok:" in out
    assert "sample.py:4:4: assert-violates:" in out


def test_doctor_on_clean_code_reports_nothing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "clean.py").write_text("x = 1\nassert x == 1\n", encoding="utf-8")
    assert main(["doctor", str(tmp_path)]) == 0
    assert capsys.readouterr().out == ""  # no findings printed to stdout


def test_citations_gate_fails_on_a_dangling_reference(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "test_real_musil.py").write_text("x = 1\n", encoding="utf-8")  # this model exists
    (tmp_path / "prod.py").write_text(
        "# design justified by test_real_musil and by test_ghost_musil\n", encoding="utf-8"
    )
    rc = main(["citations", str(tmp_path)])
    assert rc == 1  # a gate: the dangling citation fails the build
    out = capsys.readouterr().out
    assert "test_ghost_musil" in out
    assert "test_real_musil" not in out  # the resolvable one is silent


def test_citations_passes_when_all_resolve(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "test_real_musil.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "prod.py").write_text("# see test_real_musil\n", encoding="utf-8")
    assert main(["citations", str(tmp_path)]) == 0
    assert capsys.readouterr().out == ""  # nothing dangles


def test_model_check_path_still_works(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    model = tmp_path / "m.py"
    model.write_text(
        "from dataclasses import dataclass\n"
        "from musil import Action, Model\n"
        "@dataclass(frozen=True)\n"
        "class S:\n    n: int = 0\n"
        "MODEL = Model(init=S(0), actions=[Action('inc', lambda s: s.n < 2, lambda s: S(s.n + 1))],\n"
        "              invariants={'ok': lambda s: s.n <= 2}, terminal=lambda s: s.n == 2)\n",
        encoding="utf-8",
    )
    rc = main([str(model)])
    assert rc == 0  # the model holds
    assert "OK" in capsys.readouterr().out
