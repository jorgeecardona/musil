"""Tools that turn a raw counterexample into a debugging artifact: ``minimize`` shrinks the violating
trace, and ``as_regression_test`` serialises it into a committable test.

``minimize`` delta-debugs a violating trace: it drops actions and re-checks that replaying the reduced
sequence from the initial state still violates the SAME invariant, keeping only reductions that still
fail. The result is the minimal reproducer, the best debugging artifact and the seed for a fast
regression test (``as_regression_test``, issue #15).

Note on where it helps: a ``check``/``check_all`` counterexample is BFS-shortest, so no strict
subsequence of it can violate (BFS would have returned that shorter path first) and ``minimize`` returns
it essentially unchanged. Its value is on traces that are NOT step-minimal: a long simulation (VOPR) run,
an externally assembled action sequence, or any trace carrying actions irrelevant to the violation. On
those it strips the irrelevant actions down to the minimal failing subsequence.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable
from dataclasses import replace

from musil.core import Invariant, Model, Result, Step, actions_source


def _violates[S: Hashable](inv: Invariant[S], state: S) -> bool:
    """``check``'s violation semantics: a string return is a violation (a reason), else falsy is one."""
    verdict = inv(state)
    return isinstance(verdict, str) or not verdict


def _replay[S: Hashable](
    model: Model[S],
    start: S,
    sequence: list[str],
    inv: Invariant[S],
    canon: Callable[[S], S],
) -> list[S] | None:
    """Replay a sequence of ACTION NAMES from ``start``, stopping at the first state that violates ``inv``.
    Returns the states up to and including that violation, or None if the sequence cannot be replayed (a
    named action is unavailable/disabled at some step) or never reaches a violation. Where several enabled
    actions share a name at a state, the first is taken -- a heuristic that reproduces deterministic
    models exactly and is best-effort under same-named nondeterminism."""
    source = actions_source(model)
    state = start
    states = [state]
    if _violates(inv, state):
        return states
    for name in sequence:
        chosen = next((a for a in source(state) if a.name == name and a.enabled(state)), None)
        if chosen is None:
            return None
        state = canon(chosen.apply(state))
        states.append(state)
        if _violates(inv, state):
            return states
    return None


def minimize[S: Hashable](
    model: Model[S],
    result: Result[S],
    *,
    canonicalize: Callable[[S], S] | None = None,
) -> Result[S]:
    """Delta-debug the counterexample in ``result`` to a minimal action sequence that still violates the
    same invariant, and return a new ``Result`` carrying that shorter trace (all other fields preserved,
    ``reason`` recomputed at the new final state). Greedy 1-minimization: repeatedly drop any single action
    whose removal still reproduces the violation, until no single removal does.

    Only invariant counterexamples are minimized; an ``ok`` result, a deadlock, or a result with no trace
    is returned unchanged (there is no invariant to preserve). If the trace cannot be replayed
    deterministically (same-named nondeterministic actions that pick differently), the original result is
    returned unchanged rather than a possibly-wrong reduction. Pass the same ``canonicalize`` the check
    used so replayed successors match the explored ones."""
    if result.ok or result.kind != "invariant" or not result.trace or result.invariant is None:
        return result
    inv = model.invariants.get(result.invariant)
    if inv is None:
        return result
    canon: Callable[[S], S] = canonicalize if canonicalize is not None else (lambda s: s)
    start = result.trace[0].state
    sequence = [step.action for step in result.trace[1:]]

    if _replay(model, start, sequence, inv, canon) is None:
        return result  # cannot reproduce deterministically; do not risk a wrong reduction

    changed = True
    while changed and sequence:
        changed = False
        for i in range(len(sequence)):
            candidate = sequence[:i] + sequence[i + 1 :]
            if _replay(model, start, candidate, inv, canon) is not None:
                sequence = candidate
                changed = True
                break

    states = _replay(model, start, sequence, inv, canon)
    assert states is not None  # the loop only ever keeps reproducible sequences
    taken = sequence[: len(states) - 1]
    trace = (
        Step(action="<init>", state=states[0]),
        *(Step(action=taken[i], state=states[i + 1]) for i in range(len(taken))),
    )
    verdict = inv(states[-1])
    reason = verdict if isinstance(verdict, str) and verdict else result.reason
    return replace(result, trace=trace, reason=reason)
