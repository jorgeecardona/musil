# Coverage & vacuity: is a green check meaningful?

**What this teaches:** `check` returning OK means no invariant broke on the reachable space. It does
*not* mean the behaviour you wrote was exercised, or that your invariants caught anything. Two
silent failure modes survive a green check, and `coverage` / `invariant_coverage` find them. Both
run over the reachable graph, next to `check`, never inside it.

- a **dead action**: a guard never satisfiable in any reachable state, so it never fires. Usually a
  guard bug or dead code; the OK verdict hides that an interleaving you believed was covered never
  ran.
- a **vacuously-true invariant**: one no action could ever break, so it passes for the wrong reason.
  It adds nothing, and worse, lulls you into thinking a property is checked when it is not.

## The model

A tiny account passes `check` cleanly, yet has one of each. A dead action and a vacuous invariant:

```python
MODEL = Model(
    init=Account(0, "open"),
    actions=[
        Action("deposit",  lambda s: s.status == "open" and s.balance < 3, ...),
        Action("withdraw", lambda s: s.status == "open" and s.balance > 0, ...),
        # BUG: guarded on "frozen", a status nothing ever sets -> can never fire (dead code)
        Action("thaw",     lambda s: s.status == "frozen", ...),
    ],
    invariants={
        "non-negative-balance": lambda s: s.balance >= 0,   # load-bearing
        "status-known":         lambda s: s.status in {...}, # vacuously true — nothing sets a bad status
    },
)
```

## Finding the dead action: `coverage`

```python
check(MODEL).ok          # True — the sweep is green
coverage(MODEL)          # flags 'thaw' as never enabled across the reachable graph
```

`thaw` is guarded on `status == "frozen"`, but no action ever sets `"frozen"`, so its guard is never
satisfiable. It is dead code. `check` is happy (nothing broke); `coverage` is the tool that says the
interleaving through `thaw` never actually ran.

## Finding the vacuous invariant: `invariant_coverage`

```python
invariant_coverage(MODEL)  # 'non-negative-balance' load-bearing; 'status-known' candidate-vacuous
```

`invariant_coverage` separates the two invariants: `non-negative-balance` is **load-bearing**. The
`withdraw` guard (`balance > 0`) is exactly what keeps it true, and without that guard a withdraw
would break it. `status-known` is **candidate-vacuous**: no action can ever set a status outside the
known set, so it passes for the wrong reason and protects nothing. A green check that leans on a
vacuous invariant has proved less than it looks.

!!! info "Coverage is analysis, not verification"

    `coverage` and `invariant_coverage` do not change the verdict. They grade the *meaningfulness*
    of a green one. `assert_covers` turns a blind spot into a failing test, and `portfolio_coverage`
    ratchets the union of coverage across a whole suite (blind spots can only shrink). This is
    post-hoc analysis over the graph `check` already built, so it costs nothing extra to ask.

## Source

```python
--8<-- "examples/coverage_vacuity.py"
```

## Run it

```
python examples/coverage_vacuity.py
```

## See also

- [Induction](induction.md): the other "beyond a green check" technique.
- [API reference](../api.md): `coverage`, `invariant_coverage`, `assert_covers`,
  `portfolio_coverage`.
