"""Tests for the pre-built adversarial environment library (musil.environments)."""

from __future__ import annotations

from dataclasses import dataclass, replace

from musil.core import Action, Model
from musil.env import Assumption, EnvironmentSpec, check_open
from musil.environments.aws import (
    IAM_CORRECTNESS,
    S3_EVENTUAL_DELIVERY,
    THROTTLE_TRANSIENT,
    aws_api_faults,
    throttling_service,
    timeout_service,
)
from musil.environments.etcd import (
    BOUNDED_LEADER_ELECTION,
    QUORUM_MAINTAINED,
    UNIQUE_LEADER,
    cluster_faults,
    etcd_adversary,
)
from musil.environments.k8s import (
    EVICTION_RATE_BOUNDED,
    NODE_CAPACITY,
    SCHEDULER_LIVENESS,
    eviction_notifier,
    oom_notifier,
    pod_eviction,
)
from musil.environments.linux import (
    ENOSPC_RECOVERABLE,
    FS_RENAME_ATOMIC,
    OOM_KILLER_BOUNDED,
    SIGNAL_DELIVERY,
    fs_faults,
    process_faults,
    signal_sender,
)
from musil.environments.linux import (
    oom_notifier as linux_oom_notifier,
)
from musil.environments.sel4 import (
    CAP_INTEGRITY,
    HARDWARE_MEMORY_SAFETY,
    IPC_LIVENESS,
    cap_revocation_notifier,
    capability_revocation,
)

# ---------------------------------------------------------------------------
# Shared state type
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Svc:
    """Minimal service state for environment tests."""

    status: str = "running"   # "running" | "evicted" | "killed" | "failed"
    retries: int = 0


# ---------------------------------------------------------------------------
# Typed action helpers (pyright strict requires named functions, not bare lambdas,
# because the generic type parameter S cannot be inferred from unannotated lambdas)
# ---------------------------------------------------------------------------

def _can_run(s: Svc) -> bool:
    return s.status == "running"


def _evict(s: Svc) -> Svc:
    return replace(s, status="evicted")


def _kill(s: Svc) -> Svc:
    return replace(s, status="killed")


def _fail(s: Svc) -> Svc:
    return replace(s, status="failed")


def _add_retry(s: Svc) -> Svc:
    return replace(s, retries=s.retries + 1)


def _has_pending_retries(s: Svc) -> bool:
    return s.status != "running" and s.retries < 3


def _recover(s: Svc) -> Svc:
    return replace(s, status="running", retries=s.retries + 1)


def _can_retry(s: Svc) -> bool:
    return s.retries > 0


def _retries_exhausted(s: Svc) -> bool:
    return s.status != "running" and s.retries >= 3


# ---------------------------------------------------------------------------
# Minimal model builders
# ---------------------------------------------------------------------------

def _model(*, with_retry: bool = False) -> Model[Svc]:
    actions: list[Action[Svc]] = []
    if with_retry:
        actions.append(Action("retry", _has_pending_retries, _recover))
    return Model(
        init=Svc(),
        actions=actions,
        invariants={"not-failed": lambda s: s.status != "failed"},
        terminal=_retries_exhausted,
    )


def _model_not_evicted() -> Model[Svc]:
    return Model(
        init=Svc(),
        actions=[],
        invariants={"not-evicted": lambda s: s.status != "evicted"},
    )


# ---------------------------------------------------------------------------
# K8s environment tests
# ---------------------------------------------------------------------------

class TestK8sEnvironment:
    def test_eviction_env_type(self) -> None:
        env = pod_eviction(can_evict=_can_run, on_evict=_evict)
        assert isinstance(env, EnvironmentSpec)
        assert env.name == "k8s"
        assert len(env.behaviors) == 1
        assert env.behaviors[0].name == "k8s:evict-pod"

    def test_eviction_with_oom_kill(self) -> None:
        env = pod_eviction(
            can_evict=_can_run, on_evict=_evict,
            can_oom_kill=_can_run, on_oom_kill=_kill,
        )
        assert len(env.behaviors) == 2
        names = {b.name for b in env.behaviors}
        assert names == {"k8s:evict-pod", "k8s:oom-kill"}

    def test_eviction_assumptions_present(self) -> None:
        env = pod_eviction(can_evict=_can_run, on_evict=_evict)
        assert NODE_CAPACITY.name in env.assumptions
        assert SCHEDULER_LIVENESS.name in env.assumptions
        assert EVICTION_RATE_BOUNDED.name in env.assumptions

    def test_eviction_without_retry_violates(self) -> None:
        result = check_open(_model_not_evicted(), pod_eviction(can_evict=_can_run, on_evict=_evict))
        assert not result.ok

    def test_eviction_with_retry_passes(self) -> None:
        result = check_open(_model(with_retry=True), pod_eviction(can_evict=_can_run, on_evict=_evict))
        assert result.ok

    def test_unverified_assumptions_reported(self) -> None:
        result = check_open(_model(with_retry=True), pod_eviction(can_evict=_can_run, on_evict=_evict))
        names = {a.name for a in result.unverified_assumptions}
        assert NODE_CAPACITY.name in names
        assert SCHEDULER_LIVENESS.name in names

    def test_eviction_notifier_is_adversarial_node(self) -> None:
        from musil.sim import AdversarialNode
        assert isinstance(eviction_notifier(), AdversarialNode)

    def test_oom_notifier_is_adversarial_node(self) -> None:
        from musil.sim import AdversarialNode
        assert isinstance(oom_notifier(), AdversarialNode)


