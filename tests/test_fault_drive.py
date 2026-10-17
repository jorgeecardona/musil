"""FaultSchedule.drive (#33 need 2): one schedule drives both the model (in the simulator) and a real
fleet, firing apply/heal callbacks at each fault boundary. Tested on a virtual clock — no real waiting."""

from __future__ import annotations

from musil.sim import Crash, FaultDrive, FaultSchedule, Partition


class Recorder:
    """Virtual clock + callback log: `sleep` advances time, `apply`/`heal` record (kind, type, time)."""

    def __init__(self) -> None:
        self.t = 0.0
        self.log: list[tuple[str, str, float]] = []
        self.sleeps: list[float] = []

    def sleep(self, d: float) -> None:
        self.sleeps.append(d)
        self.t += d

    def apply(self, fault: Partition | Crash) -> None:
        self.log.append(("apply", type(fault).__name__, self.t))

    def heal(self, fault: Partition | Crash) -> None:
        self.log.append(("heal", type(fault).__name__, self.t))


def test_drive_fires_boundaries_in_time_order_and_paces_with_sleep() -> None:
    schedule = FaultSchedule(
        partitions=(Partition(frozenset({("n1", "n2")}), start=1, end=3),),
        crashes=(Crash(node="n3", start=2, end=5),),
    )
    rec = Recorder()
    report = schedule.drive(rec.apply, rec.heal, seconds_per_tick=1.0, sleep=rec.sleep)

    assert rec.log == [
        ("apply", "Partition", 1.0),  # partition window opens at t=1
        ("apply", "Crash", 2.0),  # crash opens at t=2
        ("heal", "Partition", 3.0),  # partition heals at t=3
        ("heal", "Crash", 5.0),  # crash heals at t=5
    ]
    assert rec.sleeps == [1.0, 1.0, 1.0, 2.0]  # paced to the gaps between boundaries
    assert report == FaultDrive(applied=2, healed=2, heal_time=5)


def test_seconds_per_tick_scales_wall_time() -> None:
    schedule = FaultSchedule(crashes=(Crash(node="n1", start=0, end=4),))
    rec = Recorder()
    schedule.drive(rec.apply, rec.heal, seconds_per_tick=0.5, sleep=rec.sleep)
    # apply at t=0 (no sleep), heal at t=4 -> one sleep of 4 ticks * 0.5s = 2.0s
    assert rec.sleeps == [2.0]
    assert [e[0] for e in rec.log] == ["apply", "heal"]


def test_heal_fires_before_apply_at_a_shared_instant() -> None:
    # a crash ends exactly when a partition begins: the link should free before the next cut
    schedule = FaultSchedule(
        partitions=(Partition(frozenset({("a", "b")}), start=3, end=6),),
        crashes=(Crash(node="n1", start=0, end=3),),
    )
    rec = Recorder()
    schedule.drive(rec.apply, rec.heal, sleep=rec.sleep)
    # at t=3, heal(Crash) must come before apply(Partition)
    assert rec.log == [
        ("apply", "Crash", 0.0),
        ("heal", "Crash", 3.0),
        ("apply", "Partition", 3.0),
        ("heal", "Partition", 6.0),
    ]


def test_empty_schedule_drives_nothing() -> None:
    rec = Recorder()
    report = FaultSchedule().drive(rec.apply, rec.heal, sleep=rec.sleep)
    assert rec.log == []
    assert report == FaultDrive(applied=0, healed=0, heal_time=0)
