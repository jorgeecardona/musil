"""seL4 microkernel fault environments.

EnvironmentSpec factory and AdversarialNode for seL4 capability revocation and IPC faults.

seL4's formal verification (Klein et al., SOSP 2009) guarantees that capability access
requires explicit delegation. The hardware memory safety assumption is an *axiom* — seL4's
proof rests on it but cannot prove it from within the system.

Model checking::

    from dataclasses import replace
    from musil.environments.sel4 import capability_revocation, HARDWARE_MEMORY_SAFETY
    env = capability_revocation(
        can_revoke=lambda s: s.cap_valid,
        on_revoke=lambda s: replace(s, cap_valid=False),
    )
    result = check_open(model, env)
    # HARDWARE_MEMORY_SAFETY will appear as an axiom assumption

Simulation::

    from musil.environments.sel4 import cap_revocation_notifier
    nodes = {"task": MyTask(), "kernel": cap_revocation_notifier()}
    report = simulate(lambda: nodes, seeds=range(100), ...)
"""

from __future__ import annotations

from collections.abc import Callable, Hashable

from musil.core import Action
from musil.env import Assumption, EnvironmentSpec
from musil.sim import AdversarialNode, Context

# ---------------------------------------------------------------------------
# Assumptions (cite seL4 paper and formal proofs)
# ---------------------------------------------------------------------------

HARDWARE_MEMORY_SAFETY = Assumption(
    name="sel4:hardware-memory-safety",
    description=(
        "Physical memory does not corrupt silently; CPU executes instructions faithfully. "
        "This is seL4's Trusted Computing Base (TCB) — the axiom the formal proof rests on."
    ),
    status="axiom",
    source="Klein et al., 'seL4: Formal Verification of an OS Kernel', SOSP 2009 § 2 (TCB)",
)

CAP_INTEGRITY = Assumption(
    name="sel4:capability-integrity",
    description=(
        "Capability access requires explicit delegation from a parent; "
        "seL4 formally proves no capability can be forged or leaked"
    ),
    status="verified",
    source="Klein et al., 'seL4: Formal Verification of an OS Kernel', SOSP 2009 § 4",
)

IPC_LIVENESS = Assumption(
    name="sel4:ipc-liveness",
    description=(
        "Blocking IPC calls with a finite timeout are eventually scheduled; "
        "the seL4 scheduler does not starve any domain indefinitely"
    ),
    status="unverified",
    source=(
        "seL4 Reference Manual § 4 (IPC); "
        "liveness is not covered by the SOSP 2009 functional correctness proof"
    ),
)


# ---------------------------------------------------------------------------
# EnvironmentSpec factories
# ---------------------------------------------------------------------------

def capability_revocation[S: Hashable](
    *,
    can_revoke: Callable[[S], bool],
    on_revoke: Callable[[S], S],
    can_ipc_timeout: Callable[[S], bool] | None = None,
    on_ipc_timeout: Callable[[S], S] | None = None,
    extra_assumptions: dict[str, Assumption] | None = None,
) -> EnvironmentSpec[S]:
    """EnvironmentSpec for seL4 capability revocation and optional IPC timeout.

    Behaviors added:
    - ``sel4:cap-revoke``: parent revokes a capability (guard: ``can_revoke``)
    - ``sel4:ipc-timeout``: blocking IPC call times out (optional)

    Pre-wired assumptions: ``HARDWARE_MEMORY_SAFETY`` (axiom), ``CAP_INTEGRITY`` (verified),
    ``IPC_LIVENESS`` (unverified).

    Note that ``CAP_INTEGRITY`` is ``status="verified"`` — it is excluded from
    ``OpenResult.unverified_assumptions``. ``HARDWARE_MEMORY_SAFETY`` (axiom) surfaces as a
    residual proof obligation because axioms are not "verified" in the model-checking sense.
    """
    behaviors: list[Action[S]] = [Action("sel4:cap-revoke", can_revoke, on_revoke)]
    if can_ipc_timeout is not None and on_ipc_timeout is not None:
        behaviors.append(Action("sel4:ipc-timeout", can_ipc_timeout, on_ipc_timeout))

    assumptions: dict[str, Assumption] = {
        HARDWARE_MEMORY_SAFETY.name: HARDWARE_MEMORY_SAFETY,
        CAP_INTEGRITY.name: CAP_INTEGRITY,
        IPC_LIVENESS.name: IPC_LIVENESS,
    }
    if extra_assumptions:
        assumptions.update(extra_assumptions)

    return EnvironmentSpec[S](name="sel4", behaviors=behaviors, assumptions=assumptions)


# ---------------------------------------------------------------------------
# AdversarialNode factories
# ---------------------------------------------------------------------------

def cap_revocation_notifier(*, msg: object = "sel4:cap-revoked") -> AdversarialNode:
    """AdversarialNode that sends a capability revocation notification to any task.

    Models the seL4 kernel notifying a task that one of its capabilities has been revoked
    by a parent (the kernel sends a fault IPC to the task's exception handler).
    """
    def guard(_src: str, _payload: object) -> bool:
        return True

    def _make_response(m: object) -> Callable[[Context, str, object], None]:
        def response(ctx: Context, src: str, _payload: object) -> None:
            ctx.send(src, m)
        return response

    return AdversarialNode(behaviors=[(guard, _make_response(msg))])
