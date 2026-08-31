# Needham-Schroeder + Lowe's attack — designed, one bounding decision pending

The single most compelling demonstration of a model checker is Gavin Lowe's 1995 result: the
Needham-Schroeder public-key authentication protocol, believed correct for seventeen years, has a
man-in-the-middle attack that a checker finds automatically as a **safety-invariant counterexample**. This
note records the full model design, the soundness argument, and the one open decision (bounding the
Dolev-Yao intruder without state explosion) that keeps it a deliberate multi-tick build rather than a
one-tick example. It documents a downstream deferral per the repo's issue-handling rule.

## The protocol (three messages)

Public-key encryption `{...}_P` is readable only by principal `P` (or by the intruder `I` for `{...}_I`).
Nonces `Na`, `Nb` are fresh secrets. The **broken** original:

1. `A -> B : {A, Na}_B`      — A sends its identity and a fresh nonce, encrypted for B.
2. `B -> A : {Na, Nb}_A`     — B echoes Na and adds its own nonce Nb.
3. `A -> B : {Nb}_B`         — A echoes Nb. Both now believe they share `{Na, Nb}` with the other.

**Lowe's fix**: message 2 becomes `{Na, Nb, B}_A` — B names itself, so A can check the responder is who A
intended to talk to.

## Lowe's attack (the interleaving check must find)

`I` is a legitimate principal that A may initiate a session with. `I(A)` denotes I impersonating A to B:

1. `A -> I   : {A, Na}_I`    — A initiates with I. I decrypts (its own key): I learns `Na`.
2. `I(A) -> B : {A, Na}_B`   — I replays, re-encrypted for B, still naming A as initiator.
3. `B -> I(A) : {Na, Nb}_A`  — B answers "A". Encrypted for A, so I cannot read it — but forwards it.
4. `I -> A   : {Na, Nb}_A`   — A accepts it as I's reply (A is in a session with I), learns `Nb`.
5. `A -> I   : {Nb}_I`       — A returns Nb to I. I decrypts: **I now knows Nb**, B's secret.
6. `I(A) -> B : {Nb}_B`      — I completes the run as A.

End state: **B believes it completed a session with A, and holds `{Na, Nb}` as a secret shared with A — but
A never spoke to B, and I knows Nb.** Authentication and secrecy are both broken.

## State representation

```
@dataclass(frozen=True)
class World:
    net: frozenset[Msg]     # ciphertexts the intruder has observed / that are in flight
    known: frozenset[str]   # atoms the intruder has learned (ids + nonces)
    a_step: int             # honest initiator A: 0 idle, 1 sent msg1, 2 done
    a_partner: str          # who A chose to talk to ("" | "B" | "I")
    b_step: int             # honest responder B: 0 idle, 1 sent msg2, 2 done
    b_partner: str          # who B THINKS it is talking to ("" | "A" | ...)
```

`Msg(tag: int, payload: tuple[str, ...], enc: str)` — `tag` ∈ {1,2,3}, `enc` the principal whose key
encrypts it. Atoms are the finite set `{A, B, I, Na, Nb, Ni}`; one session each, so one nonce per principal.

## Honest actions (guards / effects)

- **A_init(resp)** for `resp ∈ {B, I}`: `a_step==0` → emit `Msg(1,(A,Na),enc=resp)`, `a_step=1`,
  `a_partner=resp`. A may initiate with the intruder — the entry point for the attack.
- **B_respond**: `b_step==0` and some `Msg(1,(sender,nonce),enc=B)` present → emit
  `Msg(2,(nonce,Nb),enc=sender)`, `b_step=1`, `b_partner=sender`.
- **A_complete**: `a_step==1` and some `Msg(2,(na,nb),enc=A)` with `na==Na` (**fixed protocol** also
  requires `payload[2]==a_partner`) → emit `Msg(3,(nb),enc=a_partner)`, `a_step=2`.
- **B_complete**: `b_step==1` and some `Msg(3,(nb),enc=B)` with `nb==Nb` → `b_step=2`.

The single line that carries the whole attack: **A_complete emits msg3 encrypted for `a_partner`**. If A ran
with I, msg3 is `{Nb}_I` and the intruder reads it — that is how `Nb` leaks.

