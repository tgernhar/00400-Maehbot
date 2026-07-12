"""Tests for spray servo control (angle mapping, sequences, IPC)."""

from __future__ import annotations

import threading

import pytest

from spray.gpio import MockGPIO
from spray.servo import (
    ServoChannel,
    ServoSequencer,
    build_servo_channels,
    default_test_sequence,
    servo_limits,
    sequence_steps_from_config,
)
from spray.servo_command import (
    consume_servo_command,
    default_servo_status,
    queue_servo_command,
    read_servo_status,
    write_servo_status,
)
from storage.paths import StoragePaths

SERVO_CFG = {
    "pwm_frequency_hz": 50,
    "step_delay_ms": 0,  # no waiting in tests
    "position": {"pin": 18, "min_angle": -180, "max_angle": 180},
    "tension": {"pin": 19, "min_angle": -45, "max_angle": 180},
    "trigger": {"pin": 20, "min_angle": 0, "max_angle": 45},
}


def make_channel(**overrides) -> tuple[MockGPIO, ServoChannel]:
    gpio = MockGPIO()
    params = dict(
        pin=18,
        min_angle=-180.0,
        max_angle=180.0,
        min_pulse_us=500.0,
        max_pulse_us=2500.0,
        frequency_hz=50.0,
    )
    params.update(overrides)
    channel = ServoChannel(gpio, **params)
    channel.setup()
    return gpio, channel


class TestServoChannel:
    def test_duty_at_min_angle(self) -> None:
        _, ch = make_channel()
        # 500 us of a 20000 us period = 2.5 %
        assert ch.duty_for_angle(-180) == pytest.approx(2.5)

    def test_duty_at_max_angle(self) -> None:
        _, ch = make_channel()
        # 2500 us of a 20000 us period = 12.5 %
        assert ch.duty_for_angle(180) == pytest.approx(12.5)

    def test_duty_at_center(self) -> None:
        _, ch = make_channel()
        assert ch.duty_for_angle(0) == pytest.approx(7.5)

    def test_clamps_below_min(self) -> None:
        _, ch = make_channel(min_angle=0.0, max_angle=45.0)
        assert ch.move_to(-10) == 0.0

    def test_clamps_above_max(self) -> None:
        _, ch = make_channel(min_angle=-45.0, max_angle=180.0)
        assert ch.move_to(500) == 180.0

    def test_move_writes_pwm(self) -> None:
        gpio, ch = make_channel()
        ch.move_to(0)
        assert gpio.pwm[18] == pytest.approx(7.5)
        assert ch.current_angle == 0.0


class TestBuildChannels:
    def test_uses_config_pins_and_limits(self) -> None:
        channels = build_servo_channels(MockGPIO(), SERVO_CFG)
        assert channels["position"].pin == 18
        assert channels["tension"].min_angle == -45
        assert channels["trigger"].max_angle == 45

    def test_defaults_when_config_empty(self) -> None:
        channels = build_servo_channels(MockGPIO(), {})
        assert channels["position"].pin == 18
        assert channels["tension"].pin == 19
        assert channels["trigger"].pin == 20

    def test_servo_limits(self) -> None:
        limits = servo_limits(SERVO_CFG)
        assert limits["position"] == (-180.0, 180.0)
        assert limits["tension"] == (-45.0, 180.0)
        assert limits["trigger"] == (0.0, 45.0)


