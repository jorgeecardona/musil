"""State-space metrics: size + branching of a model's reachable behaviour, and solution cardinality
(how many reachable states satisfy a goal) — the design-level analog of 'expression cardinality',
measured exactly instead of guessed."""

from musil import Action, Model
from musil.metrics import solution_cardinality, state_space_metrics


def _counter(max_n: int) -> Model[int]:
    # a linear chain 0 -> 1 -> ... -> max_n
    return Model(init=0, actions=[Action("Inc", lambda s: s < max_n, lambda s: s + 1)], invariants={})


def test_linear_chain_metrics() -> None:
    m = state_space_metrics(_counter(3))
    assert m.reachable_states == 4  # 0,1,2,3
    assert m.transitions == 3  # 0->1, 1->2, 2->3
    assert m.initial_states == 1
    assert m.terminal_states == 1  # state 3 has no enabled action
    assert m.max_branching == 1
    assert m.mean_branching == 0.75  # 3 successors over 4 states
    assert m.truncated is False


def test_self_loops_do_not_count_as_branching() -> None:
    # an Idle self-loop is not a real choice — branching must ignore it (else every model looks branchy)
    m = Model(
        init=0,
        actions=[
            Action("Inc", lambda s: s < 2, lambda s: s + 1),
            Action("Idle", lambda s: True, lambda s: s),
        ],
        invariants={},
    )
    metrics = state_space_metrics(m)
    assert metrics.reachable_states == 3
    assert metrics.max_branching == 1  # the Idle self-loop is excluded from branching
    # the top state can only Idle → no forward progress → absorbing/terminal (a liveness dead-end)
    assert metrics.terminal_states == 1
    assert metrics.transitions > metrics.reachable_states  # self-loops still count as transitions


def test_solution_cardinality_counts_reachable_goal_states() -> None:
    # the design's "expression cardinality" for a goal: how many reachable states satisfy it, exactly.
    assert solution_cardinality(_counter(3), lambda s: s >= 2) == 2  # states 2 and 3
    assert solution_cardinality(_counter(3), lambda s: s == 99) == 0  # unreachable goal → zero
