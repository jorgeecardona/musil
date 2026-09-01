"""``profile`` — where a slow ``check`` spends its time.

When a ``check`` is slow, ``Result`` says nothing about WHERE the time went, so the honest answer used
to be a reverse-engineering session (a real case ran ~120s under CI coverage before anyone worked out
the guard was rebuilding an expensive menu ~100k times, amplified ~25x by line-tracing). ``profile``
runs the same breadth-first sweep as ``check`` but timed, and reports:

- time split by PHASE — invariants, enumeration (``actions``/``actions_fn``), enablement (``enabled``),
  ``apply``, ``canonicalize``, and the visited-set (identity + hashing + lookup);
- the hottest ACTIONS by cumulative ``enabled`` + ``apply`` time and call count;
- states/second and which phase dominates, so the fix (footprint memoization, a cheaper guard, symmetry,
  a smaller scope) is obvious rather than guessed.

It profiles the FULL sweep, not ``check``'s early exit: it does not stop at the first violation, because
what you profile is a passing-but-slow check exhausting the space. Timing every call adds overhead, so
the absolute seconds are indicative and the RELATIVE split is the signal. Accepts ``canonicalize`` and
``key`` exactly as ``check`` does, so a non-hashable (pydantic) model profiles the same way it checks.

An instrumented sibling of ``check``'s BFS: it deliberately duplicates the loop rather than threading
timing branches through the hot path of ``check`` itself.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable
from dataclasses import dataclass
from time import perf_counter

from musil.core import Model, actions_source

__all__ = [
    "ActionCost",
    "Phase",
    "Profile",
    "profile",
]


@dataclass(frozen=True, slots=True)
class Phase:
    """Cumulative time and call count for one phase of the sweep."""

    name: str
    seconds: float
    calls: int


@dataclass(frozen=True, slots=True)
class ActionCost:
    """Per-action cumulative cost: its ``enabled`` guard and its ``apply``, timed separately."""

    name: str
    enabled_seconds: float
    enabled_calls: int
    apply_seconds: float
    apply_calls: int

    @property
    def total_seconds(self) -> float:
        return self.enabled_seconds + self.apply_seconds


@dataclass(frozen=True, slots=True)
class Profile:
    """A timed breakdown of a ``check`` sweep. ``phases`` is ordered as executed; ``actions`` is sorted
    hottest-first by ``total_seconds``. ``truncated`` means the ``max_states`` cap was hit, so the counts
    are lower bounds."""

    states_explored: int
    elapsed_seconds: float
    phases: tuple[Phase, ...]
    actions: tuple[ActionCost, ...]
    truncated: bool

    @property
    def states_per_second(self) -> float:
        return self.states_explored / self.elapsed_seconds if self.elapsed_seconds else 0.0

    @property
    def dominant_phase(self) -> Phase | None:
        """The phase that took the most cumulative time — the thing to attack first."""
        return max(self.phases, key=lambda p: p.seconds, default=None)

    def __str__(self) -> str:
        cap = " (TRUNCATED at max_states — counts are lower bounds)" if self.truncated else ""
        lines = [
            f"PROFILE — {self.states_explored} states in {self.elapsed_seconds:.3f}s "
            f"({self.states_per_second:.0f} states/s){cap}",
            "  by phase (cumulative):",
        ]
        timed = sum(p.seconds for p in self.phases)
        for p in self.phases:
            pct = f"{100 * p.seconds / timed:4.0f}%" if timed else "   -"
            lines.append(f"    {p.name:<14} {p.seconds:8.3f}s {pct}  ({p.calls} calls)")
        if self.actions:
            lines.append("  hottest actions (enabled + apply):")
            for a in self.actions[:5]:
                lines.append(
                    f"    {a.name:<20} {a.total_seconds:8.3f}s  "
                    f"enabled {a.enabled_seconds:.3f}s/{a.enabled_calls}  "
                    f"apply {a.apply_seconds:.3f}s/{a.apply_calls}"
                )
        top = self.dominant_phase
        if top is not None and timed:
            lines.append(f"  dominant cost: {top.name} ({100 * top.seconds / timed:.0f}% of timed work)")
        return "\n".join(lines)


def profile[S: Hashable](
    model: Model[S],
    *,
    max_states: int = 1_000_000,
    canonicalize: Callable[[S], S] | None = None,
    key: Callable[[S], Hashable] | None = None,
) -> Profile:
    """Run ``model``'s reachable sweep with per-phase and per-action timing; return a :class:`Profile`
    (see the module docstring). Profiles the full space, not ``check``'s early exit. ``canonicalize`` and
    ``key`` behave as in ``check``."""
    source = actions_source(model)
    canon: Callable[[S], S] = canonicalize if canonicalize is not None else (lambda s: s)
    ident: Callable[[S], Hashable] = key if key is not None else (lambda s: s)
    invariants = tuple(model.invariants.items())

    t_inv = t_enum = t_enabled = t_apply = t_canon = t_visited = 0.0
    c_inv = c_enum = c_enabled = c_apply = c_canon = c_visited = 0
    en_sec: dict[str, float] = {}
    en_calls: dict[str, int] = {}
    ap_sec: dict[str, float] = {}
    ap_calls: dict[str, int] = {}

    start = perf_counter()
    seen: set[Hashable] = set()
    frontier: list[S] = []
    for s0 in model.initial_states():
        t0 = perf_counter()
        s = canon(s0)
        t_canon += perf_counter() - t0
        c_canon += 1
        t0 = perf_counter()
        sid = ident(s)
        is_new = sid not in seen
        if is_new:
            seen.add(sid)
        t_visited += perf_counter() - t0
        c_visited += 1
        if is_new:
            frontier.append(s)

    truncated = False
    head = 0
    while head < len(frontier):
        state = frontier[head]
        head += 1

        for _name, inv in invariants:
            t0 = perf_counter()
            inv(state)  # not stopping at a violation: profile measures the full-sweep cost
            t_inv += perf_counter() - t0
            c_inv += 1

        t0 = perf_counter()
        actions = tuple(source(state))
        t_enum += perf_counter() - t0
        c_enum += 1

        for action in actions:
            t0 = perf_counter()
            ok = action.enabled(state)
            dt = perf_counter() - t0
            t_enabled += dt
            c_enabled += 1
            en_sec[action.name] = en_sec.get(action.name, 0.0) + dt
            en_calls[action.name] = en_calls.get(action.name, 0) + 1
            if not ok:
                continue
            t0 = perf_counter()
            nxt = action.apply(state)
            dt = perf_counter() - t0
            t_apply += dt
            c_apply += 1
            ap_sec[action.name] = ap_sec.get(action.name, 0.0) + dt
            ap_calls[action.name] = ap_calls.get(action.name, 0) + 1
            t0 = perf_counter()
            ncanon = canon(nxt)
            t_canon += perf_counter() - t0
            c_canon += 1
            t0 = perf_counter()
            nid = ident(ncanon)
            is_new = nid not in seen
            if is_new:
                seen.add(nid)
            t_visited += perf_counter() - t0
            c_visited += 1
            if is_new:
                frontier.append(ncanon)
                if len(seen) >= max_states:
                    truncated = True
                    break
        if truncated:
            break

    elapsed = perf_counter() - start
    phases = (
        Phase("invariants", t_inv, c_inv),
        Phase("enumeration", t_enum, c_enum),
        Phase("enablement", t_enabled, c_enabled),
        Phase("apply", t_apply, c_apply),
        Phase("canonicalize", t_canon, c_canon),
        Phase("visited-set", t_visited, c_visited),
    )
    names = sorted(set(en_calls) | set(ap_calls))
    actions = tuple(
        sorted(
            (
                ActionCost(
                    name=n,
                    enabled_seconds=en_sec.get(n, 0.0),
                    enabled_calls=en_calls.get(n, 0),
                    apply_seconds=ap_sec.get(n, 0.0),
                    apply_calls=ap_calls.get(n, 0),
                )
                for n in names
            ),
            key=lambda a: a.total_seconds,
            reverse=True,
        )
    )
    return Profile(
        states_explored=len(seen),
        elapsed_seconds=elapsed,
        phases=phases,
        actions=actions,
        truncated=truncated,
    )
