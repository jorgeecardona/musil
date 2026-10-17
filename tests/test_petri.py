"""The Petri-net bridge (#24, part 2): build a ledger model from a ``{transition: (inputs, outputs)}``
net — split events, capacity guards, a generated terminal predicate — and derive conservation from the
net structure with place invariants instead of a hand-written invariant."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

import pytest

from musil import Model, check
from musil.petri import (
    PetriNet,
    assert_place_invariant,
    petri_actions,
    petri_enabled,
    petri_terminal,
    place_invariants,
)

# A coffee-roast net, token = 1 kg. A roast consumes 4 kg green and produces 3 kg roasted AND 1 kg
# loss from the SAME firing (the split a state machine cannot express); grind moves roasted to ground.
# Mass is conserved: every transition produces exactly what it consumes.
NET: PetriNet = {
    "roast": ({"green": 4}, {"roasted": 3, "loss": 1}),
    "grind": ({"roasted": 1}, {"ground": 1}),
}

type Marking = tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class Net:
    places: Marking


def tokens(s: Net, place: str) -> int:
    return dict(s.places).get(place, 0)


def deposit(s: Net, place: str, delta: int) -> Net:
    d = dict(s.places)
    d[place] = d.get(place, 0) + delta
    # drop drained places so the marking stays canonical (and the state space finite)
    return Net(tuple(sorted((p, c) for p, c in d.items() if c != 0)))


def marking(**kw: int) -> Net:
    return Net(tuple(sorted(kw.items())))


def test_a_transition_splits_one_input_across_several_outputs() -> None:
    actions = petri_actions(NET, tokens=tokens, deposit=deposit)
    roast = next(a for a in actions if a.name == "roast")
    after = roast.apply(marking(green=8))
    assert tokens(after, "green") == 4  # 4 consumed
    assert tokens(after, "roasted") == 3  # produced together
    assert tokens(after, "loss") == 1  # ...in the same firing


def test_transition_disabled_without_enough_input_tokens() -> None:
    actions = petri_actions(NET, tokens=tokens, deposit=deposit)
    roast = next(a for a in actions if a.name == "roast")
    grind = next(a for a in actions if a.name == "grind")
    assert not roast.enabled(marking(green=3))  # needs 4
    assert roast.enabled(marking(green=4))
    assert not grind.enabled(marking(green=8))  # no roasted yet


def test_capacity_caps_an_output_place() -> None:
    # roasted may hold at most 3 kg; with 2 already there, a roast (which would add 3 -> 5) is blocked.
    actions = petri_actions(NET, tokens=tokens, deposit=deposit, capacity={"roasted": 3})
    roast = next(a for a in actions if a.name == "roast")
    assert roast.enabled(marking(green=8))
    assert not roast.enabled(marking(green=8, roasted=2))


def test_petri_enabled_lists_what_can_fire() -> None:
    assert petri_enabled(NET, marking(green=4), tokens=tokens) == frozenset({"roast"})
    assert petri_enabled(NET, marking(green=4, roasted=1), tokens=tokens) == frozenset(
        {"roast", "grind"}
    )
    assert petri_enabled(NET, marking(ground=5), tokens=tokens) == frozenset()


def test_petri_terminal_marks_a_drained_net_as_a_rest_state() -> None:
    terminal = petri_terminal(NET, tokens=tokens)
    assert terminal(marking(ground=5, loss=1))  # nothing left to fire
    assert not terminal(marking(green=4))


def test_place_invariants_are_discovered_and_each_is_conserved() -> None:
    basis = place_invariants(NET)
    # green, ground, loss, roasted: two free quantities -> a 2-vector basis
    assert len(basis) == 2
    # every discovered weighting is genuinely conserved by the net
    for weights in basis:
        assert_place_invariant(NET, weights)  # raises if not


def test_total_mass_is_a_place_invariant() -> None:
    # raw token count (all-ones) is conserved: no firing creates or destroys a kilogram
    assert_place_invariant(NET, {"green": 1, "roasted": 1, "loss": 1, "ground": 1})


def test_assert_place_invariant_rejects_a_leaky_net() -> None:
    leaky: PetriNet = {"evaporate": ({"water": 2}, {"vapor": 1})}  # loses a token
    with pytest.raises(AssertionError, match="evaporate"):
        assert_place_invariant(leaky, {"water": 1, "vapor": 1})


def test_place_invariants_empty_when_nothing_is_conserved() -> None:
    leaky: PetriNet = {"evaporate": ({"water": 2}, {"vapor": 1})}
    # one transition, two places, rank 1 -> a 1-vector null space; it weights the loss away, and it is
    # NOT the all-ones vector, so no "count is conserved" law exists
    basis = place_invariants(leaky)
    assert all(b != {"vapor": Fraction(1), "water": Fraction(1)} for b in basis)


def test_model_from_petri_conserves_mass_and_terminates() -> None:
    start = marking(green=8)
    total = 8

    model: Model[Net] = Model(
        init=start,
        actions=petri_actions(NET, tokens=tokens, deposit=deposit),
        invariants={
            "mass-conserved": lambda s: sum(c for _p, c in s.places) == total,
            "no-negative": lambda s: all(c >= 0 for _p, c in s.places),
        },
        terminal=petri_terminal(NET, tokens=tokens),
    )
    result = check(model)
    assert result.ok
