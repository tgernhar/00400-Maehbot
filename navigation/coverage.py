"""Area coverage via outward rectangular spiral, plus web<->core IPC.

The robot starts at the center of a user-given rectangle (length x width in
meters) and drives an outward spiral: straight leg, 90-degree pivot, next
leg, ... Legs grow by ``track_spacing_m`` every other leg so adjacent lanes
overlap. Legs are clipped to the rectangle; after four consecutive clipped
legs the perimeter has been traced and coverage is complete.

Obstacles are checked with the LiDAR front sector while driving straight.
On detection the robot stops, waits (the obstacle may move), then tries a
sidestep detour towards the freer side. After ``max_avoid_attempts`` failed
tries the run is aborted.

IPC mirrors drive/recording: the web process queues ``coverage_command.json``,
the core consumes it and publishes ``coverage_status.json``.
"""

from __future__ import annotations

import json
import logging
import time
from enum import Enum
from typing import Any

from navigation.lidar import LidarReader
from navigation.motion import MotionExecutor
from storage.paths import StoragePaths

logger = logging.getLogger(__name__)

_EPS = 1e-9

# Heading index -> unit vector (x, y); 0 = +y (initial driving direction)
_LEFT_HEADINGS = [(0.0, 1.0), (-1.0, 0.0), (0.0, -1.0), (1.0, 0.0)]
_RIGHT_HEADINGS = [(0.0, 1.0), (1.0, 0.0), (0.0, -1.0), (-1.0, 0.0)]

# LiDAR sector centers (0 deg = front, clockwise)
_FRONT_DEG = 0.0
_RIGHT_DEG = 90.0
_LEFT_DEG = 270.0
_SIDE_SECTOR_DEG = 60.0


def generate_spiral_legs(
    length_m: float,
    width_m: float,
    first_leg_m: float,
    second_leg_m: float,
    track_spacing_m: float,
    max_legs: int = 500,
) -> list[float]:
    """Leg lengths of the outward spiral, clipped to the rectangle.

    ``length_m`` extends along the initial driving direction, ``width_m``
    perpendicular to it; the robot starts at the center. A 90-degree turn is
    implied between consecutive legs. Turn direction does not affect the
    lengths (the rectangle is symmetric around the start point).
    """
    half_l = max(0.0, length_m) / 2.0
    half_w = max(0.0, width_m) / 2.0
    legs: list[float] = []
    nominal: list[float] = []
    x = y = 0.0
    clipped_streak = 0
    for n in range(max_legs):
        if n == 0:
            nom = first_leg_m
        elif n == 1:
            nom = second_leg_m
        else:
            nom = nominal[n - 2] + track_spacing_m
        nominal.append(nom)
        hx, hy = _LEFT_HEADINGS[n % 4]
        if hy > 0:
            bound = half_l - y
        elif hy < 0:
            bound = half_l + y
        elif hx > 0:
            bound = half_w - x
        else:
            bound = half_w + x
        leg = min(nom, max(0.0, bound))
        legs.append(leg)
        x += hx * leg
        y += hy * leg
        clipped_streak = clipped_streak + 1 if leg < nom - _EPS else 0
        if clipped_streak >= 4:
            break
    while legs and legs[-1] <= _EPS:
        legs.pop()
    return legs


class CoverageState(str, Enum):
    IDLE = "idle"
    DRIVING = "driving"
    TURNING = "turning"
    AVOIDING = "avoiding"
    DONE = "done"
    ABORTED = "aborted"


class _AvoidPhase(str, Enum):
    WAIT = "wait"
    PIVOT_OUT = "pivot_out"
    DETOUR = "detour"
    PIVOT_BACK = "pivot_back"


