"""Build a model straight from a Petri net — ``{transition: (inputs, outputs)}`` — for the systems
that are *not* state machines. A state machine moves ONE token between states; a ledger event splits
a quantity: a roast consumes green and produces roasted AND loss from the same firing. That is a
Petri-net transition — a multiset of input places consumed, a multiset of output places produced — and
it is the shape `musil.fsm`'s `Table`/`Protocol` cannot express (they move a single token along one
edge). See #24.

Accessor-threading, the same idiom as :mod:`musil.fsm` and :func:`musil.fsm.movement_actions`: you keep
the marking (place -> token count) wherever it already lives in your own frozen state and supply two
lenses — ``tokens(state, place)`` reads a place's count, ``deposit(state, place, delta)`` returns a new
state with ``delta`` added there (``delta`` may be negative). The builder then owns the net LOGIC — the
enabledness guard (enough input tokens, and capacity headroom on the outputs), the atomic
consume-and-produce firing, and the terminal predicate — so none of it is hand-written with the
defensive comments it used to carry.

The payoff is :func:`place_invariants` / :func:`assert_place_invariant`: a conservation law is checked
against the net STRUCTURE (the weighted token change of every transition is zero), independently of
running the model. So "mass is conserved" stops being a predicate the same hand writes next to the
actions — the exact vacuity a hand-rolled ledger model documents — and becomes a theorem about the net
that holds in every reachable marking by construction."""

from __future__ import annotations

from collections.abc import Callable, Hashable, Mapping
from fractions import Fraction
from math import gcd

from musil.core import Action

__all__ = [
    "PetriNet",
    "assert_place_invariant",
    "petri_actions",
    "petri_enabled",
    "petri_terminal",
    "place_invariants",
]

# A Petri net: a transition name -> (inputs, outputs), where each of inputs/outputs maps a place to the
# number of tokens that firing consumes from / produces at that place. A place absent from a map is
# untouched (count 0). This is the ledger/accounting shape: `"roast": ({"green": 4}, {"roasted": 3,
# "loss": 1})` consumes 4 green and produces 3 roasted + 1 loss in one atomic firing.
type PetriNet = Mapping[str, tuple[Mapping[str, int], Mapping[str, int]]]

# A weighting of places — the P-invariant vector w in "w . marking is constant" (conservation).
type Weights = Mapping[str, int | Fraction]


def _delta(inputs: Mapping[str, int], outputs: Mapping[str, int]) -> dict[str, int]:
    """Net token change per place when a transition fires: outputs produced minus inputs consumed."""
    d: dict[str, int] = {}
    for place, k in inputs.items():
        d[place] = d.get(place, 0) - k
    for place, k in outputs.items():
        d[place] = d.get(place, 0) + k
    return d


def _fireable[S](
    inputs: Mapping[str, int],
    delta: Mapping[str, int],
    cap: Mapping[str, int],
    also: Callable[[S], bool] | None,
    tokens: Callable[[S, str], int],
    s: S,
) -> bool:
    """A transition is enabled when ``also`` holds, every input place has enough tokens to consume, and
    firing leaves no capacity-bounded place over its bound."""
    if also is not None and not also(s):
        return False
    if any(tokens(s, place) < k for place, k in inputs.items()):
        return False
    return all(tokens(s, place) + d <= cap[place] for place, d in delta.items() if place in cap)


def petri_actions[S: Hashable](
    net: PetriNet,
    *,
    tokens: Callable[[S, str], int],
    deposit: Callable[[S, str, int], S],
    capacity: Mapping[str, int] | None = None,
    also: Callable[[S], bool] | None = None,
    name: Callable[[str], str] = lambda transition: transition,
) -> list[Action[S]]:
    """One Action per Petri-net transition. ``tokens(state, place)`` reads a place's token count;
    ``deposit(state, place, delta)`` returns a new state with ``delta`` tokens added there (states are
    immutable); the builder applies the whole firing by depositing every place's net change, so a split
    event (one input, several outputs) lands atomically rather than as separate moves.

    A transition is enabled when every input place holds at least the tokens it consumes — so a firing
    can never drive a count negative without the author writing that guard. ``capacity`` caps named
    places: a firing is disabled if it would push any capped output place above its bound (a bounded
    buffer, a finite pool). ``also(state)`` is an extra guard ANDed in for a cross-cutting precondition
    the net does not encode (e.g. only post while the period is open)."""
    cap = dict(capacity or {})
    actions: list[Action[S]] = []
    for transition, (inputs, outputs) in net.items():
        delta = _delta(inputs, outputs)

        # default-arg capture pins inputs/delta per loop iteration (avoid late-binding);
        # tokens/deposit/cap/also are loop-invariant.
        def _enabled(
            s: S, inputs: Mapping[str, int] = inputs, delta: Mapping[str, int] = delta
        ) -> bool:
            return _fireable(inputs, delta, cap, also, tokens, s)

        def _apply(s: S, delta: Mapping[str, int] = delta) -> S:
            for place, d in delta.items():
                if d:
                    s = deposit(s, place, d)
            return s

        actions.append(Action(name=name(transition), enabled=_enabled, apply=_apply))
    return actions


def petri_enabled[S](
    net: PetriNet,
    s: S,
    *,
    tokens: Callable[[S, str], int],
    capacity: Mapping[str, int] | None = None,
    also: Callable[[S], bool] | None = None,
) -> frozenset[str]:
    """Every transition that can fire in marking ``s`` — what a guard checks against, the Petri analogue
    of :func:`musil.fsm.protocol_operations`."""
    cap = dict(capacity or {})
    fireable: set[str] = set()
    for transition, (inputs, outputs) in net.items():
        if _fireable(inputs, _delta(inputs, outputs), cap, also, tokens, s):
            fireable.add(transition)
    return frozenset(fireable)


