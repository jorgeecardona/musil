"""Known-verdict corpus — classic models whose answers are established by theory, pinned by exact
reachable-state count AND semantic verdict. Any engine change that alters a count or a verdict fails CI.
This is the correctness oracle the BFS unification and any future native (Rust) port differ-test against.

Counts are computed by the current engine and pinned; the *verdicts* (mutual exclusion holds, the naive
philosophers deadlock, the light is live) are known independently of musil, so the corpus checks
correctness, not merely "unchanged"."""

from __future__ import annotations

from collections.abc import Callable, Hashable, Sequence
from dataclasses import dataclass
from fractions import Fraction

import pytest

from musil import (
    Action,
    Always,
    Atom,
    Eventually,
    Implies,
    Model,
    Next,
    Result,
    Until,
    assert_ok,
    assert_violates,
    check,
    check_liveness,
    check_liveness_of,
    check_ltl,
    check_of,
    eventually,
    expected_reward,
    expected_reward_mdp,
    explore,
    explore_por,
    never,
    path_to,
    por_sound,
    profile,
    reach_probability,
    reach_probability_mdp,
    recurs,
    responds,
    states_where,
    witness,
)

# --------------------------------------------------------------------------------------------------
# 1. Bounded counter — a derivable-count sanity anchor
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Counter:
    n: int


def counter_model(cap: int) -> Model[Counter]:
    return Model(
        init=Counter(0),
        actions=[
            Action("inc", enabled=lambda s: s.n < cap, apply=lambda s: Counter(s.n + 1)),
            Action("dec", enabled=lambda s: s.n > 0, apply=lambda s: Counter(s.n - 1)),
        ],
        invariants={"in-range": lambda s: 0 <= s.n <= cap},
        terminal=lambda s: False,
    )


# --------------------------------------------------------------------------------------------------
# 2. Peterson's mutual exclusion (2 processes) — safety holds, deadlock-free
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Peterson:
    flag: tuple[bool, bool]
    turn: int
    pc: tuple[str, str]  # each in {"idle", "want", "wait", "crit"}


def _with(seq: tuple[object, ...], i: int, v: object) -> tuple[object, ...]:
    return tuple(v if j == i else x for j, x in enumerate(seq))


def _peterson_actions(i: int) -> list[Action[Peterson]]:
    other = 1 - i

    def want(s: Peterson) -> Peterson:
        return Peterson(flag=tuple(_with(s.flag, i, True)), turn=s.turn, pc=tuple(_with(s.pc, i, "want")))  # type: ignore[arg-type]

    def set_turn(s: Peterson) -> Peterson:
        return Peterson(flag=s.flag, turn=other, pc=tuple(_with(s.pc, i, "wait")))  # type: ignore[arg-type]

    def enter(s: Peterson) -> Peterson:
        return Peterson(flag=s.flag, turn=s.turn, pc=tuple(_with(s.pc, i, "crit")))  # type: ignore[arg-type]

    def leave(s: Peterson) -> Peterson:
        return Peterson(flag=tuple(_with(s.flag, i, False)), turn=s.turn, pc=tuple(_with(s.pc, i, "idle")))  # type: ignore[arg-type]

    return [
        Action(f"want{i}", enabled=lambda s: s.pc[i] == "idle", apply=want),
        Action(f"turn{i}", enabled=lambda s: s.pc[i] == "want", apply=set_turn),
        Action(f"enter{i}", enabled=lambda s: s.pc[i] == "wait" and (not s.flag[other] or s.turn == i), apply=enter),
        Action(f"leave{i}", enabled=lambda s: s.pc[i] == "crit", apply=leave),
    ]


def peterson_model() -> Model[Peterson]:
    return Model(
        init=Peterson(flag=(False, False), turn=0, pc=("idle", "idle")),
        actions=_peterson_actions(0) + _peterson_actions(1),
        invariants={"mutual-exclusion": lambda s: not (s.pc[0] == "crit" and s.pc[1] == "crit")},
        terminal=lambda s: False,
    )


# --------------------------------------------------------------------------------------------------
# 3. Two philosophers, naive (pick left then right) — the classic deadlock
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Dining:
    fork: tuple[int | None, int | None]  # owner of fork 0, fork 1 (None = free)
    pc: tuple[str, str]  # each in {"thinking", "has_left", "eating"}


