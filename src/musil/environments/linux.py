"""Linux kernel fault environments.

EnvironmentSpec factories and AdversarialNodes for Linux process and filesystem faults:
OOM kills, signals, and filesystem errors.

Model checking::

    from dataclasses import replace
    from musil.environments.linux import process_faults
    from musil.env import check_open
    env = process_faults(
        can_oom_kill=lambda s: s.status == "running",
        on_oom_kill=lambda s: replace(s, status="killed", exit_code=137),
    )
    result = check_open(model, env)

Simulation::

    from musil.environments.linux import oom_notifier
    nodes = {"worker": Worker(), "kernel": oom_notifier()}
    report = simulate(lambda: nodes, seeds=range(100), ...)
"""

from __future__ import annotations

from collections.abc import Callable, Hashable

from musil.core import Action
from musil.env import Assumption, EnvironmentSpec
from musil.sim import AdversarialNode, Context

# ---------------------------------------------------------------------------
# Assumptions (cite Linux kernel documentation)
# ---------------------------------------------------------------------------

OOM_KILLER_BOUNDED = Assumption(
    name="linux:oom-killer-bounded",
    description=(
        "The OOM killer fires only under genuine memory pressure; "
        "it selects victims by oom_score and kills at most one process per invocation"
    ),
    status="unverified",
    source="Linux kernel docs: admin-guide/mm/concepts § OOM killer",
)

SIGNAL_DELIVERY = Assumption(
    name="linux:signal-delivery",
    description=(
        "Signals sent to a process are eventually delivered "
        "(subject to signal masks and process state)"
    ),
    status="unverified",
    source="Linux man-pages: signal(7) § Standard signals",
)

FS_RENAME_ATOMIC = Assumption(
    name="linux:fs-rename-atomic",
    description=(
        "rename(2) is atomic within the same filesystem; "
        "either the old name or the new name is visible, never both nor neither"
    ),
    status="verified",
    source="Linux man-pages: rename(2) § NOTES",
)

ENOSPC_RECOVERABLE = Assumption(
    name="linux:enospc-recoverable",
    description=(
        "ENOSPC conditions are transient; disk space becomes available "
        "after log rotation or other cleanup"
    ),
    status="unverified",
    source="Operational assumption — must be verified per deployment",
)


# ---------------------------------------------------------------------------
# EnvironmentSpec factories
# ---------------------------------------------------------------------------

def process_faults[S: Hashable](
    *,
    can_oom_kill: Callable[[S], bool],
    on_oom_kill: Callable[[S], S],
    can_sigterm: Callable[[S], bool] | None = None,
    on_sigterm: Callable[[S], S] | None = None,
    extra_assumptions: dict[str, Assumption] | None = None,
) -> EnvironmentSpec[S]:
    """EnvironmentSpec for Linux process faults: OOM kills and optional SIGTERM.

    Behaviors added:
    - ``linux:oom-kill``: kernel OOM killer terminates the process (SIGKILL, exit 137)
    - ``linux:sigterm``: graceful shutdown signal (optional)

    Pre-wired assumptions: ``OOM_KILLER_BOUNDED``, ``SIGNAL_DELIVERY``.
    """
    behaviors: list[Action[S]] = [Action("linux:oom-kill", can_oom_kill, on_oom_kill)]
    if can_sigterm is not None and on_sigterm is not None:
        behaviors.append(Action("linux:sigterm", can_sigterm, on_sigterm))

    assumptions: dict[str, Assumption] = {
        OOM_KILLER_BOUNDED.name: OOM_KILLER_BOUNDED,
        SIGNAL_DELIVERY.name: SIGNAL_DELIVERY,
    }
    if extra_assumptions:
        assumptions.update(extra_assumptions)

    return EnvironmentSpec[S](name="linux", behaviors=behaviors, assumptions=assumptions)


def fs_faults[S: Hashable](
    *,
    can_enospc: Callable[[S], bool],
    on_enospc: Callable[[S], S],
    extra_assumptions: dict[str, Assumption] | None = None,
) -> EnvironmentSpec[S]:
    """EnvironmentSpec for Linux filesystem faults: ENOSPC (disk full).

    Behaviors added:
    - ``linux:enospc``: write fails with ENOSPC (no space left on device)

    Pre-wired assumptions: ``FS_RENAME_ATOMIC``, ``ENOSPC_RECOVERABLE``.
    """
    assumptions: dict[str, Assumption] = {
        FS_RENAME_ATOMIC.name: FS_RENAME_ATOMIC,
        ENOSPC_RECOVERABLE.name: ENOSPC_RECOVERABLE,
    }
    if extra_assumptions:
        assumptions.update(extra_assumptions)

    return EnvironmentSpec[S](
        name="linux",
        behaviors=[Action("linux:enospc", can_enospc, on_enospc)],
        assumptions=assumptions,
    )


# ---------------------------------------------------------------------------
# AdversarialNode factories
# ---------------------------------------------------------------------------

def oom_notifier(*, msg: object = "linux:oom-kill") -> AdversarialNode:
    """AdversarialNode that sends an OOM kill notification to any node that contacts it.

    Models the Linux OOM killer notifying a process before terminating it.
    """
    def guard(_src: str, _payload: object) -> bool:
        return True

    def _make_response(m: object) -> Callable[[Context, str, object], None]:
        def response(ctx: Context, src: str, _payload: object) -> None:
            ctx.send(src, m)
        return response

    return AdversarialNode(behaviors=[(guard, _make_response(msg))])


def signal_sender(*, signal: str = "SIGTERM") -> AdversarialNode:
    """AdversarialNode that sends a Linux signal to any node that contacts it.

    Models the kernel (or another process) sending SIGTERM/SIGKILL/etc.
    The signal value is passed as the payload string.
    """
    def guard(_src: str, _payload: object) -> bool:
        return True

    def _make_response(sig: str) -> Callable[[Context, str, object], None]:
        def response(ctx: Context, src: str, _payload: object) -> None:
            ctx.send(src, sig)
        return response

    return AdversarialNode(behaviors=[(guard, _make_response(signal))])
