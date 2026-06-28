"""Core checker: safety, deadlock, terminal sinks, multiple inits, concurrency interleaving."""

from __future__ import annotations

from dataclasses import dataclass, replace

from musil import Action, Invariant, Model, check


@dataclass(frozen=True)
class Light:
    color: str


def _light_model(invariant_ok: bool = True) -> Model[Light]:
    inv: dict[str, Invariant[Light]] = {"known-color": lambda s: s.color in {"red", "green", "yellow"}}
    if not invariant_ok:
        inv = {"never-yellow": lambda s: s.color != "yellow"}  # deliberately false once we reach it
    return Model(
        init=Light("red"),
        actions=[
            Action("go", lambda s: s.color == "red", lambda _s: Light("green")),
            Action("slow", lambda s: s.color == "green", lambda _s: Light("yellow")),
            Action("stop", lambda s: s.color == "yellow", lambda _s: Light("red")),
        ],
        invariants=inv,
    )


def test_safe_cyclic_machine_is_ok() -> None:
    result = check(_light_model())
    assert result.ok
    assert result.states_explored == 3  # red, green, yellow


def test_invariant_violation_reports_shortest_trace() -> None:
    result = check(_light_model(invariant_ok=False))
    assert not result.ok
    assert result.kind == "invariant"
    assert result.invariant == "never-yellow"
    # shortest path to yellow: red --go--> green --slow--> yellow
    assert [step.action for step in result.trace] == ["<init>", "go", "slow"]
    assert result.trace[-1].state == Light("yellow")


def test_deadlock_detected() -> None:
    # 'stuck' has no outgoing action and isn't terminal → deadlock
    model = Model(
        init=Light("red"),
        actions=[Action("jam", lambda s: s.color == "red", lambda _s: Light("stuck"))],
    )
    result = check(model)
    assert not result.ok
    assert result.kind == "deadlock"
    assert result.trace[-1].state == Light("stuck")


def test_terminal_sink_is_not_a_deadlock() -> None:
    model = Model(
        init=Light("red"),
        actions=[Action("off", lambda s: s.color == "red", lambda _s: Light("off"))],
        terminal=lambda s: s.color == "off",
    )
    assert check(model).ok


def test_multiple_initial_states_all_explored() -> None:
    model = Model(
        init=[Light("red"), Light("green")],
        actions=[Action("stop", lambda s: s.color == "green", lambda _s: Light("red"))],
        terminal=lambda s: s.color == "red",
    )
    result = check(model)
    assert result.ok
    assert result.states_explored == 2


# --- concurrency: a non-atomic increment race the interleaving sweep must catch -----------------


@dataclass(frozen=True)
class Counter:
    x: int = 0
    a_reg: int | None = None  # A's read-but-not-yet-written value
    b_reg: int | None = None
    a_done: bool = False
    b_done: bool = False


def _race_model() -> Model[Counter]:
    return Model(
        init=Counter(),
        actions=[
            Action("A_read", lambda s: s.a_reg is None and not s.a_done, lambda s: replace(s, a_reg=s.x)),
            Action(
                "A_write",
                lambda s: s.a_reg is not None,
                lambda s: replace(s, x=s.a_reg + 1, a_reg=None, a_done=True),  # type: ignore[operator]
            ),
            Action("B_read", lambda s: s.b_reg is None and not s.b_done, lambda s: replace(s, b_reg=s.x)),
            Action(
                "B_write",
                lambda s: s.b_reg is not None,
                lambda s: replace(s, x=s.b_reg + 1, b_reg=None, b_done=True),  # type: ignore[operator]
            ),
        ],
        invariants={"both-increments-counted": lambda s: not (s.a_done and s.b_done) or s.x == 2},
        terminal=lambda s: s.a_done and s.b_done,
    )


