"""Parallel state-space exploration: use the cores already there to cut `check`'s wall-clock (#17).

`check` is a single-threaded BFS; a large reachable space is CPU-bound on the model's own
`enabled`/`apply`/invariant closures, and under a forked test runner the one thread competes with the
other workers for cores. `parallel_check` keeps the SAME breadth-first sweep but fans each BFS LEVEL
out across `workers` processes — the pure-Python expansion is the expensive part, so parallelising it is
where the time goes.

Why processes and not threads: standard CPython 3.12 (what musil targets) still has the GIL, so threads
do not run Python bytecode in parallel — only the free-threaded build would, and we do not assume it.
Why `fork` specifically: a musil `Model` is built from lambdas and closures, which `pickle` cannot
serialize, so a worker cannot be *sent* the model. Under the POSIX `fork` start method the workers
INHERIT the parent's memory (copy-on-write), model included, with no pickling — only the STATES cross
the per-level barrier (they are frozen dataclasses / hashable, so they pickle). On a platform without
`fork` (Windows, macOS's spawn default), or for `workers <= 1`, this falls back to the serial `check`.

Design — level-synchronous (BSP) BFS with a parent-owned visited set:
  - The parent owns `seen`/`parent`/`states_by_id` in ONE process, so there is no shared visited set and
    therefore no lock contention — the sharded-visited-set the issue proposed was a way to dodge
    contention in a *threaded* design; a single-owner process model has none to dodge.
  - Each level's states are mapped across the pool; a worker reports, per state, the first invariant it
    breaks, else the first edge-invariant, else (fired?, terminal?, its canonical successors).
  - The parent scans the level's results IN INPUT ORDER, extending the frontier exactly as the serial
    FIFO queue would. Because BFS processes all of depth d before depth d+1, and successors are added in
    the same order, the discovery order — and so the visited set, the parent pointers and the FIRST
    problem found — are byte-identical to `check`. That is the correctness anchor: **`parallel_check`
    returns the same `Result` (verdict and shortest trace) as `check`, only faster**, verified by
    equality tests across models. (Under the `max_states` runaway cap the two may stop at slightly
    different points; the verdict is still `ok, truncated`, and `states_explored` is best-effort there.)"""

from __future__ import annotations

import multiprocessing as mp
from collections.abc import Callable, Hashable, Iterable, Mapping
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from musil.core import Result, Step, actions_source, check
from musil.core import _seed_frontier as _seed_frontier  # pyright: ignore[reportPrivateUsage]
from musil.core import _successors as _successors  # pyright: ignore[reportPrivateUsage]
from musil.core import _trace_to as _trace_to  # pyright: ignore[reportPrivateUsage]

if TYPE_CHECKING:
    from musil.core import Action, EdgeInvariant, Invariant, Model

__all__ = [
    "parallel_check",
]


@dataclass(frozen=True, slots=True)
class _Ctx[S: Hashable]:
    """Everything a worker needs to process one state. Lives in a module global set before the pool is
    created, so forked workers inherit it (copy-on-write); it is NEVER pickled — only states are."""

    source: Callable[[S], Iterable[Action[S]]]
    canon: Callable[[S], S]
    invariants: Mapping[str, Invariant[S]]
    terminal: Callable[[S], bool]
    edge_invariants: Mapping[str, EdgeInvariant[S]]


@dataclass(frozen=True, slots=True)
class _Out[S: Hashable]:
    """One state's worker verdict, pickled back to the parent. ``kind`` is ``"inv"`` (state invariant
    broken), ``"edge"`` (edge invariant broken on the ``action``->``nxt`` transition), or ``"exp"`` (no
    violation — ``fired``/``terminal`` for the deadlock test and ``succ`` the canonical successors)."""

    kind: str
    inv_name: str | None = None
    reason: str | None = None
    action: str | None = None
    nxt: S | None = None
    fired: bool = False
    terminal: bool = False
    succ: tuple[tuple[str, S], ...] = ()


# The forked workers read this; the parent sets it before creating the pool and clears it after. Not
# re-entrant (one parallel_check at a time), which is all check(workers=) ever needs.
_ctx: _Ctx[Any] | None = None


