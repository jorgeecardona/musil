"""State-space metrics — how big and how branchy a design's reachable behaviour is.

Inspired by "expression cardinality" (given a semantic intent, how many valid programs express it?):
for a *design* we don't have to guess a per-language score — musil already enumerates the whole
reachable state graph, so we can MEASURE the exact analog on the behaviour itself.

- ``state_space_metrics`` reports the size and branching of a model: reachable states, transitions,
  terminals, and per-state branching (distinct successors, self-loops excluded — an ``Idle`` action
  shouldn't read as a choice). Lower branching + a tighter state space = a more deterministic, more
  reviewable design. A blow-up is the MDD "design for modelability" smell: behaviour you can't reason
  about, to reshape *before* it hides a bug.
- ``solution_cardinality`` answers the cardinality question directly: how many reachable states
  satisfy a goal. Exact over the explored space, not a guessed 1-10.

Deliberately NOT a single fabricated "determinism score" — these are honest counts on your model.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable, Iterable, Mapping
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from musil.cache import (
    DEFAULT_CACHE_DIR,
    _digest,  # pyright: ignore[reportPrivateUsage]
    _load_or_store,  # pyright: ignore[reportPrivateUsage]
)
from musil.core import Graph, Invariant, Model, actions_source, explore

__all__ = [
    "Coverage",
    "InvariantCoverage",
    "PortfolioCoverage",
    "StateSpaceMetrics",
    "assert_covers",
    "coverage",
    "coverage_cached",
    "coverage_of",
    "invariant_coverage",
    "invariant_coverage_of",
    "metrics_of",
    "portfolio_coverage",
    "solution_cardinality",
    "state_space_metrics",
]


@dataclass(frozen=True, slots=True)
class StateSpaceMetrics:
    """The shape of a model's reachable behaviour. ``mean_branching``/``max_branching`` count DISTINCT
    successor states (excluding self-loops) — the real fan-out of choices; ``terminal_states`` have
    none. ``truncated`` means the ``max_states`` cap was hit, so the counts are lower bounds."""

    reachable_states: int
    transitions: int
    initial_states: int
    terminal_states: int
    max_branching: int
    mean_branching: float
    truncated: bool

    def __str__(self) -> str:
        cap = " (TRUNCATED — counts are lower bounds)" if self.truncated else ""
        return (
            f"{self.reachable_states} states, {self.transitions} transitions{cap}\n"
            f"  branching: mean {self.mean_branching:.2f}, max {self.max_branching} "
            f"(distinct successors, self-loops excluded)\n"
            f"  {self.initial_states} initial, {self.terminal_states} terminal"
        )


def metrics_of[S: Hashable](graph: Graph[S]) -> StateSpaceMetrics:
    """Compute metrics from an already-explored :class:`~musil.core.Graph`."""
    states = graph.states
    n = len(states)
    successors = [
        {nxt for _, nxt in graph.edges.get(s, ()) if nxt != s} for s in states
    ]
    degrees = [len(succ) for succ in successors]
    return StateSpaceMetrics(
        reachable_states=n,
        transitions=sum(len(graph.edges.get(s, ())) for s in states),
        initial_states=len(graph.initial),
        terminal_states=sum(1 for d in degrees if d == 0),
        max_branching=max(degrees, default=0),
        mean_branching=(sum(degrees) / n if n else 0.0),
        truncated=graph.truncated,
    )


def state_space_metrics[S: Hashable](
    model: Model[S], *, max_states: int = 1_000_000
) -> StateSpaceMetrics:
    """Explore ``model`` and report the size + branching of its reachable behaviour (see
    :class:`StateSpaceMetrics`)."""
    return metrics_of(explore(model, max_states=max_states))


@dataclass(frozen=True, slots=True)
class Coverage:
    """Which of a model's actions actually did anything over the reachable space.

    A green ``check`` says no invariant broke; it does not say the behaviour you wrote was ever
    explored. These are the three ways that goes wrong, as *sets of names* rather than accusations —
    each has legitimate cases, and only the author knows which.

    - ``dead_actions``: enabled in NO reachable state. The sharpest of the three: an action that can
      never fire is a guard bug or dead code, and it silently removes an interleaving the author
      believed was covered. A run that never explored it still reports OK.
    - ``always_enabled_actions``: enabled in EVERY reachable state, i.e. the guard never guards.
      Often intentional — an ``Idle`` step, or an adversarial ``crash`` that may happen at any
      moment — so this is a smell to confirm, not a defect. Empty whenever the model has a terminal
      state, since nothing is enabled there.
    - ``stutter_only_actions``: enabled somewhere, but every firing lands back on the state it came
      from. The action fires and changes nothing.

    ``truncated`` carries over from the graph and changes what ``dead_actions`` means: under a cap,
    an action is only *not yet seen enabled*, which is a weaker claim than dead.

    The names are action names for a static-``actions`` model, or the ``key`` buckets ("kinds") for an
    ``actions_fn`` model (see ``coverage``/``coverage_of``)."""

    dead_actions: tuple[str, ...]
    always_enabled_actions: tuple[str, ...]
    stutter_only_actions: tuple[str, ...]
    actions_total: int
    truncated: bool

    @property
    def ok(self) -> bool:
        """True when nothing was flagged. Not a verdict on the model — only the author can say
        whether an always-enabled action is intended — but a useful gate in a test suite."""
        return not (self.dead_actions or self.always_enabled_actions or self.stutter_only_actions)

    def __str__(self) -> str:
        if self.truncated:
            head = "COVERAGE INCONCLUSIVE (truncated at max_states — 'dead' only means not yet seen enabled)"
        elif self.ok:
            head = f"COVERAGE — all {self.actions_total} actions fire and move"
        else:
            head = f"COVERAGE — of {self.actions_total} actions:"
        lines = [head]
        for label, names in (
            ("never enabled (dead)", self.dead_actions),
            ("always enabled (the guard never guards)", self.always_enabled_actions),
            ("only ever self-loops (fires, changes nothing)", self.stutter_only_actions),
        ):
            if names:
                lines.append(f"  {label}: {', '.join(names)}")
        return "\n".join(lines)


def coverage_of[S: Hashable](
    graph: Graph[S], model: Model[S], *, key: Callable[[str], str] | None = None
) -> Coverage:
    """Compute coverage from an already-explored :class:`~musil.core.Graph`.

    Reads the graph's recorded edges only — ``enabled`` is never called again, so this is O(edges) and,
    unlike re-applying the actions, it stays correct under symmetry reduction (the edges are already
    canonical). The report is over an "action universe": for a STATIC ``model.actions`` it is the declared
    action names (in order); for an ``actions_fn`` model it is every action NAME the enumerator offers
    across the reachable states (so a never-enabled kind is still counted, since it left no edge).

    ``key`` maps an action NAME to a bucket ("kind") and coverage is reported over the buckets. This is how
    ``actions_fn`` models report usefully: their per-state actions typically carry per-state unique names
    (e.g. ``add_filter{field='status'}``), so ``key=lambda name: name.split('{')[0]`` collapses them to
    the kind. Without a key, names are used as-is (right for static models and for ``actions_fn`` models
    whose action names are already a fixed set)."""
    kind: Callable[[str], str] = key if key is not None else (lambda name: name)
    if model.actions_fn is None:
        universe = list(dict.fromkeys(kind(a.name) for a in model.actions))  # declared order, deduped by kind
    else:
        source = actions_source(model)
        universe = sorted({kind(a.name) for s in graph.states for a in source(s)})  # offered kinds, incl. never-enabled
    fired: set[str] = set()
    moved: set[str] = set()
    enabled_in: dict[str, int] = dict.fromkeys(universe, 0)
    for s in graph.states:
        seen_here: set[str] = set()
        for action, nxt in graph.edges.get(s, ()):
            bucket = kind(action)
            fired.add(bucket)
            if nxt != s:
                moved.add(bucket)
            seen_here.add(bucket)
        for bucket in seen_here:
            enabled_in[bucket] = enabled_in.get(bucket, 0) + 1
    total_states = len(graph.states)
    return Coverage(
        dead_actions=tuple(k for k in universe if k not in fired),
        always_enabled_actions=tuple(
            k for k in universe if total_states and enabled_in.get(k, 0) == total_states
        ),
        stutter_only_actions=tuple(k for k in universe if k in fired and k not in moved),
        actions_total=len(universe),
        truncated=graph.truncated,
    )


def coverage[S: Hashable](
    model: Model[S], *, key: Callable[[str], str] | None = None, max_states: int = 1_000_000
) -> Coverage:
    """Explore ``model`` and report which of its actions ever fired, always could, or never moved
    (see :class:`Coverage`). ``key`` buckets action names into kinds — pass it for an ``actions_fn`` model
    whose per-state action names are not a fixed set (see ``coverage_of``).

    Deliberately separate from ``check`` rather than a field on ``Result``: ``check`` early-exits at
    the first violation, so the graph it saw is partial and a coverage answer computed from it would
    be wrong in the direction that matters — actions look dead because the sweep stopped, not because
    they cannot fire. Run this on the whole space, next to ``check``, not inside it."""
    return coverage_of(explore(model, max_states=max_states), model, key=key)


def coverage_cached[S: Hashable](
    model: Model[S],
    *,
    version: str,
    cache_dir: str | Path = DEFAULT_CACHE_DIR,
    max_states: int = 1_000_000,
    key: Callable[[str], str] | None = None,
) -> Coverage:
    """Like ``coverage``, but return a cached :class:`Coverage` when the model (identified by ``version`` plus
    its readable structure) and options are unchanged; otherwise run ``coverage``, store it, and return it —
    the content-addressed parallel of ``check_cached`` (issue #41). A coverage regression test
    (``assert not coverage_cached(model, version="1").dead_actions``) then skips the whole re-exploration on
    every CI run and pre-push hook once the model is unchanged.

    ``version`` is REQUIRED and carries the same obligation as in ``check_cached``: bump it whenever an
    action/invariant/guard BODY changes, since those callables are opaque to the structural digest (a
    structural edit — a renamed/added action, changed options — invalidates the cache on its own). Unlike
    ``check``, ``coverage`` needs the whole reachable space, so the cached artifact is the final ``Coverage``
    computed once. Writing is best-effort. The entry is stored under a name distinct from ``check_cached``'s,
    so a verdict cache and a coverage cache for the same model never collide."""
    digest = _digest(model, version=version, max_states=max_states, canonicalize=None, key=key)
    path = Path(cache_dir) / f"{digest}.coverage.pkl"
    return _load_or_store(path, lambda: coverage(model, key=key, max_states=max_states))


def solution_cardinality[S: Hashable](
    model: Model[S], predicate: Callable[[S], bool], *, max_states: int = 1_000_000
) -> int:
    """How many REACHABLE states satisfy ``predicate`` — the design's "expression cardinality" for
    that intent, counted exactly over the explored state space (not a guessed score). A large number
    for a goal that *should* be reached one way is a redundancy/ambiguity smell; for a recovery goal,
    more satisfying states can mean more resilience. Interpret in context."""
    return sum(1 for s in explore(model, max_states=max_states).states if predicate(s))


def _violates[S: Hashable](inv: Invariant[S], state: S) -> bool:
    """Whether ``inv`` is violated at ``state``, with ``check``'s semantics: a string return is a
    violation (carrying a reason), and otherwise falsy (``False``/``None``/``""``) is a violation.
    (Written without the ``not inv(state)`` footgun that would read a truthy reason string as 'holds'.)"""
    verdict = inv(state)
    return isinstance(verdict, str) or not verdict


@dataclass(frozen=True, slots=True)
class InvariantCoverage:
    """Which invariants are doing work — the dual of :class:`Coverage` (which is about actions).

    A green ``check`` says every invariant held; it does not say any invariant was ever *at risk*. Over
    the reachable space, each invariant is one of:

    - ``load_bearing``: some GUARDED-OFF action, applied to a reachable state, WOULD violate it — a guard
      is what keeps it true. This is the spec constraining real behaviour: the near-miss the checker
      exists to certify. ``threats`` maps each such invariant to the actions that would break it.
    - ``candidate_vacuous``: NO guarded-off action ever produces a state that violates it, and no
      reachable state does either — it holds by CONSTRUCTION, so a passing check tells you nothing about
      it. A signal, not an accusation: an invariant true by construction can be intentional documentation.

    This is the practical form of the vacuity idea that ``coverage`` deliberately dropped as too naive:
    reachability + near-misses over the graph, rather than reasoning about opaque invariant antecedents.
    It analyses the STATIC ``model.actions`` (it needs guarded-off actions to apply; an ``actions_fn`` that
    only offers enabled actions exposes none, so those invariants read as candidate-vacuous by default).
    Actions whose ``apply`` is partial — it relies on the guard and raises without it — are skipped for
    the action that raised, since a state that cannot exist cannot witness a violation. ``truncated``
    carries over from the graph: under a cap, ``candidate_vacuous`` only means 'not yet threatened'."""

    load_bearing: tuple[str, ...]
    candidate_vacuous: tuple[str, ...]
    threats: Mapping[str, tuple[str, ...]]
    invariants_total: int
    truncated: bool

    @property
    def ok(self) -> bool:
        """True when no invariant is candidate-vacuous. Not a verdict — an invariant true by construction
        may be intended — but a useful gate that every spec'd invariant is actually exercised."""
        return not self.candidate_vacuous

    def __str__(self) -> str:
        if self.truncated:
            head = "INVARIANT COVERAGE INCONCLUSIVE (truncated — 'candidate-vacuous' only means not yet threatened)"
        elif self.ok:
            head = f"INVARIANT COVERAGE — all {self.invariants_total} invariants are load-bearing"
        else:
            head = f"INVARIANT COVERAGE — of {self.invariants_total} invariants:"
        lines = [head]
        if self.candidate_vacuous:
            lines.append(f"  candidate-vacuous (nothing ever threatens them): {', '.join(self.candidate_vacuous)}")
        for name in self.load_bearing:
            lines.append(f"  {name}: guarded off by {', '.join(self.threats.get(name, ()))}")
        return "\n".join(lines)


def invariant_coverage_of[S: Hashable](graph: Graph[S], model: Model[S]) -> InvariantCoverage:
    """Compute :class:`InvariantCoverage` from an already-explored :class:`~musil.core.Graph`.

    For every reachable state and every STATIC ``model.actions`` that is GUARDED OFF there, it applies the
    action anyway and asks whether the result violates each invariant — a guarded-off action that would
    break an invariant is the guard doing its job, and marks that invariant load-bearing. An invariant no
    guarded-off action ever threatens (and that no reachable state itself violates) is candidate-vacuous.
    Enabled actions add no information here: their successors are already reachable, so in a passing model
    they never violate. Cost is O(states x actions x invariants), so run it as an audit, next to ``check``,
    not inside it."""
    inv_items = tuple(model.invariants.items())
    actions = tuple(model.actions)
    threats: dict[str, set[str]] = {name: set() for name, _ in inv_items}
    for s in graph.states:
        # A reachable state that itself violates an invariant makes it load-bearing (it is catching a
        # real bug); in a passing model this never fires, but it keeps the report honest on a failing one.
        for name, inv in inv_items:
            if _violates(inv, s):
                threats[name].add("<reachable>")
        for a in actions:
            if a.enabled(s):
                continue  # enabled ⇒ successor already reachable ⇒ no new information
            # A partial apply that relies on its guard can raise when applied guarded-off; a state that
            # cannot exist cannot witness a violation, so that action is skipped here.
            try:
                t = a.apply(s)
            except Exception:
                continue
            for name, inv in inv_items:
                if _violates(inv, t):
                    threats[name].add(a.name)
    load_bearing = tuple(name for name, _ in inv_items if threats[name])
    candidate_vacuous = tuple(name for name, _ in inv_items if not threats[name])
    return InvariantCoverage(
        load_bearing=load_bearing,
        candidate_vacuous=candidate_vacuous,
        threats={n: tuple(sorted(v)) for n, v in threats.items() if v},
        invariants_total=len(inv_items),
        truncated=graph.truncated,
    )


def invariant_coverage[S: Hashable](model: Model[S], *, max_states: int = 1_000_000) -> InvariantCoverage:
    """Explore ``model`` and report which of its invariants are load-bearing vs candidate-vacuous (see
    :class:`InvariantCoverage`). Like ``coverage``, kept separate from ``check`` and run over the whole
    space: ``check`` early-exits at the first violation, so its graph is partial and this would misjudge
    which invariants were ever threatened."""
    return invariant_coverage_of(explore(model, max_states=max_states), model)


@dataclass(frozen=True, slots=True)
class PortfolioCoverage:
    """How much of a declared transition table a whole PORTFOLIO of models exercises — read from state-field
    VALUES across edges (action naming is irrelevant), unioned across every model, and diffed against the
    ``declared`` table. The question a *suite* asks that per-model ``coverage`` cannot: "what does the whole
    portfolio prove about the real state machine?"

    - ``covered_edges`` / ``dead_edges`` — declared ``(src, dst)`` field-transitions some model exercises /
      that NO model in the portfolio exercises.
    - ``undeclared_edges`` — field-transitions a model DOES make that the table does not declare: the
      portfolio exercises a transition the external machine forbids (drift).
    - ``covered_values`` / ``dead_values`` — declared field values seen / never seen across the portfolio.

    ``ratio`` is covered declared edges over all declared edges (exact ``Fraction``) — the number a ratchet
    gate floors so coverage cannot rot as the denominator grows."""

    covered_edges: frozenset[tuple[str, str]]
    dead_edges: frozenset[tuple[str, str]]
    undeclared_edges: frozenset[tuple[str, str]]
    covered_values: frozenset[str]
    dead_values: frozenset[str]
    declared_edges: frozenset[tuple[str, str]]

    @property
    def ratio(self) -> Fraction:
        """Covered declared edges over all declared edges (1 if the table declares no edge)."""
        return Fraction(len(self.covered_edges), len(self.declared_edges)) if self.declared_edges else Fraction(1)


def portfolio_coverage[S: Hashable](
    portfolio: Iterable[Model[S] | Graph[S]],
    *,
    get: Callable[[S], str],
    declared: Mapping[str, Iterable[str]],
    max_states: int = 1_000_000,
) -> PortfolioCoverage:
    """Union the state-field transitions exercised across a ``portfolio`` of models (or pre-built graphs) and
    diff them against the ``declared`` transition table. ``get(state)`` reads the field whose values are the
    external machine's states; ``declared`` maps each value to the values it may move to. A Model is explored;
    a ``Graph`` is used as-is (share one ``explore`` across analyses). See :class:`PortfolioCoverage`."""
    declared_edges = frozenset((src, dst) for src, dsts in declared.items() for dst in dsts)
    declared_values = set(declared) | {dst for dsts in declared.values() for dst in dsts}
    exercised_edges: set[tuple[str, str]] = set()
    exercised_values: set[str] = set()
    for item in portfolio:
        graph = item if isinstance(item, Graph) else explore(item, max_states=max_states)
        for s in graph.states:
            src = get(s)
            exercised_values.add(src)
            for _name, t in graph.edges.get(s, ()):
                dst = get(t)
                exercised_values.add(dst)
                if src != dst:
                    exercised_edges.add((src, dst))
    return PortfolioCoverage(
        covered_edges=frozenset(exercised_edges & declared_edges),
        dead_edges=frozenset(declared_edges - exercised_edges),
        undeclared_edges=frozenset(exercised_edges - declared_edges),
        covered_values=frozenset(exercised_values & declared_values),
        dead_values=frozenset(declared_values - exercised_values),
        declared_edges=declared_edges,
    )


def _fmt_edges(edges: frozenset[tuple[str, str]]) -> str:
    return ", ".join(f"{a} -> {b}" for a, b in sorted(edges))


def assert_covers[S: Hashable](
    portfolio: Iterable[Model[S] | Graph[S]],
    declared: Mapping[str, Iterable[str]],
    *,
    get: Callable[[S], str],
    ratio: float = 0.0,
    blind_spots: Iterable[tuple[str, str]] = (),
    max_states: int = 1_000_000,
    message: str | None = None,
) -> PortfolioCoverage:
    """Ratchet gate on portfolio coverage — the fix for a numerator-only "N transitions covered" gate that
    lets real coverage rot as the denominator grows (a suite once fell 67% -> 56% while staying green).
    Computes :func:`portfolio_coverage` and asserts, in order:

    1. NO undeclared edge — the portfolio never exercises a transition the table forbids;
    2. the dead (uncovered) declared edges are EXACTLY the acknowledged ``blind_spots`` — a new dead edge is a
       regression that must be covered or explicitly acknowledged, and a blind spot that is now covered must
       be removed (so the named set can only SHRINK, never grow);
    3. the coverage ``ratio`` is at least the floor.

    Raises ``AssertionError`` on the first failure and returns the report on success. This is the doctrine
    (ratio floor + named blind-spot set) as one gate."""
    __tracebackhide__ = True
    report = portfolio_coverage(portfolio, get=get, declared=declared, max_states=max_states)
    blind = frozenset(blind_spots)

    def fail(reason: str) -> None:
        raise AssertionError(f"{message}\n{reason}" if message else reason)

    if report.undeclared_edges:
        fail(f"portfolio exercises transitions not in the declared table: {_fmt_edges(report.undeclared_edges)}")
    new_dead = report.dead_edges - blind
    if new_dead:
        fail(f"newly uncovered declared transitions (add coverage, or acknowledge in blind_spots): {_fmt_edges(new_dead)}")
    stale = blind - report.dead_edges
    if stale:
        fail(f"blind_spots lists transitions that are now covered — remove them (the set must shrink): {_fmt_edges(stale)}")
    if float(report.ratio) < ratio:
        fail(f"coverage ratio {report.ratio} ({float(report.ratio):.3f}) is below the floor {ratio}")
    return report