def _dining_actions(i: int) -> list[Action[Dining]]:
    left, right = i, (i + 1) % 2

    def pick_left(s: Dining) -> Dining:
        return Dining(fork=tuple(_with(s.fork, left, i)), pc=tuple(_with(s.pc, i, "has_left")))  # type: ignore[arg-type]

    def pick_right(s: Dining) -> Dining:
        return Dining(fork=tuple(_with(s.fork, right, i)), pc=tuple(_with(s.pc, i, "eating")))  # type: ignore[arg-type]

    def release(s: Dining) -> Dining:
        freed = _with(_with(s.fork, left, None), right, None)
        return Dining(fork=tuple(freed), pc=tuple(_with(s.pc, i, "thinking")))  # type: ignore[arg-type]

    return [
        Action(f"pick_left{i}", enabled=lambda s: s.pc[i] == "thinking" and s.fork[left] is None, apply=pick_left),
        Action(f"pick_right{i}", enabled=lambda s: s.pc[i] == "has_left" and s.fork[right] is None, apply=pick_right),
        Action(f"release{i}", enabled=lambda s: s.pc[i] == "eating", apply=release),
    ]


def dining_naive_model() -> Model[Dining]:
    return Model(
        init=Dining(fork=(None, None), pc=("thinking", "thinking")),
        actions=_dining_actions(0) + _dining_actions(1),
        terminal=lambda s: False,  # nothing is a legit sink, so the both-hold-left state is a deadlock
    )


# --------------------------------------------------------------------------------------------------
# 4. Traffic light — liveness (eventually green) and safety (known colors)
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Light:
    color: str


def light_model() -> Model[Light]:
    return Model(
        init=Light("red"),
        actions=[
            Action("go", enabled=lambda s: s.color == "red", apply=lambda s: Light("green")),
            Action("slow", enabled=lambda s: s.color == "green", apply=lambda s: Light("yellow")),
            Action("stop", enabled=lambda s: s.color == "yellow", apply=lambda s: Light("red")),
        ],
        invariants={"known-color": lambda s: s.color in {"red", "green", "yellow"}},
        terminal=lambda s: False,
    )


# --------------------------------------------------------------------------------------------------
# Pinned corpus: (reachable-state count, semantic verdict)
# --------------------------------------------------------------------------------------------------


def test_counter_derivable_count_and_safe():
    m = counter_model(cap=5)
    assert len(explore(m).states) == 6  # n in 0..5, derivable
    assert check(m).ok


def test_peterson_mutual_exclusion_holds_and_no_deadlock():
    m = peterson_model()
    assert len(explore(m).states) == 20
    r = check(m)
    assert r.ok  # mutual exclusion holds AND no deadlock — the theory-known verdict
    # non-vacuous: both processes genuinely contend for the critical section
    assert any(s.pc[0] == "crit" for s in explore(m).states)


def test_naive_two_philosophers_deadlock():
    m = dining_naive_model()
    assert len(explore(m).states) == 6
    r = check(m)
    assert not r.ok
    assert r.kind == "deadlock"  # both grab left, neither can grab right — the classic deadlock


def test_traffic_light_safe_and_live():
    m = light_model()
    assert len(explore(m).states) == 3  # red, green, yellow
    assert check(m).ok  # known-color holds, no deadlock (it cycles)
    assert check_liveness(m, goal=lambda s: s.color == "green").ok  # eventually green on every run


def test_traffic_light_ltl_via_check_ltl():
    m = light_model()
    green = Atom[Light]("green", lambda s: s.color == "green")
    red = Atom[Light]("red", lambda s: s.color == "red")
    yellow = Atom[Light]("yellow", lambda s: s.color == "yellow")
    known = Atom[Light]("known", lambda s: s.color in {"red", "green", "yellow"})
    assert check_ltl(m, Always(known)).ok  # G known-color (safety)
    assert check_ltl(m, Eventually(green)).ok  # F green
    assert check_ltl(m, Always(Eventually(red))).ok  # []<> red (recurrence)
    assert check_ltl(m, Always(Implies(yellow, Eventually(red)))).ok  # yellow ~> red (response)
    # general-engine (irreducible) forms: X green holds (red->green); X red fails; known U green holds
    assert check_ltl(m, Next(green)).ok
    assert not check_ltl(m, Next(red)).ok
    assert check_ltl(m, Until(known, green)).ok