class CoverageController:
    """Executes the spiral leg list; ticked from the core loop (~50 Hz)."""

    def __init__(
        self,
        executor: MotionExecutor,
        lidar: LidarReader | None,
        config: dict[str, Any],
    ) -> None:
        self.executor = executor
        self.lidar = lidar
        self.update_config(config)
        self.state = CoverageState.IDLE
        self._legs: list[float] = []
        self._leg_index = 0
        self._total_length_m = 0.0
        self._driven_length_m = 0.0
        self._remaining_leg_m = 0.0
        self._length_m = 0.0
        self._width_m = 0.0
        self._error: str | None = None
        self._avoid_phase = _AvoidPhase.WAIT
        self._avoid_until = 0.0
        self._avoid_attempts = 0
        self._avoid_sign = 1.0  # +1 = detour to the left, -1 = right

    def update_config(self, config: dict[str, Any]) -> None:
        cov = config.get("coverage", {})
        self.first_leg_m = float(cov.get("first_leg_m", 0.20))
        self.second_leg_m = float(cov.get("second_leg_m", 0.15))
        self.track_spacing_m = float(cov.get("track_spacing_m", 0.15))
        self.turn_left = str(cov.get("turn_direction", "left")).lower() != "right"
        self.obstacle_stop_m = float(cov.get("obstacle_stop_m", 0.30))
        self.obstacle_sector_deg = float(cov.get("obstacle_sector_deg", 60.0))
        self.obstacle_wait_s = float(cov.get("obstacle_wait_s", 3.0))
        self.detour_m = float(cov.get("detour_m", 0.30))
        self.max_avoid_attempts = int(cov.get("max_avoid_attempts", 3))
        if self.lidar:
            self.lidar.set_front_sector(self.obstacle_sector_deg)

    # -- commands ------------------------------------------------------------

    @property
    def active(self) -> bool:
        return self.state in (
            CoverageState.DRIVING,
            CoverageState.TURNING,
            CoverageState.AVOIDING,
        )

    def start(self, length_m: float, width_m: float) -> None:
        if self.active:
            self._error = "Bereichsfahrt läuft bereits"
            return
        if self.lidar is not None and not self.lidar.connected:
            self.state = CoverageState.ABORTED
            self._error = "LiDAR nicht verbunden — Start verweigert"
            logger.warning("Coverage start refused: LiDAR not connected")
            return
        self._legs = generate_spiral_legs(
            length_m,
            width_m,
            self.first_leg_m,
            self.second_leg_m,
            self.track_spacing_m,
        )
        if not self._legs:
            self.state = CoverageState.ABORTED
            self._error = "Bereich zu klein — keine Fahrstrecke"
            return
        self._length_m = length_m
        self._width_m = width_m
        self._leg_index = 0
        self._total_length_m = sum(self._legs)
        self._driven_length_m = 0.0
        self._error = None
        self._avoid_attempts = 0
        self._remaining_leg_m = self._legs[0]
        self.executor.start_straight(self._remaining_leg_m)
        self.state = CoverageState.DRIVING
        logger.info(
            "Coverage started: %.2f x %.2f m, %d legs, %.2f m total",
            length_m,
            width_m,
            len(self._legs),
            self._total_length_m,
        )

    def stop(self, reason: str | None = None) -> None:
        if not self.active:
            return
        self.executor.stop()
        self.state = CoverageState.ABORTED
        self._error = reason or "Manuell gestoppt"
        logger.info("Coverage stopped: %s", self._error)

    # -- main tick -----------------------------------------------------------

    def tick(self) -> tuple[float, float]:
        """Advance the state machine; returns (left, right) track speeds."""
        if not self.active:
            return (0.0, 0.0)

        if self.lidar is not None and not self.lidar.connected:
            self._finish_leg_progress()
            self.stop("LiDAR-Signal verloren — Fahrt gestoppt")
            return (0.0, 0.0)

        if self.state == CoverageState.DRIVING:
            return self._tick_driving()
        if self.state == CoverageState.TURNING:
            return self._tick_turning()
        return self._tick_avoiding()

    # -- driving / turning -----------------------------------------------------

    def _tick_driving(self) -> tuple[float, float]:
        if self._obstacle_ahead():
            self._pause_leg_for_avoidance()
            return (0.0, 0.0)
        speeds = self.executor.tick()
        if speeds is not None:
            return speeds
        # Leg finished
        self._driven_length_m += self._remaining_leg_m
        self._remaining_leg_m = 0.0
        self._leg_index += 1
        if self._leg_index >= len(self._legs):
            self.state = CoverageState.DONE
            logger.info("Coverage done: %.2f m driven", self._driven_length_m)
            return (0.0, 0.0)
        self.executor.start_pivot(90.0 if self.turn_left else -90.0)
        self.state = CoverageState.TURNING
        return self.executor.tick() or (0.0, 0.0)

    def _tick_turning(self) -> tuple[float, float]:
        speeds = self.executor.tick()
        if speeds is not None:
            return speeds
        self._avoid_attempts = 0
        self._remaining_leg_m = self._legs[self._leg_index]
        self.executor.start_straight(self._remaining_leg_m)
        self.state = CoverageState.DRIVING
        return self.executor.tick() or (0.0, 0.0)

    # -- obstacle avoidance ------------------------------------------------------

    def _obstacle_ahead(self) -> bool:
        if self.lidar is None:
            return False
        dist = self.lidar.min_distance_in_sector(_FRONT_DEG, self.obstacle_sector_deg)
        return dist is not None and dist <= self.obstacle_stop_m

    def _pause_leg_for_avoidance(self) -> None:
        driven = self.executor.progress_m()
        self.executor.stop()
        self._driven_length_m += driven
        self._remaining_leg_m = max(0.0, self._remaining_leg_m - driven)
        self._avoid_attempts += 1
        if self._avoid_attempts > self.max_avoid_attempts:
            self.stop("Hindernis nicht umfahrbar — Fahrt gestoppt")
            return
        self.state = CoverageState.AVOIDING
        self._avoid_phase = _AvoidPhase.WAIT
        self._avoid_until = time.monotonic() + self.obstacle_wait_s
        logger.info(
            "Obstacle ahead (attempt %d/%d), waiting %.1f s",
            self._avoid_attempts,
            self.max_avoid_attempts,
            self.obstacle_wait_s,
        )

    def _tick_avoiding(self) -> tuple[float, float]:
        if self._avoid_phase == _AvoidPhase.WAIT:
            if time.monotonic() < self._avoid_until:
                return (0.0, 0.0)
            if not self._obstacle_ahead():
                self._resume_leg()
                return (0.0, 0.0)
            self._avoid_sign = self._pick_detour_side()
            self.executor.start_pivot(90.0 * self._avoid_sign)
            self._avoid_phase = _AvoidPhase.PIVOT_OUT
            return self.executor.tick() or (0.0, 0.0)

        if self._avoid_phase == _AvoidPhase.PIVOT_OUT:
            speeds = self.executor.tick()
            if speeds is not None:
                return speeds
            self.executor.start_straight(self.detour_m)
            self._avoid_phase = _AvoidPhase.DETOUR
            return self.executor.tick() or (0.0, 0.0)

        if self._avoid_phase == _AvoidPhase.DETOUR:
            if self._obstacle_ahead():
                # Detour blocked as well -> counts as a failed attempt
                self.executor.stop()
                self._avoid_attempts += 1
                if self._avoid_attempts > self.max_avoid_attempts:
                    self.stop("Hindernis nicht umfahrbar — Fahrt gestoppt")
                    return (0.0, 0.0)
                # Turn back to original heading, then wait again
                self.executor.start_pivot(-90.0 * self._avoid_sign)
                self._avoid_phase = _AvoidPhase.PIVOT_BACK
                return self.executor.tick() or (0.0, 0.0)
            speeds = self.executor.tick()
            if speeds is not None:
                return speeds
            self.executor.start_pivot(-90.0 * self._avoid_sign)
            self._avoid_phase = _AvoidPhase.PIVOT_BACK
            return self.executor.tick() or (0.0, 0.0)

        # PIVOT_BACK
        speeds = self.executor.tick()
        if speeds is not None:
            return speeds
        if self._obstacle_ahead():
            self._avoid_phase = _AvoidPhase.WAIT
            self._avoid_until = time.monotonic() + self.obstacle_wait_s
            return (0.0, 0.0)
        self._resume_leg()
        return (0.0, 0.0)

    def _pick_detour_side(self) -> float:
        """+1 = left, -1 = right; picks the side with more LiDAR clearance."""
        if self.lidar is None:
            return 1.0
        left = self.lidar.min_distance_in_sector(_LEFT_DEG, _SIDE_SECTOR_DEG)
        right = self.lidar.min_distance_in_sector(_RIGHT_DEG, _SIDE_SECTOR_DEG)
        left_clear = left if left is not None else float("inf")
        right_clear = right if right is not None else float("inf")
        return 1.0 if left_clear >= right_clear else -1.0

    def _resume_leg(self) -> None:
        if self._remaining_leg_m <= _EPS:
            # Leg was effectively finished; move on via the driving branch
            self.state = CoverageState.DRIVING
            self.executor.start_straight(0.0)
            return
        self.executor.start_straight(self._remaining_leg_m)
        self.state = CoverageState.DRIVING

    def _finish_leg_progress(self) -> None:
        if self.state == CoverageState.DRIVING:
            driven = self.executor.progress_m()
            self._driven_length_m += driven
            self._remaining_leg_m = max(0.0, self._remaining_leg_m - driven)

    # -- status ------------------------------------------------------------------

    def status_dict(self) -> dict[str, Any]:
        progress = 0.0
        if self._total_length_m > 0:
            done = self._driven_length_m
            if self.state == CoverageState.DRIVING:
                done += self.executor.progress_m()
            progress = min(100.0, 100.0 * done / self._total_length_m)
        if self.state == CoverageState.DONE:
            progress = 100.0
        return {
            "state": self.state.value,
            "length_m": self._length_m,
            "width_m": self._width_m,
            "leg_index": self._leg_index,
            "leg_count": len(self._legs),
            "progress_percent": round(progress, 1),
            "lidar_connected": bool(self.lidar.connected) if self.lidar else False,
            "error": self._error,
        }


