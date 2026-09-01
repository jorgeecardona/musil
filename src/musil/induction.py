"""``check_inductive`` — prove an invariant by INDUCTION instead of by enumerating the reachable set.

``check`` is exhaustive up to a scope; a passing run proves the invariant only within that scope. An
INDUCTIVE proof discharges it without reference to reachability:

- **base**: no reachable state violates ``I`` within the first ``k-1`` steps, and
- **step** (k-induction): along every path ``s0 -> ... -> sk`` whose first ``k`` states satisfy ``I``,
  the ``(k+1)``-th satisfies ``I`` too.

If both hold, ``I`` holds for every state the system can reach, at any scope. A failing step returns a
**counterexample-to-induction** (a state satisfying ``I`` with a successor that breaks it) so the author
strengthens ``I`` rather than widening the scope. This is what an SMT-backed inductive checker gives; we
make the "for all states s" concrete WITHOUT a solver by quantifying over a caller-supplied finite
``domain`` -- the enumerable fragment, which is decidable by exhaustion and therefore sound.

The ``domain`` must be the FULL set of candidate states (every assignment of the state's bounded
variables), INCLUDING UNREACHABLE ONES. That is the whole point: 1-induction over only the reachable set
is trivially true for any model that already passes ``check`` (a reachable state's successors are
reachable, hence satisfy ``I``), so a domain of just reachable states proves nothing new. The step only
ever follows ENABLED transitions, so a partial ``apply`` guarded correctly is never called out of bounds.

What this does NOT do: prove an unbounded number of components, or an infinite value domain, without a
domain to enumerate -- those need a symbolic decision procedure (a real SMT solver). See
``INDUCTION_NOTES.md`` for what remains out of scope and why.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable, Iterable
from dataclasses import dataclass

from musil.core import Action, Invariant, Model, actions_source

__all__ = [
    "InductionResult",
    "check_inductive",
]


@dataclass(frozen=True, slots=True)
class InductionResult[S: Hashable]:
    """The verdict of ``check_inductive``. ``proven`` is the headline. When it is False, ``failure`` is
    ``"base"`` (a reachable state violates ``I`` within ``k-1`` steps -- a genuine bug) or ``"step"`` (a
    counterexample-to-induction: ``state`` satisfies ``I`` but firing ``action`` reaches ``successor``,
    which violates it). ``reason`` carries a string-invariant's message at the violating state."""

    proven: bool
    k: int
    failure: str | None = None
    state: S | None = None
    action: str | None = None
    successor: S | None = None
    reason: str | None = None

    @property
    def ok(self) -> bool:
        return self.proven

    def __str__(self) -> str:
        if self.proven:
            return f"INDUCTIVE (k={self.k}) — I holds initially and is preserved by every action over the domain"
        if self.failure == "base":
            why = f" — {self.reason}" if self.reason else ""
            return (
                f"NOT INDUCTIVE (k={self.k}): base case — a state reachable within {self.k - 1} step(s) "
                f"violates I{why}\n  {self.state}"
            )
        why = f" — {self.reason}" if self.reason else ""
        return (
            f"NOT INDUCTIVE (k={self.k}): counterexample-to-induction{why}\n"
            f"  I holds at: {self.state}\n"
            f"  --{self.action}--> {self.successor}   (violates I)\n"
            f"  strengthen I to exclude this pre-state, or raise k"
        )


def _make_violates[S: Hashable](inv: Invariant[S]) -> Callable[[S], bool]:
    """``check``'s violation semantics as a plain predicate: a string return is a violation (a reason),
    otherwise falsy is a violation. (Avoids the ``not inv(s)`` footgun where a reason string reads truthy.)"""

    def violates(state: S) -> bool:
        verdict = inv(state)
        return isinstance(verdict, str) or not verdict

    return violates


def _reason_at[S: Hashable](inv: Invariant[S], state: S) -> str | None:
    verdict = inv(state)
    return verdict if isinstance(verdict, str) and verdict else None


def _successors[S: Hashable](
    source: Callable[[S], Iterable[Action[S]]], state: S
) -> list[tuple[str, S]]:
    """The ENABLED transitions out of ``state`` — ``(action name, successor)`` pairs. Only enabled actions,
    so a guard that protects a partial ``apply`` keeps it in bounds."""
    return [(a.name, a.apply(state)) for a in source(state) if a.enabled(state)]


def _base_cti[S: Hashable](
    source: Callable[[S], Iterable[Action[S]]],
    violates: Callable[[S], bool],
    inits: tuple[S, ...],
    k: int,
) -> S | None:
    """The base case: the first state reachable within ``k-1`` steps of ``inits`` that violates ``I``, or
    None if none does. For ``k == 1`` this is just the initial states."""
    seen: set[S] = set()
    frontier: list[tuple[S, int]] = []
    for s in inits:
        if violates(s):
            return s
        if s not in seen:
            seen.add(s)
            frontier.append((s, 0))
    head = 0
    while head < len(frontier):
        state, depth = frontier[head]
        head += 1
        if depth >= k - 1:
            continue
        for _name, nxt in _successors(source, state):
            if violates(nxt):
                return nxt
            if nxt not in seen:
                seen.add(nxt)
                frontier.append((nxt, depth + 1))
    return None


def _step_cti[S: Hashable](
    source: Callable[[S], Iterable[Action[S]]],
    violates: Callable[[S], bool],
    state: S,
    remaining: int,
) -> tuple[S, str, S] | None:
    """Depth-first search for a counterexample-to-induction on a length-``remaining`` path from ``state``
    (which satisfies ``I``). Intermediate states must satisfy ``I`` to extend the antecedent; at the last
    transition a violating successor is the counterexample ``(pre-state, action, successor)``."""
    for name, nxt in _successors(source, state):
        if remaining == 1:
            if violates(nxt):
                return (state, name, nxt)
        elif not violates(nxt):  # an intermediate must satisfy I for the k-antecedent to hold
            found = _step_cti(source, violates, nxt, remaining - 1)
            if found is not None:
                return found
    return None


def check_inductive[S: Hashable](
    model: Model[S], invariant: Invariant[S], domain: Iterable[S], *, k: int = 1
) -> InductionResult[S]:
    """Prove ``invariant`` inductive for ``model`` over the finite ``domain`` (see the module docstring).

    ``invariant`` is a predicate with ``check``'s semantics (``True`` holds; ``False``/``None``/``""`` or a
    reason string is a violation) -- pass one of ``model.invariants``' values, or any predicate. ``domain``
    is the finite set of candidate states quantified over: it MUST include unreachable states (the full
    bounded state space), or the check proves nothing beyond ``check``. ``k`` is the induction depth
    (``k=1`` is ordinary invariant induction; raise it when 1-induction reports a spurious, unreachable
    counterexample). Returns an :class:`InductionResult` -- PROVEN, a base-case bug, or a
    counterexample-to-induction."""
    if k < 1:
        raise ValueError(f"k must be >= 1, got {k}")
    source = actions_source(model)
    violates = _make_violates(invariant)

    base = _base_cti(source, violates, model.initial_states(), k)
    if base is not None:
        return InductionResult(proven=False, k=k, failure="base", state=base, reason=_reason_at(invariant, base))

    for s in domain:
        if violates(s):
            continue  # not a candidate: the antecedent I(s) is false, so it constrains nothing
        cti = _step_cti(source, violates, s, k)
        if cti is not None:
            pre, act, succ = cti
            return InductionResult(
                proven=False, k=k, failure="step", state=pre, action=act, successor=succ,
                reason=_reason_at(invariant, succ),
            )
    return InductionResult(proven=True, k=k)