def test_patterns_agree_with_check_ltl():
    # The liveness patterns are sugar over check_ltl: each must give the SAME verdict as the LTL formula it
    # builds, on a property that holds AND one that does not. Pinned so the two temporal surfaces can never
    # silently diverge.
    m = light_model()

    def is_green(s: Light) -> bool:
        return s.color == "green"

    def is_red(s: Light) -> bool:
        return s.color == "red"

    def is_yellow(s: Light) -> bool:
        return s.color == "yellow"

    def is_blue(s: Light) -> bool:
        return s.color == "blue"  # never reached

    # existence: <>green holds, <>blue does not; the pattern and the LTL formula must agree on both.
    ev_green = eventually(m, is_green)
    assert ev_green.ok and ev_green.ok == check_ltl(m, Eventually(Atom[Light]("P", is_green))).ok
    ev_blue = eventually(m, is_blue)
    assert not ev_blue.ok and ev_blue.ok == check_ltl(m, Eventually(Atom[Light]("P", is_blue))).ok

    # recurrence []<>red holds; []<>blue does not.
    rec_red = recurs(m, is_red)
    assert rec_red.ok and rec_red.ok == check_ltl(m, Always(Eventually(Atom[Light]("P", is_red)))).ok
    rec_blue = recurs(m, is_blue)
    assert not rec_blue.ok and rec_blue.ok == check_ltl(m, Always(Eventually(Atom[Light]("P", is_blue)))).ok

    # response yellow ~> red holds.
    resp = responds(m, is_yellow, is_red, name="response")
    resp_formula = Always(Implies(Atom[Light]("trigger", is_yellow), Eventually(Atom[Light]("response", is_red))))
    assert resp.ok and resp.ok == check_ltl(m, resp_formula).ok


def test_check_ltl_general_engine_returns_a_valid_counterexample_lasso():
    # A formula OUTSIDE the reducible fragment (Next) that fails goes to the general Büchi engine, which
    # must return a real counterexample run: X(red) is false from red (the next state is green). Pin that
    # the returned lasso is a genuine run of the model — starts at the initial state, every step a real edge.
    m = light_model()
    r = check_ltl(m, Next(Atom[Light]("red", lambda s: s.color == "red")))
    assert isinstance(r, Result)
    assert not r.ok and r.kind == "ltl"
    assert r.trace, "the general engine must return a counterexample trace, not an empty one"
    assert r.trace[0].state == m.init  # the run starts at the model's initial state
    edges = {s: {nxt for _, nxt in e} for s, e in explore(m).edges.items()}
    for prev, step in zip(r.trace, r.trace[1:], strict=False):
        assert step.state in edges[prev.state]  # every consecutive pair is a genuine model transition
    # the lasso marks where the infinite cycle begins, and the cycle closes back to that entry state.
    assert r.loop is not None and 0 <= r.loop < len(r.trace)
    assert r.trace[-1].state == r.trace[r.loop].state  # the suffix loops back to the marked entry
    assert "--- loops forever ---" in str(r)  # and the rendering shows it


def test_por_trivial_ample_matches_explore_and_is_sound():
    m = peterson_model()
    # the trivial ample (fire everything) reduces nothing: same reachable set as explore, and sound.
    assert len(explore_por(m, ample=lambda state, enabled: enabled).states) == 20
    assert por_sound(m, lambda state, enabled: enabled)


# --------------------------------------------------------------------------------------------------
# 5. Gambler's ruin (fair symmetric random walk) — exact reachability probability, known closed form
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Walk:
    pos: int


def walk_model(start: int, n: int) -> Model[Walk]:
    return Model(
        init=Walk(start),
        actions=[
            Action("up", enabled=lambda s: 0 < s.pos < n, apply=lambda s: Walk(s.pos + 1)),
            Action("down", enabled=lambda s: 0 < s.pos < n, apply=lambda s: Walk(s.pos - 1)),
        ],
        terminal=lambda s: s.pos in (0, n),
    )


def test_fair_walk_reach_probability_is_i_over_n():
    # Theory (gambler's ruin, fair game): P(reach N before 0 | start i) = i/N, exactly. Pinned as a
    # known-verdict oracle for the exact DTMC solver, independent of musil's implementation.
    n = 5
    for i in range(n + 1):
        assert reach_probability(walk_model(i, n), lambda s: s.pos == n) == Fraction(i, n)


