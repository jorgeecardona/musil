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


def _first_violation[S: Hashable](model: Model[S], state: S) -> tuple[str, str | None] | None:
    """The first invariant ``state`` violates, as ``(name, reason)``, or None if it satisfies them all."""
    for name, inv in model.invariants.items():
        verdict = inv(state)
        if isinstance(verdict, str):
            return (name, verdict or None)
        if not verdict:
            return (name, None)
    return None


def replay_actions[S: Hashable](
    model: Model[S],
    names: list[str],
    *,
    canonicalize: Callable[[S], S] | None = None,
) -> Result[S]:
    """Replay a fixed sequence of ACTION NAMES from the model's first initial state, checking every
    invariant at each state, and return the ``Result`` (the first invariant violation reached, else OK).
    Unlike ``check`` it explores exactly one path -- no search -- so it is a cheap, deterministic replay of
    a known counterexample, which is what a generated regression test runs. Raises ``ValueError`` if a
    named action is not available/enabled at its step (the sequence no longer fits the model -- a stale
    regression test should fail loudly rather than silently pass)."""
    canon: Callable[[S], S] = canonicalize if canonicalize is not None else (lambda s: s)
    source = actions_source(model)
    state = canon(model.initial_states()[0])
    trace = [Step(action="<init>", state=state)]
    hit = _first_violation(model, state)
    if hit is not None:
        return Result(ok=False, states_explored=1, kind="invariant", invariant=hit[0], reason=hit[1], trace=tuple(trace))
    for name in names:
        chosen = next((a for a in source(state) if a.name == name and a.enabled(state)), None)
        if chosen is None:
            raise ValueError(f"action {name!r} is not available/enabled at this step; the sequence does not replay on this model")
        state = canon(chosen.apply(state))
        trace.append(Step(action=name, state=state))
        hit = _first_violation(model, state)
        if hit is not None:
            return Result(
                ok=False, states_explored=len(trace), kind="invariant",
                invariant=hit[0], reason=hit[1], trace=tuple(trace),
            )
    return Result(ok=True, states_explored=len(trace), trace=tuple(trace))


def as_regression_test[S: Hashable](
    model: Model[S],
    result: Result[S],
    *,
    test_name: str = "regression",
    model_import: str = "from your_module import model  # <-- point this at your Model",
    minimize_first: bool = True,
) -> str:
    """Emit committable pytest SOURCE that replays this counterexample and asserts the same invariant
    breaks -- a fast, deterministic regression test that pins the exact interleaving without re-running the
    exhaustive search. By default the trace is ``minimize``d first, so the emitted sequence is the minimal
    reproducer. ``model_import`` is the line the test uses to obtain the ``Model`` (edit it to your module);
    ``test_name`` names the function. Raises ``ValueError`` unless ``result`` is an invariant
    counterexample -- there is nothing to pin otherwise."""
    if result.ok or result.kind != "invariant" or result.invariant is None:
        raise ValueError("as_regression_test needs an invariant counterexample (a failing Result with .invariant set)")
    reduced = minimize(model, result) if minimize_first else result
    names = [step.action for step in reduced.trace[1:]]
    lines = [
        f"def test_{test_name}():",
        f"    {model_import}",
        "    from musil import replay_actions",
        "",
        f"    result = replay_actions(model, {names!r})",
        "    assert not result.ok",
        f"    assert result.invariant == {reduced.invariant!r}",
        "",
    ]
    return "\n".join(lines)
