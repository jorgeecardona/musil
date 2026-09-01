"""``musil.doctor`` — spot hand-rolled patterns a shipped musil API already covers.

The recurring finding across consumers is not missing features but SHIPPED features with zero adoption:
``assert x.ok, str(x)`` written 290 times where ``assert_ok`` renders the counterexample; the trace-name
list-comprehension re-invented where ``Result.action_names`` exists; ``assert not x.ok`` where
``assert_violates`` pins the verdict. ``scan`` reads Python source with the standard-library ``ast`` (so it
is dependency-free) and returns advisory :class:`Finding`s — file positions plus the API to reach for. It is
a HINT, not a gate: heuristics match the common shapes, and a false positive costs only a suggestion.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

__all__ = [
    "Finding",
    "scan",
]


@dataclass(frozen=True, slots=True)
class Finding:
    """One advisory hit: a hand-rolled pattern at ``line``:``col`` that ``message`` says how to replace.
    ``pattern`` is a short stable id (e.g. ``"assert-ok"``) for filtering."""

    line: int
    col: int
    pattern: str
    message: str


def _is_ok_attr(node: ast.expr) -> ast.expr | None:
    """The subject ``X`` of an ``X.ok`` attribute access, else None."""
    return node.value if isinstance(node, ast.Attribute) and node.attr == "ok" else None


def scan(source: str, *, filename: str = "<source>") -> list[Finding]:
    """Scan Python ``source`` for hand-rolled patterns a shipped musil API already covers, returning advisory
    :class:`Finding`s sorted by position. Pure stdlib ``ast`` — no dependency, and it never imports or runs
    the code. Detected today:

    - ``assert X.ok, <msg>`` -> ``assert_ok(X)`` (which renders the counterexample, so the message is
      unnecessary). The message is the tell that distinguishes musil's idiom from a bare truthiness assert.
    - ``assert not X.ok`` -> ``assert_violates(X, ...)`` (the red-side helper; optionally pin
      ``kind=`` / ``invariant=``).
    - ``[s.action for s in X.trace ...]`` (list/set/generator) -> ``X.action_names``.

    Being advisory, it errs toward the specific shapes above rather than every possible match."""
    tree = ast.parse(source, filename=filename)
    findings: list[Finding] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assert):
            test = node.test
            if node.msg is not None and (subject := _is_ok_attr(test)) is not None:
                findings.append(
                    Finding(
                        node.lineno, node.col_offset, "assert-ok",
                        f"use `assert_ok({ast.unparse(subject)})` — it renders the counterexample, "
                        "so the assert message is unnecessary",
                    )
                )
            elif (
                isinstance(test, ast.UnaryOp)
                and isinstance(test.op, ast.Not)
                and (subject := _is_ok_attr(test.operand)) is not None
            ):
                findings.append(
                    Finding(
                        node.lineno, node.col_offset, "assert-violates",
                        f"use `assert_violates({ast.unparse(subject)}, ...)` — the red-side helper "
                        "(optionally pin kind=/invariant=/via=/where=)",
                    )
                )
        elif isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp)):
            elt = node.elt
            if isinstance(elt, ast.Attribute) and elt.attr == "action":
                for gen in node.generators:
                    it = gen.iter
                    if isinstance(it, ast.Attribute) and it.attr == "trace":
                        findings.append(
                            Finding(
                                node.lineno, node.col_offset, "action-names",
                                f"use `{ast.unparse(it.value)}.action_names` — the trace's action names "
                                "with the synthetic <init> step excluded",
                            )
                        )
                        break
    return sorted(findings, key=lambda f: (f.line, f.col))