# --------------------------------------------------------------------------------------------------
# 6. Two-gamble MDP — the max scheduler picks the better coin; exact value known by hand
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Gamble:
    tag: str  # "start", "win" (target), "dead"


def two_gamble_model() -> Model[Gamble]:
    win, dead = Gamble("win"), Gamble("dead")
    at_start: Callable[[Gamble], bool] = lambda s: s.tag == "start"  # noqa: E731
    return Model(
        init=Gamble("start"),
        actions=[
            Action("A_win", enabled=at_start, apply=lambda s: win),
            Action("A_lose", enabled=at_start, apply=lambda s: dead),
            Action("B_win", enabled=at_start, apply=lambda s: win),
            Action("B_lose", enabled=at_start, apply=lambda s: dead),
        ],
        terminal=lambda s: s.tag in ("win", "dead"),
    )


def test_mdp_max_and_min_reachability_pick_opposite_coins():
    # Move A is a fair coin (1/2); move B, weighted 2:1, wins with prob 2/3. The max scheduler picks B
    # (2/3), the min scheduler picks A (1/2) — both hand-computable and independent of musil, so this
    # guards the exact MDP policy-iteration solver in both directions.
    m = two_gamble_model()

    def by_letter(_s: Gamble, enabled: tuple[Action[Gamble], ...]) -> list[Sequence[Action[Gamble]]]:
        groups: dict[str, list[Action[Gamble]]] = {}
        for a in enabled:
            groups.setdefault(a.name[0], []).append(a)
        return list(groups.values())

    def biased(name: str, _s: Gamble) -> int:
        return 2 if name == "B_win" else 1

    def is_win(s: Gamble) -> bool:
        return s.tag == "win"

    assert reach_probability_mdp(m, is_win, moves=by_letter, weight=biased) == Fraction(2, 3)
    assert reach_probability_mdp(m, is_win, moves=by_letter, weight=biased, optimize="min") == Fraction(1, 2)


# --------------------------------------------------------------------------------------------------
# 7. Step-bounded reachability — geometric law P(reach within k) = 1 - (1/2)^k, known exactly
# --------------------------------------------------------------------------------------------------


def coin_loop_model() -> Model[Gamble]:
    win = Gamble("win")
    at_start: Callable[[Gamble], bool] = lambda s: s.tag == "start"  # noqa: E731
    return Model(
        init=Gamble("start"),
        actions=[
            Action("win", enabled=at_start, apply=lambda s: win),
            Action("again", enabled=at_start, apply=lambda s: Gamble("start")),
        ],
        terminal=lambda s: s.tag == "win",
    )


def test_bounded_dtmc_reachability_is_geometric():
    # Each step wins with prob 1/2, else retries: P(reach the target within k steps) = 1 - (1/2)^k, exactly.
    # Known independent of musil; guards the finite-unrolling bounded solver.
    m = coin_loop_model()

    def is_win(s: Gamble) -> bool:
        return s.tag == "win"

    for k in range(5):
        assert reach_probability(m, is_win, steps=k) == 1 - Fraction(1, 2) ** k


# --------------------------------------------------------------------------------------------------
# 8. Expected reward — symmetric-walk absorption time E = i(N-i), known exactly
# --------------------------------------------------------------------------------------------------


def test_expected_absorption_time_is_i_times_n_minus_i():
    # Symmetric walk on 0..N, both ends absorbing: expected time to absorption from i is exactly i(N-i)
    # (classic gambler's-ruin duration). Reached almost surely, so the expectation is finite. Known
    # independent of musil; guards the exact expected-reward solver.
    n = 6

    def absorbed(s: Walk) -> bool:
        return s.pos in (0, n)

    for i in range(1, n):
        assert expected_reward(walk_model(i, n), absorbed) == Fraction(i * (n - i))


# --------------------------------------------------------------------------------------------------
# 9. MDP min expected reward (SSP) — retry-until-success minimal expected attempts = 1/p, known exactly
# --------------------------------------------------------------------------------------------------


