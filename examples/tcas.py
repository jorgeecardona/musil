"""TCAS II Resolution Advisory coordination example.

Own aircraft (lower ICAO address) detects a conflict and selects a Resolution
Advisory (RA) sense. It immediately broadcasts a Vertical Resolution Advisory
Complement (VRC) constraint to the intruder via a UF=16 addressed Mode S
message (BDS register 0x30, bits MB:23-26). The constraint encodes what the
intruder must NOT do:

  - Own selects CLIMB  → VRC "no-climb"   → intruder forced to DESCEND
  - Own selects DESCEND → VRC "no-descend" → intruder forced to CLIMB

The intruder receives the constraint in the DF=16 reply and selects the only
remaining sense. Tie-breaking uses the ICAO 24-bit address: the higher-addressed
aircraft adapts its RA to produce complement. This is the actual coordination
protocol of TCAS II v7.1 (RTCA DO-185B / EUROCAE ED-143).

The safety invariant:

  "Both aircraft never maneuver in the same vertical direction simultaneously."

Four scenarios are checked:

1. CLOSED — both pilots follow their RA → invariant holds.
2. OPEN (Überlingen) — environment injects pilot_deviation: a pilot follows ATC
   instead of TCAS. Invariant violated. Unverified assumption PILOT_FOLLOWS_RA
   surfaces as a residual proof obligation.
3. OPEN with enforcement — a "TCAS-only" policy suppresses ATC during an active
   RA. Invariant holds; PILOT_FOLLOWS_RA is no longer needed.
4. OPEN (Tenerife, v7.1 reversal) — model includes the v7.1 reversal system
   action (own reverses sense when intruder hasn't maneuvered). Environment
   injects intruder non-compliance: intruder maneuvers on its old RA while
   re-coordination is incomplete. Invariant violated. Unverified assumption
   INTRUDER_FOLLOWS_REVERSAL surfaces.

Background — Überlingen (2002): 71 killed. TCAS issued correct complementary
RAs (DHL: CLIMB, Bashkirian: DESCEND). The Bashkirian crew followed the ATC
controller instead; both aircraft descended. The system worked; the assumption
that pilots follow TCAS over ATC did not hold.

Background — Tenerife (2011): A Thomas Cook crew failed to follow its RA
promptly. This triggered a v7.1 sense reversal on the Finnair aircraft. The
reversal mechanism (added in DO-185B) handles the case where the intruder fails
to respond within the required timing window (ICAO Doc 9863: 5 seconds for
initial RA, 2.5 seconds for reversals). Without the assumption that the intruder
re-coordinates after a reversal, the invariant can be violated.

Run::

    uv run python examples/tcas.py
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

from musil import Action, Model, check
from musil.env import Assumption, EnvironmentSpec, check_open

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

RAState = Literal["none", "climb", "descend"]
VRCConstraint = Literal["none", "no-climb", "no-descend"]


@dataclass(frozen=True)
class Aircraft:
    ra: RAState = "none"                 # current RA sense
    vrc_received: VRCConstraint = "none" # VRC constraint received from peer (via Mode S)
    maneuvering: bool = False            # pilot has begun the maneuver
    atc_override: bool = False           # pilot chose ATC instruction over TCAS RA


@dataclass(frozen=True)
class TCASSystem:
    """State of two TCAS-equipped aircraft in a conflict."""

    own: Aircraft = Aircraft()
    intruder: Aircraft = Aircraft()
    conflict_detected: bool = False
    ra_coordinated: bool = False  # both RAs are complementary and acknowledged
    reversed: bool = False        # v7.1: at most one sense reversal per encounter


# ---------------------------------------------------------------------------
# Safety invariants
# ---------------------------------------------------------------------------

def _no_same_direction_maneuver(s: TCASSystem) -> bool:
    """Both aircraft must never maneuver in the same vertical direction."""
    if not (s.own.maneuvering and s.intruder.maneuvering):
        return True
    return s.own.ra != s.intruder.ra


def _ra_always_complementary(s: TCASSystem) -> bool:
    """Once coordinated, the two RAs must be opposite senses."""
    if not s.ra_coordinated:
        return True
    if s.own.ra == "none" or s.intruder.ra == "none":
        return True
    return s.own.ra != s.intruder.ra


# ---------------------------------------------------------------------------
# Closed model actions: both pilots follow their RA
# ---------------------------------------------------------------------------

def _detect_conflict(s: TCASSystem) -> bool:
    return not s.conflict_detected


def _after_detect(s: TCASSystem) -> TCASSystem:
    return replace(s, conflict_detected=True)


def _issue_own_ra_climb(s: TCASSystem) -> bool:
    # Own selects CLIMB; only allowed if intruder hasn't constrained us otherwise.
    return (
        s.conflict_detected
        and s.own.ra == "none"
        and s.intruder.ra in ("none", "descend")
        and s.intruder.vrc_received != "no-climb"
    )


def _after_own_climb(s: TCASSystem) -> TCASSystem:
    # Own selects CLIMB and broadcasts VRC "no-climb" to intruder (MB:24 = 1:
    # "do not pass above me" → intruder cannot climb past own → must descend).
    return replace(
        s,
        own=replace(s.own, ra="climb"),
        intruder=replace(s.intruder, vrc_received="no-climb"),
    )


def _issue_own_ra_descend(s: TCASSystem) -> bool:
    return (
        s.conflict_detected
        and s.own.ra == "none"
        and s.intruder.ra in ("none", "climb")
        and s.intruder.vrc_received != "no-descend"
    )


def _after_own_descend(s: TCASSystem) -> TCASSystem:
    # Own selects DESCEND and broadcasts VRC "no-descend" to intruder (MB:23 = 1:
    # "do not pass below me" → intruder cannot descend past own → must climb).
    return replace(
        s,
        own=replace(s.own, ra="descend"),
        intruder=replace(s.intruder, vrc_received="no-descend"),
    )


def _issue_intruder_ra(s: TCASSystem) -> bool:
    # Intruder issues its RA after receiving a VRC constraint from own.
    return (
        s.conflict_detected
        and s.own.ra != "none"
        and s.intruder.ra == "none"
        and s.intruder.vrc_received != "none"
    )


def _after_intruder_ra(s: TCASSystem) -> TCASSystem:
    # Intruder is forced by the VRC constraint it received:
    #   "no-climb"   → own is climbing → intruder must descend
    #   "no-descend" → own is descending → intruder must climb
    forced: RAState = "descend" if s.intruder.vrc_received == "no-climb" else "climb"
    return replace(
        s,
        intruder=replace(s.intruder, ra=forced),
        ra_coordinated=True,
    )


def _own_maneuvers(s: TCASSystem) -> bool:
    return s.own.ra != "none" and not s.own.maneuvering and not s.own.atc_override


def _after_own_maneuvers(s: TCASSystem) -> TCASSystem:
    return replace(s, own=replace(s.own, maneuvering=True))


def _intruder_maneuvers(s: TCASSystem) -> bool:
    # Intruder maneuvers only when coordinated — its RA reflects the current
    # VRC constraint. This prevents it from executing a stale RA after a reversal.
    return (
        s.intruder.ra != "none"
        and not s.intruder.maneuvering
        and not s.intruder.atc_override
        and s.ra_coordinated
    )


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
        Action("detect-conflict",   _detect_conflict,    _after_detect),
        Action("own:ra=climb",      _issue_own_ra_climb, _after_own_climb),
        Action("own:ra=descend",    _issue_own_ra_descend, _after_own_descend),
        Action("intruder:ra=forced", _issue_intruder_ra,  _after_intruder_ra),
        Action("own:maneuver",      _own_maneuvers,      _after_own_maneuvers),
        Action("intruder:maneuver", _intruder_maneuvers, _after_intruder_maneuvers),
    ],
    invariants={
        "no-same-direction": _no_same_direction_maneuver,
        "ra-complementary":  _ra_always_complementary,
    },
    terminal=_resolution_complete,
)

# ---------------------------------------------------------------------------
# v7.1 reversal system action
# (DO-185B condition: intruder has RA but hasn't maneuvered within timing window)
# ---------------------------------------------------------------------------

def _can_reverse(s: TCASSystem) -> bool:
    """
    Own reverses its RA when intruder holds an RA but hasn't maneuvered.
    v7.1 allows at most one reversal per encounter (≥10 s since initial RA,
    ≥4 s to CPA, 100-foot VMD threshold). We model the one-reversal limit with
    the `reversed` flag.
    """
    return (
        s.own.ra != "none"
        and s.intruder.ra != "none"
        and not s.intruder.maneuvering
        and s.ra_coordinated
        and not s.reversed
    )


def _after_reverse(s: TCASSystem) -> TCASSystem:
    """
    Own flips its RA sense and broadcasts the updated VRC. Coordination resets
    so the intruder must re-coordinate before maneuvering. At most one reversal
    is allowed per encounter (DO-185B timing gate).

    The intruder's old RA is NOT cleared here — it still holds its original
    sense. In the closed model, a `intruder:ra=recoord` action lets the intruder
    update to the new complementary sense. In the adversarial environment, the
    intruder can instead maneuver on its stale RA before re-coordinating.
    """
    new_ra: RAState = "descend" if s.own.ra == "climb" else "climb"
    new_vrc: VRCConstraint = "no-climb" if new_ra == "climb" else "no-descend"
    return replace(
        s,
        own=replace(s.own, ra=new_ra),
        intruder=replace(s.intruder, vrc_received=new_vrc),  # old ra preserved
        ra_coordinated=False,
        reversed=True,
    )


def _intruder_recoordinates(s: TCASSystem) -> bool:
    """Intruder updates its RA to comply with the new VRC after own's reversal."""
    return (
        not s.ra_coordinated
        and s.own.ra != "none"
        and s.intruder.ra != "none"
        and s.intruder.vrc_received != "none"
    )


