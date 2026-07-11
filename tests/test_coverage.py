"""Tests for spiral coverage: leg generator, state machine, timed executor."""

from __future__ import annotations

import time

import pytest

from navigation.coverage import (
    CoverageController,
    CoverageState,
    generate_spiral_legs,
)
from navigation.motion import TimedMotionExecutor


# -- generate_spiral_legs -----------------------------------------------------


def test_spiral_legs_grow_by_track_spacing() -> None:
    legs = generate_spiral_legs(
        length_m=100.0,
        width_m=100.0,
        first_leg_m=0.20,
        second_leg_m=0.15,
        track_spacing_m=0.15,
        max_legs=8,
    )
    assert legs[:8] == pytest.approx([0.20, 0.15, 0.35, 0.30, 0.50, 0.45, 0.65, 0.60])


def test_spiral_legs_clip_to_area_and_terminate() -> None:
    legs = generate_spiral_legs(
        length_m=1.0,
        width_m=1.0,
        first_leg_m=0.20,
        second_leg_m=0.15,
        track_spacing_m=0.15,
    )
    # Stays finite and no leg exceeds the rectangle diagonal extent
    assert 0 < len(legs) < 50
    assert max(legs) <= 1.0 + 1e-9

    # End position must lie inside the rectangle (dead-reckoned, left turns)
    x = y = 0.0
    headings = [(0.0, 1.0), (-1.0, 0.0), (0.0, -1.0), (1.0, 0.0)]
    for i, leg in enumerate(legs):
        hx, hy = headings[i % 4]
        x += hx * leg
        y += hy * leg
        assert abs(x) <= 0.5 + 1e-9
        assert abs(y) <= 0.5 + 1e-9


def test_spiral_legs_empty_for_zero_area() -> None:
    assert generate_spiral_legs(0.0, 0.0, 0.2, 0.15, 0.15) == []


# -- TimedMotionExecutor ------------------------------------------------------


def test_timed_executor_straight_duration() -> None:
    ex = TimedMotionExecutor(drive_speed=0.5, turn_speed=0.5, speed_m_s=10.0, pivot_deg_s=45.0)
    ex.start_straight(1.0)  # 1 m at 10 m/s -> 0.1 s
    assert ex.tick() == (0.5, 0.5)
    time.sleep(0.12)
    assert ex.tick() is None


def test_timed_executor_reverse_and_pivot_signs() -> None:
    ex = TimedMotionExecutor(drive_speed=0.6, turn_speed=0.4, speed_m_s=100.0, pivot_deg_s=9000.0)
    ex.start_straight(-1.0)
    assert ex.tick() == (-0.6, -0.6)
    ex.start_pivot(90.0)  # left: left track backwards
    assert ex.tick() == (-0.4, 0.4)
    ex.start_pivot(-90.0)  # right
    assert ex.tick() == (0.4, -0.4)


def test_timed_executor_progress() -> None:
    ex = TimedMotionExecutor(drive_speed=0.5, turn_speed=0.5, speed_m_s=10.0, pivot_deg_s=45.0)
    ex.start_straight(1.0)
    time.sleep(0.05)
    assert 0.2 <= ex.progress_m() <= 1.0


# -- CoverageController state machine -----------------------------------------


class InstantExecutor:
    """Completes every segment after exactly one tick (deterministic tests)."""

    def __init__(self) -> None:
        self.log: list[tuple[str, float]] = []
        self._pending: tuple[float, float] | None = None
        self._distance = 0.0

    def start_straight(self, distance_m: float) -> None:
        self.log.append(("straight", round(distance_m, 6)))
        self._distance = abs(distance_m)
        self._pending = (0.5, 0.5)

    def start_pivot(self, degrees: float) -> None:
        self.log.append(("pivot", degrees))
        self._distance = 0.0
        self._pending = (-0.5, 0.5)

    def tick(self) -> tuple[float, float] | None:
        speeds, self._pending = self._pending, None
        return speeds

    def progress_m(self) -> float:
        return self._distance

    def stop(self) -> None:
        self._pending = None


class FakeLidar:
    def __init__(self) -> None:
        self.connected = True
        self.front_distance: float | None = 10.0
        self.left_distance: float | None = 10.0
        self.right_distance: float | None = 10.0

    def set_front_sector(self, width_deg: float) -> None:
        pass

    def min_distance_in_sector(self, center_deg: float, width_deg: float) -> float | None:
        if center_deg == 0.0:
            return self.front_distance
        if center_deg == 270.0:
            return self.left_distance
        return self.right_distance