def test_ssp_min_expected_attempts_is_one_over_p():
    # start: "retry" wins with prob 1/2 else loops back (expected attempts 1/p = 2), or a sure but slower
    # 4-step "detour". The min scheduler retries -> exactly 2, a known geometric mean independent of musil.
    start, win = Gamble("start"), Gamble("win")
    chain = [Gamble(f"d{i}") for i in range(4)]
    at_start: Callable[[Gamble], bool] = lambda s: s.tag == "start"  # noqa: E731
    actions = [
        Action("R_win", enabled=at_start, apply=lambda s: win),
        Action("R_loop", enabled=at_start, apply=lambda s: start),
        Action("detour", enabled=at_start, apply=lambda s: chain[0]),
    ]
    for i, node in enumerate(chain):
        nxt = chain[i + 1] if i + 1 < len(chain) else win
        actions.append(Action(f"step{i}", enabled=lambda s, node=node: s.tag == node.tag, apply=lambda s, nxt=nxt: nxt))

    m: Model[Gamble] = Model(init=start, actions=actions, terminal=lambda s: s.tag == "win")

    def moves(_s: Gamble, enabled: tuple[Action[Gamble], ...]) -> list[Sequence[Action[Gamble]]]:
        retry = [a for a in enabled if a.name.startswith("R_")]
        others: list[Sequence[Action[Gamble]]] = [[a] for a in enabled if not a.name.startswith("R_")]
        return ([retry] if retry else []) + others

    def is_win(s: Gamble) -> bool:
        return s.tag == "win"

    assert expected_reward_mdp(m, is_win, moves=moves) == Fraction(2)


def test_profile_explores_the_same_reachable_set():
    # profile keeps its own instrumented loop (it times enabled/apply/canonicalize separately, which the
    # shared _successors kernel bundles). This pins its full-sweep reachable count to the corpus so it can
    # never silently drift from check/explore.
    assert profile(counter_model(5)).states_explored == len(explore(counter_model(5)).states) == 6
    assert profile(peterson_model()).states_explored == len(explore(peterson_model()).states) == 20
    assert profile(dining_naive_model()).states_explored == len(explore(dining_naive_model()).states) == 6
    assert profile(light_model()).states_explored == len(explore(light_model()).states) == 3


# --------------------------------------------------------------------------------------------------
# 10. Strong-fairness sub-SCC — a fair counterexample confined to a sub-SCC must be found (issue #22)
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class FairS:
    at: str  # "s0", "s1", "s2", "done"


def subscc_fairness_model() -> Model[FairS]:
    # Maximal SCC {s0, s1, s2}; the strongly-fair action "g" is enabled only at s2 (-> done). The s0<->s1
    # sub-cycle never enables g, so looping there forever is FAIR and never reaches done: <>done is VIOLATED
    # under strong fairness. Judging fairness on the maximal SCC alone misses this (the fixed bug).
    return Model(
        init=FairS("s0"),
        actions=[
            Action("step", enabled=lambda s: s.at == "s0", apply=lambda s: FairS("s1")),
            Action("back", enabled=lambda s: s.at == "s1", apply=lambda s: FairS("s0")),
            Action("advance", enabled=lambda s: s.at == "s1", apply=lambda s: FairS("s2")),
            Action("g", enabled=lambda s: s.at == "s2", apply=lambda s: FairS("done")),
            Action("retreat", enabled=lambda s: s.at == "s2", apply=lambda s: FairS("s1")),
        ],
        terminal=lambda s: s.at == "done",
    )


def forced_fairness_model() -> Model[FairS]:
    # The only ¬done cycle is {s0, s1}, and the strongly-fair action "g" is enabled in BOTH its states
    # (-> done). Strong fairness then FORCES g, so every fair run reaches done: <>done HOLDS. Guards the
    # other direction -- the fix must still rule out a cycle whose fair action really is forced.
    return Model(
        init=FairS("s0"),
        actions=[
            Action("a", enabled=lambda s: s.at == "s0", apply=lambda s: FairS("s1")),
            Action("b", enabled=lambda s: s.at == "s1", apply=lambda s: FairS("s0")),
            Action("g", enabled=lambda s: s.at in ("s0", "s1"), apply=lambda s: FairS("done")),
        ],
        terminal=lambda s: s.at == "done",
    )


