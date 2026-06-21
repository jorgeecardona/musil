"""Refinement: hold real code to a model by checking its *observed states*, not its actions.

A run of the real system produces a sequence of concrete states (snapshots). An ``abstraction`` maps
each concrete state to a model state. The run **refines** the model iff every consecutive pair maps
to either the same abstract state (a stutter -- the real code took an internal step the model doesn't
care about) or to an abstract transition the model actually allows. The first observation must map to
a model initial state (unless ``require_init=False``, for checking a mid-run fragment).

This is the runtime analog of refinement in the seL4/TLA+ sense (concrete behaviors are a subset of
abstract behaviors), done by *checking* against the explored model rather than *proving* -- the
practical bridge from a model-checked design to the running implementation. ``musil.sim`` feeds a
``RefinementMonitor`` a snapshot after every step so the simulated real code is held to the spec.

Complement of ``conformance`` (which drives the real code with model-generated action labels); here
the real code drives itself and we watch where it goes."""

from __future__ import annotations

from collections.abc import Callable, Hashable, Iterable
from dataclasses import dataclass

from musil.core import Model, explore


@dataclass(frozen=True, slots=True)
class RefinementViolation[C, S: Hashable]:
    """The real run left the model. ``reason`` is ``"bad-init"`` (first state isn't a model initial
    state), ``"unknown-state"`` (mapped to a state the model can't reach), or ``"no-model-step"`` (the
    abstract transition isn't a model edge). ``index`` is the offending observation's position."""

    index: int
    reason: str
    concrete_from: C | None
    concrete_to: C
    abstract_from: S | None
    abstract_to: S

    def __str__(self) -> str:
        if self.reason == "bad-init":
            return f"REFINEMENT: observation 0 maps to {self.abstract_to!r}, not a model initial state"
        if self.reason == "unknown-state":
            return f"REFINEMENT: observation {self.index} maps to {self.abstract_to!r}, unreachable in the model"
        return (
            f"REFINEMENT: observation {self.index} steps {self.abstract_from!r} -> {self.abstract_to!r}, "
            f"which the model does not allow"
        )


@dataclass(frozen=True, slots=True)
class RefinementResult[C, S: Hashable]:
    ok: bool
    steps_checked: int
    violation: RefinementViolation[C, S] | None = None

    def __bool__(self) -> bool:
        return self.ok

    def __str__(self) -> str:
        if self.ok:
            return f"REFINES -- {self.steps_checked} observations, no divergence"
        assert self.violation is not None
        return f"{self.violation}\n({self.steps_checked} observations checked)"


class RefinementMonitor[C, S: Hashable]:
    """Streaming refinement check. Construct with a model and an abstraction; feed observed concrete
    states one at a time to ``observe``, which returns a ``RefinementViolation`` the first time the
    run leaves the model (and ``None`` otherwise). The model is explored once, up front, so this is
    for bounded models (the explicit-state regime musil lives in)."""

    __slots__ = ("_abs", "_edges", "_index", "_inits", "_prev_abstract", "_prev_concrete", "_require_init", "_started", "_states")

    def __init__(
        self,
        model: Model[S],
        abstraction: Callable[[C], S],
        *,
        require_init: bool = True,
        max_states: int = 1_000_000,
    ) -> None:
        g = explore(model, max_states=max_states)
        self._states: frozenset[S] = frozenset(g.states)
        self._inits: frozenset[S] = frozenset(g.initial)
        self._edges: dict[S, frozenset[S]] = {s: frozenset(t for _, t in outs) for s, outs in g.edges.items()}
        self._abs = abstraction
        self._require_init = require_init
        self._started = False
        self._index = -1
        self._prev_concrete: C | None = None
        self._prev_abstract: S | None = None

    def observe(self, concrete: C) -> RefinementViolation[C, S] | None:
        self._index += 1
        a = self._abs(concrete)
        if not self._started:
            self._started = True
            self._prev_concrete, self._prev_abstract = concrete, a
            if a not in self._states:
                return RefinementViolation(self._index, "unknown-state", None, concrete, None, a)
            if self._require_init and a not in self._inits:
                return RefinementViolation(self._index, "bad-init", None, concrete, None, a)
            return None
        prev_a = self._prev_abstract
        if a not in self._states:
            return RefinementViolation(self._index, "unknown-state", self._prev_concrete, concrete, prev_a, a)
        if a != prev_a and a not in self._edges.get(prev_a, frozenset()):  # type: ignore[arg-type]
            return RefinementViolation(self._index, "no-model-step", self._prev_concrete, concrete, prev_a, a)
        self._prev_concrete, self._prev_abstract = concrete, a
        return None


def check_refinement[C, S: Hashable](
    model: Model[S],
    observations: Iterable[C],
    abstraction: Callable[[C], S],
    *,
    require_init: bool = True,
    max_states: int = 1_000_000,
) -> RefinementResult[C, S]:
    """Check a whole observed run against the model. Returns at the first divergence (with the
    offending observation), else OK once the run is exhausted. ``abstraction`` maps each observed
    concrete state to a model state; ``require_init`` demands the first observation be a model initial
    state (set False to check a mid-run fragment)."""
    monitor = RefinementMonitor(model, abstraction, require_init=require_init, max_states=max_states)
    checked = 0
    for obs in observations:
        checked += 1
        violation = monitor.observe(obs)
        if violation is not None:
            return RefinementResult(ok=False, steps_checked=checked, violation=violation)
    return RefinementResult(ok=True, steps_checked=checked)
