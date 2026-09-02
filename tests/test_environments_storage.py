"""`block_volume_faults` (#40): the block-volume fault contract, checked via `check_open`.

Pins the semantics of the new EnvironmentSpec: a naive node that serves without sensing suffers the
wrong-volume data-loss (a safety violation whose counterexample names the fault), a sensing node is safe
against the same fault, a sensing-and-recovering node eventually recovers under strong fairness, and the
factory's input guards and surfaced assumptions behave as documented.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import pytest

from musil import Action, Model
from musil.env import EnvironmentSpec, check_liveness_open, check_open
from musil.environments.storage import (
    DATA_PRESENCE_SENSED,
    VOLUME_ATTACH_EXCLUSIVE,
    block_volume_faults,
)


@dataclass(frozen=True)
class Node:
    attached: bool = False
    data_ok: bool = True  # whether the attached volume holds THIS node's data
    serving: bool = False


def _wrong_attach_env() -> EnvironmentSpec[Node]:
    return block_volume_faults(
        can_wrong_attach=lambda s: s.attached and not s.serving,
        on_wrong_attach=lambda s: replace(s, data_ok=False),  # a different volume's data
    )


def test_check_open_finds_the_wrong_volume_data_loss() -> None:
    # a node that serves as soon as a volume is attached, WITHOUT sensing whether the data is its own
    naive = Model(
        init=Node(),
        actions=[
            Action("attach", enabled=lambda s: not s.attached, apply=lambda s: replace(s, attached=True, data_ok=True)),
            Action("serve", enabled=lambda s: s.attached and not s.serving, apply=lambda s: replace(s, serving=True)),
        ],
        invariants={"no-wrong-serve": lambda s: not (s.serving and not s.data_ok)},
        terminal=lambda s: s.serving,
    )
    r = check_open(naive, _wrong_attach_env())
    assert not r.ok
    assert r.result.invariant == "no-wrong-serve"
    # the counterexample is caused by the fault contract, named in the trace
    assert any(step.action == "storage:wrong-volume-attached" for step in r.result.trace)


def test_sensing_node_is_safe_against_the_same_fault() -> None:
    # the fix: serve only after sensing the data is its own -> the same fault can no longer cause a wrong-serve
    sensing = Model(
        init=Node(),
        actions=[
            Action("attach", enabled=lambda s: not s.attached, apply=lambda s: replace(s, attached=True, data_ok=True)),
            Action("serve", enabled=lambda s: s.attached and s.data_ok and not s.serving, apply=lambda s: replace(s, serving=True)),
        ],
        invariants={"no-wrong-serve": lambda s: not (s.serving and not s.data_ok)},
        terminal=lambda s: s.serving,
    )
    assert check_open(sensing, _wrong_attach_env()).ok


def test_sensing_recovering_node_eventually_recovers_under_strong_fairness() -> None:
    # senses AND recovers: a wrong volume is re-attached correct, and the node serves once its data is present.
    # Under STRONG fairness on serve (enabled infinitely often as the fault toggles data_ok), every run reaches
    # the recovered (serving) state -- []<>recovered is provable, which DATA_PRESENCE_SENSED is the basis for.
    recovering = Model(
        init=Node(),
        actions=[
            Action("attach", enabled=lambda s: not s.attached, apply=lambda s: replace(s, attached=True, data_ok=True)),
            Action("serve", enabled=lambda s: s.attached and s.data_ok and not s.serving, apply=lambda s: replace(s, serving=True)),
            Action("reattach", enabled=lambda s: s.attached and not s.data_ok and not s.serving, apply=lambda s: replace(s, data_ok=True)),
        ],
        terminal=lambda s: s.serving,
    )
    r = check_liveness_open(recovering, _wrong_attach_env(), goal=lambda s: s.serving, fair_strong=["serve"])
    assert r.ok


def test_surfaces_the_storage_assumptions() -> None:
    naive = Model(
        init=Node(),
        actions=[Action("attach", enabled=lambda s: not s.attached, apply=lambda s: replace(s, attached=True))],
        terminal=lambda s: s.attached,
    )
    names = {a.name for a in check_open(naive, _wrong_attach_env()).unverified_assumptions}
    assert VOLUME_ATTACH_EXCLUSIVE.name in names
    assert DATA_PRESENCE_SENSED.name in names


def test_factory_rejects_a_half_supplied_pair_and_an_empty_fault_set() -> None:
    with pytest.raises(ValueError, match="BOTH"):
        block_volume_faults(can_detach=lambda s: True)  # on_detach missing
    with pytest.raises(ValueError, match="at least one"):
        block_volume_faults()  # no faults at all
