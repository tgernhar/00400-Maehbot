"""Tests for GPIO mock and spray controller."""

import time

from spray.gpio import MockGPIO, PinMap
from spray.controller import SprayController


def test_mock_gpio_write():
    gpio = MockGPIO()
    gpio.setup_output(17)
    gpio.write(17, True)
    assert gpio.read(17) is False  # outputs not readable as inputs
    assert (17, True) in gpio.write_log


def test_spray_controller_schedules():
    gpio = MockGPIO()
    pins = PinMap(gpio, {"nozzle_valve": 17, "pump": 27, "tank_full": 22, "tank_empty": 23})
    ctrl = SprayController(pins, duration_ms=20)
    ctrl.start()
    fire_at = time.monotonic() * 1000.0 + 5
    ctrl.schedule(fire_at)
    time.sleep(0.15)
    ctrl.stop()
    assert any(pin == 17 and val for pin, val in gpio.write_log)
