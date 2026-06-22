"""Shared runtime health and status."""

from __future__ import annotations

import time

from maehbot.types import SystemStatus
from spray.gpio import PinMap


class HealthMonitor:
    def __init__(
        self,
        camera_timeout_ms: float = 2000.0,
        pins: PinMap | None = None,
    ) -> None:
        self.camera_timeout_ms = camera_timeout_ms
        self.pins = pins
        self._last_frame_ms = 0.0
        self.test_mode = True

    def record_frame(self, timestamp_ms: float) -> None:
        self._last_frame_ms = timestamp_ms

    def set_test_mode(self, test_mode: bool) -> None:
        self.test_mode = test_mode

    def build_status(self) -> SystemStatus:
        now_ms = time.monotonic() * 1000.0
        camera_healthy = (
            self._last_frame_ms > 0
            and (now_ms - self._last_frame_ms) < self.camera_timeout_ms
        )
        tank_empty = False
        tank_full = False
        if self.pins:
            tank_empty = self.pins.read_tank_empty()
            tank_full = self.pins.read_tank_full()
        return SystemStatus(
            test_mode=self.test_mode,
            camera_healthy=camera_healthy,
            tank_empty=tank_empty,
            tank_full=tank_full,
            last_frame_ms=self._last_frame_ms,
        )
