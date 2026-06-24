# Byzantine service — wrong answers and wire corruption

**What this teaches:** a Byzantine node doesn't just fail silently — it actively sends wrong data. `AdversarialNode` models a service that lies; `NetworkModel(mutate=...)` models a network that corrupts payloads in transit. Both are seeded and deterministic.

## Byzantine faults

A crash-stop failure is clean — the node goes silent. A Byzantine failure is worse: the node remains active and sends plausible-looking but incorrect responses (Castro & Liskov, OSDI 1999). Real-world examples include corrupted disk sectors returning wrong checksums, load balancers that return stale cache entries, and misconfigured services that respond with data from the wrong tenant.

## Scenario 1: wrong-answer injection (AdversarialNode)

An `AdversarialNode` receives the `"query"` and always responds with `_BAD_VALUE = -1` instead of the expected `42`.

**Without validation** — the client accepts whatever it receives:

```
Without validation: SimFailure(kind=liveness, ...)   ← accepted wrong value
```

**With validation** — the client checks `payload == _EXPECTED_VALUE` and rejects anything else:

```
With validation: SimReport(ok=True, ...)   ← bad value rejected on all seeds
```

The validation guard is the boundary check: trust nothing arriving from an external service.

## Scenario 2: wire-level payload corruption (NetworkModel.mutate)

`NetworkModel(mutate=_corrupt_int_to_string)` intercepts every message and converts integer payloads to strings. The `HonestService` sends the right value; the network corrupts it before delivery. The `StrictClient` crashes when it receives a non-integer:

```python
def _corrupt_int_to_string(_src, _dst, payload):
    if isinstance(payload, int):
        return f"corrupted:{payload}"
    return payload
```

```
Clean network:      SimReport(ok=True)
Corrupted network:  SimFailure(kind=safety, ...)   ← client received non-int
```

The `mutate` hook models Byzantine behavior at the network layer — below the application protocol.

## Source

```python
--8<-- "examples/byzantine_service.py"
```

## Run it

```
python examples/byzantine_service.py
```

## See also

- [Reconciliation under loss](route_delivery.md) — honest nodes, lossy network; the focus is convergence not correctness of content.
- [K8s scheduler](k8s_scheduler.md) — platform-level adversarial behavior modeled via `EnvironmentSpec` in the model checker rather than simulation.
- [Open systems (conceptual guide)](../open-systems.md) — the theory connecting `AdversarialNode` to the model-checker `EnvironmentSpec`.
