"""Command line: ``python -m musil <model.py> [--dot]``.

Loads a Python module (by file path or dotted name), finds a ``Model`` named ``MODEL`` (or
``model``), and either runs ``check`` and prints the result (exit 0 if it holds, 1 if a violation is
found) or, with ``--dot``, prints the Graphviz DOT of its reachable state graph."""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from musil.core import Model, check
from musil.graph import to_dot

_USAGE = "usage: python -m musil <model.py | dotted.module> [--dot]"


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


def _find_model(module: ModuleType) -> Model:
    for name in ("MODEL", "model"):
        candidate = getattr(module, name, None)
        if isinstance(candidate, Model):
            return candidate
    raise ValueError("no Model named MODEL or model in the module")


def main(argv: list[str]) -> int:
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
