"""Known-verdict corpus — classic models whose answers are established by theory, pinned by exact
reachable-state count AND semantic verdict. Any engine change that alters a count or a verdict fails CI.
This is the correctness oracle the BFS unification and any future native (Rust) port differ-test against.

Counts are computed by the current engine and pinned; the *verdicts* (mutual exclusion holds, the naive
philosophers deadlock, the light is live) are known independently of musil, so the corpus checks
correctness, not merely "unchanged"."""

from __future__ import annotations

from dataclasses import dataclass

from musil import (
    Action,
    Always,
    Atom,
    Eventually,
    Implies,
    Model,
    check,
    check_liveness,
    check_ltl,
    explore,
    profile,
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


def test_profile_explores_the_same_reachable_set():
    # profile keeps its own instrumented loop (it times enabled/apply/canonicalize separately, which the
    # shared _successors kernel bundles). This pins its full-sweep reachable count to the corpus so it can
    # never silently drift from check/explore.
    assert profile(counter_model(5)).states_explored == len(explore(counter_model(5)).states) == 6
    assert profile(peterson_model()).states_explored == len(explore(peterson_model()).states) == 20
    assert profile(dining_naive_model()).states_explored == len(explore(dining_naive_model()).states) == 6
    assert profile(light_model()).states_explored == len(explore(light_model()).states) == 3
