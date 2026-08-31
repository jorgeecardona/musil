"""Needham-Schroeder + Lowe's attack — a checker finding a famous security bug.

The Needham-Schroeder public-key protocol (1978) was believed to authenticate two parties for seventeen
years. In 1995 Gavin Lowe found a man-in-the-middle attack — and found it with a model checker, as a
violation of a safety invariant. This example reproduces that: `check` on the original protocol returns a
counterexample whose trace *is* Lowe's attack, and `check` on Lowe's fix is clean.

The three messages (`{...}_P` is readable only by principal `P`, or by the intruder `I` for `{...}_I`):

1. `A -> B : {A, Na}_B`      A sends its name and a fresh nonce.
2. `B -> A : {Na, Nb}_A`     B echoes Na and adds its own nonce (Lowe's fix: `{Na, Nb, B}_A`).
3. `A -> B : {Nb}_B`         A echoes Nb; both believe they share {Na, Nb}.

**Lowe's attack.** `I` is a principal A may legitimately talk to. A starts a session with I; I replays A's
message to B as if from A; B answers "A" (a message I forwards but cannot read); A accepts it, and returns
Nb encrypted *for I* — leaking B's secret. I completes the run with B, who now believes it authenticated A.

**The model.** The intruder's knowledge *is* the network — there is no separate message pool to explode.
`seen` holds the ciphertexts honest agents put on the wire (at most three); `known` holds the atoms the
intruder has derived (identities are public; nonces only by decrypting messages sent to it). The intruder
can DELIVER a message to an honest agent if it can replay a seen ciphertext or fabricate one from known
atoms (`_producible`). This is a bounded, sound Dolev-Yao intruder: two honest principals, one intruder,
one session each — 46 reachable states. See `src/musil/NEEDHAM_SCHROEDER_NOTES.md` for the soundness
argument (the invariant fails only via the real attack) and why the general case is out of scope.

Run: python examples/needham_schroeder.py
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from musil import Action, Model, check, format_trace

IDS = ("A", "B", "I")
NONCES = ("Na", "Nb", "Ni")


@dataclass(frozen=True)
class Msg:
    tag: int  # 1, 2, or 3 — which protocol message
    payload: tuple[str, ...]  # its plaintext fields (identities and nonces)
    enc: str  # the principal whose public key encrypts it (only they, or I for enc="I", can read it)


@dataclass(frozen=True)
class World:
    seen: frozenset[Msg]  # every ciphertext the intruder has grabbed off the wire
    known: frozenset[str]  # atoms the intruder has derived (ids are public; nonces via decrypting enc="I")
    a_step: int = 0  # honest initiator A: 0 idle -> 1 sent msg1 -> 2 done
    a_partner: str = ""  # who A chose to talk to
    b_step: int = 0  # honest responder B: 0 idle -> 1 sent msg2 -> 2 done
    b_partner: str = ""  # who B BELIEVES it is talking to


def _producible(w: World, m: Msg) -> bool:
    """The Dolev-Yao intruder can deliver `m` to an honest agent if it can REPLAY a ciphertext it has seen
    (verbatim, even one it cannot read) or FABRICATE one whose every atom it knows (public keys let it
    encrypt for anyone)."""
    return m in w.seen or set(m.payload) <= w.known


def _send(w: World, m: Msg) -> World:
    """An honest agent puts `m` on the wire; the intruder grabs it, and decrypts it if it is encrypted for I."""
    known = w.known | set(m.payload) if m.enc == "I" else w.known
    return replace(w, seen=w.seen | {m}, known=known)


def _a_init(resp: str) -> Action[World]:
    def apply(w: World) -> World:
        return replace(_send(w, Msg(1, ("A", "Na"), resp)), a_step=1, a_partner=resp)

    return Action(f"A initiates with {resp}", enabled=lambda w: w.a_step == 0, apply=apply)


def _b_respond(sender: str, nonce: str, *, fixed: bool) -> Action[World]:
    def enabled(w: World) -> bool:
        return w.b_step == 0 and _producible(w, Msg(1, (sender, nonce), "B"))

    def apply(w: World) -> World:
        payload = (nonce, "Nb", "B") if fixed else (nonce, "Nb")  # Lowe's fix: B names itself
        return replace(_send(w, Msg(2, payload, sender)), b_step=1, b_partner=sender)

    return Action(f"B answers {sender} (nonce {nonce})", enabled=enabled, apply=apply)


def _a_complete(nb: str, resp: str, *, fixed: bool) -> Action[World]:
    def enabled(w: World) -> bool:
        if w.a_step != 1:
            return False
        if fixed:  # A checks the responder named itself, and it is who A intended to talk to
            return resp == w.a_partner and _producible(w, Msg(2, ("Na", nb, resp), "A"))
        return _producible(w, Msg(2, ("Na", nb), "A"))

    def apply(w: World) -> World:
        return replace(_send(w, Msg(3, (nb,), w.a_partner)), a_step=2)  # msg3 goes to whoever A thinks it is

    return Action(f"A completes (learns {nb})", enabled=enabled, apply=apply)


def _b_complete() -> Action[World]:
    return Action(
        "B completes",
        enabled=lambda w: w.b_step == 1 and _producible(w, Msg(3, ("Nb",), "B")),
        apply=lambda w: replace(w, b_step=2),
    )


def _authentication(w: World) -> bool:
    # If B finished a run believing its peer was A, then A must actually have run with B. Lowe's attack
    # reaches "B done, b_partner = A" while A ran with the intruder -- exactly this predicate's failure.
    return not (w.b_step == 2 and w.b_partner == "A" and w.a_partner != "B")


def needham_schroeder(*, fixed: bool) -> Model[World]:
    """The protocol as a model. `fixed=False` is the original (vulnerable); `fixed=True` is Lowe's fix
    (message 2 names the responder, and A checks it)."""
    actions: list[Action[World]] = [_a_init("B"), _a_init("I")]
    actions += [_b_respond(s, n, fixed=fixed) for s in IDS for n in NONCES]
    if fixed:
        actions += [_a_complete(nb, resp, fixed=True) for nb in NONCES for resp in IDS]
    else:
        actions += [_a_complete(nb, "A", fixed=False) for nb in NONCES]
    actions.append(_b_complete())
    return Model(
        init=World(seen=frozenset(), known=frozenset(IDS) | {"Ni"}),
        actions=actions,
        invariants={"authentication": _authentication},
        terminal=lambda w: True,  # a pure safety check: every state is a legitimate stop, deadlock is not the concern
    )


def _render(w: World) -> str:
    return f"A={w.a_step}/{w.a_partner or '-'}  B={w.b_step}/{w.b_partner or '-'}  I knows {{{', '.join(sorted(w.known))}}}"


if __name__ == "__main__":
    broken = check(needham_schroeder(fixed=False))
    assert not broken.ok and broken.invariant == "authentication"
    print("Original Needham-Schroeder — authentication FAILS. Lowe's man-in-the-middle attack:\n")
    print(format_trace(broken.trace, render=_render))
    end = broken.trace[-1].state
    print(f"\n  => B believes it authenticated A, but A ran with I, and I learned B's secret Nb: {'Nb' in end.known}.")

    fixed = check(needham_schroeder(fixed=True))
    assert fixed.ok
    print("\nLowe's fix (message 2 names the responder, B): authentication HOLDS — check is clean.")