## Intruder (Dolev-Yao) — and the open bounding decision

Two powers: **learn** (from any `enc==I` message, add its payload atoms to `known`) and **inject** (place on
the net a message whose atoms are all in `known`, encrypted for anyone; plus verbatim replay of any observed
ciphertext, needed to forward the unreadable `{Na,Nb}_A` in step 3→4).

**The measured problem.** A prototype with a *persistent* net and an inject action for **every** constructible
message truncated at **200,000 states** before B's actions were added: `known` grows and the intruder can add
any subset of dozens of message templates, so the net ranges over a powerset. This is precisely the
enumeration limitation (README Limitations, first bullet) — an unbounded intruder is not a bounded model.

**The bounding options (pick one, argue soundness before building):**

1. **Needs-driven (lazy) intruder** — the intruder fabricates a message only when a specific honest action is
   waiting to consume exactly that shape. Smallest state space; but "lazy" must be shown not to *hide* an
   attack the eager intruder would find. Sound for demonstrating *this* attack; weaker as a general
   "the fix has no attack" claim.
2. **Consume-on-read + capped in-flight** — honest agents remove the message they read; cap the net at a small
   number of concurrent in-flight messages. Keeps the powerset tiny. Needs the cap justified (Lowe's attack
   needs ≤ 2 in flight at once).
3. **Typed fabrication** — the intruder may only fabricate the three protocol message shapes with type-correct
   fields (an id where an id belongs, a nonce where a nonce belongs), not arbitrary atom soup. Cuts the
   template count sharply and is the standard "typed model" soundness assumption.

Recommended: **(3) typed fabrication + (2) consume-on-read**, which together are both sound for the
differential below and small. Prototype the state count first; build only if it stays well under `max_states`.

## The property and the differential (the validation)

Authentication invariant:

```
not (b_step == 2 and b_partner == "A" and a_partner != "B")
```

"If B completed a run believing it spoke with A, then A actually ran with B." Lowe's attack reaches
`b_step==2, b_partner=A, a_partner=I` — a violation, and `check`'s counterexample trace is the six-message
attack.

**Differential (this is the soundness gate for the whole model):**

- **Broken protocol** → `check` returns `not ok`; the trace is Lowe's attack.
- **Fixed protocol** (msg2 = `{Na,Nb,B}_A`, A checks `payload[2]==a_partner`) → `check` returns `ok`: when I
  forwards `{Na,Nb,B}_A` to A, A sees responder `B` but intended `I`, rejects, never sends msg3, never leaks
  `Nb`. The attack is gone.

The corpus pins both verdicts. Broken→attack / fixed→clean is what makes the model trustworthy: the same
harness that exhibits the bug confirms the textbook fix removes it.

## Soundness argument (why no spurious attack)

The invariant can be violated only via the real attack. `b_step==2, b_partner==A` requires B to have consumed
`{Na,Nb}_?`… no: B completes on `Msg(3,(Nb),enc=B)`, which requires the intruder (or A) to produce `{Nb}_B`,
which requires knowing `Nb`. `Nb` appears only inside `{Na,Nb}_A` (created when B answers a msg1 naming sender
A). The intruder cannot read `{...}_A`. The only way `Nb` reaches `known` is A emitting `{Nb}_I` in
A_complete — which requires `a_partner==I` (A initiated with I) and A having accepted `{Na,Nb}_A`. So
`b_partner==A` while `Nb` is known forces `a_partner==I`, i.e. the attack. No honest-only or fabricate-only
run reaches the violation. (Using its own nonce `Ni` as the initiator nonce gets the intruder a msg2
`{Ni,Nb}_A` it still cannot read, so that route is dead.)

## Scope / deferral

Bounded to two honest principals, one intruder, fixed nonces, one session each — enough for Lowe's attack.
A general Dolev-Yao term algebra, multiple concurrent sessions, and unbounded nonces are explicitly out of
scope: they are the infinite/huge-state regime that needs a symbolic method (this is the same boundary the
Limitations section draws, and why tools like ProVerif/Tamarin exist). This note is the plan; the build is a
separate guarded increment that must prototype the bounded state count and pass the broken/fixed differential
before it is committed.