def _after_intruder_recoordinates(s: TCASSystem) -> TCASSystem:
    forced: RAState = "descend" if s.intruder.vrc_received == "no-climb" else "climb"
    return replace(
        s,
        intruder=replace(s.intruder, ra=forced),
        ra_coordinated=True,
    )


reversal_model = Model(
    init=TCASSystem(),
    actions=[
        Action("detect-conflict",     _detect_conflict,           _after_detect),
        Action("own:ra=climb",        _issue_own_ra_climb,        _after_own_climb),
        Action("own:ra=descend",      _issue_own_ra_descend,      _after_own_descend),
        Action("intruder:ra=forced",  _issue_intruder_ra,         _after_intruder_ra),
        Action("own:ra=reversed",     _can_reverse,               _after_reverse),
        Action("intruder:ra=recoord", _intruder_recoordinates,    _after_intruder_recoordinates),
        Action("own:maneuver",        _own_maneuvers,             _after_own_maneuvers),
        Action("intruder:maneuver",   _intruder_maneuvers,        _after_intruder_maneuvers),
    ],
    invariants={
        "no-same-direction": _no_same_direction_maneuver,
        "ra-complementary":  _ra_always_complementary,
    },
    terminal=_resolution_complete,
)

# ---------------------------------------------------------------------------
# Open model — Scenario 2: Überlingen (pilot follows ATC over TCAS)
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
# Open model — Scenario 3: ATC suppression enforcement (post-Überlingen fix)
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
# Open model — Scenario 4: v7.1 reversal + intruder non-compliance (Tenerife)
# ---------------------------------------------------------------------------