# ---------------------------------------------------------------------------
# AWS environment tests
# ---------------------------------------------------------------------------

class TestAwsEnvironment:
    def test_throttle_env_type(self) -> None:
        env = aws_api_faults(can_throttle=_can_run, on_throttle=_evict)
        assert isinstance(env, EnvironmentSpec)
        assert env.name == "aws"
        assert len(env.behaviors) == 1
        assert env.behaviors[0].name == "aws:throttle"

    def test_throttle_and_timeout(self) -> None:
        env = aws_api_faults(
            can_throttle=_can_run, on_throttle=_evict,
            can_timeout=_can_run, on_timeout=_kill,
        )
        names = {b.name for b in env.behaviors}
        assert names == {"aws:throttle", "aws:timeout"}

    def test_iam_correctness_is_verified(self) -> None:
        assert IAM_CORRECTNESS.status == "verified"

    def test_unverified_assumptions_exclude_verified(self) -> None:
        result = check_open(_model(with_retry=True), aws_api_faults(can_throttle=_can_run, on_throttle=_evict))
        names = {a.name for a in result.unverified_assumptions}
        assert IAM_CORRECTNESS.name not in names
        assert S3_EVENTUAL_DELIVERY.name in names
        assert THROTTLE_TRANSIENT.name in names

    def test_throttling_service_is_adversarial_node(self) -> None:
        from musil.sim import AdversarialNode
        assert isinstance(throttling_service(), AdversarialNode)

    def test_timeout_service_is_adversarial_node(self) -> None:
        from musil.sim import AdversarialNode
        assert isinstance(timeout_service(), AdversarialNode)

    def test_timeout_service_drops_all(self) -> None:
        node = timeout_service()
        assert len(node._behaviors) == 0  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Linux environment tests
# ---------------------------------------------------------------------------

class TestLinuxEnvironment:
    def test_process_faults_type(self) -> None:
        env = process_faults(can_oom_kill=_can_run, on_oom_kill=_kill)
        assert isinstance(env, EnvironmentSpec)
        assert env.name == "linux"
        assert env.behaviors[0].name == "linux:oom-kill"

    def test_process_faults_with_sigterm(self) -> None:
        env = process_faults(
            can_oom_kill=_can_run, on_oom_kill=_kill,
            can_sigterm=_can_run, on_sigterm=_evict,
        )
        names = {b.name for b in env.behaviors}
        assert names == {"linux:oom-kill", "linux:sigterm"}

    def test_fs_faults_type(self) -> None:
        env = fs_faults(can_enospc=_can_run, on_enospc=_fail)
        assert env.name == "linux"
        assert env.behaviors[0].name == "linux:enospc"

    def test_fs_rename_atomic_is_verified(self) -> None:
        assert FS_RENAME_ATOMIC.status == "verified"

    def test_oom_notifier_sends_oom(self) -> None:
        from musil.sim import AdversarialNode
        assert isinstance(linux_oom_notifier(), AdversarialNode)

    def test_signal_sender_is_adversarial_node(self) -> None:
        from musil.sim import AdversarialNode
        assert isinstance(signal_sender(), AdversarialNode)

    def test_oom_assumption_present(self) -> None:
        env = process_faults(can_oom_kill=_can_run, on_oom_kill=_kill)
        assert OOM_KILLER_BOUNDED.name in env.assumptions
        assert SIGNAL_DELIVERY.name in env.assumptions

    def test_enospc_assumption_present(self) -> None:
        env = fs_faults(can_enospc=_can_run, on_enospc=_fail)
        assert ENOSPC_RECOVERABLE.name in env.assumptions


