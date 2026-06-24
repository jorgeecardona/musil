"""TCAS II Resolution Advisory coordination example.

Two aircraft detect a conflict. Each independently selects a Resolution Advisory
(RA) sense: CLIMB or DESCEND. They coordinate over 1090 MHz to ensure complementary
advisories — if one climbs, the other must descend. The safety invariant:

  "Both aircraft never maneuver in the same vertical direction simultaneously."

Three scenarios are checked:

1. CLOSED — both pilots follow their RA → invariant holds.
2. OPEN (Überlingen) — the environment can inject pilot_deviation: a pilot follows
   ATC instead of TCAS. The invariant is violated. The unverified assumption
   PILOT_FOLLOWS_RA surfaces as a residual proof obligation.
3. OPEN with enforcement — model a "TCAS-only" policy that locks out ATC during
   an RA. Invariant holds; PILOT_FOLLOWS_RA is no longer needed.

Background: the 2002 Überlingen mid-air collision killed 71 people. TCAS issued
correct complementary RAs (DHL: CLIMB, Bashkirian: DESCEND). The DHL crew followed
TCAS. The Bashkirian crew followed the ATC controller (who was unaware of the RA
and issued a conflicting descent instruction). Both aircraft descended. The system
worked; the assumption that pilots follow TCAS over ATC did not hold.

Run::

    uv run python examples/tcas.py
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

from musil import Action, Model, check, check_open
from musil.env import Assumption, EnvironmentSpec

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

RAState = Literal["none", "climb", "descend", "maneuvering"]


@dataclass(frozen=True)
class Aircraft:
    ra: RAState = "none"          # current RA sense
    maneuvering: bool = False     # pilot has begun the maneuver
    atc_override: bool = False    # pilot chose ATC instruction over TCAS RA


@dataclass(frozen=True)
class TCASSystem:
    """State of two TCAS-equipped aircraft in a conflict."""

    own: Aircraft = Aircraft()
    intruder: Aircraft = Aircraft()
    conflict_detected: bool = False
    ra_coordinated: bool = False  # both RAs are complementary and acknowledged


# ---------------------------------------------------------------------------
# Safety invariant
# ---------------------------------------------------------------------------

def _no_same_direction_maneuver(s: TCASSystem) -> bool:
    """Both aircraft must never maneuver in the same vertical direction."""
    if not (s.own.maneuvering and s.intruder.maneuvering):
        return True  # only one (or zero) is maneuvering — no conflict
    return s.own.ra != s.intruder.ra


def _ra_always_complementary(s: TCASSystem) -> bool:
    """Once coordinated, the two RAs must be opposite senses."""
    if not s.ra_coordinated:
        return True
    if s.own.ra == "none" or s.intruder.ra == "none":
        return True
    return s.own.ra != s.intruder.ra


# ---------------------------------------------------------------------------
# Closed model: both pilots follow their RA
# ---------------------------------------------------------------------------

def _detect_conflict(s: TCASSystem) -> bool:
    return not s.conflict_detected


def _after_detect(s: TCASSystem) -> TCASSystem:
    return replace(s, conflict_detected=True)


def _issue_own_ra_climb(s: TCASSystem) -> bool:
    return s.conflict_detected and s.own.ra == "none" and s.intruder.ra in ("none", "descend")


def _after_own_climb(s: TCASSystem) -> TCASSystem:
    return replace(s, own=replace(s.own, ra="climb"))


def _issue_own_ra_descend(s: TCASSystem) -> bool:
    return s.conflict_detected and s.own.ra == "none" and s.intruder.ra in ("none", "climb")


def _after_own_descend(s: TCASSystem) -> TCASSystem:
    return replace(s, own=replace(s.own, ra="descend"))


def _issue_intruder_ra(s: TCASSystem) -> bool:
    return (
        s.conflict_detected
        and s.own.ra != "none"
        and s.intruder.ra == "none"
    )


def _after_intruder_ra(s: TCASSystem) -> TCASSystem:
    complementary = "descend" if s.own.ra == "climb" else "climb"
    return replace(
        s,
        intruder=replace(s.intruder, ra=complementary),
        ra_coordinated=True,
    )


def _own_maneuvers(s: TCASSystem) -> bool:
    return s.own.ra != "none" and not s.own.maneuvering and not s.own.atc_override


def _after_own_maneuvers(s: TCASSystem) -> TCASSystem:
    return replace(s, own=replace(s.own, maneuvering=True))


def _intruder_maneuvers(s: TCASSystem) -> bool:
    return s.intruder.ra != "none" and not s.intruder.maneuvering and not s.intruder.atc_override


def _after_intruder_maneuvers(s: TCASSystem) -> TCASSystem:
    return replace(s, intruder=replace(s.intruder, maneuvering=True))


def _resolution_complete(s: TCASSystem) -> bool:
    """Both aircraft are executing complementary maneuvers — RA is resolved."""
    return (
        s.own.maneuvering
        and s.intruder.maneuvering
        and s.own.ra != "none"
        and s.intruder.ra != "none"
        and s.own.ra != s.intruder.ra
    )


closed_model = Model(
    init=TCASSystem(),
    actions=[
        Action("detect-conflict",       _detect_conflict,      _after_detect),
        Action("own:ra=climb",          _issue_own_ra_climb,   _after_own_climb),
        Action("own:ra=descend",        _issue_own_ra_descend, _after_own_descend),
        Action("intruder:ra=coord",     _issue_intruder_ra,    _after_intruder_ra),
        Action("own:maneuver",          _own_maneuvers,        _after_own_maneuvers),
        Action("intruder:maneuver",     _intruder_maneuvers,   _after_intruder_maneuvers),
    ],
    invariants={
        "no-same-direction": _no_same_direction_maneuver,
        "ra-complementary":  _ra_always_complementary,
    },
    terminal=_resolution_complete,
)

# ---------------------------------------------------------------------------
# Open model: adversarial environment can inject a pilot deviation
# (Überlingen scenario: pilot follows ATC instead of TCAS RA)
# ---------------------------------------------------------------------------

PILOT_FOLLOWS_RA = Assumption(
    name="tcas:pilot-follows-ra",
    description=(
        "Pilots comply with TCAS Resolution Advisories and do not follow conflicting "
        "ATC instructions during an active RA. Violated in the 2002 Überlingen disaster."
    ),
    status="unverified",
    source="BFU Aircraft Accident Investigation Report AX001-1-2/02, 2004",
)


def _can_deviate(s: TCASSystem) -> bool:
    return s.own.ra != "none" and not s.own.maneuvering


def _after_deviate(s: TCASSystem) -> TCASSystem:
    # Pilot follows ATC descent instruction despite TCAS CLIMB RA —
    # the Überlingen scenario: own aircraft descends regardless of RA sense.
    return replace(
        s,
        own=replace(s.own, atc_override=True, ra="descend", maneuvering=True),
    )


ueberlingen_env: EnvironmentSpec[TCASSystem] = EnvironmentSpec(
    name="atc-override",
    behaviors=[
        Action("pilot:deviates-from-ra", _can_deviate, _after_deviate),
    ],
    assumptions={PILOT_FOLLOWS_RA.name: PILOT_FOLLOWS_RA},
)

# ---------------------------------------------------------------------------
# Open model with enforcement: "TCAS-only" policy locks out ATC during RA
# (the fix: modern avionics suppress ATC audio during active RA)
# ---------------------------------------------------------------------------

def _atc_suppressed(s: TCASSystem) -> bool:
    """ATC communication is suppressed while an RA is active."""
    return s.own.ra != "none" and s.conflict_detected


ATC_SUPPRESSED_DURING_RA = Assumption(
    name="tcas:atc-suppressed-during-ra",
    description=(
        "ATC audio/uplink is suppressed by the avionics while a TCAS RA is active, "
        "preventing conflicting ATC instructions from reaching the crew."
    ),
    status="unverified",
    source="ICAO Annex 2, Rules of the Air, Amendment 42 (post-Überlingen)",
)


def _can_deviate_if_not_suppressed(s: TCASSystem) -> bool:
    return _can_deviate(s) and not _atc_suppressed(s)


enforced_env: EnvironmentSpec[TCASSystem] = EnvironmentSpec(
    name="atc-override-enforced",
    behaviors=[
        Action("pilot:deviates-from-ra", _can_deviate_if_not_suppressed, _after_deviate),
    ],
    assumptions={ATC_SUPPRESSED_DURING_RA.name: ATC_SUPPRESSED_DURING_RA},
)

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("=" * 64)
    print("TCAS II RA coordination — musil open-system verification")
    print("=" * 64)

    # --- Scenario 1: closed model (both pilots follow RA) ---
    print("\n[1] Closed model: both pilots follow their RA")
    r1 = check(closed_model)
    if r1.ok:
        print("    PASS  Complementary RAs, no same-direction maneuver.")
    else:
        print("    FAIL")
        for step in r1.trace:
            print(f"      {step}")

    # --- Scenario 2: open model (Überlingen — pilot deviates) ---
    print("\n[2] Open model: Überlingen scenario (pilot follows ATC over TCAS)")
    r2 = check_open(closed_model, ueberlingen_env)
    if r2.ok:
        print("    PASS  (unexpected)")
    else:
        print("    FAIL  Invariant violated — both aircraft maneuvered in same direction.")
        print("    Trace:")
        for step in r2.result.trace:
            print(f"      {step}")
    if r2.unverified_assumptions:
        print("    Residual proof obligations:")
        for a in r2.unverified_assumptions:
            print(f"      [{a.status}] {a.name}")
            print(f"              {a.description}")

    # --- Scenario 3: open model with ATC suppression enforcement ---
    print("\n[3] Open model: ATC suppressed during RA (post-Überlingen fix)")
    r3 = check_open(closed_model, enforced_env)
    if r3.ok:
        print("    PASS  Complementary RAs hold even with adversarial environment.")
    else:
        print("    FAIL")
        for step in r3.result.trace:
            print(f"      {step}")
    if r3.unverified_assumptions:
        print("    Residual proof obligations:")
        for a in r3.unverified_assumptions:
            print(f"      [{a.status}] {a.name}")
            print(f"              {a.description}")


if __name__ == "__main__":
    main()
