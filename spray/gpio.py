"""GPIO abstraction for nozzle, pump, and tank sensors."""

from __future__ import annotations

import json
import logging
import sys
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# region agent log
def _agent_log(location: str, message: str, data: dict[str, Any], hypothesis_id: str) -> None:
    entry = {
        "sessionId": "0911b3",
        "timestamp": int(time.time() * 1000),
        "location": location,
        "message": message,
        "data": data,
        "hypothesisId": hypothesis_id,
        "runId": "pre-fix",
    }
    line = json.dumps(entry) + "\n"
    for path in (Path("debug-0911b3.log"), Path(__file__).resolve().parents[1] / "debug-0911b3.log"):
        try:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line)
            return
        except OSError:
            continue
# endregion


class GPIOBackend(ABC):
    @abstractmethod
    def setup_output(self, pin: int) -> None: ...

    @abstractmethod
    def setup_input(self, pin: int) -> None: ...

    @abstractmethod
    def write(self, pin: int, value: bool) -> None: ...

    @abstractmethod
    def read(self, pin: int) -> bool: ...

    @abstractmethod
    def setup_pwm(self, pin: int, frequency_hz: float) -> None:
        """Claim a pin for PWM output at the given frequency, initial duty 0."""

    @abstractmethod
    def set_pwm_duty(self, pin: int, duty_percent: float) -> None:
        """Set PWM duty cycle in percent (0..100)."""

    @abstractmethod
    def stop_pwm(self, pin: int) -> None:
        """Stop PWM on a pin (servos go limp, no holding torque)."""

    @abstractmethod
    def close(self) -> None: ...


class MockGPIO(GPIOBackend):
    def __init__(self) -> None:
        self._outputs: dict[int, bool] = {}
        self._inputs: dict[int, bool] = {}
        self._pwm_freq: dict[int, float] = {}
        self.pwm: dict[int, float] = {}
        self.write_log: list[tuple[int, bool]] = []
        self.pwm_log: list[tuple[int, float]] = []

    def setup_output(self, pin: int) -> None:
        self._outputs.setdefault(pin, False)

    def setup_input(self, pin: int) -> None:
        self._inputs.setdefault(pin, False)

    def write(self, pin: int, value: bool) -> None:
        self._outputs[pin] = value
        self.write_log.append((pin, value))

    def read(self, pin: int) -> bool:
        return self._inputs.get(pin, False)

    def setup_pwm(self, pin: int, frequency_hz: float) -> None:
        self._pwm_freq[pin] = frequency_hz
        self.pwm.setdefault(pin, 0.0)

    def set_pwm_duty(self, pin: int, duty_percent: float) -> None:
        duty = max(0.0, min(100.0, duty_percent))
        self.pwm[pin] = duty
        self.pwm_log.append((pin, duty))

    def stop_pwm(self, pin: int) -> None:
        self.pwm[pin] = 0.0
        self.pwm_log.append((pin, -1.0))

    def set_input(self, pin: int, value: bool) -> None:
        self._inputs[pin] = value

    def close(self) -> None:
        pass


class LgpioGPIO(GPIOBackend):
    """Real GPIO via lgpio on Raspberry Pi."""

    def __init__(self) -> None:
        try:
            import lgpio
        except ImportError as e:
            raise RuntimeError("lgpio not available") from e
        self._lgpio = lgpio
        self._chip = lgpio.gpiochip_open(0)
        self._pwm_freq: dict[int, float] = {}

    def setup_output(self, pin: int) -> None:
        self._lgpio.gpio_claim_output(self._chip, pin)

    def setup_input(self, pin: int) -> None:
        self._lgpio.gpio_claim_input(self._chip, pin)

    def write(self, pin: int, value: bool) -> None:
        self._lgpio.gpio_write(self._chip, pin, 1 if value else 0)

    def read(self, pin: int) -> bool:
        return bool(self._lgpio.gpio_read(self._chip, pin))

    def setup_pwm(self, pin: int, frequency_hz: float) -> None:
        self._lgpio.gpio_claim_output(self._chip, pin)
        self._pwm_freq[pin] = frequency_hz
        self._lgpio.tx_pwm(self._chip, pin, frequency_hz, 0.0)

    def set_pwm_duty(self, pin: int, duty_percent: float) -> None:
        freq = self._pwm_freq.get(pin, 1000.0)
        duty = max(0.0, min(100.0, duty_percent))
        result = self._lgpio.tx_pwm(self._chip, pin, freq, duty)
        # region agent log
        _agent_log(
            "gpio.py:set_pwm_duty",
            "tx_pwm duty",
            {"pin": pin, "freq": freq, "duty": duty, "result": result},
            "H4",
        )
        # endregion

    def stop_pwm(self, pin: int) -> None:
        tx_pwm_kind = getattr(self._lgpio, "TX_PWM", 0)
        busy_before = self._lgpio.tx_busy(self._chip, pin, tx_pwm_kind)
        result = self._lgpio.tx_pwm(self._chip, pin, 0, 0)
        busy_after = self._lgpio.tx_busy(self._chip, pin, tx_pwm_kind)
        # region agent log
        _agent_log(
            "gpio.py:stop_pwm",
            "tx_pwm stop",
            {
                "pin": pin,
                "result": result,
                "busy_before": busy_before,
                "busy_after": busy_after,
            },
            "H3",
        )
        # endregion

    def close(self) -> None:
        self._lgpio.gpiochip_close(self._chip)


def create_gpio_backend(config: dict[str, Any], force_mock: bool = False) -> GPIOBackend:
    if force_mock or sys.platform != "linux":
        logger.info("Using MockGPIO")
        return MockGPIO()
    try:
        return LgpioGPIO()
    except RuntimeError:
        logger.warning("lgpio unavailable, falling back to MockGPIO")
        return MockGPIO()


class PinMap:
    def __init__(self, gpio: GPIOBackend, pins: dict[str, int]) -> None:
        self.gpio = gpio
        self.nozzle_valve = pins.get("nozzle_valve", 17)
        self.pump = pins.get("pump", 27)
        self.tank_full = pins.get("tank_full", 22)
        self.tank_empty = pins.get("tank_empty", 23)

    def setup(self) -> None:
        self.gpio.setup_output(self.nozzle_valve)
        self.gpio.setup_output(self.pump)
        self.gpio.setup_input(self.tank_full)
        self.gpio.setup_input(self.tank_empty)
        self.gpio.write(self.nozzle_valve, False)
        self.gpio.write(self.pump, False)

    def read_tank_empty(self) -> bool:
        return self.gpio.read(self.tank_empty)

    def read_tank_full(self) -> bool:
        return self.gpio.read(self.tank_full)

    def tank_ok(self) -> bool:
        empty = self.read_tank_empty()
        full = self.read_tank_full()
        if empty:
            return False
        if full and empty:
            return False
        return True
