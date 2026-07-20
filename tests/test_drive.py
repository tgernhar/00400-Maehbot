"""Tests for the tank-chassis drive (motor driver + controller + IPC)."""

import time

from drive.command import (
    consume_drive_command,
    default_drive_status,
    queue_drive_command,
    read_drive_status,
    write_drive_status,
)
from drive.controller import DriveController
from drive.motor import MotorDriver, MotorPins
from spray.gpio import MockGPIO
from storage.paths import StoragePaths


def _driver() -> tuple[MockGPIO, MotorDriver]:
    gpio = MockGPIO()
    pins = MotorPins({})
    return gpio, MotorDriver(gpio, pins)


def test_pwm_duty_clamped_and_logged():
    gpio = MockGPIO()
    gpio.setup_pwm(12, 1000)
    gpio.set_pwm_duty(12, 150)
    assert gpio.pwm[12] == 100.0
    gpio.set_pwm_duty(12, -10)
    assert gpio.pwm[12] == 0.0


def test_motor_forward_sets_direction_and_pwm():
    gpio, driver = _driver()
    driver.setup()
    driver.set_left(0.5)
    assert gpio._outputs[driver.pins.left_in1] is True
    assert gpio._outputs[driver.pins.left_in2] is False
    assert gpio.pwm[driver.pins.left_pwm] == 50.0


def test_motor_reverse_inverts_direction_pins():
    gpio, driver = _driver()
    driver.setup()
    driver.set_right(-1.0)
    assert gpio._outputs[driver.pins.right_in1] is False
    assert gpio._outputs[driver.pins.right_in2] is True
    assert gpio.pwm[driver.pins.right_pwm] == 100.0


def test_invert_left_flips_direction():
    gpio = MockGPIO()
    driver = MotorDriver(gpio, MotorPins({}), invert_left=True)
    driver.setup()
    driver.set_left(1.0)
    assert gpio._outputs[driver.pins.left_in1] is False
    assert gpio._outputs[driver.pins.left_in2] is True


def test_controller_applies_speed_with_max_scale():
    gpio, driver = _driver()
    ctrl = DriveController(driver, max_speed=0.5, watchdog_timeout_s=5.0)
    ctrl.start()
    try:
        ctrl.set_speeds(1.0, -1.0)
        time.sleep(0.1)
        assert gpio.pwm[driver.pins.left_pwm] == 50.0
        assert gpio.pwm[driver.pins.right_pwm] == 50.0
    finally:
        ctrl.stop()


def test_controller_watchdog_stops_motors():
    gpio, driver = _driver()
    ctrl = DriveController(driver, max_speed=1.0, watchdog_timeout_s=0.1)
    ctrl.start()
    try:
        ctrl.set_speeds(1.0, 1.0)
        time.sleep(0.05)
        assert gpio.pwm[driver.pins.left_pwm] == 100.0
        time.sleep(0.2)
        assert gpio.pwm[driver.pins.left_pwm] == 0.0
        assert gpio.pwm[driver.pins.right_pwm] == 0.0
    finally:
        ctrl.stop()


def test_controller_stop_disables_standby():
    gpio, driver = _driver()
    ctrl = DriveController(driver, watchdog_timeout_s=5.0)
    ctrl.start()
    assert gpio._outputs[driver.pins.standby] is True
    ctrl.stop()
    assert gpio._outputs[driver.pins.standby] is False


def test_drive_command_ipc_roundtrip(tmp_path):
    paths = StoragePaths(tmp_path)
    paths.ensure()
    assert consume_drive_command(paths) is None
    queue_drive_command(paths, 0.3, -0.7)
    cmd = consume_drive_command(paths)
    assert cmd is not None
    assert cmd["left"] == 0.3
    assert cmd["right"] == -0.7
    assert consume_drive_command(paths) is None


def test_drive_status_roundtrip(tmp_path):
    paths = StoragePaths(tmp_path)
    paths.ensure()
    assert read_drive_status(paths) == default_drive_status()
    write_drive_status(
        paths,
        {
            "left": 0.5,
            "right": 0.5,
            "moving": True,
            "encoder_enabled": True,
            "encoder_left_m": 1.234,
            "encoder_right_m": 1.198,
        },
    )
    status = read_drive_status(paths)
    assert status["left"] == 0.5
    assert status["moving"] is True
    assert status["encoder_enabled"] is True
    assert status["encoder_left_m"] == 1.234
    assert status["encoder_right_m"] == 1.198
