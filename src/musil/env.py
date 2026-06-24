"""Open-system verification: check a system against adversarial external environments.

Real distributed systems do not operate in isolation. A service runs on Linux, inside K8s, talking
to AWS -- components that can crash, evict, throttle, or return wrong answers at any moment. musil's
closed-system ``check`` assumes the entire state space is under the model's control. ``check_open``
lifts that restriction: each external component is an ``EnvironmentSpec`` -- a contract consisting of
the non-deterministic *behaviors* it can exhibit, the *guarantees* it commits to, and the
*assumptions* those guarantees rest on (following seL4's two-layer assurance model: Klein et al.,
SOSP 2009).

``check_open`` composes by merging: env behaviors become additional actions (the BFS explores
*every* thing the environment can do), env guarantees become additional invariants. This is
Interface Automata composition (de Alfaro & Henzinger, ESEC/FSE 2001) -- the environment acts
adversarially within its contract; the system must handle all of it.

Assumptions are first-class: they are printed in the result, never silently swallowed. A guarantee
that rests on an unverified assumption is weaker than one that rests on a verified proof -- the
caller knows exactly what the verification is worth."""

from __future__ import annotations

from collections.abc import Callable, Hashable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from musil.core import Action, Invariant, Model, Result, check


@dataclass(frozen=True, slots=True)
class Assumption:
    """A named proof obligation taken on faith or verified elsewhere.

    ``status`` tracks where the assumption stands:
    - ``"axiom"``      — taken as a foundation; not expected to be proved (e.g., hardware correctness)
    - ``"verified"``   — machine-checked or formally proved (e.g., seL4 kernel proof)
    - ``"unverified"`` — stated but not yet validated (the default; should be addressed)

    ``source`` cites where the assumption comes from (paper, spec, URL).
    ``predicate`` is an optional machine-checkable version of the assumption; ``None`` for
    assumptions that cannot be expressed as a state predicate (e.g., "network eventually delivers").
    """

    name: str
    description: str
    status: Literal["axiom", "verified", "unverified"] = "unverified"
    source: str = ""
    predicate: Callable[[Any], bool] | None = None


@dataclass(slots=True)
class EnvironmentSpec[S: Hashable]:
    """A contract for one external component: what it can do, what it promises, and what it assumes.

    ``behaviors`` — the non-deterministic actions the environment can take. Each is an ``Action[S]``
    that fires from the *same* global state the system uses. The BFS in ``check_open`` explores
    every possible environment action from every state, so the system is checked against the worst
    possible environment (within the contract). Model each distinct failure mode -- crash, evict,
    wrong-answer, timeout -- as a separate behavior.

    ``guarantees`` — invariants the environment commits to hold in every reachable state. If the
    environment breaks one, ``check_open`` reports it as ``"<env.name>:<guarantee_name>"``.

    ``assumptions`` — named ``Assumption`` objects the guarantees rest on. Unverified assumptions
    are surfaced in ``OpenResult.unverified_assumptions``; they are never silently dropped.
    """

    name: str
    behaviors: list[Action[S]]
    guarantees: Mapping[str, Invariant[S]] = field(default_factory=dict[str, Invariant[S]])
    assumptions: Mapping[str, Assumption] = field(default_factory=dict[str, Assumption])


@dataclass(frozen=True, slots=True)
class OpenResult[S: Hashable]:
    """The outcome of ``check_open``. Wraps the underlying ``Result`` and surfaces every
    ``Assumption`` that is not yet ``"verified"`` -- these are the residual proof obligations
    the caller must discharge for the verification to be unconditional.

    ``bool(open_result)`` delegates to ``result.ok`` so it works in assertions."""

    result: Result[S]
    unverified_assumptions: tuple[Assumption, ...]

    @property
    def ok(self) -> bool:
        return self.result.ok

    def __bool__(self) -> bool:
        return self.ok

    def __str__(self) -> str:
        lines = [str(self.result)]
        if self.unverified_assumptions:
            lines.append("Unverified assumptions (residual proof obligations):")
            for a in self.unverified_assumptions:
                src = f"  [{a.source}]" if a.source else ""
                lines.append(f"  [{a.status}] {a.name}: {a.description}{src}")
        return "\n".join(lines)


def check_open[S: Hashable](
    system: Model[S],
    *envs: EnvironmentSpec[S],
    max_states: int = 1_000_000,
) -> OpenResult[S]:
    """Check ``system`` against adversarial external environments.

    Composes the system and every environment by merging:
    - all ``env.behaviors`` into the system's actions (the BFS explores every env action)
    - all ``env.guarantees`` into the system's invariants (qualified as ``"<env.name>:<k>"``)

    Then calls the standard ``check`` on the composed model.

    ``check_open(system)`` with no environments is identical to ``check(system)``.

    Unverified assumptions from all environments are collected and returned in
    ``OpenResult.unverified_assumptions`` -- they are the residual proof obligations.
    """
    all_actions = list(system.actions)
    for env in envs:
        all_actions.extend(env.behaviors)

    all_invariants: dict[str, Invariant[S]] = dict(system.invariants)
    for env in envs:
        for k, inv in env.guarantees.items():
            all_invariants[f"{env.name}:{k}"] = inv

    composed = Model(
        init=system.init,
        actions=all_actions,
        invariants=all_invariants,
        terminal=system.terminal,
    )
    result = check(composed, max_states=max_states)

    unverified: list[Assumption] = []
    for env in envs:
        for assumption in env.assumptions.values():
            if assumption.status != "verified":
                unverified.append(assumption)

    return OpenResult(result=result, unverified_assumptions=tuple(unverified))
