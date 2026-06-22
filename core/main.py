"""Core realtime loop: vision → safety → spray schedule → async storage."""

from __future__ import annotations

import logging
import signal
import sys
import time
from pathlib import Path
from typing import Any

from maehbot.config_loader import get_config_dir, load_config
from maehbot.types import Detection, Frame, SprayEvent, SystemStatus
from core.health import HealthMonitor
from spray.controller import SprayController
from spray.gpio import create_gpio_backend, PinMap
from spray.safety import evaluate_spray_allowed
from spray.scheduler import SprayScheduler
from storage.async_writer import AsyncStorageWriter
from storage.database import Database
from storage.paths import StoragePaths
from storage.retention import RetentionManager
from vision.camera import create_camera
from vision.detector import create_detector
from vision.pipeline import VisionPipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("maehbot.core")


class CoreApplication:
    def __init__(self, force_mock: bool = False) -> None:
        self.force_mock = force_mock
        self.config = load_config()
        self._apply_storage_root_for_dev()
        self._init_storage()
        self._init_gpio()
        self._init_spray()
        self.health = HealthMonitor(pins=self.pins)
        self.health.set_test_mode(bool(self.config.get("mode", {}).get("test_mode", True)))
        self._config_mtime = self._local_config_mtime()
        self._last_status_write = 0.0
        self.pipeline: VisionPipeline | None = None

    def _apply_storage_root_for_dev(self) -> None:
        root = self.config.get("storage", {}).get("root_path", "/var/lib/maehbot")
        if sys.platform != "linux":
            dev_root = Path("./data/maehbot")
            if str(root).startswith("/var"):
                self.config.setdefault("storage", {})["root_path"] = str(dev_root)

    def _init_storage(self) -> None:
        storage_cfg = self.config.get("storage", {})
        self.paths = StoragePaths(storage_cfg.get("root_path", "/var/lib/maehbot"))
        self.paths.ensure()
        self.db = Database(self.paths.db_path)
        self.retention = RetentionManager(
            self.paths,
            self.db,
            max_archived_images=int(storage_cfg.get("max_archived_images", 1000)),
            max_total_bytes=int(storage_cfg.get("max_total_bytes", 10 * 1024**3)),
        )
        self.writer = AsyncStorageWriter(self.paths, self.db, self.retention)
        self.writer.start()

    def _init_gpio(self) -> None:
        gpio_cfg = self.config.get("gpio", {})
        self.gpio_backend = create_gpio_backend(self.config, force_mock=self.force_mock)
        self.pins = PinMap(self.gpio_backend, gpio_cfg)

    def _init_spray(self) -> None:
        spray_cfg = self.config.get("spray", {})
        self.scheduler = SprayScheduler(
            spray_delay_ms=float(spray_cfg.get("delay_ms", 0)),
            camera_to_nozzle_mm=float(spray_cfg.get("camera_to_nozzle_mm", 20)),
            mower_speed_mm_s=float(spray_cfg.get("mower_speed_mm_s", 100)),
        )
        self.spray_controller = SprayController(
            self.pins,
            duration_ms=float(spray_cfg.get("duration_ms", 100)),
        )

    def _local_config_mtime(self) -> float:
        p = get_config_dir() / "local.yaml"
        return p.stat().st_mtime if p.exists() else 0.0

    def reload_config_if_changed(self) -> None:
        mtime = self._local_config_mtime()
        if mtime == self._config_mtime:
            return
        self._config_mtime = mtime
        self.config = load_config()
        self._apply_storage_root_for_dev()
        spray_cfg = self.config.get("spray", {})
        self.scheduler.update(
            spray_delay_ms=float(spray_cfg.get("delay_ms", 0)),
            camera_to_nozzle_mm=float(spray_cfg.get("camera_to_nozzle_mm", 20)),
            mower_speed_mm_s=float(spray_cfg.get("mower_speed_mm_s", 100)),
        )
        self.spray_controller.update_duration(float(spray_cfg.get("duration_ms", 100)))
        self.health.set_test_mode(bool(self.config.get("mode", {}).get("test_mode", True)))
        logger.info("Config reloaded from local.yaml")

    def _on_detections(self, frame: Frame, detections: list[Detection]) -> None:
        t_schedule_start = time.monotonic()
        self.health.record_frame(frame.timestamp_ms)
        status = self.health.build_status()

        for det in detections:
            allowed, reason = evaluate_spray_allowed(det, self.config, status)
            fire_at_ms: float | None = None
            if allowed:
                fire_at_ms = self.scheduler.schedule_fire_at(det.frame_timestamp_ms)
                schedule_latency_ms = (time.monotonic() - t_schedule_start) * 1000.0
                if schedule_latency_ms > 10:
                    logger.warning("Schedule latency %.1f ms exceeds 10 ms target", schedule_latency_ms)
                self.spray_controller.schedule(fire_at_ms)

            event = SprayEvent(
                detection=det,
                spray_scheduled=allowed,
                spray_blocked_reason=reason,
                fire_at_ms=fire_at_ms,
                image_bytes=frame.data,
            )
            self.writer.enqueue(event)

        now = time.monotonic()
        if now - self._last_status_write > 2.0:
            self._write_status(status)
            if frame.data:
                try:
                    self.paths.preview_path.write_bytes(frame.data)
                except OSError:
                    logger.warning("Failed to write camera preview")
            self._last_status_write = now

    def _write_status(self, status: SystemStatus) -> None:
        data: dict[str, Any] = {
            "test_mode": status.test_mode,
            "camera_healthy": status.camera_healthy,
            "tank_empty": status.tank_empty,
            "tank_full": status.tank_full,
            "last_frame_ms": status.last_frame_ms,
        }
        if self.pipeline:
            data["latency"] = self.pipeline.latency.summary()
        self.writer.write_status(data)

    def run(self) -> None:
        self.spray_controller.start()
        camera = create_camera(self.config, force_mock=self.force_mock)
        detector = create_detector(self.config, force_mock=self.force_mock)
        self.pipeline = VisionPipeline(camera, detector, self._on_detections)
        self.pipeline.start()

        fps = int(self.config.get("camera", {}).get("fps", 30))
        logger.info("Core started (test_mode=%s, force_mock=%s)", self.health.test_mode, self.force_mock)

        while True:
            self.reload_config_if_changed()
            if not self.pipeline.process_one():
                time.sleep(0.01)
            else:
                interval = 1.0 / max(fps, 1)
                time.sleep(max(0.0, interval - 0.001))

    def shutdown(self) -> None:
        if self.pipeline:
            self.pipeline.stop()
        self.spray_controller.stop()
        self.writer.stop()
        self.gpio_backend.close()


def main() -> None:
    force_mock = "--mock" in sys.argv
    app = CoreApplication(force_mock=force_mock)

    def _signal_handler(_sig: int, _frame: Any) -> None:
        logger.info("Shutdown requested")
        app.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    try:
        app.run()
    except KeyboardInterrupt:
        app.shutdown()


if __name__ == "__main__":
    main()
