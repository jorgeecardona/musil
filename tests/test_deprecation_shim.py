"""The 0.35 API reorg moved specialised names into submodules; a module-level ``__getattr__`` shim keeps the
old flat imports working with a ``DeprecationWarning`` until a future release. This pins that behaviour and,
importantly, checks that every entry in the shim's table actually resolves (no dangling / mis-typed mapping)."""

from __future__ import annotations

import importlib
import warnings

import pytest

import musil


def test_moved_name_warns_and_resolves_to_the_submodule() -> None:
    from musil.probabilistic import reach_probability as canonical

    with pytest.warns(DeprecationWarning, match=r"musil\.probabilistic"):
        obj = musil.reach_probability
    assert obj is canonical  # the shim returns the genuine function, not a copy


def test_core_name_does_not_warn() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # any warning becomes an error
        assert callable(musil.check)  # a real top-level attribute -> __getattr__ is never consulted


def test_unknown_name_raises_attributeerror() -> None:
    with pytest.raises(AttributeError):
        _ = musil.definitely_not_a_real_name


def test_package_exposes_version_matching_the_distribution() -> None:
    from importlib.metadata import version

    assert musil.__version__ == version("musil")  # issue #39: musil.__version__ must exist and match the dist
    assert musil.__version__ and musil.__version__[0].isdigit()


def test_every_moved_name_resolves_in_its_submodule() -> None:
    moved: dict[str, str] = musil._MOVED  # pyright: ignore[reportPrivateUsage]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        for name, module in moved.items():
            assert hasattr(importlib.import_module(f"musil.{module}"), name), f"{name} not in musil.{module}"