# -- file-based IPC (web -> core commands, core -> web status) -------------------


def default_coverage_status() -> dict[str, Any]:
    return {
        "state": CoverageState.IDLE.value,
        "length_m": 0.0,
        "width_m": 0.0,
        "leg_index": 0,
        "leg_count": 0,
        "progress_percent": 0.0,
        "lidar_connected": False,
        "error": None,
    }


def read_coverage_status(paths: StoragePaths) -> dict[str, Any]:
    path = paths.coverage_status_path
    if not path.exists():
        return default_coverage_status()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {**default_coverage_status(), **data}
    except (json.JSONDecodeError, OSError):
        return default_coverage_status()


def write_coverage_status(paths: StoragePaths, status: dict[str, Any]) -> None:
    paths.coverage_status_path.write_text(
        json.dumps(status, ensure_ascii=False),
        encoding="utf-8",
    )


def queue_coverage_command(
    paths: StoragePaths,
    action: str,
    length_m: float = 0.0,
    width_m: float = 0.0,
) -> None:
    payload: dict[str, Any] = {"action": action, "ts": time.time()}
    if action == "start":
        payload["length_m"] = float(length_m)
        payload["width_m"] = float(width_m)
    paths.coverage_command_path.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )


def consume_coverage_command(paths: StoragePaths) -> dict[str, Any] | None:
    path = paths.coverage_command_path
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        path.unlink(missing_ok=True)
        return data
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Invalid coverage command file: %s", exc)
        path.unlink(missing_ok=True)
        return None
