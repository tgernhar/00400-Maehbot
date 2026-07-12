"""Servo control for the spray mechanism.

Three hobby servos driven via 50 Hz PWM through the GPIOBackend abstraction:

- ``position`` (servo 1): rotates the nozzle, -180..180 deg
- ``tension``  (servo 2): pre-tensions the spray pressure, -45..180 deg
- ``trigger``  (servo 3): actuation mechanism, 0..45 deg

The ``ServoSequencer`` runs the home / test sequences in a worker thread so
the core realtime loop never blocks on servo travel time.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from spray.gpio import GPIOBackend

logger = logging.getLogger(__name__)

SERVO_NAMES = ("position", "tension", "trigger")


def home_sequence_steps() -> list[tuple[str, float]]:
    """Default home sequence (Grundstellung)."""
    return [
        ("trigger", 0.0),
        ("tension", -45.0),
        ("position", 0.0),
        ("tension", 0.0),
        ("trigger", 0.0),
    ]


def default_test_sequence(test_angles: dict[str, Any] | None = None) -> list[tuple[str, float]]:
    """Test targets followed by the home sequence."""
    angles = test_angles or {}
    return [
        ("tension", float(angles.get("tension", 0.0))),
        ("position", float(angles.get("position", 0.0))),
        ("trigger", float(angles.get("trigger", 0.0))),
    ] + home_sequence_steps()


def sequence_steps_from_config(servo_cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Editable test steps from config; falls back to legacy test_angles."""
    raw = servo_cfg.get("test_sequence")
    if raw:
        steps: list[dict[str, Any]] = []
        for item in raw:
            name = str(item.get("servo", ""))
            if name in SERVO_NAMES:
                steps.append({"servo": name, "angle": float(item.get("angle", 0.0))})
        if steps:
            return steps
    return [
        {"servo": name, "angle": angle}
        for name, angle in default_test_sequence(servo_cfg.get("test_angles"))
    ]


_DEFAULTS: dict[str, dict[str, float]] = {
    "position": {"pin": 18, "min_angle": -180, "max_angle": 180},
    "tension": {"pin": 19, "min_angle": -45, "max_angle": 180},
    "trigger": {"pin": 20, "min_angle": 0, "max_angle": 45},
}


class ServoChannel:
    """Maps an angle to a PWM duty cycle for one servo."""

    def __init__(
        self,
        gpio: GPIOBackend,
        pin: int,
        min_angle: float,
        max_angle: float,
        min_pulse_us: float = 500.0,
        max_pulse_us: float = 2500.0,
        frequency_hz: float = 50.0,
    ) -> None:
        self.gpio = gpio
        self.pin = pin
        self.min_angle = min_angle
        self.max_angle = max_angle
        self.min_pulse_us = min_pulse_us
        self.max_pulse_us = max_pulse_us
        self.frequency_hz = frequency_hz
        self.current_angle: float | None = None

    def setup(self) -> None:
        self.gpio.setup_pwm(self.pin, self.frequency_hz)

    def clamp(self, angle: float) -> float:
        return max(self.min_angle, min(self.max_angle, angle))

    def duty_for_angle(self, angle: float) -> float:
        angle = self.clamp(angle)
        span = self.max_angle - self.min_angle
        fraction = (angle - self.min_angle) / span if span else 0.0
        pulse_us = self.min_pulse_us + fraction * (self.max_pulse_us - self.min_pulse_us)
        period_us = 1_000_000.0 / self.frequency_hz
        return pulse_us / period_us * 100.0

    def move_to(self, angle: float) -> float:
        angle = self.clamp(angle)
        self.gpio.set_pwm_duty(self.pin, self.duty_for_angle(angle))
        self.current_angle = angle
        return angle

    def release(self) -> None:
        """Stop PWM so the servo is not actively holding position."""
        self.gpio.stop_pwm(self.pin)


def servo_limits(servo_cfg: dict[str, Any]) -> dict[str, tuple[float, float]]:
    """Angle limits per servo from config (no GPIO needed, safe for web)."""
    limits: dict[str, tuple[float, float]] = {}
    for name in SERVO_NAMES:
        cfg = servo_cfg.get(name, {}) or {}
        defaults = _DEFAULTS[name]
        limits[name] = (
            float(cfg.get("min_angle", defaults["min_angle"])),
            float(cfg.get("max_angle", defaults["max_angle"])),
        )
    return limits


