"""``check_cached`` — content-addressed verdict caching, and ``clear_verdict_cache``."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace as dc_replace
from pathlib import Path

from musil import Action, Model, Result
from musil.cache import check_cached, clear_verdict_cache
from musil.metrics import Coverage, coverage_cached


@dataclass(frozen=True)
class C:  # module-level so a cached Result (pickled) can be loaded back
    n: int


def _model(inv_holds: bool) -> Model[C]:
    return Model(
        init=C(0),
        actions=[Action("inc", enabled=lambda s: s.n < 3, apply=lambda s: dc_replace(s, n=s.n + 1))],
        invariants={"inv": (lambda s: True) if inv_holds else (lambda s: s.n == 0)},
        terminal=lambda s: s.n == 3,
    )


def test_hit_returns_stale_verdict_when_version_is_not_bumped(tmp_path: Path):
    assert check_cached(_model(inv_holds=True), version="v1", cache_dir=tmp_path).ok
    # Same names/init/options/version but the invariant now FAILS. Because version was not bumped, the
    # digest is identical and the cache returns the stale OK verdict — proving the hit and the contract.
    assert check_cached(_model(inv_holds=False), version="v1", cache_dir=tmp_path).ok
    # Bumping version changes the digest → recomputed → the real (failing) verdict.
    r = check_cached(_model(inv_holds=False), version="v2", cache_dir=tmp_path)
    assert not r.ok
    assert r.invariant == "inv"


def test_structural_change_invalidates_without_a_version_bump(tmp_path: Path):
    assert check_cached(_model(inv_holds=True), version="v1", cache_dir=tmp_path).ok
    # A new invariant NAME is a readable structural change, so the digest differs even at version v1.
    m2 = Model(
        init=C(0),
        actions=[Action("inc", enabled=lambda s: s.n < 3, apply=lambda s: dc_replace(s, n=s.n + 1))],
        invariants={"inv": lambda s: True, "boom": lambda s: False},
        terminal=lambda s: s.n == 3,
    )
    r = check_cached(m2, version="v1", cache_dir=tmp_path)
    assert not r.ok
    assert r.invariant == "boom"


def test_cached_result_round_trips_the_trace_with_live_states(tmp_path: Path):
    r1 = check_cached(_model(inv_holds=False), version="v1", cache_dir=tmp_path)  # miss: real check
    r2 = check_cached(_model(inv_holds=False), version="v1", cache_dir=tmp_path)  # hit: from disk
    assert not r2.ok
    assert r2.invariant == r1.invariant
    assert [st.action for st in r2.trace] == [st.action for st in r1.trace]
    assert isinstance(r2.trace[-1].state, C)  # a live state object, reconstructed from the cache


def test_clear_verdict_cache_counts_and_tolerates_missing_dir(tmp_path: Path):
    check_cached(_model(inv_holds=True), version="v1", cache_dir=tmp_path)
    assert clear_verdict_cache(tmp_path) == 1
    assert clear_verdict_cache(tmp_path) == 0  # already emptied
    assert clear_verdict_cache(tmp_path / "does-not-exist") == 0


# --- coverage_cached (issue #41): the content-addressed parallel of check_cached over coverage() ---


def _cov_model(*, alive: bool) -> Model[C]:
    # same action NAMES either way; only the guard BODY of 'maybe' differs (opaque to the digest, like a
    # changed lambda body under an unchanged name -- exactly what `version` exists to catch).
    return Model(
        init=C(0),
        actions=[
            Action("inc", enabled=lambda s: s.n < 3, apply=lambda s: dc_replace(s, n=s.n + 1)),
            Action("maybe", enabled=(lambda s: s.n < 3) if alive else (lambda s: False), apply=lambda s: s),
        ],
        terminal=lambda s: s.n == 3,
    )


def test_coverage_cached_hit_returns_stale_coverage_until_version_bump(tmp_path: Path):
    assert "maybe" not in coverage_cached(_cov_model(alive=True), version="v1", cache_dir=tmp_path).dead_actions
    # 'maybe' is now never enabled (dead), but names/options/version are identical -> stale cache hit.
    assert "maybe" not in coverage_cached(_cov_model(alive=False), version="v1", cache_dir=tmp_path).dead_actions
    # bumping version changes the digest -> recomputed -> 'maybe' correctly reported dead.
    assert "maybe" in coverage_cached(_cov_model(alive=False), version="v2", cache_dir=tmp_path).dead_actions


def test_coverage_and_verdict_caches_coexist_without_collision(tmp_path: Path):
    model = _cov_model(alive=True)
    r = check_cached(model, version="v1", cache_dir=tmp_path)
    c = coverage_cached(model, version="v1", cache_dir=tmp_path)
    assert isinstance(r, Result) and isinstance(c, Coverage)  # each artifact keeps its own type
    # same digest, distinct filenames ({digest}.pkl vs {digest}.coverage.pkl) -> two files, no clobber
    assert len(list(tmp_path.glob("*.pkl"))) == 2
