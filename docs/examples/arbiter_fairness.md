# Arbiter fairness — action-sequence liveness, three ways

**What this teaches:** some properties are about the *sequence of actions*, not any single state, and they
only hold under *fairness*. musil expresses "nobody who asks is starved" as a liveness property over actions,
checks it with and without fairness, and even computes its probability under a random scheduler — all exact.

## The model

Two clients share a resource through an arbiter. Each may REQUEST (start waiting) and be SERVED (stop
waiting); the arbiter may also STALL (do nothing). The state is just the two "waiting" flags; the actions are
`req_A`, `req_B`, `serve_A`, `serve_B`, `stall`.

## The property is about actions, not states

"Every `req_A` is eventually followed by a `serve_A`" cannot be written as a state predicate — "`req_A` was
just taken" is not a fact about *where* the system is. `with_last_action` puts the action that produced each
state INTO the state, so `action_taken('req_A')` becomes an ordinary atom and the response property is plain
LTL:

```python
aug = with_last_action(ARBITER)
req_a  = Atom("req_A",   action_taken("req_A"))
serve_a = Atom("serve_A", action_taken("serve_A"))
no_starvation = Always(Implies(req_a, Eventually(serve_a)))   # G(req_A -> F serve_A)
```

## Without fairness it fails

```python
check_ltl(aug, no_starvation).ok        # False
```

The arbiter can `stall` forever, or keep serving B, and never serve A — a real starvation counterexample.

## Fairness carries the liveness

```python
check_ltl(aug, no_starvation, fair=("serve_A",)).ok         # True
check_ltl(aug, no_starvation, fair_strong=("serve_A",)).ok  # True
```

Under weak *or* strong fairness on `serve_A`, the property holds: a fair arbiter cannot leave an enabled
`serve_A` untaken forever. This is the fair-ours / unfair-faults discipline — the arbiter's own `serve` is
fair, the `stall` fault is not — and fairness is exactly what turns "can be served" into "must be served".

## Under a random arbiter, the probability

Treat the arbiter as a uniform-random scheduler — a DTMC — and ask the probability that `serve_A` happens
infinitely often:

```python
probability_ltl(aug, Always(Eventually(serve_a)))   # 1  — P(GF serve_A)
```

It is 1: a random arbiter serves A infinitely often almost surely, even though the adversarial scheduler above
could avoid it. `probability_ltl` reads `GF p` as "absorbed into a bottom SCC that visits `p`", solved exactly.

## Source

```python
--8<-- "examples/arbiter_fairness.py"
```

## Run it

```
python examples/arbiter_fairness.py
```

## See also

- [API reference](../api.md) — `with_last_action`, `action_taken`, `check_ltl`, `probability_ltl`.
- [Availability](availability.md) — steady-state and until probabilities on a DTMC.
