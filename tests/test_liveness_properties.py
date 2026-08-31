"""Metamorphic property tests for the liveness layer (the fair-cycle / Emerson-Lei sub-SCC search -- the most
complex, soundness-critical code, where the #22 bug lived): relationships that must hold on EVERY model,
checked over many randomly generated small models (fixed seed, pure stdlib). Independent cross-checks:

- ``check_liveness(goal=p).ok`` (every run eventually reaches p, AF p) IMPLIES p is reachable from every
  reachable state (``reaches`` == all states) -- liveness by fair-cycle search vs reachability by backward BFS.
- Fairness is MONOTONE: assuming MORE fair actions can only keep a liveness property holding, never break it.
- Recurrence (``everywhere=True``, GF p) IMPLIES plain reachability liveness (AF p).
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass

from musil import Action, Model, check_liveness, explore, reaches


@dataclass(frozen=True)
class St:
    id: int


def _edge_action(src: int, dst: int, name: str) -> Action[St]:
    return Action(name, enabled=lambda s: s.id == src, apply=lambda s: St(dst))


def _random_model(rng: random.Random, n: int) -> Model[St]:
    # states 0..n-1, each with 0-2 random outgoing edges (0 -> a sink); never terminal, so a sink from which
    # the goal is unreachable is a real liveness failure.
    actions = [
        _edge_action(src, rng.randrange(n), f"e{src}_{j}")
        for src in range(n)
        for j in range(rng.randint(0, 2))
    ]
    return Model(init=St(0), actions=actions, terminal=lambda s: s.id == -1)  # id == -1 never holds


def _random_goal(rng: random.Random, n: int) -> Callable[[St], bool]:
    ids = frozenset(i for i in range(n) if rng.random() < 0.5)
    return lambda s: s.id in ids


def test_recurrence_ok_implies_goal_reachable_from_every_state() -> None:
    # RECURRENCE (everywhere=True, GF p: on every run p holds infinitely often) requires p to be reachable
    # from every reachable state; otherwise a run could get trapped where p is lost forever. So it implies
    # reaches(graph, p) == all states. (Note: plain <>P does NOT imply this -- p at the initial state alone
    # satisfies "p holds at some point", regardless of reachability elsewhere.)
    rng = random.Random(30)
    for _ in range(60):
        n = rng.randint(2, 5)
        m = _random_model(rng, n)
        goal = _random_goal(rng, n)
        if check_liveness(m, goal=goal, everywhere=True).ok:
            g = explore(m)
            assert reaches(g, goal) == set(g.states)


def test_liveness_fairness_is_monotone() -> None:
    # Assuming more fair actions excludes more (unfair) runs, so a property that holds under fewer assumptions
    # still holds under more: A subset of B => (holds under A => holds under B).
    rng = random.Random(31)
    for _ in range(60):
        n = rng.randint(2, 4)
        m = _random_model(rng, n)
        goal = _random_goal(rng, n)
        names = [a.name for a in m.actions]
        a_set = {nm for nm in names if rng.random() < 0.5}
        b_set = a_set | {nm for nm in names if rng.random() < 0.5}  # a superset
        if check_liveness(m, goal=goal, fair=tuple(a_set)).ok:
            assert check_liveness(m, goal=goal, fair=tuple(b_set)).ok


def test_recurrence_implies_reachability_liveness() -> None:
    # GF p (everywhere=True: on every run, always eventually p) implies F p (eventually p at least once).
    rng = random.Random(32)
    for _ in range(60):
        n = rng.randint(2, 5)
        m = _random_model(rng, n)
        goal = _random_goal(rng, n)
        if check_liveness(m, goal=goal, everywhere=True).ok:
            assert check_liveness(m, goal=goal).ok
