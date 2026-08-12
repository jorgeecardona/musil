"""Core checker: safety, deadlock, terminal sinks, multiple inits, concurrency interleaving."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

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


def test_a_string_state_is_one_state_not_its_characters() -> None:
    """A ``str`` is iterable, so the "several initial states" heuristic used to take one apart.

    That is the worst shape of bug a checker can have: it did not fail, it checked the model
    whose states are ``"r"``, ``"e"``, ``"d"`` and reported OK. A ``StrEnum`` is the common way
    to spell the states of a protocol, so this is not a corner.
    """
    colors = Model(
        init="red",
        actions=[Action("go", lambda s: s == "red", lambda _s: "green")],
        terminal=lambda s: s == "green",
    )
    assert colors.initial_states() == ("red",)
    result = check(colors)
    assert result.ok
    assert result.states_explored == 2


def test_a_strenum_state_survives_being_an_enum_and_a_string() -> None:
    class Light(StrEnum):
        RED = "red"
        GREEN = "green"

    model = Model(
        init=Light.RED,
        actions=[Action("go", lambda s: s is Light.RED, lambda _s: Light.GREEN)],
        terminal=lambda s: s is Light.GREEN,
    )
    assert model.initial_states() == (Light.RED,)
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


def test_reaches_returns_states_that_can_still_get_to_goal() -> None:
    from musil import explore, reaches

    # red -> green -> yellow -> red cycle, plus a trap door: green -> off (absorbing).
    model = Model(
        init=Light("red"),
        actions=[
            Action("go", lambda s: s.color == "red", lambda _s: Light("green")),
            Action("slow", lambda s: s.color == "green", lambda _s: Light("yellow")),
            Action("stop", lambda s: s.color == "yellow", lambda _s: Light("red")),
            Action("kill", lambda s: s.color == "green", lambda _s: Light("off")),
        ],
        terminal=lambda s: s.color == "off",
    )
    g = explore(model)
    can = reaches(g, lambda s: s.color == "yellow")
    assert can == {Light("red"), Light("green"), Light("yellow")}
    # the complement is the trap: from off, yellow is lost forever.
    assert set(g.states) - can == {Light("off")}


def test_reaches_available_from_everywhere_idiom() -> None:
    from musil import explore, reaches

    # "the goal stays available from every reachable state" — the fmi3FreeInstance question.
    model = Model(
        init=Light("red"),
        actions=[
            Action("go", lambda s: s.color == "red", lambda _s: Light("green")),
            Action("back", lambda s: s.color == "green", lambda _s: Light("red")),
            Action("kill", lambda s: s.color != "off", lambda _s: Light("off")),
        ],
        terminal=lambda s: s.color == "off",
    )
    g = explore(model)
    assert reaches(g, lambda s: s.color == "off") == set(g.states)


def test_fixed_points_different_starts_may_settle_differently() -> None:
    from musil import fixed_points

    # a latch: two starts settle in different places, but each start deterministically.
    model = Model(
        init=[Light("red"), Light("green")],
        actions=[
            Action("r-done", lambda s: s.color == "red", lambda _s: Light("red-done")),
            Action("g-done", lambda s: s.color == "green", lambda _s: Light("green-done")),
        ],
    )
    fp = fixed_points(model)
    assert fp.by_init == {
        Light("red"): frozenset({Light("red-done")}),
        Light("green"): frozenset({Light("green-done")}),
    }
    assert fp.confluent


def test_fixed_points_detects_order_dependent_settlement() -> None:
    from musil import fixed_points

    # two racing steps from one start, each disabling the other: where it settles depends on
    # which fired first — the confluence bug.
    model = Model(
        init=Light("red"),
        actions=[
            Action("a", lambda s: s.color == "red", lambda _s: Light("a-done")),
            Action("b", lambda s: s.color == "red", lambda _s: Light("b-done")),
        ],
    )
    fp = fixed_points(model)
    assert fp.by_init[Light("red")] == {Light("a-done"), Light("b-done")}
    assert not fp.confluent
    assert "NOT CONFLUENT" in str(fp)


def test_fixed_points_never_settling_start_is_liveness_not_confluence() -> None:
    from musil import fixed_points

    # a pure cycle has no terminal state: empty set, still confluent — never settling is a
    # liveness question, not a confluence one.
    model = Model(
        init=Light("red"),
        actions=[
            Action("go", lambda s: s.color == "red", lambda _s: Light("green")),
            Action("back", lambda s: s.color == "green", lambda _s: Light("red")),
        ],
    )
    fp = fixed_points(model)
    assert fp.by_init[Light("red")] == frozenset()
    assert fp.confluent


def test_fixed_points_truncated_is_inconclusive() -> None:
    from musil import fixed_points

    # an unbounded counter: truncation makes the terminal sets unreliable, so confluent is False.
    model = Model(init=0, actions=[Action("inc", lambda _s: True, lambda s: s + 1)])
    fp = fixed_points(model, max_states=3)
    assert fp.truncated
    assert not fp.confluent


# --- assert_ok: the counterexample survives the test runner ------------------------------------


def test_assert_ok_is_silent_on_a_passing_result() -> None:
    from musil import assert_ok

    assert assert_ok(check(_light_model())) is None


def test_assert_ok_raises_with_the_rendered_trace_not_the_repr() -> None:
    from musil import assert_ok

    result = check(_light_model(invariant_ok=False))
    try:
        assert_ok(result)
    except AssertionError as exc:
        message = str(exc)
    else:
        raise AssertionError("assert_ok did not raise on a violated invariant")
    assert message == str(result)
    assert "INVARIANT VIOLATED: never-yellow" in message
    assert "Init: Light(color='red')" in message  # the initial state, which the repr elides
    assert "→ slow: Light(color='yellow')" in message
    assert "Step(action=" not in message  # the raw repr form is gone


def test_assert_ok_prefixes_a_caller_message() -> None:
    from musil import assert_ok

    try:
        assert_ok(check(_light_model(invariant_ok=False)), "the 3-worker instance")
    except AssertionError as exc:
        assert str(exc).startswith("the 3-worker instance\nINVARIANT VIOLATED")
    else:
        raise AssertionError("assert_ok did not raise")


def test_assert_ok_accepts_any_musil_result() -> None:
    # Verdict is structural, so every result type satisfies it -- checked here against one from
    # another module (a liveness result), not just core's Result.
    from musil import assert_ok, check_liveness

    live = check_liveness(_light_model(), goal=lambda s: s.color == "red")
    assert assert_ok(live) is None
    stuck = check_liveness(_light_model(), goal=lambda s: s.color == "blue")
    try:
        assert_ok(stuck)
    except AssertionError as exc:
        assert str(exc) == str(stuck)
    else:
        raise AssertionError("assert_ok did not raise on a liveness violation")


def test_pytest_shows_the_whole_trace_through_assert_ok_and_elides_it_without() -> None:
    """The claim is about what the *runner* prints, so run pytest and read its output."""
    import os
    import subprocess
    import sys
    import tempfile
    from pathlib import Path
    from textwrap import dedent

    source = dedent(
        """
        from dataclasses import dataclass

        from musil import Action, Model, assert_ok, check

        @dataclass(frozen=True)
        class S:
            n: int

        MODEL = Model(
            init=S(0),
            actions=[Action("inc", lambda s: s.n < 5, lambda s: S(s.n + 1))],
            invariants={"below-3": lambda s: s.n < 3},
            terminal=lambda s: s.n >= 5,
        )

        def test_bare_assert() -> None:
            assert check(MODEL)

        def test_via_assert_ok() -> None:
            assert_ok(check(MODEL))
        """
    )
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "test_generated.py"
        path.write_text(source)
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", str(path), "-p", "no:cacheprovider"],
            capture_output=True, text=True, cwd=Path(__file__).resolve().parent.parent,
            env={**os.environ, "COLUMNS": "100"},  # pin the width; the summary is wrapped to it
        )
    out = proc.stdout
    # the two FAILURES sections, without the trailing short-summary block -- that block repeats both
    # failures on one line each, so leaving it in would put the bare test's repr inside `via`. It is
    # also wrapped to the terminal width, which is how this first passed locally and failed in CI.
    bare, rest = out.split("_ test_via_assert_ok _", 1)
    via = rest.split("short test summary info", 1)[0]

    # bare assert: pytest renders the repr and elides its middle, losing the initial state
    assert "Step(action=" in bare
    assert "..." in bare
    assert "Init: S(n=0)" not in bare

    # assert_ok: every step of the counterexample is there, and the Model repr is not
    for line in ("INVARIANT VIOLATED: below-3", "Init: S(n=0)", "→ inc: S(n=1)", "→ inc: S(n=2)", "→ inc: S(n=3)"):
        assert line in via, f"missing from pytest output: {line}"
    assert "Step(action=" not in via
    assert "<function <lambda>" not in via
    assert "def assert_ok" not in via  # __tracebackhide__ keeps the helper's own frame out