def test_strong_fairness_finds_a_subscc_counterexample():
    done: Callable[[FairS], bool] = lambda s: s.at == "done"  # noqa: E731
    # The s0<->s1 loop never enables g, so it is a genuine fair counterexample under strong fairness of g.
    r = check_liveness(subscc_fairness_model(), goal=done, goal_name="done", fair_strong=("g",))
    assert not r.ok and r.kind == "fair-cycle"
    assert {step.state.at for step in r.cycle} == {"s0", "s1"}  # confined to the sub-SCC that avoids g

    # Other direction: when g is enabled throughout the only cycle, strong fairness forces it -> <>done holds.
    assert check_liveness(forced_fairness_model(), goal=done, goal_name="done", fair_strong=("g",)).ok


# --------------------------------------------------------------------------------------------------
# 11. Witness API — the positive counterpart to a counterexample: a path to a GOOD state (#30)
# --------------------------------------------------------------------------------------------------


def test_witness_and_path_to_return_shortest_paths():
    g = explore(counter_model(5))  # states n in 0..5

    # witness: shortest path to SOME state satisfying the predicate. n==5 is 5 incs from 0.
    w = witness(g, lambda s: s.n == 5)
    assert w is not None
    assert w[0].state == Counter(0) and w[-1].state == Counter(5)
    assert len(w) == 6  # <init> at n=0, then five inc steps

    # path_to: shortest path to a SPECIFIC state.
    p = path_to(g, Counter(3))
    assert p is not None and tuple(step.state.n for step in p) == (0, 1, 2, 3)

    # states_where: the reachable states matching a predicate.
    assert {s.n for s in states_where(g, lambda s: s.n >= 4)} == {4, 5}

    # unreachable target / unsatisfiable predicate -> None.
    assert path_to(g, Counter(9)) is None
    assert witness(g, lambda s: s.n == 9) is None


# --------------------------------------------------------------------------------------------------
# 12. Negative-side assertion helpers — action_names / witness / assert_violates / truncated (#32)
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Acct:
    bal: int


def overdraw_model() -> Model[Acct]:
    # "overdraw" is always enabled and drives the balance negative in one step, so the non-neg invariant
    # breaks at bal=-1, one step from init: a deterministic, known counterexample.
    return Model(
        init=Acct(0),
        actions=[Action("overdraw", enabled=lambda s: True, apply=lambda s: Acct(s.bal - 1))],
        invariants={"non-neg": lambda s: s.bal >= 0},
        terminal=lambda s: False,
    )


def test_negative_assertion_helpers_pin_the_counterexample():
    r = check(overdraw_model())
    assert r.action_names == ("overdraw",)  # trace action names, the synthetic <init> step excluded
    assert r.witness == Acct(-1)  # the offending state (last of the trace)
    # assert_violates matches the full shape...
    assert_violates(r, kind="invariant", invariant="non-neg", via=["overdraw"], where=lambda s: s.bal < 0)
    # ...and raises when any constraint is wrong, or when the check actually passed.
    with pytest.raises(AssertionError):
        assert_violates(r, kind="deadlock")
    with pytest.raises(AssertionError):
        assert_violates(check(counter_model(5)))


def test_assert_ok_rejects_a_truncated_green_by_default():
    # An unbounded upward counter truncates at the cap: ok=True but inconclusive (the space wasn't swept).
    m = Model(
        init=Acct(0),
        actions=[Action("up", enabled=lambda s: True, apply=lambda s: Acct(s.bal + 1))],
        terminal=lambda s: False,
    )
    r = check(m, max_states=5)
    assert r.ok and r.truncated
    with pytest.raises(AssertionError):
        assert_ok(r)  # a truncated green proves nothing -> fail by default
    assert_ok(r, truncated="ok")  # explicit opt-in accepts an inconclusive pass


# --------------------------------------------------------------------------------------------------
# 13. Graph-first check_of must agree with check on every corpus model (differential guard, #31)
# --------------------------------------------------------------------------------------------------


def _assert_check_of_agrees[S: Hashable](m: Model[S]) -> None:
    r_check = check(m)
    r_of = check_of(explore(m), m)
    assert r_of.ok == r_check.ok
    assert r_of.kind == r_check.kind
    assert r_of.invariant == r_check.invariant
    assert r_of.trace == r_check.trace  # identical shortest counterexample, not merely same verdict


