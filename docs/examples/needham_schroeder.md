# Needham-Schroeder — a checker finding a famous attack

**What this teaches:** model checking's most cited success. The Needham-Schroeder public-key protocol (1978)
was believed to authenticate two parties for seventeen years. In 1995 Gavin Lowe found a man-in-the-middle
attack — using a model checker, as the violation of a safety invariant. Here `check` on the original protocol
returns a counterexample whose trace *is* Lowe's attack, and `check` on Lowe's fix is clean.

## The protocol

`{...}_P` is readable only by principal `P` (or by the intruder `I` for `{...}_I`); `Na`, `Nb` are fresh
nonces:

1. `A → B : {A, Na}_B` — A sends its name and a fresh nonce.
2. `B → A : {Na, Nb}_A` — B echoes `Na` and adds its own nonce.
3. `A → B : {Nb}_B` — A echoes `Nb`; both believe they share `{Na, Nb}`.

## The result

=== "Original — attack found"

    ```python
    result = check(needham_schroeder(fixed=False))
    assert not result.ok and result.invariant == "authentication"
    print(format_trace(result.trace, render=_render))
    ```

    ```
    Init:                   A=0/-  B=0/-  I knows {A, B, I, Ni}
    A initiates with I:     A=1/I  B=0/-  I knows {A, B, I, Na, Ni}
    B answers A (nonce Na): A=1/I  B=1/A  I knows {A, B, I, Na, Ni}
    A completes (learns Nb):A=2/I  B=1/A  I knows {A, B, I, Na, Nb, Ni}
    B completes:            A=2/I  B=2/A  I knows {A, B, I, Na, Nb, Ni}
    ```

    B ends believing it authenticated **A**, but A ran with **I** — and I learned B's secret `Nb`. That is
    Lowe's attack, as a safety-invariant counterexample.

=== "Lowe's fix — clean"

    ```python
    assert check(needham_schroeder(fixed=True)).ok
    ```

    Message 2 becomes `{Na, Nb, B}_A` — B names itself — and A checks the responder is who it intended to
    talk to. When I forwards `{Na, Nb, B}_A` to A, A sees responder `B` but intended `I`, rejects, and never
    returns `Nb`. The attack is gone, and `check` proves it over the whole reachable space.

## The invariant

```python
def _authentication(w: World) -> bool:
    # If B finished believing its peer was A, then A must actually have run with B.
    return not (w.b_step == 2 and w.b_partner == "A" and w.a_partner != "B")
```

## The intruder, without state explosion

!!! info "The intruder's knowledge *is* the network"

    A naive Dolev-Yao model — a persistent message pool the intruder may add any fabricated message to —
    explodes (a prototype truncated at 200,000 states). This model avoids that: there is no separate pool.
    `seen` holds only the ciphertexts honest agents actually put on the wire (at most three), and `known`
    holds the atoms the intruder has derived — identities are public, but a nonce enters `known` only by
    decrypting a message sent *to* the intruder. The intruder can deliver a message to an honest agent when
    it can replay a seen ciphertext (verbatim, even one it cannot read) or fabricate one from known atoms.
    The result is **46 reachable states**, and the search is exact.

??? note "Why this is sound (the invariant fails only via the real attack)"

    B completes believing A only on `{Nb}_B`, which needs the intruder to know `Nb`. `Nb` appears only inside
    `{Na, Nb}_A` (created when B answers a message naming sender A), which the intruder cannot read. The one
    way `Nb` reaches `known` is A returning `{Nb}_I` — which requires A to have initiated with `I` and
    accepted `{Na, Nb}_A`. So "B fooled about A" forces "A ran with I": exactly the attack. No honest-only or
    fabricate-only run reaches the violation. See `src/musil/NEEDHAM_SCHROEDER_NOTES.md` for the full argument
    and why unbounded sessions / a general term algebra are out of scope.

## Source

```python
--8<-- "examples/needham_schroeder.py"
```

## Run it

```
python examples/needham_schroeder.py
```

## See also

- [River crossing](river_crossing.md) — the same `check`-plus-counterexample machinery used to find a plan.
- [API reference](../api.md) — `check`, `format_trace`.
