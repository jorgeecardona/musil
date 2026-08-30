"""Temporal properties beyond invariants — the LTL layer, with a looping counterexample.

An invariant says "this holds in every state." Many real requirements are about SEQUENCES: eventually,
always-eventually, "whenever A then later B," "A holds until B." `check_ltl` takes a linear-temporal-logic
formula as data (`Always`, `Eventually`, `Next`, `Until`, `Implies`, `Atom`, ...) and decides it over the
reachable graph — reducing the shapes that map onto the proven `check`/`check_liveness` primitives, and
handing everything else (`Next`, `Until`, nesting) to a general Büchi engine.

A traffic light (generic, universally understood) cycles red -> green -> yellow -> red. We state several
properties about that cycle. The last one is FALSE, and `check_ltl` returns a counterexample as an infinite
`run` — a lasso — with a `--- loops forever ---` marker showing exactly which suffix repeats.

Run: python examples/ltl_properties.py
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from musil import Action, Always, Atom, Eventually, Implies, Model, Next, Result, Until, check_ltl


@dataclass(frozen=True)
class Light:
    color: str = "red"


MODEL = Model(
    init=Light("red"),
    actions=[
        Action("go", lambda s: s.color == "red", lambda s: replace(s, color="green")),
        Action("slow", lambda s: s.color == "green", lambda s: replace(s, color="yellow")),
        Action("stop", lambda s: s.color == "yellow", lambda s: replace(s, color="red")),
    ],
    invariants={},
    terminal=lambda s: False,  # it cycles forever; nothing is a legitimate sink
)

# Atomic state predicates the formulas are built from.
green = Atom[Light]("green", lambda s: s.color == "green")
red = Atom[Light]("red", lambda s: s.color == "red")
yellow = Atom[Light]("yellow", lambda s: s.color == "yellow")
known = Atom[Light]("known", lambda s: s.color in {"red", "green", "yellow"})


if __name__ == "__main__":
    # Each of these HOLDS. The first four reduce onto check / check_liveness; the last two (Next, Until) are
    # decided by the general Büchi engine.
    holds = {
        "G known           (safety: always a known color)": Always(known),
        "F green           (eventually green)": Eventually(green),
        "G F red           (red infinitely often)": Always(Eventually(red)),
        "G(yellow -> F red)(every yellow is followed by red)": Always(Implies(yellow, Eventually(red))),
        "X green           (next state is green, from red)": Next(green),
        "known U green      (stays known until green)": Until(known, green),
    }
    for label, formula in holds.items():
        result = check_ltl(MODEL, formula)
        print(f"[{'OK ' if result.ok else 'BAD'}] {label}")
        assert result.ok, label

    # This one is FALSE: the light never STABILISES on green (it always moves on to yellow), so
    # "eventually green forever" cannot hold. The counterexample is the infinite cycle, with the loop marked.
    stabilises_green = Eventually(Always(green))
    bad = check_ltl(MODEL, stabilises_green)
    assert isinstance(bad, Result)  # a nested-temporal formula is decided by the general engine -> Result
    print(f"\n[{'OK ' if bad.ok else 'BAD'}] F G green      (eventually green forever) -- expected to fail")
    print(bad)

    assert not bad.ok
    assert bad.kind == "ltl"
    assert bad.loop is not None  # an infinite-run counterexample marks where the cycle begins
    assert "--- loops forever ---" in str(bad)
    print("\nAll temporal verdicts match, and the false property returned a looping counterexample.")