def test_interleaving_finds_lost_update_race() -> None:
    result = check(_race_model())
    assert not result.ok
    assert result.kind == "invariant"
    assert result.invariant == "both-increments-counted"
    # the classic interleaving: both read 0 before either writes → final x == 1, not 2
    actions = [step.action for step in result.trace]
    assert actions.count("A_read") == 1 and actions.count("B_read") == 1
    assert result.trace[-1].state.x == 1


def test_max_states_truncation_is_reported() -> None:
    # an unbounded counter — cap the sweep and confirm it reports truncation rather than running away
    @dataclass(frozen=True)
    class N:
        n: int = 0

    model = Model(init=N(0), actions=[Action("inc", lambda _s: True, lambda s: N(s.n + 1))])
    result = check(model, max_states=50)
    assert result.ok and result.truncated
    assert result.states_explored >= 50


def test_string_returning_invariant_carries_a_reason() -> None:
    # an invariant that returns a string signals a violation AND a human-readable reason — useful
    # when wrapping a richer checker that reports which sub-rule/entity broke.
    def at_most_two(s: Light) -> bool | str:
        order = {"red": 0, "green": 1, "yellow": 2}
        return True if order[s.color] < 2 else f"reached {s.color} (rank {order[s.color]})"

    result = check(_light_model().__class__(  # reuse the light machine with the string invariant
        init=Light("red"),
        actions=_light_model().actions,
        invariants={"rank-bound": at_most_two},
    ))
    assert not result.ok
    assert result.kind == "invariant"
    assert result.invariant == "rank-bound"
    assert result.reason == "reached yellow (rank 2)"
    assert "reached yellow (rank 2)" in str(result)


def test_empty_string_invariant_is_a_violation_without_reason() -> None:
    # an empty string is falsy-but-str: still a violation, just no reason text.
    result = check(
        Model(init=Light("red"),
              actions=[Action("go", lambda s: s.color == "red", lambda _s: Light("green"))],
              invariants={"never": lambda _s: ""})
    )
    assert not result.ok and result.kind == "invariant" and result.reason is None


def test_reachable_violations_enumerates_all_bad_states() -> None:
    # a 3-state cycle red->green->yellow->red; two invariants, one with a reason string.
    from musil import reachable_violations

    model = Model(
        init=Light("red"),
        actions=[
            Action("go", lambda s: s.color == "red", lambda _s: Light("green")),
            Action("slow", lambda s: s.color == "green", lambda _s: Light("yellow")),
            Action("stop", lambda s: s.color == "yellow", lambda _s: Light("red")),
        ],
        invariants={
            "not-yellow": lambda s: s.color != "yellow",
            "not-green": lambda s: True if s.color != "green" else "green is forbidden",
        },
    )
    vs = reachable_violations(model)
    by_inv = {(v.invariant, v.reason) for v in vs}
    assert ("not-yellow", None) in by_inv  # bool invariant, no reason
    assert ("not-green", "green is forbidden") in by_inv  # string invariant carries its reason
    # exactly one violating state per invariant (yellow, green respectively)
    assert len(vs) == 2


def test_invariant_from_violations_adapts_a_checker() -> None:
    from musil import invariant_from_violations, reachable_violations

    # a checker that returns "violations" (here just strings) — empty means OK
    def checker(s: Light) -> list[str]:
        return [] if s.color != "yellow" else ["yellow-is-bad"]

    inv = invariant_from_violations(checker, describe=lambda v: f"rule:{v}")
    assert inv(Light("red")) is True
    assert inv(Light("yellow")) == "rule:yellow-is-bad"

    model = Model(
        init=Light("red"),
        actions=[
            Action("go", lambda s: s.color == "red", lambda _s: Light("green")),
            Action("slow", lambda s: s.color == "green", lambda _s: Light("yellow")),
        ],
        invariants={"checker": inv},
    )
    vs = reachable_violations(model)
    assert len(vs) == 1 and vs[0].reason == "rule:yellow-is-bad"
