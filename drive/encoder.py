"""Quadrature wheel encoder reading (left + right track).

Each encoder outputs two square waves (A/B) 90 degrees apart. Counting all
four edge transitions gives 4x resolution and the transition order gives the
direction. On the Pi the channels are read via lgpio alerts (edge callbacks),
so the core loop never has to poll at pulse rate.

``encoder.pulses_per_rev`` in the config is the number of *quadrature counts*
per wheel revolution (encoder PPR x 4).
"""

from __future__ import annotations

import logging
import math
import sys
import threading
from typing import Any, Protocol

logger = logging.getLogger(__name__)

# (previous_state, new_state) -> count delta; state = (A << 1) | B
_QUAD_DELTA = {
    (0b00, 0b01): 1,
    (0b01, 0b11): 1,
    (0b11, 0b10): 1,
    (0b10, 0b00): 1,
    (0b00, 0b10): -1,
    (0b10, 0b11): -1,
    (0b11, 0b01): -1,
    (0b01, 0b00): -1,
}


class QuadratureDecoder:
    """Direction-aware edge counter for one A/B channel pair."""

    def __init__(self) -> None:
        self._state: int | None = None
        self.count = 0

    def update(self, a: int, b: int) -> None:
        state = ((1 if a else 0) << 1) | (1 if b else 0)
        if self._state is not None:
            # Invalid transitions (both channels flipped at once) count as 0
            self.count += _QUAD_DELTA.get((self._state, state), 0)
        self._state = state


class EncoderPair(Protocol):
    """Travelled distance per track in meters (signed, forward positive)."""

    def distances_m(self) -> tuple[float, float]: ...

    def counts(self) -> tuple[int, int]: ...

    def reset(self) -> None: ...

    def close(self) -> None: ...


class LgpioEncoderPair:
    """Reads both wheel encoders via lgpio edge alerts on the Pi."""

    def __init__(
        self,
        *,
        left_a: int,
        left_b: int,
        right_a: int,
        right_b: int,
        meters_per_count: float,
        invert_left: bool = False,
        invert_right: bool = False,
        debounce_us: int = 200,
    ) -> None:
        import lgpio

        self._lgpio = lgpio
        self._chip = lgpio.gpiochip_open(0)
        self._meters_per_count = meters_per_count
        self._sign_left = -1.0 if invert_left else 1.0
        self._sign_right = -1.0 if invert_right else 1.0
        self._lock = threading.Lock()
        self._left = QuadratureDecoder()
        self._right = QuadratureDecoder()
        self._left_a = left_a
        self._left_b = left_b
        self._right_a = right_a
        self._right_b = right_b
        # pin -> (decoder, is_channel_a, partner_pin)
        self._pin_map = {
            left_a: (self._left, True, left_b),
            left_b: (self._left, False, left_a),
            right_a: (self._right, True, right_b),
            right_b: (self._right, False, right_a),
        }
        self._levels: dict[int, int] = {}
        self._callbacks: list[Any] = []
        pull_up = getattr(lgpio, "SET_PULL_UP", 0)
        try:
            for pin in self._pin_map:
                lgpio.gpio_claim_alert(self._chip, pin, lgpio.BOTH_EDGES, pull_up)
                if debounce_us > 0:
                    lgpio.gpio_set_debounce_micros(self._chip, pin, debounce_us)
                self._levels[pin] = lgpio.gpio_read(self._chip, pin)
            for pin in self._pin_map:
                self._callbacks.append(
                    lgpio.callback(self._chip, pin, lgpio.BOTH_EDGES, self._on_edge)
                )
        except Exception:
            self.close()
            raise
        logger.info(
            "Encoder GPIO levels at init: left A/B=%d/%d, right A/B=%d/%d",
            self._levels[left_a],
            self._levels[left_b],
            self._levels[right_a],
            self._levels[right_b],
        )
        logger.info(
            "Wheel encoders active: left A/B=%d/%d, right A/B=%d/%d, %.4f mm/count",
            left_a,
            left_b,
            right_a,
            right_b,
            meters_per_count * 1000.0,
        )

    def _on_edge(self, chip: int, gpio: int, level: int, timestamp: int) -> None:
        if level > 1:  # watchdog / no-change notification
            return
        decoder, is_a, partner = self._pin_map[gpio]
        with self._lock:
            self._levels[gpio] = level
            other = self._levels[partner]
            if is_a:
                decoder.update(level, other)
            else:
                decoder.update(other, level)

    def distances_m(self) -> tuple[float, float]:
        with self._lock:
            left = self._left.count
            right = self._right.count
        return (
            left * self._meters_per_count * self._sign_left,
            right * self._meters_per_count * self._sign_right,
        )

    def counts(self) -> tuple[int, int]:
        with self._lock:
            return (self._left.count, self._right.count)

    def reset(self) -> None:
        with self._lock:
            self._left.count = 0
            self._right.count = 0

    def close(self) -> None:
        for cb in self._callbacks:
            try:
                cb.cancel()
            except Exception:
                pass
        self._callbacks.clear()
        for pin in self._pin_map:
            try:
                self._lgpio.gpio_free(self._chip, pin)
            except Exception:
                pass
        try:
            self._lgpio.gpiochip_close(self._chip)
        except Exception:
            pass


def create_encoder_pair(
    config: dict[str, Any], force_mock: bool = False
) -> EncoderPair | None:
    """Build the encoder reader, or return None when disabled/unavailable."""
    enc = config.get("encoder", {})
    if not bool(enc.get("enabled", False)):
        return None
    if force_mock or sys.platform != "linux":
        logger.info("Encoders enabled but no GPIO hardware — ignoring")
        return None
    pulses_per_rev = float(enc.get("pulses_per_rev", 0))
    wheel_diameter_mm = float(enc.get("wheel_diameter_mm", 0))
    if pulses_per_rev <= 0 or wheel_diameter_mm <= 0:
        logger.warning(
            "encoder.pulses_per_rev / wheel_diameter_mm nicht kalibriert — "
            "Encoder bleiben deaktiviert"
        )
        return None
    meters_per_count = math.pi * (wheel_diameter_mm / 1000.0) / pulses_per_rev
    left = enc.get("left", {})
    right = enc.get("right", {})
    try:
        return LgpioEncoderPair(
            left_a=int(left.get("channel_a", 21)),
            left_b=int(left.get("channel_b", 24)),
            right_a=int(right.get("channel_a", 14)),
            right_b=int(right.get("channel_b", 15)),
            meters_per_count=meters_per_count,
            invert_left=bool(enc.get("invert_left", False)),
            invert_right=bool(enc.get("invert_right", False)),
            debounce_us=int(enc.get("debounce_us", 200)),
        )
    except Exception as exc:
        logger.warning("Encoder-Setup fehlgeschlagen (%s) — nutze Zeitsteuerung", exc)
        return None
