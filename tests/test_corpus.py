"""Known-verdict corpus — classic models whose answers are established by theory, pinned by exact
reachable-state count AND semantic verdict. Any engine change that alters a count or a verdict fails CI.
This is the correctness oracle the BFS unification and any future native (Rust) port differ-test against.

Counts are computed by the current engine and pinned; the *verdicts* (mutual exclusion holds, the naive
philosophers deadlock, the light is live) are known independently of musil, so the corpus checks
correctness, not merely "unchanged"."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from fractions import Fraction

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
    check,
    check_liveness,
    check_ltl,
    eventually,
    expected_reward,
    expected_reward_mdp,
    explore,
    explore_por,
    por_sound,
    profile,
    reach_probability,
    reach_probability_mdp,
    recurs,
    responds,
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
