"""Low-level TB6612FNG dual-motor driver for the tank chassis.

Each motor uses two direction pins (IN1/IN2) plus a PWM pin for speed.
A shared STBY pin enables/disables both channels.

TB6612FNG truth table per channel:
  IN1=1 IN2=0 -> forward (PWM sets speed)
  IN1=0 IN2=1 -> reverse (PWM sets speed)
  IN1=0 IN2=0 -> coast/stop
  IN1=1 IN2=1 -> short brake
"""

from __future__ import annotations

import logging
from typing import Any

from spray.gpio import GPIOBackend

logger = logging.getLogger(__name__)

DEFAULT_PWM_FREQUENCY_HZ = 1000.0


def _clamp(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


class MotorPins:
    """BCM pin assignment for the TB6612FNG wired to two tracks."""

    def __init__(self, pins: dict[str, Any]) -> None:
        self.standby = int(pins.get("standby", 25))
        # Left track = channel A
        self.left_in1 = int(pins.get("left_in1", 5))
        self.left_in2 = int(pins.get("left_in2", 6))
        self.left_pwm = int(pins.get("left_pwm", 12))
        # Right track = channel B
        self.right_in1 = int(pins.get("right_in1", 16))
        self.right_in2 = int(pins.get("right_in2", 26))
        self.right_pwm = int(pins.get("right_pwm", 13))
        self.pwm_frequency_hz = float(pins.get("pwm_frequency_hz", DEFAULT_PWM_FREQUENCY_HZ))


class MotorDriver:
    """Translates signed track speeds (-1..1) into TB6612FNG GPIO levels."""

    def __init__(
        self,
        gpio: GPIOBackend,
        pins: MotorPins,
        invert_left: bool = False,
        invert_right: bool = False,
    ) -> None:
        self.gpio = gpio
        self.pins = pins
        self.invert_left = invert_left
        self.invert_right = invert_right

    def setup(self) -> None:
        for pin in (
            self.pins.standby,
            self.pins.left_in1,
            self.pins.left_in2,
            self.pins.right_in1,
            self.pins.right_in2,
        ):
            self.gpio.setup_output(pin)
            self.gpio.write(pin, False)
        self.gpio.setup_pwm(self.pins.left_pwm, self.pins.pwm_frequency_hz)
        self.gpio.setup_pwm(self.pins.right_pwm, self.pins.pwm_frequency_hz)
        self.gpio.set_pwm_duty(self.pins.left_pwm, 0.0)
        self.gpio.set_pwm_duty(self.pins.right_pwm, 0.0)
        logger.info("Motor driver pins initialised (STBY held low until enabled)")

    def enable(self) -> None:
        self.gpio.write(self.pins.standby, True)

    def disable(self) -> None:
        self.gpio.write(self.pins.standby, False)

    def set_left(self, speed: float) -> None:
        speed = -speed if self.invert_left else speed
        self._drive(self.pins.left_in1, self.pins.left_in2, self.pins.left_pwm, speed)

    def set_right(self, speed: float) -> None:
        speed = -speed if self.invert_right else speed
        self._drive(self.pins.right_in1, self.pins.right_in2, self.pins.right_pwm, speed)

    def stop(self) -> None:
        """Coast both motors (PWM 0, direction pins low)."""
        self.gpio.set_pwm_duty(self.pins.left_pwm, 0.0)
        self.gpio.set_pwm_duty(self.pins.right_pwm, 0.0)
        for pin in (
            self.pins.left_in1,
            self.pins.left_in2,
            self.pins.right_in1,
            self.pins.right_in2,
        ):
            self.gpio.write(pin, False)

    def _drive(self, in1: int, in2: int, pwm: int, speed: float) -> None:
        speed = _clamp(speed)
        if speed > 0:
            self.gpio.write(in1, True)
            self.gpio.write(in2, False)
        elif speed < 0:
            self.gpio.write(in1, False)
            self.gpio.write(in2, True)
        else:
            self.gpio.write(in1, False)
            self.gpio.write(in2, False)
        self.gpio.set_pwm_duty(pwm, abs(speed) * 100.0)