class TestServoSequencer:
    def make_sequencer(self) -> ServoSequencer:
        seq = ServoSequencer(MockGPIO(), SERVO_CFG, sleep_fn=lambda _s: None)
        seq.setup()
        return seq

    def test_home_sequence_order(self) -> None:
        seq = self.make_sequencer()
        assert seq.run_home()
        seq.wait_idle()
        assert seq.move_log == [
            ("trigger", 0.0),
            ("tension", -45.0),
            ("position", 0.0),
            ("tension", 0.0),
            ("trigger", 0.0),
        ]

    def test_test_sequence_order_then_home(self) -> None:
        seq = self.make_sequencer()
        assert seq.run_test(position=90.0, tension=120.0, trigger=30.0)
        seq.wait_idle()
        assert seq.move_log == [
            ("tension", 120.0),
            ("position", 90.0),
            ("trigger", 30.0),
            ("trigger", 0.0),
            ("tension", -45.0),
            ("position", 0.0),
            ("tension", 0.0),
            ("trigger", 0.0),
        ]

    def test_test_angles_clamped(self) -> None:
        seq = self.make_sequencer()
        seq.run_test(position=999.0, tension=-999.0, trigger=999.0)
        seq.wait_idle()
        assert seq.move_log[0] == ("tension", -45.0)
        assert seq.move_log[1] == ("position", 180.0)
        assert seq.move_log[2] == ("trigger", 45.0)

    def test_run_sequence_custom(self) -> None:
        seq = self.make_sequencer()
        custom = [("position", 45.0), ("trigger", 10.0)]
        assert seq.run_sequence(custom)
        seq.wait_idle()
        assert seq.move_log == custom

    def test_run_sequence_rejects_unknown_servo(self) -> None:
        seq = self.make_sequencer()
        assert not seq.run_sequence([("unknown", 0.0)])

    def test_sequence_steps_from_config(self) -> None:
        cfg = {
            "test_sequence": [
                {"servo": "position", "angle": 10},
                {"servo": "trigger", "angle": 5},
            ]
        }
        assert sequence_steps_from_config(cfg) == [
            {"servo": "position", "angle": 10.0, "hold_until_step": None},
            {"servo": "trigger", "angle": 5.0, "hold_until_step": None},
        ]

    def test_sequence_steps_fallback_from_test_angles(self) -> None:
        steps = sequence_steps_from_config({"test_angles": {"position": 90, "tension": 30, "trigger": 15}})
        assert len(steps) == 8
        assert steps[0] == {"servo": "tension", "angle": 30.0, "hold_until_step": None}
        assert steps[1] == {"servo": "position", "angle": 90.0, "hold_until_step": None}
        assert steps[2] == {"servo": "trigger", "angle": 15.0, "hold_until_step": None}

    def test_default_test_sequence(self) -> None:
        names = [n for n, _ in default_test_sequence({"position": 1, "tension": 2, "trigger": 3})]
        assert names == [
            "tension", "position", "trigger",
            "trigger", "tension", "position", "tension", "trigger",
        ]

    def test_rejects_while_busy(self) -> None:
        # Block the worker thread inside the sequence to keep it busy
        release = threading.Event()
        seq = ServoSequencer(MockGPIO(), SERVO_CFG, sleep_fn=lambda _s: release.wait(5))
        seq.setup()
        assert seq.run_home()
        assert not seq.run_test(position=0, tension=0, trigger=0)
        release.set()
        seq.wait_idle()
        assert seq.state == "idle"

    def test_status_dict(self) -> None:
        seq = self.make_sequencer()
        seq.run_home()
        seq.wait_idle()
        status = seq.status_dict()
        assert status["state"] == "idle"
        assert status["error"] is None
        assert status["angles"]["position"] == 0.0

    def test_run_home_blocking(self) -> None:
        seq = self.make_sequencer()
        seq.run_home_blocking()
        assert seq.state == "idle"
        assert seq.channels["tension"].current_angle == 0.0

    def test_release_pwm_after_sequence(self) -> None:
        gpio = MockGPIO()
        seq = ServoSequencer(gpio, SERVO_CFG, sleep_fn=lambda _s: None)
        seq.setup()
        seq.run_home()
        seq.wait_idle()
        assert any(duty == -1.0 for _pin, duty in gpio.pwm_log)

    def test_release_pwm_after_single_step(self) -> None:
        gpio = MockGPIO()
        seq = ServoSequencer(gpio, SERVO_CFG, sleep_fn=lambda _s: None)
        seq.setup()
        assert seq.run_sequence([("position", 45.0)])
        seq.wait_idle()
        stops = [pin for pin, duty in gpio.pwm_log if duty == -1.0]
        assert 18 in stops

    def test_hold_until_step_keeps_pwm_between_steps(self) -> None:
        gpio = MockGPIO()
        seq = ServoSequencer(gpio, SERVO_CFG, sleep_fn=lambda _s: None)
        seq.setup()
        assert seq.run_sequence([("tension", 10.0, 2), ("position", 20.0, None)])
        seq.wait_idle()
        # tension: move, no release after step 1 (hold until 2), release after step 2
        # position: move, release after step 2
        tension_stops = [i for i, (p, d) in enumerate(gpio.pwm_log) if p == 19 and d == -1.0]
        assert len(tension_stops) >= 1
        assert gpio.pwm_log[0] == (19, pytest.approx(seq.channels["tension"].duty_for_angle(10.0)))


class TestServoCommandIpc:
    def test_queue_and_consume(self, tmp_path) -> None:
        paths = StoragePaths(tmp_path)
        queue_servo_command(
            paths,
            "test",
            steps=[
                {"servo": "position", "angle": 10},
                {"servo": "tension", "angle": 20},
            ],
        )
        cmd = consume_servo_command(paths)
        assert cmd is not None
        assert cmd["action"] == "test"
        assert cmd["steps"] == [
            {"servo": "position", "angle": 10.0},
            {"servo": "tension", "angle": 20.0},
        ]
        # consumed: file removed
        assert consume_servo_command(paths) is None

    def test_consume_invalid_file(self, tmp_path) -> None:
        paths = StoragePaths(tmp_path)
        paths.servo_command_path.write_text("not json", encoding="utf-8")
        assert consume_servo_command(paths) is None
        assert not paths.servo_command_path.exists()

    def test_status_roundtrip(self, tmp_path) -> None:
        paths = StoragePaths(tmp_path)
        assert read_servo_status(paths) == default_servo_status()
        write_servo_status(
            paths,
            {"state": "testing", "angles": {"position": 90.0}, "error": None},
        )
        status = read_servo_status(paths)
        assert status["state"] == "testing"
        assert status["angles"]["position"] == 90.0
