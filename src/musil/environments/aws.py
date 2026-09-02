"""AWS platform fault environments.

EnvironmentSpec factory and AdversarialNode for AWS API failures: throttling,
request timeouts, and regional failover.

Model checking::

    from dataclasses import replace
    from musil.environments.aws import aws_api_faults
    from musil.env import check_open
    env = aws_api_faults(
        can_throttle=lambda s: s.in_flight > 0,
        on_throttle=lambda s: replace(s, last_error="ThrottlingException"),
        can_timeout=lambda s: s.in_flight > 0,
        on_timeout=lambda s: replace(s, in_flight=0, last_error="RequestTimeout"),
    )
    result = check_open(model, env)

Simulation::

    from musil.environments.aws import throttling_service
    nodes = {"client": MyClient(), "s3": throttling_service()}
    report = simulate(lambda: nodes, seeds=range(100), ...)
"""

from __future__ import annotations

from collections.abc import Callable, Hashable

from musil.core import Action
from musil.env import Assumption, EnvironmentSpec
from musil.sim import AdversarialNode, Context

# ---------------------------------------------------------------------------
# Assumptions (cite AWS documentation and SLAs)
# ---------------------------------------------------------------------------

S3_EVENTUAL_DELIVERY = Assumption(
    name="aws:s3-eventual-delivery",
    description="S3 PUT responses are eventually delivered; strong consistency for new objects",
    status="unverified",
    source="AWS docs: Amazon S3 > Strong consistency",
)

REGION_AVAILABILITY = Assumption(
    name="aws:region-availability",
    description=(
        "At least one AWS region is available and reachable; "
        "multi-region failover eventually succeeds"
    ),
    status="unverified",
    source="AWS SLA: Compute Service Level Agreement",
)

THROTTLE_TRANSIENT = Assumption(
    name="aws:throttle-transient",
    description=(
        "Throttling events are transient; exponential backoff with jitter eventually succeeds "
        "(SDK default: up to 8 retries)"
    ),
    status="unverified",
    source="AWS docs: General reference > Error retries and exponential backoff",
)

IAM_CORRECTNESS = Assumption(
    name="aws:iam-correctness",
    description="IAM correctly enforces permissions; unauthorized requests are rejected",
    status="verified",
    source="AWS docs: IAM > Security in AWS Identity and Access Management",
)


# ---------------------------------------------------------------------------
# EnvironmentSpec factories
# ---------------------------------------------------------------------------

def aws_api_faults[S: Hashable](
    *,
    can_throttle: Callable[[S], bool],
    on_throttle: Callable[[S], S],
    can_timeout: Callable[[S], bool] | None = None,
    on_timeout: Callable[[S], S] | None = None,
    extra_assumptions: dict[str, Assumption] | None = None,
) -> EnvironmentSpec[S]:
    """EnvironmentSpec for AWS API failures: throttling and optional request timeouts.

    Behaviors added:
    - ``aws:throttle``: API call returns ThrottlingException (guard: ``can_throttle``)
    - ``aws:timeout``: API call times out and returns no response (optional)

    Pre-wired assumptions: ``S3_EVENTUAL_DELIVERY``, ``REGION_AVAILABILITY``,
    ``THROTTLE_TRANSIENT``. ``IAM_CORRECTNESS`` is ``status="verified"``.
    """
    behaviors: list[Action[S]] = [Action("aws:throttle", can_throttle, on_throttle)]
    if can_timeout is not None and on_timeout is not None:
        behaviors.append(Action("aws:timeout", can_timeout, on_timeout))

    assumptions: dict[str, Assumption] = {
        S3_EVENTUAL_DELIVERY.name: S3_EVENTUAL_DELIVERY,
        REGION_AVAILABILITY.name: REGION_AVAILABILITY,
        THROTTLE_TRANSIENT.name: THROTTLE_TRANSIENT,
    }
    if extra_assumptions:
        assumptions.update(extra_assumptions)

    return EnvironmentSpec[S](name="aws", behaviors=behaviors, assumptions=assumptions)


# ---------------------------------------------------------------------------
# AdversarialNode factories
# ---------------------------------------------------------------------------

def throttling_service(
    *,
    throttle_msg: object = {"error": "ThrottlingException", "code": 429},
) -> AdversarialNode:
    """AdversarialNode that responds to every request with a ThrottlingException.

    Models an AWS API endpoint under severe rate limiting.
    """
    def guard(_src: str, _payload: object) -> bool:
        return True

    def _make_response(m: object) -> Callable[[Context, str, object], None]:
        def response(ctx: Context, src: str, _payload: object) -> None:
            ctx.send(src, m)
        return response

    return AdversarialNode(behaviors=[(guard, _make_response(throttle_msg))])


def timeout_service() -> AdversarialNode:
    """AdversarialNode that silently drops all messages (request timeout).

    Models an AWS API endpoint that never responds — the caller must have its own
    timeout logic or the simulation hangs.
    """
    return AdversarialNode(behaviors=[])