# ---------------------------------------------------------------------------
# seL4 environment tests
# ---------------------------------------------------------------------------

class TestSel4Environment:
    def test_capability_revocation_type(self) -> None:
        env = capability_revocation(can_revoke=_can_run, on_revoke=_evict)
        assert isinstance(env, EnvironmentSpec)
        assert env.name == "sel4"
        assert env.behaviors[0].name == "sel4:cap-revoke"

    def test_hardware_memory_safety_is_axiom(self) -> None:
        assert HARDWARE_MEMORY_SAFETY.status == "axiom"

    def test_cap_integrity_is_verified(self) -> None:
        assert CAP_INTEGRITY.status == "verified"

    def test_ipc_liveness_is_unverified(self) -> None:
        assert IPC_LIVENESS.status == "unverified"

    def test_axiom_surfaces_as_unverified_assumption(self) -> None:
        result = check_open(_model(with_retry=True), capability_revocation(can_revoke=_can_run, on_revoke=_evict))
        names = {a.name for a in result.unverified_assumptions}
        assert HARDWARE_MEMORY_SAFETY.name in names
        assert IPC_LIVENESS.name in names
        assert CAP_INTEGRITY.name not in names

    def test_cap_revocation_notifier_is_adversarial_node(self) -> None:
        from musil.sim import AdversarialNode
        assert isinstance(cap_revocation_notifier(), AdversarialNode)


# ---------------------------------------------------------------------------
# etcd environment tests
# ---------------------------------------------------------------------------

class TestEtcdEnvironment:
    def test_cluster_faults_type(self) -> None:
        env = cluster_faults(can_leader_change=_can_run, on_leader_change=_evict)
        assert isinstance(env, EnvironmentSpec)
        assert env.name == "etcd"
        assert env.behaviors[0].name == "etcd:leader-change"

    def test_all_three_behaviors(self) -> None:
        env = cluster_faults(
            can_leader_change=_can_run, on_leader_change=_evict,
            can_write_conflict=_can_run, on_write_conflict=_add_retry,
            can_compaction=_can_retry, on_compaction=_fail,
        )
        names = {b.name for b in env.behaviors}
        assert names == {"etcd:leader-change", "etcd:write-conflict", "etcd:compaction"}

    def test_unique_leader_is_verified(self) -> None:
        assert UNIQUE_LEADER.status == "verified"

    def test_verified_assumption_excluded(self) -> None:
        result = check_open(_model(with_retry=True), cluster_faults(can_leader_change=_can_run, on_leader_change=_evict))
        names = {a.name for a in result.unverified_assumptions}
        assert UNIQUE_LEADER.name not in names
        assert QUORUM_MAINTAINED.name in names
        assert BOUNDED_LEADER_ELECTION.name in names

    def test_etcd_adversary_is_adversarial_node(self) -> None:
        from musil.sim import AdversarialNode
        assert isinstance(etcd_adversary(), AdversarialNode)


# ---------------------------------------------------------------------------
# Multi-environment composition tests
# ---------------------------------------------------------------------------

class TestMultiEnvironment:
    def test_compose_k8s_and_linux(self) -> None:
        result = check_open(
            _model(with_retry=True),
            pod_eviction(can_evict=_can_run, on_evict=_evict),
            process_faults(can_oom_kill=_can_run, on_oom_kill=_kill),
        )
        names = {a.name for a in result.unverified_assumptions}
        assert NODE_CAPACITY.name in names
        assert OOM_KILLER_BOUNDED.name in names

    def test_compose_aws_and_etcd(self) -> None:
        result = check_open(
            _model(with_retry=True),
            aws_api_faults(can_throttle=_can_run, on_throttle=_evict),
            cluster_faults(can_leader_change=_can_run, on_leader_change=_evict),
        )
        names = {a.name for a in result.unverified_assumptions}
        assert S3_EVENTUAL_DELIVERY.name in names
        assert QUORUM_MAINTAINED.name in names

    def test_extra_assumptions_propagated(self) -> None:
        custom = Assumption(
            name="my-service:rate-limited",
            description="Our service rate-limits external callers",
            status="unverified",
        )
        env = pod_eviction(
            can_evict=_can_run, on_evict=_evict,
            extra_assumptions={custom.name: custom},
        )
        result = check_open(_model(with_retry=True), env)
        names = {a.name for a in result.unverified_assumptions}
        assert custom.name in names
