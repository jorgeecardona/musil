"""Block-volume (block-storage) fault environments.

The fault class behind most stateful-node data-loss incidents: a volume detached or lost, the WRONG volume
reattached (a tenant silently wiped), a present-but-empty volume, or a detach racing an in-flight write.
Modelling these as bespoke ``Action``s in every stateful model duplicates the same subtle contract; this
composes them once as an ``EnvironmentSpec`` for ``check_open`` (issue #40).

Model checking::

    from dataclasses import replace
    from musil.environments.storage import block_volume_faults
    from musil.env import check_open

    env = block_volume_faults(
        can_wrong_attach=lambda s: s.attached and not s.serving,
        on_wrong_attach=lambda s: replace(s, data_ok=False),          # a different volume's data
        can_detach=lambda s: s.attached,
        on_detach=lambda s: replace(s, attached=False),
    )
    result = check_open(model, env)   # finds the interleaving where a wrong volume is served

Each fault is opt-in: pass a ``can_<fault>`` / ``on_<fault>`` pair for the behaviors your model can exhibit
(both of a pair, or neither). The two pre-wired assumptions are the storage contract the recovery rests on:
one node attaches a volume at a time, and a data-presence SENSE eventually resolves so a wrong/empty volume
is detectable — the latter is what makes ``[]<>recovered`` provable rather than a wrong volume served forever.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable

from musil.core import Action
from musil.env import Assumption, EnvironmentSpec

# ---------------------------------------------------------------------------
# Assumptions (the block-storage contract the recovery rests on)
# ---------------------------------------------------------------------------

VOLUME_ATTACH_EXCLUSIVE = Assumption(
    name="storage:attach-exclusive",
    description=(
        "A block volume is attached to at most one node at a time; a second attach waits for or "
        "force-detaches the first (barring explicit multi-attach)"
    ),
    status="unverified",
    source="AWS EBS docs: a volume attaches to one instance at a time (except Multi-Attach); general block-storage contract",
)

DATA_PRESENCE_SENSED = Assumption(
    name="storage:data-presence-sensed",
    description=(
        "After an attach a node eventually SENSES whether the volume holds its own data (a sentinel/marker "
        "read) and refuses to serve a wrong or empty volume, so a data-loss state is detectable and thus "
        "recoverable -- this is what makes []<>recovered provable rather than a wrong volume silently served"
    ),
    status="unverified",
    source="Operational assumption: the node must implement the sense and the deployment must guarantee it resolves",
)


# ---------------------------------------------------------------------------
# EnvironmentSpec factory
# ---------------------------------------------------------------------------


def block_volume_faults[S: Hashable](
    *,
    can_detach: Callable[[S], bool] | None = None,
    on_detach: Callable[[S], S] | None = None,
    can_wrong_attach: Callable[[S], bool] | None = None,
    on_wrong_attach: Callable[[S], S] | None = None,
    can_empty_attach: Callable[[S], bool] | None = None,
    on_empty_attach: Callable[[S], S] | None = None,
    can_detach_during_write: Callable[[S], bool] | None = None,
    on_detach_during_write: Callable[[S], S] | None = None,
    extra_assumptions: dict[str, Assumption] | None = None,
) -> EnvironmentSpec[S]:
    """EnvironmentSpec for block-volume faults: the stateful-node data-loss class.

    Behaviors (each opt-in — pass BOTH ``can_``/``on_`` of a pair, or neither; at least one pair required):
    - ``storage:volume-detached``: the volume is detached / lost (``can_detach`` / ``on_detach``)
    - ``storage:wrong-volume-attached``: a DIFFERENT volume is attached — a data mismatch that wipes a tenant
      if served (``can_wrong_attach`` / ``on_wrong_attach``)
    - ``storage:empty-volume-attached``: a present-but-empty volume is attached (``can_empty_attach`` /
      ``on_empty_attach``)
    - ``storage:detach-during-write``: a detach races an in-flight write (``can_detach_during_write`` /
      ``on_detach_during_write``)

    Pre-wired assumptions: ``VOLUME_ATTACH_EXCLUSIVE`` (single-writer attach) and ``DATA_PRESENCE_SENSED``
    (a data-presence sense eventually resolves, so a wrong/empty volume is detectable — the basis for
    ``[]<>recovered``). Both are surfaced in ``OpenResult.unverified_assumptions`` — residual proof
    obligations, never silently dropped.

    Passing only one half of a fault's pair raises ``ValueError`` (refuse rather than silently drop a fault
    the caller believed they added); passing no pair at all raises too (an empty fault set is useless)."""
    pairs = (
        ("storage:volume-detached", can_detach, on_detach),
        ("storage:wrong-volume-attached", can_wrong_attach, on_wrong_attach),
        ("storage:empty-volume-attached", can_empty_attach, on_empty_attach),
        ("storage:detach-during-write", can_detach_during_write, on_detach_during_write),
    )
    behaviors: list[Action[S]] = []
    for name, guard, effect in pairs:
        if guard is not None and effect is not None:
            behaviors.append(Action(name, guard, effect))
        elif (guard is None) != (effect is None):
            raise ValueError(f"block_volume_faults: {name!r} needs BOTH its can_/on_ callables, or neither")
    if not behaviors:
        raise ValueError("block_volume_faults: supply at least one fault's can_/on_ pair")

    assumptions: dict[str, Assumption] = {
        VOLUME_ATTACH_EXCLUSIVE.name: VOLUME_ATTACH_EXCLUSIVE,
        DATA_PRESENCE_SENSED.name: DATA_PRESENCE_SENSED,
    }
    if extra_assumptions:
        assumptions.update(extra_assumptions)

    return EnvironmentSpec[S](name="storage", behaviors=behaviors, assumptions=assumptions)