INTRUDER_FOLLOWS_REVERSAL = Assumption(
    name="tcas:intruder-follows-reversal",
    description=(
        "When own aircraft issues a v7.1 sense reversal and broadcasts an updated "
        "VRC constraint, the intruder crew maneuvers in the newly required sense "
        "rather than executing the original RA. Failure observed in the 2011 "
        "Tenerife near-collision (Thomas Cook / Finnair). Eurocontrol (2017) reports "
        "approximately 25% of TCAS encounters involve some pilot non-compliance."
    ),
    status="unverified",
    source="CIAIAC Report A-032/2011; Eurocontrol SISG 2017 RA compliance study",
)


def _can_maneuver_with_old_ra(s: TCASSystem) -> bool:
    # Intruder maneuvers on its stale RA while re-coordination is incomplete.
    # This is the adversarial action: intruder ignores the reversal notification.
    return (
        s.intruder.ra != "none"
        and not s.intruder.maneuvering
        and not s.ra_coordinated  # reversal in progress
    )


def _after_maneuver_with_old_ra(s: TCASSystem) -> TCASSystem:
    return replace(s, intruder=replace(s.intruder, maneuvering=True))


tenerife_env: EnvironmentSpec[TCASSystem] = EnvironmentSpec(
    name="intruder-ignores-reversal",
    behaviors=[
        Action(
            "intruder:maneuvers-with-old-ra",
            _can_maneuver_with_old_ra,
            _after_maneuver_with_old_ra,
        ),
    ],
    assumptions={INTRUDER_FOLLOWS_REVERSAL.name: INTRUDER_FOLLOWS_REVERSAL},
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
        print("    PASS  VRC constraint forces complementary RAs; no same-direction maneuver.")
    else:
        print("    FAIL")
        for step in r1.trace:
            print(f"      {step}")

    # --- Scenario 2: open model (Überlingen — pilot deviates from RA) ---
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

    # --- Scenario 4: v7.1 reversal + intruder ignores new coordination ---
    print("\n[4] Open model: v7.1 reversal + intruder ignores updated VRC (Tenerife)")
    r4 = check_open(reversal_model, tenerife_env)
    if r4.ok:
        print("    PASS  (unexpected)")
    else:
        print("    FAIL  Invariant violated — intruder maneuvered on stale RA after reversal.")
        print("    Trace:")
        for step in r4.result.trace:
            print(f"      {step}")
    if r4.unverified_assumptions:
        print("    Residual proof obligations:")
        for a in r4.unverified_assumptions:
            print(f"      [{a.status}] {a.name}")
            print(f"              {a.description}")


if __name__ == "__main__":
    main()
