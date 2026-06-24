"""etcd cluster fault environments.

EnvironmentSpec factory and AdversarialNode for etcd cluster faults: leader election,
write conflicts, and compaction.

Model checking::

    from dataclasses import replace
    from musil.environments.etcd import cluster_faults
    env = cluster_faults(
        can_leader_change=lambda s: s.etcd_connected,
        on_leader_change=lambda s: replace(s, etcd_leader_known=False),
        can_write_conflict=lambda s: s.write_in_flight,
        on_write_conflict=lambda s: replace(s, write_in_flight=False, last_rev=-1),
    )
    result = check_open(model, env)

Simulation::

    from musil.environments.etcd import etcd_adversary
    nodes = {"service": MyService(), "etcd": etcd_adversary()}
    report = simulate(lambda: nodes, seeds=range(100), ...)
"""

from __future__ import annotations

from collections.abc import Callable, Hashable

from musil.core import Action
from musil.env import Assumption, EnvironmentSpec
from musil.sim import AdversarialNode, Context

# ---------------------------------------------------------------------------
# Assumptions (cite etcd documentation and Raft paper)
# ---------------------------------------------------------------------------

QUORUM_MAINTAINED = Assumption(
    name="etcd:quorum-maintained",
    description=(
        "etcd cluster maintains quorum (>50% of members healthy) throughout; "
        "a minority partition cannot elect a leader or accept writes"
    ),
    status="unverified",
    source="etcd docs: Clustering guide § Fault tolerance; Ongaro & Ousterhout, USENIX ATC 2014",
)

BOUNDED_LEADER_ELECTION = Assumption(
    name="etcd:bounded-leader-election",
    description=(
        "Leader elections complete within a bounded time (default election timeout: 1000ms); "
        "clients that retry writes after an election eventually succeed"
    ),
    status="unverified",
    source="etcd docs: Tuning § Time parameters",
)

UNIQUE_LEADER = Assumption(
    name="etcd:unique-leader",
    description=(
        "At most one etcd leader exists at any point; "
        "Raft guarantees linearizability for committed writes"
    ),
    status="verified",
    source="Ongaro & Ousterhout, 'In Search of an Understandable Consensus Algorithm', "
           "USENIX ATC 2014 § 5 (Safety)",
)

COMPACTION_BOUNDED = Assumption(
    name="etcd:compaction-bounded",
    description=(
        "etcd compaction removes only revisions older than the configured retention window; "
        "keys within the window are always readable"
    ),
    status="unverified",
    source="etcd docs: Operations guide § Maintenance § History compaction",
)


# ---------------------------------------------------------------------------
# EnvironmentSpec factories
# ---------------------------------------------------------------------------

def cluster_faults[S: Hashable](
    *,
    can_leader_change: Callable[[S], bool],
    on_leader_change: Callable[[S], S],
    can_write_conflict: Callable[[S], bool] | None = None,
    on_write_conflict: Callable[[S], S] | None = None,
    can_compaction: Callable[[S], bool] | None = None,
    on_compaction: Callable[[S], S] | None = None,
    extra_assumptions: dict[str, Assumption] | None = None,
) -> EnvironmentSpec[S]:
    """EnvironmentSpec for etcd cluster faults: leader change, write conflicts, compaction.

    Behaviors added:
    - ``etcd:leader-change``: Raft leader changes; in-flight writes may be rejected
    - ``etcd:write-conflict``: concurrent write with conflicting revision (optional)
    - ``etcd:compaction``: old revisions compacted away; watchers may miss events (optional)

    Pre-wired assumptions: ``QUORUM_MAINTAINED``, ``BOUNDED_LEADER_ELECTION``,
    ``COMPACTION_BOUNDED``. ``UNIQUE_LEADER`` is ``status="verified"`` (Raft safety proof).
    """
    behaviors: list[Action[S]] = [Action("etcd:leader-change", can_leader_change, on_leader_change)]
    if can_write_conflict is not None and on_write_conflict is not None:
        behaviors.append(Action("etcd:write-conflict", can_write_conflict, on_write_conflict))
    if can_compaction is not None and on_compaction is not None:
        behaviors.append(Action("etcd:compaction", can_compaction, on_compaction))

    assumptions: dict[str, Assumption] = {
        QUORUM_MAINTAINED.name: QUORUM_MAINTAINED,
        BOUNDED_LEADER_ELECTION.name: BOUNDED_LEADER_ELECTION,
        COMPACTION_BOUNDED.name: COMPACTION_BOUNDED,
    }
    if extra_assumptions:
        assumptions.update(extra_assumptions)

    return EnvironmentSpec[S](name="etcd", behaviors=behaviors, assumptions=assumptions)


# ---------------------------------------------------------------------------
# AdversarialNode factories
# ---------------------------------------------------------------------------

def etcd_adversary(*, msg: object = "etcd:leader-change") -> AdversarialNode:
    """AdversarialNode that responds to writes with a leader-change error.

    Models an etcd cluster mid-election: write requests return an error indicating
    that the current leader has changed and the client must retry.
    """
    def guard(_src: str, _payload: object) -> bool:
        return True

    def _make_response(m: object) -> Callable[[Context, str, object], None]:
        def response(ctx: Context, src: str, _payload: object) -> None:
            ctx.send(src, m)
        return response

    return AdversarialNode(behaviors=[(guard, _make_response(msg))])
