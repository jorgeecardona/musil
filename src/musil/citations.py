"""``musil.citations`` — keep "the models are the spec" honest: model references must not dangle.

A good practice is for production code to CITE the model that justifies a non-obvious design ("the musil
model proved timer fairness alone cannot guarantee reconvergence — test_mesh_membership_musil"). The
practice fails silently when the pointer rots: a model cited by production code and a schema migration, whose
file no longer exists anywhere. ``find_citations`` locates the references (regex, so it sees comments and
prose, not only identifiers) and ``dangling_citations`` reports the ones that do not resolve against the set
of models that actually exist — the check a ``musil citations`` gate runs so a spec pointer cannot dangle.
Pure stdlib (``re`` + ``pathlib``), so it is dependency-free and never imports or runs the scanned code.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

# The default reference shape: a ``test_<something>_musil`` model name, as a whole word.
DEFAULT_PATTERN = r"\btest_\w+_musil\b"


@dataclass(frozen=True, slots=True)
class Citation:
    """A model reference found in source: the model ``name`` cited at 1-based ``line``."""

    name: str
    line: int


def find_citations(text: str, *, pattern: str = DEFAULT_PATTERN) -> list[Citation]:
    """Every model reference in ``text`` (production code, comments, or prose), as ``Citation``s sorted by
    position. ``pattern`` is a regex; the default matches ``test_*_musil`` names. One entry per distinct
    ``(name, line)``."""
    rx = re.compile(pattern)
    found: set[Citation] = set()
    for lineno, line in enumerate(text.splitlines(), start=1):
        for match in rx.finditer(line):
            found.add(Citation(name=match.group(0), line=lineno))
    return sorted(found, key=lambda c: (c.line, c.name))


def dangling_citations(text: str, known: Iterable[str], *, pattern: str = DEFAULT_PATTERN) -> list[Citation]:
    """The citations in ``text`` whose model name is NOT in ``known`` — spec pointers that dangle. ``known``
    is the set of model names that actually resolve (typically ``known_models`` over the test tree)."""
    names = set(known)
    return [c for c in find_citations(text, pattern=pattern) if c.name not in names]


def known_models(root: Path, *, pattern: str = DEFAULT_PATTERN) -> set[str]:
    """The model names that RESOLVE under ``root``: the stems of ``.py`` files whose stem matches ``pattern``
    (the existing ``test_*_musil.py`` model files). Feed this as ``known`` to ``dangling_citations``."""
    rx = re.compile(pattern)
    return {f.stem for f in root.rglob("*.py") if rx.fullmatch(f.stem) is not None}
