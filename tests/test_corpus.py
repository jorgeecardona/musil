"""Known-verdict corpus — classic models whose answers are established by theory, pinned by exact
reachable-state count AND semantic verdict. Any engine change that alters a count or a verdict fails CI.
This is the correctness oracle the BFS unification and any future native (Rust) port differ-test against.

Counts are computed by the current engine and pinned; the *verdicts* (mutual exclusion holds, the naive
philosophers deadlock, the light is live) are known independently of musil, so the corpus checks
correctness, not merely "unchanged"."""

from __future__ import annotations

from collections.abc import Callable, Hashable, Sequence
from dataclasses import dataclass, replace
from fractions import Fraction
from typing import Literal

import pytest

from musil import (
    LTL,
    Action,
    Always,
    Atom,
    Eventually,
    Implies,
    LastAction,
    Model,
    Next,
    Result,
    Until,
    action_taken,
    assert_covers,
    assert_covers_table,
    assert_ok,
    assert_violates,
    check,
    check_all,
    check_liveness,
    check_liveness_of,
    check_ltl,
    check_of,
    crash_actions,
    eventually,
    expected_reward,
    expected_reward_mdp,
    explore,
    explore_por,
    fixed_points,
    fixed_points_of,
    long_run_probability,
    long_run_reward,
    never,
    partition_actions,
    path_to,
    por_sound,
    portfolio_coverage,
    probability_ltl,
    profile,
    reach_probability,
    reach_probability_mdp,
    reconciler,
    recurs,
    replicated_transition_actions,
    responds,
    states_where,
    with_last_action,
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


@dataclass(frozen=True)
class AB:
    tag: str  # "a" or "b"


def _ab_model() -> Model[AB]:
    # From "a" a scheduler may WORK (-> b) or IDLE (-> a, a fault); from "b", go back. The property A U B
    # ("stay in a until reaching b") is violated by the idle-forever run, but every run that treats WORK
    # fairly reaches b -- so fairness on WORK flips the verdict. WORK is the "ours" action, IDLE the fault.
    return Model(
        init=AB("a"),
        actions=[
            Action("work", enabled=lambda s: s.tag == "a", apply=lambda s: AB("b")),
            Action("idle", enabled=lambda s: s.tag == "a", apply=lambda s: AB("a")),
            Action("back", enabled=lambda s: s.tag == "b", apply=lambda s: AB("a")),
        ],
        terminal=lambda s: False,
    )


def test_check_ltl_fairness_on_the_general_engine_flips_an_until():
    # Fair LTL by reduction (with_last_action + fairness premise): a general-engine formula (Until) now
    # composes fairness instead of refusing. A U B FAILS unfair (idle forever), HOLDS under weak OR strong
    # fairness on WORK. Empty fairness is no constraint; an unknown fair name is rejected.
    m = _ab_model()
    a = Atom[AB]("A", lambda s: s.tag == "a")
    b = Atom[AB]("B", lambda s: s.tag == "b")
    assert not check_ltl(m, Until(a, b)).ok  # idle-forever run violates A U B
    assert not check_ltl(m, Until(a, b), fair=()).ok  # empty fairness is no constraint
    assert check_ltl(m, Until(a, b), fair=("work",)).ok  # weak fairness on work forces reaching b
    assert check_ltl(m, Until(a, b), fair_strong=("work",)).ok  # strong fairness likewise
    # the unfair counterexample maps back to ORIGINAL states (not LastAction), with a loop marker.
    cex = check_ltl(m, Until(a, b))
    assert isinstance(cex, Result) and not cex.ok and cex.loop is not None
    assert all(isinstance(step.state, AB) for step in cex.trace)
    with pytest.raises(ValueError, match="unknown fair action name"):
        check_ltl(m, Until(a, b), fair=("nope",))


@dataclass(frozen=True)
class RR:
    st: str  # "idle", "requested", "done"


def request_response_model() -> Model[RR]:
    return Model(
        init=RR("idle"),
        actions=[
            Action("request", enabled=lambda s: s.st == "idle", apply=lambda s: RR("requested")),
            Action("respond", enabled=lambda s: s.st == "requested", apply=lambda s: RR("done")),
            Action("timeout", enabled=lambda s: s.st == "requested", apply=lambda s: RR("idle")),
            Action("reset", enabled=lambda s: s.st == "done", apply=lambda s: RR("idle")),
        ],
        terminal=lambda s: False,
    )


def test_with_last_action_enables_action_sequence_ltl():
    # with_last_action puts the action that produced a state INTO the state, so an LTL property can name WHICH
    # action was taken -- something a state-only predicate cannot say. Two known verdicts on a request/respond
    # protocol, plus the safety verdict preserved by the augmentation.
    m = request_response_model()
    aug = with_last_action(m)
    req = Atom[LastAction[RR]]("req", action_taken("request"))
    resp = Atom[LastAction[RR]]("resp", action_taken("respond"))
    reset = Atom[LastAction[RR]]("reset", action_taken("reset"))

    # HOLDS: every respond is eventually followed by a reset (done's only action is reset).
    assert check_ltl(aug, Always(Implies(resp, Eventually(reset)))).ok
    # FAILS: a request need NOT be followed by a respond -- the timeout loop can starve it forever (no
    # fairness). This is exactly the property action-fairness would later rescue.
    assert not check_ltl(aug, Always(Implies(req, Eventually(resp)))).ok
    # The augmentation only refines states by the action that reached them, so the safety verdict is unchanged.
    assert check(aug).ok == check(m).ok


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


# --------------------------------------------------------------------------------------------------
# 9b. MDP max expected reward (stochastic LONGEST path) — finite only when every scheduler is proper
# --------------------------------------------------------------------------------------------------


def _tag(tag: str) -> Callable[[Gamble], bool]:
    return lambda s: s.tag == tag


def test_ssp_max_expected_steps_and_the_infinite_guard():
    # start chooses a FAST route (1 step to win) or a SLOW route (start -> mid -> win, 2 steps). Every
    # scheduler reaches win almost surely, so both the min and the max expected number of steps are finite:
    # min takes fast (= 1), max takes slow (= 2). A known verdict independent of musil.
    start, mid, win = Gamble("start"), Gamble("mid"), Gamble("win")
    actions = [
        Action("fast", enabled=_tag("start"), apply=lambda s: win),
        Action("slow", enabled=_tag("start"), apply=lambda s: mid),
        Action("m_step", enabled=_tag("mid"), apply=lambda s: win),
    ]
    m: Model[Gamble] = Model(init=start, actions=actions, terminal=lambda s: s.tag == "win")

    def singles(_s: Gamble, enabled: tuple[Action[Gamble], ...]) -> list[Sequence[Action[Gamble]]]:
        return [[a] for a in enabled]  # each action is its own move: the scheduler picks fast vs slow

    def is_win(s: Gamble) -> bool:
        return s.tag == "win"

    assert expected_reward_mdp(m, is_win, moves=singles, optimize="min") == Fraction(1)  # fast route
    assert expected_reward_mdp(m, is_win, moves=singles, optimize="max") == Fraction(2)  # slow route

    # Add a self-loop move at start: now a scheduler can STALL forever, so min reachability drops below 1 and
    # the MAX expected cost is infinite -- the degenerate cycle the guard exists for. The guard raises; min is
    # still 1 (a scheduler can still take fast).
    stall: Model[Gamble] = replace(
        m, actions=[*actions, Action("stall", enabled=_tag("start"), apply=lambda s: start)]
    )
    assert expected_reward_mdp(stall, is_win, moves=singles, optimize="min") == Fraction(1)
    with pytest.raises(ValueError, match="maximal expected cost is infinite"):
        expected_reward_mdp(stall, is_win, moves=singles, optimize="max")


# --------------------------------------------------------------------------------------------------
# 9c. DTMC long-run / steady-state — the exact fraction of time spent in a target set (known verdicts)
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Chain:
    tag: str


def test_long_run_two_cycle_is_one_half_even_though_periodic():
    # A <-> B, deterministic 2-cycle (period 2). P^n never converges, but the long-run TIME average does:
    # exactly half the time in each state. long_run_probability uses the stationary distribution (= Cesàro
    # average), so it returns 1/2 where a naive P^n limit would not exist.
    m: Model[Chain] = Model(
        init=Chain("A"),
        actions=[
            Action("toB", enabled=lambda s: s.tag == "A", apply=lambda s: Chain("B")),
            Action("toA", enabled=lambda s: s.tag == "B", apply=lambda s: Chain("A")),
        ],
    )
    assert long_run_probability(m, lambda s: s.tag == "A") == Fraction(1, 2)


def test_long_run_biased_chain_matches_the_closed_form():
    # A -> B always; from B, uniform over {toA, stay}, so P(B->A)=P(B->B)=1/2. Stationary of the two-state
    # chain with P(A->B)=1, P(B->A)=1/2 is pi(A)=b/(a+b)=(1/2)/(3/2)=1/3, pi(B)=2/3 -- a known closed form.
    m: Model[Chain] = Model(
        init=Chain("A"),
        actions=[
            Action("toB", enabled=lambda s: s.tag == "A", apply=lambda s: Chain("B")),
            Action("toA", enabled=lambda s: s.tag == "B", apply=lambda s: Chain("A")),
            Action("stay", enabled=lambda s: s.tag == "B", apply=lambda s: Chain("B")),
        ],
    )
    assert long_run_probability(m, lambda s: s.tag == "A") == Fraction(1, 3)
    assert long_run_probability(m, lambda s: s.tag == "B") == Fraction(2, 3)


def test_long_run_weights_absorption_across_two_bsccs():
    # A transient start splits 1/2 to an absorbing X (self-loop) and 1/2 to an absorbing Y (self-loop). The
    # long-run time in X is P(absorbed in X) * pi_X(X) = 1/2 * 1; the start itself is transient (measure 0).
    m: Model[Chain] = Model(
        init=Chain("I"),
        actions=[
            Action("left", enabled=lambda s: s.tag == "I", apply=lambda s: Chain("X")),
            Action("right", enabled=lambda s: s.tag == "I", apply=lambda s: Chain("Y")),
            Action("loopX", enabled=lambda s: s.tag == "X", apply=lambda s: Chain("X")),
            Action("loopY", enabled=lambda s: s.tag == "Y", apply=lambda s: Chain("Y")),
        ],
    )
    assert long_run_probability(m, lambda s: s.tag == "X") == Fraction(1, 2)
    assert long_run_probability(m, lambda s: s.tag == "I") == Fraction(0)  # transient: no long-run time
    assert long_run_probability(m, lambda s: s.tag in {"X", "Y"}) == Fraction(1)  # absorbed a.s.


# --------------------------------------------------------------------------------------------------
# 9d. Constrained (until) reachability — P(¬avoid U target), DTMC and MDP (avoid changes the verdict)
# --------------------------------------------------------------------------------------------------


def _is(tag: str) -> Callable[[Chain], bool]:
    return lambda s: s.tag == tag


def test_long_run_reward_average_rate():
    # long_run_reward is the steady-state AVERAGE reward per step. A <-> B periodic 2-cycle, pi = 1/2 each:
    # reward 3 on A, 1 on B -> long-run average = 3/2 + 1/2 = 2. The indicator reward recovers
    # long_run_probability (which now delegates to long_run_reward).
    cycle: Model[Chain] = Model(
        init=Chain("A"),
        actions=[
            Action("toB", enabled=_is("A"), apply=lambda s: Chain("B")),
            Action("toA", enabled=_is("B"), apply=lambda s: Chain("A")),
        ],
    )
    assert long_run_reward(cycle, lambda s: 3 if s.tag == "A" else 1) == Fraction(2)
    assert long_run_reward(cycle, lambda s: 1 if s.tag == "A" else 0) == Fraction(1, 2)  # = long_run_probability
    # a transient start splitting 1/2 into two absorbing sinks with rates 10 and 2 -> 1/2*10 + 1/2*2 = 6;
    # the reward may be NEGATIVE (a net cost rate): -1 on Y -> 1/2*0 + 1/2*(-1) = -1/2.
    split: Model[Chain] = Model(
        init=Chain("I"),
        actions=[
            Action("left", enabled=_is("I"), apply=lambda s: Chain("X")),
            Action("right", enabled=_is("I"), apply=lambda s: Chain("Y")),
            Action("loopX", enabled=_is("X"), apply=lambda s: Chain("X")),
            Action("loopY", enabled=_is("Y"), apply=lambda s: Chain("Y")),
        ],
    )
    assert long_run_reward(split, lambda s: {"X": 10, "Y": 2}.get(s.tag, 0)) == Fraction(6)
    assert long_run_reward(split, lambda s: -1 if s.tag == "Y" else 0) == Fraction(-1, 2)


def test_constrained_reachability_dtmc_avoid_changes_the_answer():
    # one -> up:win or down:zero (1/2 each); zero -> back:one (NOT absorbing); win absorbing target. Plain
    # reach(win) from one is 1 (it bounces until it goes up). Reaching win WITHOUT visiting zero requires
    # going up immediately: P(not zero U win) = 1/2.
    m: Model[Chain] = Model(
        init=Chain("one"),
        actions=[
            Action("up", enabled=_is("one"), apply=lambda s: Chain("win")),
            Action("down", enabled=_is("one"), apply=lambda s: Chain("zero")),
            Action("back", enabled=_is("zero"), apply=lambda s: Chain("one")),
        ],
        terminal=_is("win"),
    )
    assert reach_probability(m, _is("win")) == Fraction(1)
    assert reach_probability(m, _is("win"), avoid=_is("zero")) == Fraction(1, 2)


def test_constrained_reachability_mdp_min_max_with_avoid():
    # one has two moves: SURE (-> win) and RISK (1/2 win, 1/2 zero); zero -> back:one; win absorbing.
    m: Model[Chain] = Model(
        init=Chain("one"),
        actions=[
            Action("sure", enabled=_is("one"), apply=lambda s: Chain("win")),
            Action("risk_up", enabled=_is("one"), apply=lambda s: Chain("win")),
            Action("risk_down", enabled=_is("one"), apply=lambda s: Chain("zero")),
            Action("back", enabled=_is("zero"), apply=lambda s: Chain("one")),
        ],
        terminal=_is("win"),
    )

    def moves(_s: Chain, enabled: tuple[Action[Chain], ...]) -> list[Sequence[Action[Chain]]]:
        risk = [a for a in enabled if a.name.startswith("risk_")]
        others: list[Sequence[Action[Chain]]] = [[a] for a in enabled if not a.name.startswith("risk_")]
        return ([risk] if risk else []) + others

    # both moves reach win a.s. (zero loops back), so unconstrained min reach is 1.
    assert reach_probability_mdp(m, _is("win"), moves=moves, optimize="min") == Fraction(1)
    # with avoid=zero: RISK yields 1/2 (half the time it hits zero and fails), SURE yields 1. Min picks RISK
    # (= 1/2), max picks SURE (= 1) -- avoid discriminates the two schedulers.
    assert reach_probability_mdp(m, _is("win"), moves=moves, optimize="min", avoid=_is("zero")) == Fraction(1, 2)
    assert reach_probability_mdp(m, _is("win"), moves=moves, optimize="max", avoid=_is("zero")) == Fraction(1)


def test_negative_weight_is_rejected_across_probabilistic_functions():
    # Weights are relative likelihoods normalised into a probability distribution; a negative one is never
    # meaningful and would otherwise silently produce a bogus 'probability' (a spurious 0 here). Every entry
    # point rejects it rather than returning a wrong quantitative answer.
    m: Model[Chain] = Model(
        init=Chain("a"),
        actions=[
            Action("win", enabled=_is("a"), apply=lambda s: Chain("win")),
            Action("loop", enabled=_is("a"), apply=lambda s: Chain("a")),
        ],
        terminal=_is("win"),
    )

    def bad(name: str, _s: Chain) -> int:
        return -1 if name == "loop" else 1

    def one_move(_s: Chain, enabled: tuple[Action[Chain], ...]) -> list[Sequence[Action[Chain]]]:
        return [list(enabled)]

    win = _is("win")
    calls = (
        lambda: reach_probability(m, win, weight=bad),
        lambda: expected_reward(m, win, weight=bad),
        lambda: reach_probability_mdp(m, win, moves=one_move, weight=bad),
        lambda: expected_reward_mdp(m, win, moves=one_move, weight=bad),
        lambda: long_run_probability(m, win, weight=bad),
    )
    for call in calls:
        with pytest.raises(ValueError, match="weight must be non-negative"):
            call()


def test_probability_ltl_reducible_fragment_known_verdicts():
    # I -> A or Z (1/2 each); A<->B is a 2-cycle with the target p={A}; Z absorbs. Two bottom SCCs: {A,B}
    # (meets p, so GF p holds if absorbed there) and {Z} (no p). This separates GF from FG.
    m: Model[Chain] = Model(
        init=Chain("I"),
        actions=[
            Action("toA", enabled=_is("I"), apply=lambda s: Chain("A")),
            Action("toZ", enabled=_is("I"), apply=lambda s: Chain("Z")),
            Action("AtoB", enabled=_is("A"), apply=lambda s: Chain("B")),
            Action("BtoA", enabled=_is("B"), apply=lambda s: Chain("A")),
            Action("loopZ", enabled=_is("Z"), apply=lambda s: Chain("Z")),
        ],
        terminal=lambda s: False,
    )
    at_a = Atom[Chain]("A", _is("A"))
    not_z = Atom[Chain]("notZ", lambda s: s.tag != "Z")
    assert probability_ltl(m, Eventually(at_a)) == Fraction(1, 2)  # P(F A): reach A
    assert probability_ltl(m, Always(Eventually(at_a))) == Fraction(1, 2)  # P(GF A): absorbed into {A,B}
    assert probability_ltl(m, Eventually(Always(at_a))) == Fraction(0)  # P(FG A): no BSCC inside {A}
    assert probability_ltl(m, Always(not_z)) == Fraction(1, 2)  # P(G !Z) = 1 - P(F Z)
    with pytest.raises(NotImplementedError):  # general PLTL (Until) needs a deterministic automaton
        probability_ltl(m, Until(at_a, not_z))


def test_probability_ltl_mdp_full_fragment_max_and_min():
    # The whole F/G/GF/FG fragment for an MDP, max AND min. I -> A (win) or Z (dead); A<->B is a cycle;
    # Z absorbs. A scheduler that CHOOSES at I can steer into the {A,B} cycle or into Z, so max/min differ;
    # a single probabilistic move (a coin) cannot steer, so max == min == the 1/2 reach probability.
    m: Model[Chain] = Model(
        init=Chain("I"),
        actions=[
            Action("win", enabled=_is("I"), apply=lambda s: Chain("A")),
            Action("dead", enabled=_is("I"), apply=lambda s: Chain("Z")),
            Action("AtoB", enabled=_is("A"), apply=lambda s: Chain("B")),
            Action("BtoA", enabled=_is("B"), apply=lambda s: Chain("A")),
            Action("loopZ", enabled=_is("Z"), apply=lambda s: Chain("Z")),
        ],
        terminal=lambda s: False,
    )
    at_a = Atom[Chain]("A", _is("A"))
    in_cyc = Atom[Chain]("cyc", lambda s: s.tag in {"A", "B"})
    not_z = Atom[Chain]("notZ", lambda s: s.tag != "Z")

    def choose(_s: Chain, en: tuple[Action[Chain], ...]) -> list[Sequence[Action[Chain]]]:
        return [[a] for a in en]  # scheduler picks each action -> can steer

    def coin(_s: Chain, en: tuple[Action[Chain], ...]) -> list[Sequence[Action[Chain]]]:
        return [list(en)]  # all enabled in one move -> a probabilistic coin, no steering

    def p(
        formula: LTL[Chain],
        mv: Callable[[Chain, tuple[Action[Chain], ...]], list[Sequence[Action[Chain]]]],
        opt: Literal["max", "min"],
    ) -> Fraction:
        return probability_ltl(m, formula, moves=mv, optimize=opt)

    half = Fraction(1, 2)
    for formula in (Eventually(at_a), Always(Eventually(at_a)), Eventually(Always(in_cyc))):
        assert p(formula, choose, "max") == Fraction(1)  # steer into the cycle: F/GF A, FG cyc all reachable
        assert p(formula, choose, "min") == Fraction(0)  # steer into Z instead
        assert p(formula, coin, "max") == half  # the coin reaches the cycle with probability 1/2
        assert p(formula, coin, "min") == half
    # G !Z: the scheduler can avoid Z forever (max 1) or dive into it (min 0)
    assert p(Always(not_z), choose, "max") == Fraction(1)
    assert p(Always(not_z), choose, "min") == Fraction(0)


def test_bounded_expected_reward_dtmc_and_mdp():
    # DTMC: a fair-coin retry loop. Expected attempts until delivered OR k steps is 2*(1-(1/2)^k), a known
    # closed form; the unbounded value is 1/p = 2. A bounded horizon is always finite (no a.s. guard).
    m: Model[Chain] = Model(
        init=Chain("send"),
        actions=[
            Action("ack", enabled=_is("send"), apply=lambda s: Chain("done")),
            Action("drop", enabled=_is("send"), apply=lambda s: Chain("send")),
        ],
        terminal=_is("done"),
    )
    done = _is("done")
    assert expected_reward(m, done) == Fraction(2)  # unbounded 1/p
    for k in range(5):
        assert expected_reward(m, done, steps=k) == 2 * (1 - Fraction(1, 2) ** k)

    # MDP: staged (cheap, two hops) vs direct (dear, one hop) recovery. Bounded min/max expected cost.
    rec: Model[Chain] = Model(
        init=Chain("F"),
        actions=[
            Action("staged", enabled=_is("F"), apply=lambda s: Chain("R")),
            Action("direct", enabled=_is("F"), apply=lambda s: Chain("W")),
            Action("finish", enabled=_is("R"), apply=lambda s: Chain("W")),
        ],
        terminal=_is("W"),
    )
    at_w = _is("W")

    def singles(_s: Chain, en: tuple[Action[Chain], ...]) -> list[Sequence[Action[Chain]]]:
        return [[a] for a in en]

    def cost(name: str, _s: Chain) -> int:
        return {"staged": 1, "direct": 3, "finish": 1}[name]

    assert expected_reward_mdp(rec, at_w, moves=singles, cost=cost, optimize="min") == Fraction(2)  # unbounded
    assert expected_reward_mdp(rec, at_w, moves=singles, cost=cost, optimize="max") == Fraction(3)
    # bounded: at k=1 min fits one staged step (=1), max takes direct to the target (=3); k>=2 min reaches (=2)
    assert expected_reward_mdp(rec, at_w, moves=singles, cost=cost, optimize="min", steps=1) == Fraction(1)
    assert expected_reward_mdp(rec, at_w, moves=singles, cost=cost, optimize="max", steps=1) == Fraction(3)
    assert expected_reward_mdp(rec, at_w, moves=singles, cost=cost, optimize="min", steps=2) == Fraction(2)


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


def test_fixed_points_of_agrees_with_fixed_points():
    # fixed_points_of is the graph-first fixed_points (as check_of is to check): it must give the identical
    # per-initial settlement over a pre-built graph. Pinned on a confluent latch (two starts settle in two
    # different places, each deterministically) and a non-confluent race (one start settles two ways).
    latch: Model[Light] = Model(
        init=[Light("red"), Light("green")],
        actions=[
            Action("r-done", enabled=lambda s: s.color == "red", apply=lambda s: Light("red-done")),
            Action("g-done", enabled=lambda s: s.color == "green", apply=lambda s: Light("green-done")),
        ],
    )
    race: Model[Light] = Model(
        init=Light("red"),
        actions=[
            Action("a", enabled=lambda s: s.color == "red", apply=lambda s: Light("a-done")),
            Action("b", enabled=lambda s: s.color == "red", apply=lambda s: Light("b-done")),
        ],
    )
    for m in (latch, race):
        of = fixed_points_of(explore(m))
        assert of.by_init == fixed_points(m).by_init  # identical settlement
        assert of.confluent == fixed_points(m).confluent
    assert fixed_points_of(explore(latch)).confluent  # latch: each start settles in one place
    assert not fixed_points_of(explore(race)).confluent  # race: the order-dependent settlement


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


@dataclass(frozen=True)
class Ctr:
    v: int = 0


def _monotone(before: Ctr, _action: str, after: Ctr) -> bool:
    return after.v == before.v + 1


def _unbounded_ctr_edge() -> Model[Ctr]:
    return Model(
        init=Ctr(0),
        actions=[Action("up", enabled=lambda s: True, apply=lambda s: Ctr(s.v + 1))],
        edge_invariants={"monotone": _monotone},
    )


def _bounded_ctr_edge() -> Model[Ctr]:
    return Model(
        init=Ctr(0),
        actions=[Action("up", enabled=lambda s: s.v < 4, apply=lambda s: Ctr(s.v + 1))],
        edge_invariants={"monotone": _monotone},
        terminal=lambda s: s.v == 4,
    )


def test_edge_invariant_expansion_truncates_and_covers_the_same_space():
    # check/check_all now compute successors ONCE on the edge-invariant path and reuse them to expand
    # (_extend_frontier), instead of running _successors twice. Pin the two properties that guards:
    # (a) a runaway counter with a trivially-holding edge invariant stops at the cap (truncation honoured),
    r = check(_unbounded_ctr_edge(), max_states=5)
    assert r.ok and r.truncated and r.states_explored == 5
    # (b) a bounded model sweeps exactly the reachable set explore builds -- no successor dropped or dup'd --
    m = _bounded_ctr_edge()
    assert check(m).ok  # the edge invariant holds on every real transition
    assert check(m).states_explored == len(explore(m).states) == 5  # v in 0..4
    assert check_all(m) == []  # exhaustive audit agrees: nothing broken


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


# --------------------------------------------------------------------------------------------------
# 16. Fairness by action tag — derive fair sets from Action(fair=...), and validate names (#27)
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Loop:
    at: str  # "a", "b", "goal"


def tagged_fairness_model() -> Model[Loop]:
    # a <-> b loop; "finish" (b -> goal) is enabled infinitely often, so STRONG fairness forces it and the
    # goal is reached. The action carries its own fair tag instead of a hand-maintained name tuple.
    return Model(
        init=Loop("a"),
        actions=[
            Action("work", enabled=lambda s: s.at == "a", apply=lambda s: Loop("b")),
            Action("back", enabled=lambda s: s.at == "b", apply=lambda s: Loop("a")),
            Action("finish", enabled=lambda s: s.at == "b", apply=lambda s: Loop("goal"), fair="strong"),
        ],
        terminal=lambda s: s.at == "goal",
    )


def test_fairness_by_tag_matches_explicit_and_validates_names():
    m = tagged_fairness_model()

    def at_goal(s: Loop) -> bool:
        return s.at == "goal"

    # Deriving from the "finish" strong tag equals passing fair_strong=("finish",) explicitly.
    assert check_liveness(m, goal=at_goal).ok
    assert check_liveness(m, goal=at_goal).ok == check_liveness(m, goal=at_goal, fair_strong=("finish",)).ok
    # The tags flow through the patterns sugar too (eventually -> check_ltl -> check_liveness).
    assert eventually(m, at_goal, name="goal").ok
    # An explicit empty set overrides the tags -> no fairness -> the a<->b loop is a counterexample.
    assert not check_liveness(m, goal=at_goal, fair_strong=()).ok
    assert not eventually(m, at_goal, name="goal", fair_strong=()).ok
    # A fairness name matching no action is an error (the rename/typo hazard), not silently ignored.
    with pytest.raises(ValueError, match="match no action"):
        check_liveness(m, goal=at_goal, fair_strong=("typo_finish",))


def test_check_all_reports_edge_and_state_violations_together():
    # check_all (the all-violations audit) must not silently ignore edge invariants. This model breaks a
    # STATE invariant (corrupt -> "bad") and an EDGE invariant (force_publish); the audit reports BOTH, each
    # with its shortest trace, and they never collide in the bucketing.
    m: Model[Doc] = Model(
        init=Doc("draft"),
        actions=[
            Action("review", enabled=lambda s: s.stage == "draft", apply=lambda s: Doc("reviewed")),
            Action("publish", enabled=lambda s: s.stage == "reviewed", apply=lambda s: Doc("published")),
            Action("force_publish", enabled=lambda s: s.stage == "draft", apply=lambda s: Doc("published")),
            Action("corrupt", enabled=lambda s: s.stage == "draft", apply=lambda s: Doc("bad")),
        ],
        invariants={"known-stage": lambda s: s.stage in ("draft", "reviewed", "published")},
        edge_invariants={"no-force-publish": never("force_publish")},
        terminal=lambda s: s.stage in ("published", "bad"),
    )
    kinds = {(r.kind, r.invariant) for r in check_all(m)}
    assert ("edge-invariant", "no-force-publish") in kinds
    assert ("invariant", "known-stage") in kinds
    assert len(kinds) == 2


# --------------------------------------------------------------------------------------------------
# 17. crash_actions — explicit-state crash/revive faults under a budget (#29)
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Mesh:
    up: frozenset[int]


def mesh_model(budget: int) -> Model[Mesh]:
    # 3 nodes; crash_actions generate crash/revive edges under a SIMULTANEOUS-failure budget. Quorum is
    # "at least 2 of 3 up" -- it survives 1 crash but not 2.
    def get_up(s: Mesh, n: Hashable) -> bool:
        return n in s.up

    def set_up(s: Mesh, n: Hashable, up: bool) -> Mesh:
        assert isinstance(n, int)
        return Mesh(up=(s.up | {n}) if up else (s.up - {n}))

    return Model(
        init=Mesh(frozenset(range(3))),
        actions=crash_actions(range(3), get_up=get_up, set_up=set_up, budget=budget, revive=True),
        invariants={"quorum": lambda s: len(s.up) >= 2},
        terminal=lambda s: False,
    )


def test_crash_actions_budget_bounds_simultaneous_failures():
    # budget=1: at most one node down at a time -> quorum (>=2 up) always holds. Reachable states: all-up
    # plus each single-down = 1 + 3 = 4, derivable.
    assert check(mesh_model(1)).ok
    assert len(explore(mesh_model(1)).states) == 4
    # budget=2: two nodes can be down at once -> only one up -> quorum fails, via two crash edges.
    r = check(mesh_model(2))
    assert not r.ok
    assert r.invariant == "quorum"
    assert r.action_names == ("fault:crash:0", "fault:crash:1")


# --------------------------------------------------------------------------------------------------
# 18. partition_actions — explicit-state network partition/heal faults (#29)
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Net:
    parts: frozenset[frozenset[int]]  # the current partition of {0,1,2} into reachable groups


_HEALED = frozenset({frozenset({0, 1, 2})})
_MAJORITY = frozenset({frozenset({0}), frozenset({1, 2})})  # {0} | {1,2}: the {1,2} side keeps a majority
_ISOLATE = frozenset({frozenset({0}), frozenset({1}), frozenset({2})})  # all isolated: no majority anywhere


def net_model(splits: list[frozenset[frozenset[int]]]) -> Model[Net]:
    return Model(
        init=Net(_HEALED),
        actions=partition_actions(
            splits, get_reach=lambda s: s.parts, set_reach=lambda s, r: Net(r), healed=_HEALED  # type: ignore[arg-type]
        ),
        invariants={"quorum-side": lambda s: any(len(g) >= 2 for g in s.parts)},
        terminal=lambda s: False,
    )


def test_partition_actions_install_and_heal_faults():
    # healed <-> {0}|{1,2}: 2 reachable states; quorum-side (some group >=2) holds in both.
    m = net_model([_MAJORITY])
    assert check(m).ok
    assert len(explore(m).states) == 2
    # A split into singletons breaks quorum-side -> check finds it via the partition edge.
    r = check(net_model([_ISOLATE]))
    assert not r.ok
    assert r.invariant == "quorum-side"
    assert r.action_names == ("fault:partition:0",)


# --------------------------------------------------------------------------------------------------
# 19. replicated_transition_actions — N entities on one table, with per-instance effects/guards (#26)
# --------------------------------------------------------------------------------------------------


_LEDGER_TABLE: dict[str, frozenset[str]] = {
    "draft": frozenset({"posted"}),
    "posted": frozenset({"closed"}),
    "closed": frozenset(),
}


@dataclass(frozen=True)
class Ledger:
    status: tuple[str, str]  # two entries share one lifecycle table
    balance: int  # a side-effect field the transitions move
    period_open: bool = True


def ledger_model() -> Model[Ledger]:
    def get(s: Ledger, i: Hashable) -> str:
        assert isinstance(i, int)
        return s.status[i]

    def set_status(s: Ledger, i: Hashable, dst: str) -> Ledger:
        assert isinstance(i, int)
        return replace(s, status=tuple(dst if j == i else x for j, x in enumerate(s.status)))  # type: ignore[arg-type]

    def effect(s: Ledger, _i: Hashable, _frm: str, to: str) -> Ledger:
        return replace(s, balance=s.balance + 1) if to == "posted" else s  # posting moves the balance

    def also(s: Ledger, _i: Hashable) -> bool:
        return s.period_open  # a cross-cutting guard the table itself does not encode

    return Model(
        init=Ledger(("draft", "draft"), 0),
        actions=replicated_transition_actions(
            _LEDGER_TABLE, 2, get=get, set_status=set_status, effect=effect, also=also
        ),
        # the effect keeps balance == number of entries that have posted (a cross-instance invariant that a
        # Composite tuple state could not express as flatly)
        invariants={"balance-tracks-posted": lambda s: s.balance == sum(1 for st in s.status if st in ("posted", "closed"))},
        terminal=lambda s: all(st == "closed" for st in s.status),
    )


def test_replicated_transition_actions_flat_state_with_effects_and_guards():
    m = ledger_model()
    # 2 entries x 2 edges (draft->posted, posted->closed) = 4 actions.
    assert len(m.actions) == 4  # type: ignore[arg-type]
    assert {a.name for a in m.actions} == {  # type: ignore[union-attr]
        "0:draft->posted", "0:posted->closed", "1:draft->posted", "1:posted->closed",
    }
    # Each entry independently in {draft, posted, closed} -> 3 x 3 = 9 reachable states, and the balance
    # side-effect keeps the cross-instance invariant, so the model is correct.
    assert len(explore(m).states) == 9
    assert check(m).ok


def _entry0(s: Ledger) -> str:
    return s.status[0]


def _entry1(s: Ledger) -> str:
    return s.status[1]


def _skip0(s: Ledger) -> Ledger:
    return replace(s, status=("closed", s.status[1]))


def test_assert_covers_table_catches_undeclared_transitions():
    # The table-built ledger conforms: each entry's status only ever moves along the declared edges.
    m = ledger_model()
    assert_covers_table(m, _LEDGER_TABLE, get=_entry0)
    assert_covers_table(m, _LEDGER_TABLE, get=_entry1)

    # A hand-written extra action that skips draft -> closed on entry 0 drifts ABOVE the table.
    extra: Action[Ledger] = Action("0:skip", enabled=lambda s: s.status[0] == "draft", apply=_skip0)
    bad: Model[Ledger] = replace(m, actions=[*m.actions, extra])
    with pytest.raises(AssertionError, match="draft -> closed"):
        assert_covers_table(bad, _LEDGER_TABLE, get=_entry0)


# --------------------------------------------------------------------------------------------------
# 20. reconciler — desired<->actual convergence; fair reconcile vs an unfair competitor (#23)
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Ctrl:
    desired: str
    actual: str


def _ctrl_desired(s: Ctrl) -> str:
    return s.desired


def _ctrl_actual(s: Ctrl) -> str:
    return s.actual


def _ctrl_set_actual(s: Ctrl, v: str) -> Ctrl:
    return replace(s, actual=v)


def reconciler_model() -> tuple[Model[Ctrl], Callable[[Ctrl], bool]]:
    converged, reconcile = reconciler(
        get_desired=_ctrl_desired, get_actual=_ctrl_actual, set_actual=_ctrl_set_actual
    )
    # an UNFAIR idle self-loop competes with reconcile: without fairness the scheduler can idle forever and
    # never converge; the reconcile action's own weak-fair tag is what rules that cycle out.
    idle: Action[Ctrl] = Action("idle", enabled=lambda s: True, apply=lambda s: s)
    m = Model(init=Ctrl("a", "b"), actions=[reconcile, idle], terminal=lambda s: False)
    return m, converged


def test_reconciler_converges_under_reconcile_fairness_only():
    m, converged = reconciler_model()
    assert len(explore(m).states) == 2  # (a,b) not converged, (a,a) converged
    # []<>converged holds because reconcile is weak-fair by construction (the tag the builder attaches)...
    assert check_liveness(m, goal=converged, everywhere=True).ok
    # ...and fails without fairness: the idle self-loop can starve reconcile forever.
    assert not check_liveness(m, goal=converged, everywhere=True, fair=()).ok


# --------------------------------------------------------------------------------------------------
# 21. portfolio_coverage — how much of a declared table a SET of models exercises, with a ratchet (#35)
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class St:
    v: str


_EXT_TABLE = {"a": frozenset({"b", "c"}), "b": frozenset({"a"}), "c": frozenset({"a"})}


def _walk(*edges: tuple[str, str]) -> Model[St]:
    # a model that only ever walks the given (src -> dst) value edges
    acts = [
        Action(f"{x}->{y}", enabled=lambda s, x=x: s.v == x, apply=lambda s, y=y: St(y)) for x, y in edges
    ]
    return Model(init=St("a"), actions=acts, terminal=lambda s: False)


def _v(s: St) -> str:
    return s.v


def test_portfolio_coverage_unions_models_and_ratchets():
    m1 = _walk(("a", "b"), ("b", "a"))  # covers a->b, b->a
    m2 = _walk(("a", "c"), ("c", "a"))  # covers a->c, c->a

    # Unioned over both models, all four declared edges are exercised: ratio 1, nothing dead.
    both = portfolio_coverage([m1, m2], get=_v, declared=_EXT_TABLE)
    assert both.dead_edges == frozenset()
    assert both.ratio == Fraction(1)
    assert both.covered_edges == frozenset({("a", "b"), ("b", "a"), ("a", "c"), ("c", "a")})

    # m1 alone covers only half; the other two edges are dead.
    one = portfolio_coverage([m1], get=_v, declared=_EXT_TABLE)
    assert one.ratio == Fraction(1, 2)
    assert one.dead_edges == frozenset({("a", "c"), ("c", "a")})

    # Ratchet gate: full portfolio meets ratio 1.0; the m1-only suite needs its dead edges named exactly.
    assert_covers([m1, m2], _EXT_TABLE, get=_v, ratio=1.0)
    assert_covers([m1], _EXT_TABLE, get=_v, blind_spots={("a", "c"), ("c", "a")})
    # A new uncovered edge that is NOT acknowledged in blind_spots is a regression the gate rejects.
    with pytest.raises(AssertionError, match="newly uncovered"):
        assert_covers([m1], _EXT_TABLE, get=_v, blind_spots={("a", "c")})
    # A model exercising a transition the table forbids is drift the gate rejects.
    with pytest.raises(AssertionError, match="not in the declared table"):
        assert_covers([_walk(("a", "z"))], _EXT_TABLE, get=_v)
