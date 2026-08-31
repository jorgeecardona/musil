"""Command line (also installed as the ``musil`` command):

- ``python -m musil <model.py> [--dot]`` — load a module, find a ``Model`` named ``MODEL`` (or ``model``),
  and either run ``check`` (exit 0 if it holds, 1 on a violation) or, with ``--dot``, print its Graphviz DOT.
- ``python -m musil doctor <path>`` — scan a file or directory for hand-rolled patterns a shipped musil API
  already covers (see ``musil.doctor.scan``), printing ``file:line:col: pattern: suggestion``. Advisory:
  it always exits 0."""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, cast

from musil.core import Model, check
from musil.doctor import scan
from musil.graph import to_dot

_USAGE = "usage: python -m musil <model.py | dotted.module> [--dot]  |  python -m musil doctor <path>"


def _load(target: str) -> ModuleType:
    path = Path(target)
    if path.suffix == ".py" or path.exists():
        spec = importlib.util.spec_from_file_location(path.stem or "model", path)
        if spec is None or spec.loader is None:
            raise ValueError(f"cannot load {target!r}")
        module = importlib.util.module_from_spec(spec)
        # register before exec: dataclass annotation resolution looks the module up in sys.modules
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    return importlib.import_module(target)


def _find_model(module: ModuleType) -> Model[Any]:
    for name in ("MODEL", "model"):
        candidate = getattr(module, name, None)
        if isinstance(candidate, Model):
            return cast("Model[Any]", candidate)
    raise ValueError("no Model named MODEL or model in the module")


def _doctor(path: Path) -> int:
    """Scan ``path`` (a file, or a directory recursively) for hand-rolled patterns and print suggestions.
    Advisory: unreadable or un-parseable files are skipped, and it always returns 0."""
    files = [path] if path.is_file() else sorted(path.rglob("*.py"))
    total = 0
    for file in files:
        try:
            findings = scan(file.read_text(encoding="utf-8"), filename=str(file))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        for finding in findings:
            print(f"{file}:{finding.line}:{finding.col}: {finding.pattern}: {finding.message}")
            total += 1
    print(f"{total} suggestion(s) across {len(files)} file(s)", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if argv and argv[0] == "doctor":
        if len(argv) < 2:
            print("usage: python -m musil doctor <path>", file=sys.stderr)
            return 2
        return _doctor(Path(argv[1]))
    args = [a for a in argv if a != "--dot"]
    want_dot = "--dot" in argv
    if not args:
        print(_USAGE, file=sys.stderr)
        return 2
    try:
        model = _find_model(_load(args[0]))
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if want_dot:
        print(to_dot(model))
        return 0
    result = check(model)
    print(result)
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
