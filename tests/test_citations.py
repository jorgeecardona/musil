"""``musil.citations``: locating model references in source and reporting the ones that dangle against the
set of models that actually exist."""

from __future__ import annotations

from pathlib import Path

from musil.citations import (
    Citation,
    dangling_citations,
    find_citations,
    known_models,
)

_SRC = (
    "# reconvergence needs strong fairness — see test_mesh_membership_musil\n"
    'CITE = "justified by test_ledger_quorum_musil"\n'
    "def handler():  # test_mesh_membership_musil again, same line as a comment\n"
    "    return 1  # unrelated: my_test_helper, testing_musil_thing\n"
)


def test_find_citations_sees_comments_and_strings_deduped_per_line() -> None:
    found = find_citations(_SRC)
    # both distinct names, each once per line; the line-3 repeat collapses to one (name, line)
    assert found == [
        Citation("test_mesh_membership_musil", 1),
        Citation("test_ledger_quorum_musil", 2),
        Citation("test_mesh_membership_musil", 3),
    ]


def test_find_citations_respects_word_boundaries() -> None:
    # neither `my_test_helper` nor `testing_musil_thing` matches test_*_musil as a whole word
    assert find_citations("x = my_test_helper + testing_musil_thing\n") == []


def test_dangling_are_exactly_the_unknown_names() -> None:
    known = {"test_mesh_membership_musil"}  # the quorum model does NOT exist
    dangling = dangling_citations(_SRC, known)
    assert [c.name for c in dangling] == ["test_ledger_quorum_musil"]
    assert dangling[0].line == 2


def test_no_dangling_when_all_known() -> None:
    known = {"test_mesh_membership_musil", "test_ledger_quorum_musil"}
    assert dangling_citations(_SRC, known) == []


def test_known_models_reads_matching_file_stems(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_mesh_membership_musil.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "tests" / "test_plain.py").write_text("x = 1\n", encoding="utf-8")  # not a model
    (tmp_path / "notes_test_x_musil.txt").write_text("x\n", encoding="utf-8")  # not .py
    assert known_models(tmp_path) == {"test_mesh_membership_musil"}


def test_end_to_end_resolution_against_a_tree(tmp_path: Path) -> None:
    # a model exists; production code cites it (resolves) and a stale one (dangles)
    (tmp_path / "test_mesh_membership_musil.py").write_text("x = 1\n", encoding="utf-8")
    src = "a = 1  # test_mesh_membership_musil\nb = 2  # test_gone_musil\n"
    dangling = dangling_citations(src, known_models(tmp_path))
    assert [c.name for c in dangling] == ["test_gone_musil"]


def test_custom_pattern_overrides_the_default() -> None:
    src = "y = 1  # spec: model_login_v2\n"
    found = find_citations(src, pattern=r"\bmodel_\w+\b")
    assert [c.name for c in found] == ["model_login_v2"]
    assert dangling_citations(src, {"model_login_v2"}, pattern=r"\bmodel_\w+\b") == []
