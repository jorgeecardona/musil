"""Parallel composition of component models (I/O-automata style).

Specify each component independently as a Model (states + named actions), then ``compose`` them into
one Model whose state is the tuple of component states and whose actions are the interleaving of all
components' actions, each lifted to act on its own slice. This is the "specify per component, compose"
discipline from the methodology note (docs/specs/formal-modeling-distributed-systems.md): the joint
behaviour is every interleaving of the parts, which is exactly where concurrency bugs live.

Component actions are name-qualified (``"<component>:<action>"``) and component invariants are lifted
(checked against that component's slice). Pass extra ``invariants`` to compose for *joint* properties
that span components. The composite is terminal only when every component is terminal."""

from __future__ import annotations

from collections.abc import Hashable, Mapping
from dataclasses import dataclass
from itertools import product
from typing import Any

from musil.core import Action, Invariant, Model

__all__ = [
    "Composite",
    "compose",
]


@dataclass(frozen=True, slots=True)
class Composite:
    """A joint state: one component state per name, kept sorted by name so it hashes deterministically.
    Read a component's slice with ``state["name"]``."""

    parts: tuple[tuple[str, Hashable], ...]

    def __getitem__(self, name: str) -> Hashable:
        for n, s in self.parts:
            if n == name:
                return s
        raise KeyError(name)

    def with_part(self, name: str, new: Hashable) -> Composite:
        return Composite(tuple((n, new if n == name else s) for n, s in self.parts))


def compose(
    components: Mapping[str, Model[Any]],
    *,
    invariants: Mapping[str, Invariant[Composite]] | None = None,
) -> Model[Composite]:
    """Interleaving product of ``components`` (name -> Model). The result's reachable states are every
    interleaving of the parts; component invariants are lifted (``"<name>:<inv>"``) and ``invariants``
    adds joint properties over the whole composite."""
    names = sorted(components)
    init_slices = [[(n, s) for s in components[n].initial_states()] for n in names]
    inits = [Composite(tuple(combo)) for combo in product(*init_slices)]

    actions: list[Action[Composite]] = []
    for n in names:
        for action in components[n].actions:
            actions.append(
                Action(
                    name=f"{n}:{action.name}",
                    enabled=lambda s, _n=n, _a=action: _a.enabled(s[_n]),
                    apply=lambda s, _n=n, _a=action: s.with_part(_n, _a.apply(s[_n])),
                )
            )

    inv: dict[str, Invariant[Composite]] = {}
    for n in names:
        for iname, ipred in components[n].invariants.items():
            inv[f"{n}:{iname}"] = lambda s, _n=n, _p=ipred: _p(s[_n])
    if invariants:
        inv.update(invariants)

    def terminal(s: Composite) -> bool:
        return all(components[n].terminal(s[n]) for n in names)

    return Model(init=inits, actions=actions, invariants=inv, terminal=terminal)