def make_controller(
    lidar: FakeLidar | None,
    **overrides: object,
) -> tuple[CoverageController, InstantExecutor]:
    cov = {
        "first_leg_m": 0.20,
        "second_leg_m": 0.15,
        "track_spacing_m": 0.15,
        "turn_direction": "left",
        "obstacle_stop_m": 0.30,
        "obstacle_sector_deg": 60,
        "obstacle_wait_s": 0.0,
        "detour_m": 0.30,
        "max_avoid_attempts": 2,
    }
    cov.update(overrides)
    executor = InstantExecutor()
    controller = CoverageController(executor, lidar, {"coverage": cov})
    return controller, executor


def run_until_inactive(controller: CoverageController, max_ticks: int = 10000) -> int:
    ticks = 0
    while controller.active and ticks < max_ticks:
        controller.tick()
        ticks += 1
    assert ticks < max_ticks, "state machine did not terminate"
    return ticks


def test_full_run_completes_and_alternates_segments() -> None:
    controller, executor = make_controller(FakeLidar())
    controller.start(1.0, 1.0)
    assert controller.state == CoverageState.DRIVING
    run_until_inactive(controller)
    assert controller.state == CoverageState.DONE
    assert controller.status_dict()["progress_percent"] == 100.0

    straights = [entry for entry in executor.log if entry[0] == "straight"]
    pivots = [entry for entry in executor.log if entry[0] == "pivot"]
    assert straights[0] == ("straight", 0.20)
    assert straights[1] == ("straight", 0.15)
    assert straights[2] == ("straight", 0.35)
    assert straights[3] == ("straight", 0.30)
    # One pivot between consecutive legs, all 90 degrees left
    assert len(pivots) == len(straights) - 1
    assert all(deg == 90.0 for (_kind, deg) in pivots)


def test_right_turn_direction() -> None:
    controller, executor = make_controller(FakeLidar(), turn_direction="right")
    controller.start(0.5, 0.5)
    run_until_inactive(controller)
    pivots = [deg for (kind, deg) in executor.log if kind == "pivot"]
    assert pivots and all(deg == -90.0 for deg in pivots)


def test_start_refused_without_lidar_connection() -> None:
    lidar = FakeLidar()
    lidar.connected = False
    controller, _executor = make_controller(lidar)
    controller.start(1.0, 1.0)
    assert controller.state == CoverageState.ABORTED
    assert "LiDAR" in (controller.status_dict()["error"] or "")


def test_runs_without_lidar_object() -> None:
    controller, _executor = make_controller(None)
    controller.start(0.5, 0.5)
    run_until_inactive(controller)
    assert controller.state == CoverageState.DONE


def test_obstacle_triggers_detour_then_resumes() -> None:
    lidar = FakeLidar()
    controller, executor = make_controller(lidar)
    controller.start(1.0, 1.0)

    # Obstacle appears while driving the first leg
    lidar.front_distance = 0.2
    controller.tick()
    assert controller.state == CoverageState.AVOIDING

    # Still blocked after the wait -> pivot out (left is freer by default)
    controller.tick()
    assert ("pivot", 90.0) in executor.log

    # Clear the way for the detour and everything after
    lidar.front_distance = 10.0
    run_until_inactive(controller)
    assert controller.state == CoverageState.DONE

    kinds = [kind for (kind, _v) in executor.log]
    assert "straight" in kinds
    # Detour drove sideways and pivoted back
    assert ("straight", 0.30) in executor.log
    assert ("pivot", -90.0) in executor.log


def test_detour_picks_freer_side() -> None:
    lidar = FakeLidar()
    lidar.left_distance = 0.1  # left blocked
    lidar.right_distance = 5.0
    controller, executor = make_controller(lidar)
    controller.start(1.0, 1.0)

    lidar.front_distance = 0.2
    controller.tick()  # -> AVOIDING (wait 0 s)
    controller.tick()  # -> pivot out towards the right
    assert ("pivot", -90.0) in executor.log


def test_persistent_obstacle_aborts() -> None:
    lidar = FakeLidar()
    controller, _executor = make_controller(lidar, max_avoid_attempts=1)
    controller.start(1.0, 1.0)

    lidar.front_distance = 0.1  # blocked everywhere, forever
    ticks = 0
    while controller.active and ticks < 1000:
        controller.tick()
        ticks += 1
    assert controller.state == CoverageState.ABORTED
    assert "Hindernis" in (controller.status_dict()["error"] or "")


def test_manual_stop_aborts() -> None:
    controller, _executor = make_controller(FakeLidar())
    controller.start(1.0, 1.0)
    controller.stop("Manuell gestoppt")
    assert controller.state == CoverageState.ABORTED
    assert controller.tick() == (0.0, 0.0)


def test_lidar_loss_mid_run_aborts() -> None:
    lidar = FakeLidar()
    controller, _executor = make_controller(lidar)
    controller.start(1.0, 1.0)
    controller.tick()
    lidar.connected = False
    controller.tick()
    assert controller.state == CoverageState.ABORTED
    assert "LiDAR" in (controller.status_dict()["error"] or "")
