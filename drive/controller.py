"""Drive controller: applies track speeds with a safety watchdog.

The controller runs a worker thread that continuously pushes the latest
requested track speeds to the motor driver. If no fresh command arrives
within ``watchdog_timeout_s`` (e.g. the web UI lost connection), the motors
are stopped automatically. The web UI must therefore send periodic keep-alive
commands while a direction button is held.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from drive.motor import MotorDriver, _clamp

logger = logging.getLogger(__name__)


class DriveController:
    def __init__(
        self,
        driver: MotorDriver,
        max_speed: float = 1.0,
        watchdog_timeout_s: float = 1.0,
        enabled: bool = True,
        update_interval_s: float = 0.02,
    ) -> None:
        self.driver = driver
        self.max_speed = _clamp(max_speed, 0.0, 1.0)
        self.watchdog_timeout_s = max(0.1, watchdog_timeout_s)
        self.enabled = enabled
        self.update_interval_s = update_interval_s
        self._left = 0.0
        self._right = 0.0
        self._last_command_ts = 0.0
        self._applied_left = 0.0
        self._applied_right = 0.0
        self._lock = threading.Lock()
        self._worker = threading.Thread(target=self._run_worker, name="drive-worker", daemon=True)
        self._running = False

    def start(self) -> None:
        self.driver.setup()
        if self.enabled:
            self.driver.enable()
        self._running = True
        self._worker.start()
        logger.info("Drive controller started (enabled=%s, max_speed=%.2f)", self.enabled, self.max_speed)

    def stop(self) -> None:
        self._running = False
        self._worker.join(timeout=2)
        self.driver.stop()
        self.driver.disable()

    def set_speeds(self, left: float, right: float) -> None:
        with self._lock:
            self._left = _clamp(left)
            self._right = _clamp(right)
            self._last_command_ts = time.monotonic()

    def stop_motion(self) -> None:
        self.set_speeds(0.0, 0.0)

    def set_enabled(self, enabled: bool) -> None:
        with self._lock:
            self.enabled = enabled
            if not enabled:
                self._left = 0.0
                self._right = 0.0
        if enabled:
            self.driver.enable()
        else:
            self.driver.stop()
            self.driver.disable()

    def update_config(
        self,
        max_speed: float,
        watchdog_timeout_s: float,
        enabled: bool,
        invert_left: bool | None = None,
        invert_right: bool | None = None,
    ) -> None:
        with self._lock:
            self.max_speed = _clamp(max_speed, 0.0, 1.0)
            self.watchdog_timeout_s = max(0.1, watchdog_timeout_s)
            if invert_left is not None:
                self.driver.invert_left = invert_left
            if invert_right is not None:
                self.driver.invert_right = invert_right
        if enabled != self.enabled:
            self.set_enabled(enabled)

    def status_dict(self) -> dict[str, Any]:
        with self._lock:
            return {
                "left": round(self._applied_left, 3),
                "right": round(self._applied_right, 3),
                "enabled": self.enabled,
                "moving": self._applied_left != 0.0 or self._applied_right != 0.0,
                "max_speed": round(self.max_speed, 3),
                "error": None,
            }

    def _run_worker(self) -> None:
        while self._running:
            now = time.monotonic()
            with self._lock:
                left, right = self._left, self._right
                enabled = self.enabled
                age = now - self._last_command_ts
                scale = self.max_speed
            if not enabled or age > self.watchdog_timeout_s:
                left = right = 0.0
            out_left = left * scale
            out_right = right * scale
            self.driver.set_left(out_left)
            self.driver.set_right(out_right)
            with self._lock:
                self._applied_left = out_left
                self._applied_right = out_right
            time.sleep(self.update_interval_s)
