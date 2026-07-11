"""Motion primitives for coverage driving.

``MotionExecutor`` abstracts *how* a straight leg or an in-place pivot is
measured. The current implementation is purely time-based (no wheel
encoders yet): distance and angle are converted to a drive duration using
calibration values from the config. Once encoders exist, an
``EncoderMotionExecutor`` with the same interface can replace it without
touching the coverage state machine.

Convention: positive pivot degrees = turn left (counter-clockwise),
matching the teleop mapping (left track backwards, right track forwards).
"""

from __future__ import annotations

import time
from typing import Protocol


class MotionExecutor(Protocol):
    """Non-blocking executor for one motion segment at a time."""

    def start_straight(self, distance_m: float) -> None:
        """Begin driving straight for ``distance_m`` (negative = backwards)."""

    def start_pivot(self, degrees: float) -> None:
        """Begin turning in place; positive = left, negative = right."""

    def tick(self) -> tuple[float, float] | None:
        """Return current (left, right) track speeds, or None when done."""

    def progress_m(self) -> float:
        """Distance travelled in the current/last straight segment."""

    def stop(self) -> None:
        """Abort the current segment."""


class TimedMotionExecutor:
    """Time-based dead reckoning executor (no encoders).

    Calibration values:
    - ``speed_m_s``: ground speed when driving straight at ``drive_speed``
    - ``pivot_deg_s``: rotation rate when pivoting at ``turn_speed``
    Both must be measured on the real robot and tuned via the web UI.
    """

    def __init__(
        self,
        drive_speed: float,
        turn_speed: float,
        speed_m_s: float,
        pivot_deg_s: float,
    ) -> None:
        self.drive_speed = drive_speed
        self.turn_speed = turn_speed
        self.speed_m_s = max(0.001, speed_m_s)
        self.pivot_deg_s = max(0.1, pivot_deg_s)
        self._mode: str | None = None  # "straight" | "pivot"
        self._started_at = 0.0
        self._duration_s = 0.0
        self._speeds = (0.0, 0.0)
        self._target_distance_m = 0.0

    def update_config(
        self,
        drive_speed: float,
        turn_speed: float,
        speed_m_s: float,
        pivot_deg_s: float,
    ) -> None:
        self.drive_speed = drive_speed
        self.turn_speed = turn_speed
        self.speed_m_s = max(0.001, speed_m_s)
        self.pivot_deg_s = max(0.1, pivot_deg_s)

    def start_straight(self, distance_m: float) -> None:
        direction = 1.0 if distance_m >= 0 else -1.0
        self._mode = "straight"
        self._target_distance_m = abs(distance_m)
        self._duration_s = abs(distance_m) / self.speed_m_s
        self._speeds = (direction * self.drive_speed, direction * self.drive_speed)
        self._started_at = time.monotonic()

    def start_pivot(self, degrees: float) -> None:
        # Positive = left: left track backwards, right track forwards
        direction = 1.0 if degrees >= 0 else -1.0
        self._mode = "pivot"
        self._target_distance_m = 0.0
        self._duration_s = abs(degrees) / self.pivot_deg_s
        self._speeds = (-direction * self.turn_speed, direction * self.turn_speed)
        self._started_at = time.monotonic()

    def tick(self) -> tuple[float, float] | None:
        if self._mode is None:
            return None
        if time.monotonic() - self._started_at >= self._duration_s:
            self._mode = None
            return None
        return self._speeds

    def progress_m(self) -> float:
        if self._duration_s <= 0.0:
            return self._target_distance_m
        elapsed = time.monotonic() - self._started_at
        fraction = min(1.0, elapsed / self._duration_s)
        return self._target_distance_m * fraction

    def stop(self) -> None:
        self._mode = None
        self._speeds = (0.0, 0.0)