def _process_state(state: Any) -> _Out[Any]:
    """Run the per-state work serial ``check`` does when it dequeues a state, but in a worker: state
    invariants first (report the first broken one), then expand — edge invariants per successor (report
    the first broken one), else report ``(fired, terminal, succ)`` for the parent to enqueue."""
    ctx = _ctx
    assert ctx is not None  # set by the parent before the pool forked
    for name, inv in ctx.invariants.items():
        verdict = inv(state)
        if isinstance(verdict, str):
            return _Out("inv", inv_name=name, reason=verdict or None)
        if not verdict:
            return _Out("inv", inv_name=name)
    succ: list[tuple[str, Any]] = []
    fired = False
    for name, nxt in _successors(ctx.source, ctx.canon, state):
        fired = True
        if ctx.edge_invariants:
            for iname, einv in ctx.edge_invariants.items():
                everdict = einv(state, name, nxt)
                if isinstance(everdict, str):
                    return _Out(
                        "edge", inv_name=iname, reason=everdict or None, action=name, nxt=nxt
                    )
                if not everdict:
                    return _Out("edge", inv_name=iname, action=name, nxt=nxt)
        succ.append((name, nxt))
    return _Out("exp", fired=fired, terminal=ctx.terminal(state), succ=tuple(succ))


def _chunksize(level: int, workers: int) -> int:
    """A few chunks per worker: big enough to amortise the per-task pickling, small enough to balance a
    lumpy level across the pool."""
    return max(1, level // (workers * 4))


def parallel_check[S: Hashable](
    model: Model[S],
    *,
    workers: int,
    max_states: int = 1_000_000,
    canonicalize: Callable[[S], S] | None = None,
    key: Callable[[S], Hashable] | None = None,
) -> Result[S]:
    """Breadth-first ``check`` fanned across ``workers`` fork processes — same verdict and same shortest
    counterexample as :func:`musil.core.check`, using the cores to cut wall-clock on a large space. See
    ``check`` for ``max_states``/``canonicalize``/``key`` (identical meaning and obligations here).

    Falls back to the serial ``check`` when ``workers <= 1`` or the platform has no ``fork`` start method.
    States cross the per-level barrier by pickling, so they must be picklable (frozen dataclasses are); a
    ``canonicalize``/``key`` must be fork-visible, which closures and lambdas defined before the call are,
    being inherited in memory."""
    if workers <= 1 or "fork" not in mp.get_all_start_methods():
        return check(model, max_states=max_states, canonicalize=canonicalize, key=key)

    canon: Callable[[S], S] = canonicalize if canonicalize is not None else (lambda s: s)
    ident: Callable[[S], Hashable] = key if key is not None else (lambda s: s)
    seen, parent, states_by_id, frontier = _seed_frontier(model.initial_states(), canon, ident)

    global _ctx
    _ctx = _Ctx(
        source=actions_source(model),
        canon=canon,
        invariants=model.invariants,
        terminal=model.terminal,
        edge_invariants=model.edge_invariants,
    )
    try:
        mp_ctx = mp.get_context("fork")
        with ProcessPoolExecutor(max_workers=workers, mp_context=mp_ctx) as pool:
            level: list[S] = frontier  # level 0: the seeded initial states, in order
            while level:
                outs = pool.map(_process_state, level, chunksize=_chunksize(len(level), workers))
                next_level: list[S] = []
                for state, out in zip(level, outs, strict=True):
                    sid = ident(state)
                    if out.kind == "inv":
                        return Result(
                            ok=False,
                            states_explored=len(seen),
                            kind="invariant",
                            invariant=out.inv_name,
                            reason=out.reason,
                            trace=_trace_to(parent, states_by_id, sid),
                        )
                    if out.kind == "edge":
                        assert out.nxt is not None and out.action is not None
                        return Result(
                            ok=False,
                            states_explored=len(seen),
                            kind="edge-invariant",
                            invariant=out.inv_name,
                            reason=out.reason,
                            trace=(
                                *_trace_to(parent, states_by_id, sid),
                                Step(action=out.action, state=out.nxt),
                            ),
                        )
                    if not out.fired and not out.terminal:
                        return Result(
                            ok=False,
                            states_explored=len(seen),
                            kind="deadlock",
                            trace=_trace_to(parent, states_by_id, sid),
                        )
                    for name, nxt in out.succ:
                        nid = ident(nxt)
                        if nid not in seen:
                            seen.add(nid)
                            parent[nid] = (sid, name)
                            states_by_id[nid] = nxt
                            next_level.append(nxt)
                            if len(seen) >= max_states:
                                return Result(ok=True, states_explored=len(seen), truncated=True)
                level = next_level
        return Result(ok=True, states_explored=len(seen))
    finally:
        _ctx = None
