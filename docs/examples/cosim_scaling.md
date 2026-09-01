# Composed components — the scaling curve, and the symmetry lever

**What this teaches:** when a model composes N interchangeable components, every interleaving of their
independent moves is explored, so the reachable state space grows as `(k+1) ** N`. If the components are
*anonymous* (nothing outside a component's own slice names it), that blowup is redundant: symmetry reduction
(`canonical_by_sorting`) collapses the `N!` orderings to one representative and the space becomes polynomial.
This is the documented recipe for the "interchangeable components in a composed model" case, and the measured
answer to "do we need partial-order reduction here?" — for this workload, no.

## The workload

A co-simulation master (FMI-style) advances N sub-components in lock-step. Within one macro step each
component takes up to `k` local micro-steps; when all reach the boundary the master commits, or on a failure
it rolls back every component to the macro-start snapshot and retries. The per-component `step` actions are
mutually **independent** — each reads and writes only its own slot — so musil explores every interleaving.
The reachable set is exactly `(k+1) ** N` (rollback adds interleavings, not states).

## The curve (`k = 3`, with rollback)

| N | full interleaving `(k+1)ᴺ` | under sorting symmetry `C(N+k, N)` | shrink |
|---|---------------------------:|-----------------------------------:|-------:|
| 2 | 16                         | 10                                 |  1.6× |
| 3 | 64                         | 20                                 |  3.2× |
| 4 | 256                        | 35                                 |  7.3× |
| 5 | 1,024                      | 56                                 | 18.3× |

The full column is exponential in N; the symmetry column is polynomial. The full search crosses musil's
default `max_states=1_000_000` cap around N = 10 (`4¹⁰ = 1,048,576`), where the symmetric search is still
`C(13, 10) = 286` states. Symmetry reduction, not POR, is what makes this workload scale — which is why POR
stays deferred behind a measured curve (see `REDUCTION_NOTES.md`).

## The lever (the recipe)

The components are interchangeable and nothing outside a component's slice names it, so canonicalizing by
**sorting the per-component slices** is a sound symmetry. Build the accessor pair over the slices, hand it to
`canonical_by_sorting`, and — this is not optional — **validate it with `symmetry_reduction_sound` on a small
instance** before trusting it on a large one:

```python
from musil import check
from musil.core import symmetry_reduction_sound
from musil.symmetry import canonical_by_sorting

canon = canonical_by_sorting(
    get=lambda s: s.steps,                 # the per-component slices, in component order
    put=lambda s, xs: replace(s, steps=xs),  # write a reordered tuple back
)
assert symmetry_reduction_sound(master_model(5), canon)  # trust, but verify
result = check(master_model(5), canonicalize=canon)      # explores C(N+k, N), not (k+1)ᴺ
```

`canonical_by_sorting` is sound only when the slices are the *only* place a component is named. A `leader:
int` indexing into them, an id inside a message, a per-component key elsewhere — any of those and sorting
breaks the reference while leaving the state well-formed (the quiet kind of wrong). Use
`canonical_by_permutations` there instead, and either way run `symmetry_reduction_sound` first.

## Source

```python
--8<-- "examples/cosim_master_scaling.py"
```

## Run it

```
python examples/cosim_master_scaling.py
```

## See also

- [API reference](../api.md) — `canonical_by_sorting`, `canonical_by_permutations`, `symmetry_reduction_sound`.
