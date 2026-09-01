"""Fairness and action-sequence liveness — an arbiter that must not starve a client.

Two clients share a resource through an arbiter. Each may REQUEST (start waiting) and be SERVED (stop
waiting); the arbiter may also STALL (do nothing). The property that matters is a liveness claim about the
ACTION SEQUENCE, not any single state: "every ``req_A`` is eventually followed by a ``serve_A``" — nobody who
asks is starved. musil expresses and checks it three ways, all exact:

- ``with_last_action`` + ``check_ltl`` — put the action that produced each state INTO the state, so
  ``action_taken('req_A')`` is an ordinary atom and the response property is plain LTL:
  ``G(req_A -> F serve_A)``. Without fairness it FAILS: the arbiter can stall forever, or keep serving the
  other client, and starve A.
- ``check_ltl(..., fair=/fair_strong=)`` — under weak OR strong fairness on ``serve_A`` the same property
  HOLDS: a fair arbiter cannot leave an enabled ``serve_A`` untaken forever. Fairness is exactly what carries
  the liveness (the fair-ours discipline: the arbiter's own ``serve`` is fair, the ``stall`` fault is not).
- ``probability_ltl`` — treat the arbiter as a uniform-random scheduler (a DTMC) and ask the PROBABILITY that
  ``serve_A`` happens infinitely often, ``P(GF serve_A)``. It is 1: a random arbiter serves A infinitely often
  almost surely, even though the adversarial (unfair) scheduler above could avoid it.

Run: python examples/arbiter_fairness.py
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from fractions import Fraction

from musil import Action, Always, Atom, Eventually, Implies, Model, check_ltl
from musil.history import LastAction, action_taken, with_last_action
from musil.probabilistic import probability_ltl


@dataclass(frozen=True)
class Arb:
    a_wait: bool  # client A has an outstanding request
    b_wait: bool  # client B has an outstanding request


ARBITER = Model(
    init=Arb(a_wait=False, b_wait=False),
    actions=[
        Action("req_A", enabled=lambda s: not s.a_wait, apply=lambda s: replace(s, a_wait=True)),
        Action("req_B", enabled=lambda s: not s.b_wait, apply=lambda s: replace(s, b_wait=True)),
        Action("serve_A", enabled=lambda s: s.a_wait, apply=lambda s: replace(s, a_wait=False)),
        Action("serve_B", enabled=lambda s: s.b_wait, apply=lambda s: replace(s, b_wait=False)),
        Action("stall", enabled=lambda s: True, apply=lambda s: s),  # the fault: the arbiter defers
    ],
    terminal=lambda s: False,  # it runs forever
)


def main() -> None:
    aug = with_last_action(ARBITER)  # each state now records the action that produced it
    req_a: Atom[LastAction[Arb]] = Atom("req_A", action_taken("req_A"))
    serve_a: Atom[LastAction[Arb]] = Atom("serve_A", action_taken("serve_A"))
    # "every req_A is eventually followed by a serve_A" -- a response property over ACTIONS
    no_starvation = Always(Implies(req_a, Eventually(serve_a)))

    unfair = check_ltl(aug, no_starvation).ok
    weak = check_ltl(aug, no_starvation, fair=("serve_A",)).ok
    strong = check_ltl(aug, no_starvation, fair_strong=("serve_A",)).ok
    print(f"G(req_A -> F serve_A), no fairness    : {'OK' if unfair else 'BAD'}")  # BAD: A can be starved
    print(f"G(req_A -> F serve_A), weak-fair serve : {'OK' if weak else 'BAD'}")  # OK
    print(f"G(req_A -> F serve_A), strong-fair     : {'OK' if strong else 'BAD'}")  # OK

    # As a uniform-random arbiter (a DTMC): the probability serve_A happens infinitely often.
    p_gf = probability_ltl(aug, Always(Eventually(serve_a)))
    print(f"P(GF serve_A), uniform-random arbiter  : {p_gf}")  # 1: served infinitely often a.s.

    # Exact verdicts -- assert them.
    assert not unfair  # the unfair arbiter starves A
    assert weak and strong  # fairness carries the liveness
    assert p_gf == Fraction(1)
    print("\nFairness is what turns 'can be served' into 'must be served'; a random arbiter gets there a.s.")


if __name__ == "__main__":
    main()
