"""#19 — the API reference must document every public module, so the docs cannot silently drift behind
the code again. api.md uses mkdocstrings (`::: musil.<module>`), which auto-includes each module's public
members; this only guards that every module HAS a section."""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def test_every_public_module_appears_in_the_api_reference():
    src = _ROOT / "src" / "musil"
    api = (_ROOT / "docs" / "api.md").read_text(encoding="utf-8")
    modules = sorted(p.stem for p in src.glob("*.py") if not p.stem.startswith("__"))
    missing = [m for m in modules if f"::: musil.{m}" not in api]
    assert not missing, f"docs/api.md is missing a `::: musil.<module>` section for: {missing}"