def build_servo_channels(
    gpio: GPIOBackend, servo_cfg: dict[str, Any]
) -> dict[str, ServoChannel]:
    frequency = float(servo_cfg.get("pwm_frequency_hz", 50))
    channels: dict[str, ServoChannel] = {}
    for name in SERVO_NAMES:
        cfg = servo_cfg.get(name, {}) or {}
        defaults = _DEFAULTS[name]
        channels[name] = ServoChannel(
            gpio,
            pin=int(cfg.get("pin", defaults["pin"])),
            min_angle=float(cfg.get("min_angle", defaults["min_angle"])),
            max_angle=float(cfg.get("max_angle", defaults["max_angle"])),
            min_pulse_us=float(cfg.get("min_pulse_us", 500)),
            max_pulse_us=float(cfg.get("max_pulse_us", 2500)),
            frequency_hz=frequency,
        )
    return channels


class ServoSequencer:
    """Runs home / test sequences on a worker thread.

    Only one sequence can run at a time; further requests are rejected until
    the current one finishes.
    """

    def __init__(
        self,
        gpio: GPIOBackend,
        servo_cfg: dict[str, Any],
        sleep_fn: Any = time.sleep,
    ) -> None:
        self.channels = build_servo_channels(gpio, servo_cfg)
        self.step_delay_s = float(servo_cfg.get("step_delay_ms", 800)) / 1000.0
        self.release_when_idle = bool(servo_cfg.get("release_when_idle", True))
        self._sleep = sleep_fn
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._state = "idle"
        self._error: str | None = None
        # Ordered log of (servo_name, angle) moves, useful for tests/debugging
        self.move_log: list[tuple[str, float]] = []

    def setup(self) -> None:
        for channel in self.channels.values():
            channel.setup()

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    @property
    def busy(self) -> bool:
        return self.state != "idle"

    def status_dict(self) -> dict[str, Any]:
        with self._lock:
            return {
                "state": self._state,
                "angles": {
                    name: ch.current_angle for name, ch in self.channels.items()
                },
                "error": self._error,
                "updated_at": time.time(),
            }

    def run_home(self) -> bool:
        """Drive the home sequence asynchronously. Returns False when busy."""
        return self._start("homing", self._home_steps())

    def run_test(self, position: float, tension: float, trigger: float) -> bool:
        """Legacy test run: three targets then home. False when busy."""
        return self.run_sequence(
            default_test_sequence(
                {"position": position, "tension": tension, "trigger": trigger}
            )
        )

    def run_sequence(self, steps: list[tuple[str, float]]) -> bool:
        """Run a custom step list. False when busy or an unknown servo is given."""
        parsed: list[tuple[str, float]] = []
        for name, angle in steps:
            if name not in self.channels:
                return False
            parsed.append((name, self.channels[name].clamp(angle)))
        return self._start("testing", parsed)

    def run_sweep(self, servo_name: str) -> bool:
        """Diagnostic sweep for one servo only (min → mid → max → neutral).

        Mirrors the manual lgpio duty sweep used for hardware checks.
        Only the named servo moves; the others stay put.
        """
        if servo_name not in self.channels:
            return False
        steps = [(servo_name, angle) for angle in self._sweep_angles(servo_name)]
        return self._start("sweeping", steps)

    @staticmethod
    def _sweep_angles(servo_name: str) -> list[float]:
        """Per-servo sweep positions: neutral, high, low, neutral."""
        sweeps: dict[str, list[float]] = {
            "position": [0.0, 90.0, -90.0, 0.0],
            "tension": [0.0, 90.0, -45.0, 0.0],
            "trigger": [0.0, 22.0, 45.0, 0.0],
        }
        return sweeps[servo_name]

    def run_home_blocking(self) -> None:
        """Home sequence executed on the caller's thread (startup init)."""
        with self._lock:
            self._state = "homing"
            self._error = None
        self._execute(self._home_steps())

    def wait_idle(self, timeout_s: float = 30.0) -> None:
        deadline = time.monotonic() + timeout_s
        while self.busy and time.monotonic() < deadline:
            time.sleep(0.02)

    def stop(self) -> None:
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=10.0)

    def _home_steps(self) -> list[tuple[str, float]]:
        return home_sequence_steps()

    def _start(self, state: str, steps: list[tuple[str, float]]) -> bool:
        with self._lock:
            if self._state != "idle":
                return False
            self._state = state
            self._error = None
        self._thread = threading.Thread(
            target=self._execute, args=(steps,), daemon=True
        )
        self._thread.start()
        return True

    def _release_all(self) -> None:
        if not self.release_when_idle:
            return
        for channel in self.channels.values():
            channel.release()

    def _execute(self, steps: list[tuple[str, float]]) -> None:
        error: str | None = None
        try:
            for i, (name, angle) in enumerate(steps):
                moved = self.channels[name].move_to(angle)
                self.move_log.append((name, moved))
                if i < len(steps) - 1:
                    self._sleep(self.step_delay_s)
            # Let the final position settle before cutting PWM
            if steps:
                self._sleep(self.step_delay_s)
        except Exception as exc:
            logger.exception("Servo sequence failed")
            error = str(exc)
        finally:
            self._release_all()
            with self._lock:
                self._state = "idle"
                self._error = error
