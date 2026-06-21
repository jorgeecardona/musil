"""Core checker: safety, deadlock, terminal sinks, multiple inits, concurrency interleaving."""

from __future__ import annotations

from dataclasses import dataclass, replace

from musil import Action, Model, check


@dataclass(frozen=True)
class Light:
    color: str


def _light_model(invariant_ok: bool = True) -> Model[Light]:
    inv = {"known-color": lambda s: s.color in {"red", "green", "yellow"}}
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
