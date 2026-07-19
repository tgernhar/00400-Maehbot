"""Motion primitives for coverage driving.

``MotionExecutor`` abstracts *how* a straight leg or an in-place pivot is
measured:

- ``TimedMotionExecutor``: time-based dead reckoning from calibration values
  (fallback when no encoders are wired or calibrated).
- ``EncoderMotionExecutor``: measures the real wheel travel via quadrature
  encoders; straight legs end at the measured distance, pivots at the
  measured arc length (track width based).

Convention: positive pivot degrees = turn left (counter-clockwise),
matching the teleop mapping (left track backwards, right track forwards).
"""

from __future__ import annotations

import logging
import math
import time
from typing import Protocol

from drive.encoder import EncoderPair

logger = logging.getLogger(__name__)


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


class EncoderMotionExecutor:
    """Encoder-based executor: segments end at the *measured* wheel travel.

    - Straight legs: mean of both signed track distances; a proportional trim
      slows the faster track so the robot keeps a straight line.
    - Pivots: mean of both absolute arc lengths; target arc per track is
      ``track_width_m / 2 * angle_rad``.

    ``speed_m_s`` / ``pivot_deg_s`` are only used for a safety timeout: if a
    segment takes far longer than the calibration predicts (stalled wheel,
    lost pulses), the segment is aborted so coverage cannot hang forever.
    """

    TIMEOUT_FACTOR = 3.0
    MIN_TIMEOUT_S = 2.0
    TRIM_GAIN = 2.0  # speed trim per meter of left/right distance difference
    MAX_TRIM = 0.3   # cap trim at 30 % of drive_speed

    def __init__(
        self,
        encoders: EncoderPair,
        drive_speed: float,
        turn_speed: float,
        speed_m_s: float,
        pivot_deg_s: float,
        track_width_m: float,
    ) -> None:
        self.encoders = encoders
        self.drive_speed = drive_speed
        self.turn_speed = turn_speed
        self.speed_m_s = max(0.001, speed_m_s)
        self.pivot_deg_s = max(0.1, pivot_deg_s)
        self.track_width_m = max(0.01, track_width_m)
        self._mode: str | None = None  # "straight" | "pivot"
        self._direction = 1.0
        self._target_m = 0.0  # straight: distance; pivot: arc length per track
        self._start_left = 0.0
        self._start_right = 0.0
        self._deadline = 0.0
        self._last_progress_m = 0.0

    def update_config(
        self,
        drive_speed: float,
        turn_speed: float,
        speed_m_s: float,
        pivot_deg_s: float,
        track_width_m: float | None = None,
    ) -> None:
        self.drive_speed = drive_speed
        self.turn_speed = turn_speed
        self.speed_m_s = max(0.001, speed_m_s)
        self.pivot_deg_s = max(0.1, pivot_deg_s)
        if track_width_m is not None:
            self.track_width_m = max(0.01, track_width_m)

    def _begin(self, mode: str, target_m: float, expected_s: float) -> None:
        left, right = self.encoders.distances_m()
        self._start_left = left
        self._start_right = right
        self._mode = mode
        self._target_m = target_m
        self._last_progress_m = 0.0
        self._deadline = time.monotonic() + max(
            self.MIN_TIMEOUT_S, expected_s * self.TIMEOUT_FACTOR
        )

    def _travelled(self) -> tuple[float, float]:
        left, right = self.encoders.distances_m()
        return (left - self._start_left, right - self._start_right)

    def start_straight(self, distance_m: float) -> None:
        self._direction = 1.0 if distance_m >= 0 else -1.0
        self._begin(
            "straight",
            abs(distance_m),
            abs(distance_m) / self.speed_m_s,
        )

    def start_pivot(self, degrees: float) -> None:
        self._direction = 1.0 if degrees >= 0 else -1.0
        arc_m = self.track_width_m / 2.0 * math.radians(abs(degrees))
        self._begin("pivot", arc_m, abs(degrees) / self.pivot_deg_s)

    def tick(self) -> tuple[float, float] | None:
        if self._mode is None:
            return None
        d_left, d_right = self._travelled()
        if self._mode == "straight":
            progress = (d_left + d_right) / 2.0 * self._direction
        else:
            progress = (abs(d_left) + abs(d_right)) / 2.0
        self._last_progress_m = max(0.0, progress)
        if self._last_progress_m >= self._target_m:
            self._mode = None
            return None
        if time.monotonic() >= self._deadline:
            logger.warning(
                "Encoder segment timeout (%s: %.2f/%.2f m) — Rad blockiert oder "
                "Encoder liefert keine Impulse",
                self._mode,
                self._last_progress_m,
                self._target_m,
            )
            self._mode = None
            return None
        if self._mode == "pivot":
            return (
                -self._direction * self.turn_speed,
                self._direction * self.turn_speed,
            )
        # Straight: trim the faster track so left/right stay in sync
        diff = (d_left - d_right) * self._direction
        trim = max(-self.MAX_TRIM, min(self.MAX_TRIM, self.TRIM_GAIN * diff))
        base = self._direction * self.drive_speed
        return (base * (1.0 - max(0.0, trim)), base * (1.0 + min(0.0, trim)))

    def progress_m(self) -> float:
        if self._mode == "straight":
            d_left, d_right = self._travelled()
            return max(0.0, (d_left + d_right) / 2.0 * self._direction)
        return min(self._last_progress_m, self._target_m)

    def stop(self) -> None:
        if self._mode == "straight":
            d_left, d_right = self._travelled()
            self._last_progress_m = max(0.0, (d_left + d_right) / 2.0 * self._direction)
        self._mode = None
