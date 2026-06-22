"""Spray controller: scheduled GPIO activation for valve and pump."""

from __future__ import annotations

import heapq
import logging
import threading
import time
from dataclasses import dataclass, field

from spray.gpio import PinMap

logger = logging.getLogger(__name__)


@dataclass(order=True)
class ScheduledSpray:
    fire_at_ms: float
    duration_ms: float = field(compare=False)
    seq: int = field(compare=False, default=0)


class SprayController:
    def __init__(self, pins: PinMap, duration_ms: float) -> None:
        self.pins = pins
        self.duration_ms = duration_ms
        self._heap: list[ScheduledSpray] = []
        self._lock = threading.Lock()
        self._seq = 0
        self._worker = threading.Thread(target=self._run_worker, name="spray-worker", daemon=True)
        self._running = False
        self._active = False

    def start(self) -> None:
        self.pins.setup()
        self._running = True
        self._worker.start()

    def stop(self) -> None:
        self._running = False
        self._worker.join(timeout=2)
        self._deactivate()

    def update_duration(self, duration_ms: float) -> None:
        self.duration_ms = duration_ms

    def schedule(self, fire_at_ms: float) -> None:
        with self._lock:
            self._seq += 1
            heapq.heappush(
                self._heap,
                ScheduledSpray(fire_at_ms=fire_at_ms, duration_ms=self.duration_ms, seq=self._seq),
            )

    def _run_worker(self) -> None:
        while self._running:
            now_ms = time.monotonic() * 1000.0
            item: ScheduledSpray | None = None
            with self._lock:
                if self._heap and self._heap[0].fire_at_ms <= now_ms:
                    item = heapq.heappop(self._heap)
            if item is None:
                sleep_s = 0.001
                with self._lock:
                    if self._heap:
                        wait_ms = max(0.0, self._heap[0].fire_at_ms - now_ms)
                        sleep_s = min(wait_ms / 1000.0, 0.05)
                time.sleep(sleep_s)
                continue
            self._activate()
            time.sleep(item.duration_ms / 1000.0)
            self._deactivate()

    def _activate(self) -> None:
        self._active = True
        self.pins.gpio.write(self.pins.pump, True)
        self.pins.gpio.write(self.pins.nozzle_valve, True)
        logger.debug("Spray activated")

    def _deactivate(self) -> None:
        self._active = False
        self.pins.gpio.write(self.pins.pump, False)
        self.pins.gpio.write(self.pins.nozzle_valve, False)
