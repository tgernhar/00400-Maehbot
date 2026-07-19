"""Tests for quadrature decoding and encoder-based motion execution."""

from __future__ import annotations

import math

from drive.encoder import QuadratureDecoder, create_encoder_pair
from navigation.motion import EncoderMotionExecutor


class FakeEncoderPair:
    """Encoder stub the tests advance manually."""

    def __init__(self) -> None:
        self.left = 0.0
        self.right = 0.0
        self.closed = False

    def distances_m(self) -> tuple[float, float]:
        return (self.left, self.right)

    def reset(self) -> None:
        self.left = 0.0
        self.right = 0.0

    def close(self) -> None:
        self.closed = True


def make_executor(enc: FakeEncoderPair) -> EncoderMotionExecutor:
    return EncoderMotionExecutor(
        enc,
        drive_speed=0.5,
        turn_speed=0.4,
        speed_m_s=0.1,
        pivot_deg_s=45.0,
        track_width_m=0.2,
    )


# -- QuadratureDecoder -----------------------------------------------------------


def test_decoder_counts_forward() -> None:
    d = QuadratureDecoder()
    # Full forward cycle: 00 -> 01 -> 11 -> 10 -> 00 = +4
    for a, b in [(0, 0), (0, 1), (1, 1), (1, 0), (0, 0)]:
        d.update(a, b)
    assert d.count == 4


def test_decoder_counts_backward() -> None:
    d = QuadratureDecoder()
    for a, b in [(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)]:
        d.update(a, b)
    assert d.count == -4


def test_decoder_ignores_invalid_transition() -> None:
    d = QuadratureDecoder()
    d.update(0, 0)
    d.update(1, 1)  # both channels flipped at once -> ignored
    assert d.count == 0


# -- factory ---------------------------------------------------------------------


def test_create_encoder_pair_disabled_returns_none() -> None:
    assert create_encoder_pair({"encoder": {"enabled": False}}) is None


def test_create_encoder_pair_uncalibrated_returns_none() -> None:
    cfg = {"encoder": {"enabled": True, "pulses_per_rev": 0, "wheel_diameter_mm": 65}}
    assert create_encoder_pair(cfg) is None


def test_create_encoder_pair_force_mock_returns_none() -> None:
    cfg = {"encoder": {"enabled": True, "pulses_per_rev": 44, "wheel_diameter_mm": 65}}
    assert create_encoder_pair(cfg, force_mock=True) is None


# -- EncoderMotionExecutor: straight ----------------------------------------------


def test_straight_runs_until_measured_distance() -> None:
    enc = FakeEncoderPair()
    ex = make_executor(enc)
    ex.start_straight(1.0)
    assert ex.tick() == (0.5, 0.5)
    enc.left = enc.right = 0.5
    assert ex.tick() == (0.5, 0.5)
    assert ex.progress_m() == 0.5
    enc.left = enc.right = 1.0
    assert ex.tick() is None  # target reached
    assert ex.tick() is None  # stays finished


def test_straight_backwards_uses_negative_speeds() -> None:
    enc = FakeEncoderPair()
    ex = make_executor(enc)
    ex.start_straight(-0.4)
    assert ex.tick() == (-0.5, -0.5)
    enc.left = enc.right = -0.4
    assert ex.tick() is None
    assert ex.progress_m() == 0.4


def test_straight_trims_faster_track() -> None:
    enc = FakeEncoderPair()
    ex = make_executor(enc)
    ex.start_straight(2.0)
    enc.left = 0.6  # left track ahead by 10 cm
    enc.right = 0.5
    left, right = ex.tick()
    assert left < 0.5  # faster track slowed down
    assert right == 0.5


def test_straight_ignores_start_offset() -> None:
    enc = FakeEncoderPair()
    enc.left = enc.right = 3.0  # counts from earlier segments
    ex = make_executor(enc)
    ex.start_straight(0.5)
    enc.left = enc.right = 3.5
    assert ex.tick() is None


def test_progress_after_stop_matches_travel() -> None:
    enc = FakeEncoderPair()
    ex = make_executor(enc)
    ex.start_straight(1.0)
    enc.left = enc.right = 0.3
    ex.stop()
    assert ex.progress_m() == 0.3


# -- EncoderMotionExecutor: pivot --------------------------------------------------


def test_pivot_left_track_speeds() -> None:
    enc = FakeEncoderPair()
    ex = make_executor(enc)
    ex.start_pivot(90.0)
    assert ex.tick() == (-0.4, 0.4)


def test_pivot_finishes_at_arc_length() -> None:
    enc = FakeEncoderPair()
    ex = make_executor(enc)
    ex.start_pivot(90.0)
    arc = 0.1 * math.radians(90.0)  # track_width/2 * angle
    enc.left = -arc
    enc.right = arc
    assert ex.tick() is None


def test_pivot_right_direction() -> None:
    enc = FakeEncoderPair()
    ex = make_executor(enc)
    ex.start_pivot(-90.0)
    assert ex.tick() == (0.4, -0.4)


# -- timeout safety ---------------------------------------------------------------


def test_segment_timeout_aborts(monkeypatch) -> None:
    import navigation.motion as motion_mod

    enc = FakeEncoderPair()
    ex = make_executor(enc)
    now = {"t": 100.0}
    monkeypatch.setattr(motion_mod.time, "monotonic", lambda: now["t"])
    ex.start_straight(1.0)
    assert ex.tick() is not None
    # Wheels never move; jump past the timeout deadline
    now["t"] += 1000.0
    assert ex.tick() is None
