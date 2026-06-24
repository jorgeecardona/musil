# TCAS II resolution advisory coordination

**What this teaches:** how open-system verification handles real-world safety-critical protocols where correct behavior depends on assumptions about human actors. The four scenarios turn three aviation incidents into machine-checked counterexamples.

## The system

TCAS II (Traffic Alert and Collision Avoidance System) is mandated on all large commercial aircraft. When two aircraft are projected to come too close, each aircraft's TCAS independently selects a Resolution Advisory (RA): one climbs, one descends.

Coordination is not negotiated — it is imposed. The aircraft with the **lower ICAO 24-bit address** selects its RA first and immediately broadcasts a Vertical Resolution Advisory Complement (VRC) constraint to the intruder via an addressed Mode S message (BDS register 0x30, bits MB:23–26). The constraint encodes what the intruder must *not* do:

| Own selects | VRC sent         | Intruder is forced to |
|-------------|------------------|-----------------------|
| CLIMB       | `"no-climb"`     | DESCEND               |
| DESCEND     | `"no-descend"`   | CLIMB                 |

The intruder receives the constraint and selects the only remaining sense. Coordination completes in ~400–600 microseconds via a single UF=16/DF=16 Mode S round-trip.

The **safety invariant**: both aircraft must never maneuver in the same vertical direction simultaneously.

## Four scenarios

### 1 — Closed model: both pilots follow their RA

`check(closed_model)` → **PASS**

The VRC constraint forces complementary senses. The BFS finds no state where both aircraft maneuver in the same direction.

### 2 — Überlingen (pilot follows ATC over TCAS)

`check_open(closed_model, ueberlingen_env)` → **FAIL**

The environment injects a `pilot:deviates-from-ra` action: own aircraft receives CLIMB but follows an ATC descent instruction instead. Both aircraft end up descending. The 5-step counterexample:

```
detect-conflict → own:ra=climb → intruder:ra=forced →
own:maneuver (ATC descent) → intruder:maneuver → INVARIANT VIOLATED
```

This models the 2002 Überlingen disaster: 71 killed. DHL received CLIMB, Bashkirian received DESCEND. The Bashkirian crew followed the ATC controller instead of TCAS; both aircraft descended.

Residual obligation: `tcas:pilot-follows-ra` (unverified) — the assumption that pilots follow TCAS over ATC. Violated in the incident.

### 3 — ATC suppression enforcement (post-Überlingen fix)

`check_open(closed_model, enforced_env)` → **PASS**

ICAO Amendment 42 (2003) mandated that TCAS takes absolute priority over ATC during an active RA. The `enforced_env` gates the deviation action behind `not _atc_suppressed(s)` — if an RA is active, the deviation cannot fire. The BFS finds no violation.

Residual obligation: `tcas:atc-suppressed-during-ra` (unverified) — the assumption that avionics and crew procedures actually enforce the suppression. Verified formally, unverified operationally.

### 4 — v7.1 reversal + Tenerife (intruder ignores updated VRC)

`check_open(reversal_model, tenerife_env)` → **FAIL**

TCAS II v7.1 (DO-185B) added a *sense reversal*: if the intruder holds an RA but hasn't maneuvered within the timing window (5 s initial, 2.5 s reversal), own aircraft reverses its RA and broadcasts an updated VRC. This was triggered in the 2011 Tenerife near-collision when a Thomas Cook crew delayed responding to its RA.

The `tenerife_env` injects `intruder:maneuvers-with-old-ra`: the intruder executes its *original* RA while re-coordination is incomplete. The 7-step counterexample:

```
detect-conflict → own:ra=climb → intruder:ra=forced(descend) →
own:ra=reversed(now descend) → own:maneuver(descend) →
intruder:maneuvers-with-old-ra(descend) → INVARIANT VIOLATED
```

Both aircraft descend simultaneously. Residual obligation: `tcas:intruder-follows-reversal` (unverified, citing CIAIAC Report A-032/2011 and Eurocontrol SISG 2017 — ~25% non-compliance rate).

## Formal verification lineage

This model sits in a line of formal TCAS work:

- **Heimdahl & Leveson (1994–1996)** — RSML spec, found incompleteness/inconsistency in the original requirements.
- **Chan et al. (1998)** — SMV model checking; state explosion was the key obstacle.
- **Livadas, Lygeros & Lynch (2000)** — Hybrid I/O Automata; proved minimum separation theorems. `EnvironmentSpec.behaviors` = input actions, `Model.actions` = output actions — the same partition as Lynch's HIOA model.
- **Muñoz, Narkawicz & Chamberlain (2013)** — PVS proof of the RA detection algorithm.
- **Jeannin, Platzer et al. (2015/2017)** — KeYmaera dL proof of ACAS X; found real bugs in the deployed system.

## Source

```python
--8<-- "examples/tcas.py"
```

## Run it

```
python examples/tcas.py
```

## See also

- [K8s scheduler](k8s_scheduler.md) — the same `check_open` + `EnvironmentSpec` pattern on a simpler infrastructure problem.
- [Open systems (conceptual guide)](../open-systems.md) — the theory behind `Assumption`, `EnvironmentSpec`, and `check_open`.
- [Multi-environment composition](open_system_composed.md) — composing multiple adversarial environments simultaneously.