def petri_terminal[S](
    net: PetriNet,
    *,
    tokens: Callable[[S, str], int],
    capacity: Mapping[str, int] | None = None,
    also: Callable[[S], bool] | None = None,
) -> Callable[[S], bool]:
    """A terminal predicate that is true exactly when no transition can fire — a drained or stuck net is
    a legitimate resting state, so it is not reported as a deadlock. Pass it as a model's ``terminal``."""
    return lambda s: not petri_enabled(net, s, tokens=tokens, capacity=capacity, also=also)


def _weighted_change(net: PetriNet, weights: Weights) -> dict[str, Fraction]:
    """For each transition, the weighted net token change ``sum_p w[p] * delta[p]`` — zero on every
    transition iff ``weights`` is a P-invariant (``w . marking`` is then constant everywhere)."""
    changes: dict[str, Fraction] = {}
    for transition, (inputs, outputs) in net.items():
        delta = _delta(inputs, outputs)
        changes[transition] = sum(
            (Fraction(weights.get(place, 0)) * d for place, d in delta.items()),
            start=Fraction(0),
        )
    return changes


def assert_place_invariant(net: PetriNet, weights: Weights, *, message: str | None = None) -> None:
    """Assert ``weights`` is a P-invariant of ``net`` — the conservation law ``sum_p w[p] * tokens[p]``
    is preserved by every transition, so it holds in every reachable marking BY CONSTRUCTION, with no
    state-space search and no runtime invariant written by the hand that wrote the net.

    This is the de-vacuifying check: a hand-written "mass is conserved" invariant only re-checks the
    author's own arithmetic, but this proves the net's structure conserves the weighted total — a typo
    in an output count (produce 2 where 1 belongs) is caught here, at the net, not by the model agreeing
    with itself. Raises ``AssertionError`` naming every transition whose weighted token change is nonzero
    (the amount by which it breaks conservation)."""
    __tracebackhide__ = True
    offenders = {t: c for t, c in _weighted_change(net, weights).items() if c != 0}
    if offenders:
        # Fraction has no "+" format spec, so sign the change by hand; show integers without a "/1".
        listing = ", ".join(
            f"{t} ({'+' if c > 0 else ''}{c.numerator if c.denominator == 1 else c})"
            for t, c in sorted(offenders.items())
        )
        head = f"weights are not a place-invariant; these transitions change the weighted total: {listing}"
        raise AssertionError(f"{message}\n{head}" if message else head)


def _normalize(vec: list[Fraction]) -> list[Fraction]:
    """Scale a rational vector to the smallest integer vector, with the first nonzero entry positive."""
    denom = 1
    for x in vec:
        denom = denom * x.denominator // gcd(denom, x.denominator)
    ints = [int(x * denom) for x in vec]
    g = 0
    for v in ints:
        g = gcd(g, abs(v))
    if g:
        ints = [v // g for v in ints]
    for v in ints:
        if v != 0:
            if v < 0:
                ints = [-x for x in ints]
            break
    return [Fraction(v) for v in ints]


def place_invariants(net: PetriNet) -> list[dict[str, Fraction]]:
    """Discover a basis of the net's P-invariants: every weighting ``w`` for which ``w . marking`` is
    conserved by every transition. Each returned dict maps a place to its weight (normalized to the
    smallest integers, first nonzero positive); the empty list means the net conserves no weighted total.

    "Automatic" is the point of #24: conservation is derived from the net's structure — the left
    null space of its incidence matrix — rather than stated by hand. The all-ones vector in the output
    means raw token count is conserved; a weighting (e.g. grams per token) means that weighted quantity
    is. Use the basis to confirm the law you expect is present, or pass a chosen ``w`` to
    :func:`assert_place_invariant`."""
    places = sorted({p for inputs, outputs in net.values() for p in (*inputs, *outputs)})
    # Incidence matrix, transposed: one row per transition, one column per place, entry = delta. A
    # P-invariant w satisfies M w = 0 (row . w == 0 for every transition), i.e. w is in its null space.
    matrix = [
        [Fraction(outputs.get(p, 0) - inputs.get(p, 0)) for p in places]
        for inputs, outputs in net.values()
    ]
    return [dict(zip(places, vec, strict=True)) for vec in _null_space(matrix, len(places))]


def _null_space(matrix: list[list[Fraction]], ncols: int) -> list[list[Fraction]]:
    """A basis of ``{x : matrix @ x == 0}`` over the rationals, via Gauss-Jordan to reduced row echelon
    form then one basis vector per free column."""
    m = [row[:] for row in matrix]
    nrows = len(m)
    pivots: list[int] = []
    r = 0
    for c in range(ncols):
        piv = next((i for i in range(r, nrows) if m[i][c] != 0), None)
        if piv is None:
            continue
        m[r], m[piv] = m[piv], m[r]
        pv = m[r][c]
        m[r] = [x / pv for x in m[r]]
        for i in range(nrows):
            if i != r and m[i][c] != 0:
                f = m[i][c]
                m[i] = [a - f * b for a, b in zip(m[i], m[r], strict=True)]
        pivots.append(c)
        r += 1
        if r == nrows:
            break
    pivot_cols = set(pivots)
    basis: list[list[Fraction]] = []
    for free in (c for c in range(ncols) if c not in pivot_cols):
        vec = [Fraction(0)] * ncols
        vec[free] = Fraction(1)
        for row_i, pc in enumerate(pivots):
            vec[pc] = -m[row_i][free]
        basis.append(_normalize(vec))
    return basis