def test_check_of_agrees_with_check_over_a_prebuilt_graph():
    # check_of runs the safety verdict over an already-explored graph (no re-exploration). It must give the
    # SAME verdict AND the same shortest trace as check on every model in this corpus -- the guard against
    # the two code paths silently diverging.
    _assert_check_of_agrees(counter_model(5))
    _assert_check_of_agrees(peterson_model())
    _assert_check_of_agrees(dining_naive_model())
    _assert_check_of_agrees(light_model())
    _assert_check_of_agrees(overdraw_model())


# --------------------------------------------------------------------------------------------------
# 14. Graph-first check_liveness_of must agree with check_liveness (#31)
# --------------------------------------------------------------------------------------------------


def test_check_liveness_of_agrees_with_check_liveness():
    # check_liveness now delegates to check_liveness_of(explore(model), ...). Pin that the graph-first entry
    # gives the identical LivenessResult on a passing case AND a strong-fairness sub-SCC counterexample.
    def green(s: Light) -> bool:
        return s.color == "green"

    m = light_model()
    a = check_liveness(m, goal=green, goal_name="green")
    b = check_liveness_of(explore(m), goal=green, goal_name="green")
    assert (a.ok, a.kind, a.stem, a.cycle) == (b.ok, b.kind, b.stem, b.cycle)

    def done(s: FairS) -> bool:
        return s.at == "done"

    fm = subscc_fairness_model()
    a2 = check_liveness(fm, goal=done, goal_name="done", fair_strong=("g",))
    b2 = check_liveness_of(explore(fm), goal=done, goal_name="done", fair_strong=("g",))
    assert (a2.ok, a2.kind, a2.stem, a2.cycle) == (b2.ok, b2.kind, b2.stem, b2.cycle)
    assert not b2.ok  # sanity: it really is the fair counterexample


# --------------------------------------------------------------------------------------------------
# 15. Edge (transition) invariants — a property about the STEP, not the state (#25)
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Doc:
    stage: str  # "draft", "reviewed", "published"


def _published_only_after_review(before: Doc, _action: str, after: Doc) -> bool:
    return after.stage != "published" or before.stage == "reviewed"


def doc_model(edge: bool) -> Model[Doc]:
    # "published" is legitimately reachable (draft -> reviewed -> publish), but "force_publish" reaches it
    # illegally from draft, skipping review. The bad EDGE, not the bad state, is the violation.
    return Model(
        init=Doc("draft"),
        actions=[
            Action("review", enabled=lambda s: s.stage == "draft", apply=lambda s: Doc("reviewed")),
            Action("publish", enabled=lambda s: s.stage == "reviewed", apply=lambda s: Doc("published")),
            Action("force_publish", enabled=lambda s: s.stage == "draft", apply=lambda s: Doc("published")),
        ],
        edge_invariants={"published-only-after-review": _published_only_after_review} if edge else {},
        terminal=lambda s: s.stage == "published",
    )


def test_edge_invariant_catches_an_illegal_transition_a_state_check_misses():
    # State-only check is GREEN -- "published" is a legitimately reachable state.
    assert check(doc_model(edge=False)).ok

    # With the edge invariant, the illegal force_publish edge is caught, with the offending step in the trace.
    r = check(doc_model(edge=True))
    assert not r.ok
    assert r.kind == "edge-invariant"
    assert r.invariant == "published-only-after-review"
    assert r.action_names == ("force_publish",)
    assert r.witness == Doc("published")

    # check_of gives the identical edge-invariant verdict AND trace over a pre-built graph.
    r_of = check_of(explore(doc_model(edge=True)), doc_model(edge=True))
    assert (r_of.kind, r_of.invariant, r_of.trace) == (r.kind, r.invariant, r.trace)


def test_never_forbids_a_transition_directly():
    m = Model(
        init=Doc("draft"),
        actions=[
            Action("review", enabled=lambda s: s.stage == "draft", apply=lambda s: Doc("reviewed")),
            Action("publish", enabled=lambda s: s.stage == "reviewed", apply=lambda s: Doc("published")),
            Action("force_publish", enabled=lambda s: s.stage == "draft", apply=lambda s: Doc("published")),
        ],
        edge_invariants={"no-force-publish": never("force_publish")},
        terminal=lambda s: s.stage == "published",
    )
    r = check(m)
    assert r.kind == "edge-invariant" and r.action_names == ("force_publish",)
