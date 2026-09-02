"""Distributed storage/state fault environments.

``EnvironmentSpec`` factories for the fault classes that dominate a STATEFUL distributed system's incident
history but are not process/filesystem/cloud-API specific:

- ``credential_rotation`` — a credential is rotated (invalidated) mid-flight.
- ``record_reality_divergence`` — a component's cached RECORD of external state stops matching REALITY (a
  restart, a cutover, a re-attached or empty volume). The general "trusts its own record instead of sensing
  the real state" fault; "stale view after restart" and "wrong/empty volume attached" are both instances of
  it, so there is one factory rather than a domain-specific "volume" env.

Each is parameterized over model-supplied accessors (it does not assume a state shape) and ships with a
cited ``Assumption``, so it composes into ``check_open`` (and ``check_liveness_open``) uniformly.

Model checking::

    from dataclasses import replace
    from musil.environments.distributed import record_reality_divergence
    from musil.env import check_open
    env = record_reality_divergence(
        can_diverge=lambda s: s.record == s.reality,
        on_diverge=lambda s: replace(s, reality=s.reality + 1),  # reality drifts; the record goes stale
    )
    result = check_open(model, env)

Deliberately NOT here:

- **message lost / reordered / duplicated** — already covered by ``musil.channels`` (lossy / duplicating /
  unordered ``channel_actions``) and ``sim.NetworkModel`` (per-message loss/duplication). Reuse those; a
  new EnvironmentSpec would duplicate them.
- **grace-window races** (a timer fires against state that already moved) — couples to the model's clock
  (``bounded_clock``); left to downstream fixtures until a clock-aware env abstraction is worth committing
  to.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable

from musil.core import Action
from musil.env import Assumption, EnvironmentSpec

# ---------------------------------------------------------------------------
# Assumptions (cite the engineering principle the guarantee rests on)
# ---------------------------------------------------------------------------

CREDENTIAL_ROTATION_OBSERVED = Assumption(
    name="distributed:credential-rotation-observed",
    description=(
        "A credential can be rotated (invalidated) at any moment; the holder eventually observes the "
        "invalidation on its next authenticated call and re-authenticates, rather than trusting a cached "
        "token indefinitely"
    ),
    status="unverified",
    source="OAuth 2.0 access-token expiry (RFC 6749 §1.5); secret-rotation practice",
)

REALITY_EVENTUALLY_SENSED = Assumption(
    name="distributed:reality-eventually-sensed",
    description=(
        "A component's cached RECORD of external state can diverge from REALITY at any time (a restart, a "
        "cutover, a re-attached or empty volume); a correct component re-validates the record against a real "
        "read on recovery and does not treat its own record as ground truth"
    ),
    status="unverified",
    source="Read-repair / cache-invalidation practice: the record is not the territory",
)


def credential_rotation[S: Hashable](
    *,
    can_rotate: Callable[[S], bool],
    on_rotate: Callable[[S], S],
    extra_assumptions: dict[str, Assumption] | None = None,
) -> EnvironmentSpec[S]:
    """EnvironmentSpec for a credential rotated mid-flight.

    ``can_rotate(state)`` says when a rotation may happen (typically: the credential is currently valid);
    ``on_rotate(state)`` returns the state with the credential invalidated. The BFS then explores a rotation
    from every such state, so the system is checked against a rotation at the worst possible moment.

    Behavior added:
    - ``distributed:credential-rotation``: the credential becomes invalid.

    Pre-wired assumption: ``CREDENTIAL_ROTATION_OBSERVED`` (the holder eventually re-authenticates rather
    than trusting a cached token forever)."""
    behaviors: list[Action[S]] = [Action("distributed:credential-rotation", can_rotate, on_rotate)]
    assumptions: dict[str, Assumption] = {CREDENTIAL_ROTATION_OBSERVED.name: CREDENTIAL_ROTATION_OBSERVED}
    if extra_assumptions:
        assumptions.update(extra_assumptions)
    return EnvironmentSpec[S](name="distributed", behaviors=behaviors, assumptions=assumptions)


def record_reality_divergence[S: Hashable](
    *,
    can_diverge: Callable[[S], bool],
    on_diverge: Callable[[S], S],
    extra_assumptions: dict[str, Assumption] | None = None,
) -> EnvironmentSpec[S]:
    """EnvironmentSpec for a component's RECORD ceasing to match REALITY — the general "trusts its own record
    instead of sensing the real state" fault.

    ``can_diverge(state)`` says when reality may drift from the record (typically: they currently agree);
    ``on_diverge(state)`` returns the state with reality changed but the record left stale. Both "stale view
    after restart/cutover" and "wrong/empty volume attached (record != reality on recovery)" are usages: the
    caller's ``on_diverge`` chooses how reality moves. The BFS explores a divergence from every such state,
    so a system that acts on its record without re-validating is caught.

    Behavior added:
    - ``distributed:record-reality-divergence``: reality moves; the record goes stale.

    Pre-wired assumption: ``REALITY_EVENTUALLY_SENSED`` (a correct component re-validates against a real read
    on recovery)."""
    behaviors: list[Action[S]] = [Action("distributed:record-reality-divergence", can_diverge, on_diverge)]
    assumptions: dict[str, Assumption] = {REALITY_EVENTUALLY_SENSED.name: REALITY_EVENTUALLY_SENSED}
    if extra_assumptions:
        assumptions.update(extra_assumptions)
    return EnvironmentSpec[S](name="distributed", behaviors=behaviors, assumptions=assumptions)
