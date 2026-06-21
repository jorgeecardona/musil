"""A traffic light: the smallest useful musil model — safety + a DOT render.

Run: python examples/traffic_light.py
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from musil import Action, Model, check, to_dot


@dataclass(frozen=True)
class Light:
    color: str = "red"


MODEL = Model(
    init=Light("red"),
    actions=[
        Action("go", lambda s: s.color == "red", lambda s: replace(s, color="green")),
        Action("slow", lambda s: s.color == "green", lambda s: replace(s, color="yellow")),
        Action("stop", lambda s: s.color == "yellow", lambda s: replace(s, color="red")),
    ],
    invariants={"known-color": lambda s: s.color in {"red", "green", "yellow"}},
)


if __name__ == "__main__":
    print(check(MODEL))
    print("\n--- DOT (pipe to: dot -Tsvg) ---")
    print(to_dot(MODEL))
