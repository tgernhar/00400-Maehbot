"""Core realtime loop: vision → safety → spray schedule → async storage."""

from __future__ import annotations

import logging
import signal
import sys
import time
from pathlib import Path
from typing import Any

from maehbot.config_loader import get_config_dir, load_config
from maehbot.node import NodeConfig
from maehbot.types import Detection, Frame, SprayEvent, SystemStatus
from core.health import HealthMonitor
from drive.command import consume_drive_command, write_drive_status
from drive.controller import DriveController
from drive.motor import MotorDriver, MotorPins
from spray.controller import SprayController
from spray.gpio import create_gpio_backend, PinMap
from spray.safety import evaluate_spray_allowed
from spray.scheduler import SprayScheduler
from storage.async_writer import AsyncStorageWriter
from storage.database import Database
from storage.paths import StoragePaths
from storage.retention import RetentionManager
from training.recording import (
    LearningDriveRecorder,
    RecordingState,
    consume_recording_command,
    default_recording_status,
    write_recording_status,
)
from training.session import register_snapshot_session
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
        self.node = NodeConfig(self.config)
        self._apply_storage_root_for_dev()
        self._init_storage()
        self._init_gpio()
        self._init_spray()
        self._init_drive()
        # Tank sensors belong to the spray hardware (vision node only)
        self.health = HealthMonitor(pins=self.pins if self.node.runs_vision else None)
        self.health.set_test_mode(bool(self.config.get("mode", {}).get("test_mode", True)))
        self._config_mtime = self._local_config_mtime()
        self._last_status_write = 0.0
        self._last_preview_write = 0.0
        self._preview_interval_s = self._preview_interval_from_config()
        self._last_recording_status_write = 0.0
        self.pipeline: VisionPipeline | None = None
        self._preview_camera: Any = None
        self.recorder: LearningDriveRecorder | None = None
        if self.node.runs_vision:
            fps = int(self.config.get("camera", {}).get("fps", 30))
            self.recorder = LearningDriveRecorder(self.paths, self.db, fps=fps)
            self.recorder.publish_status()
        self._last_frame: Frame | None = None

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

    def _init_drive(self) -> None:
        drive_cfg = self.config.get("drive", {})
        motor_pins = MotorPins(self.config.get("motor", {}))
        driver = MotorDriver(
            self.gpio_backend,
            motor_pins,
            invert_left=bool(drive_cfg.get("invert_left", False)),
            invert_right=bool(drive_cfg.get("invert_right", False)),
        )
        self.drive_controller = DriveController(
            driver,
            max_speed=float(drive_cfg.get("max_speed", 1.0)),
            watchdog_timeout_s=float(drive_cfg.get("watchdog_timeout_ms", 1000)) / 1000.0,
            enabled=bool(drive_cfg.get("enabled", True)),
        )
        self._last_drive_status_write = 0.0

    def _local_config_mtime(self) -> float:
        p = get_config_dir() / "local.yaml"
        return p.stat().st_mtime if p.exists() else 0.0

    def _preview_interval_from_config(self) -> float:
        preview_fps = float(self.config.get("camera", {}).get("preview_fps", 5))
        return 1.0 / max(preview_fps, 0.5)

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
        drive_cfg = self.config.get("drive", {})
        self.drive_controller.update_config(
            max_speed=float(drive_cfg.get("max_speed", 1.0)),
            watchdog_timeout_s=float(drive_cfg.get("watchdog_timeout_ms", 1000)) / 1000.0,
            enabled=bool(drive_cfg.get("enabled", True)),
            invert_left=bool(drive_cfg.get("invert_left", False)),
            invert_right=bool(drive_cfg.get("invert_right", False)),
        )
        self.health.set_test_mode(bool(self.config.get("mode", {}).get("test_mode", True)))
        self._preview_interval_s = self._preview_interval_from_config()
        logger.info("Config reloaded from local.yaml")

    def _on_detections(self, frame: Frame, detections: list[Detection]) -> None:
        t_schedule_start = time.monotonic()
        self._last_frame = frame
        self.health.record_frame(frame.timestamp_ms)
        if self.recorder:
            self.recorder.write_frame(frame)
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
        if frame.data and now - self._last_preview_write >= self._preview_interval_s:
            try:
                self.paths.preview_path.write_bytes(frame.data)
                self._last_preview_write = now
            except OSError:
                logger.warning("Failed to write camera preview")

        if now - self._last_status_write > 2.0:
            self._write_status(status)
            self._maybe_publish_recording_status()
            self._last_status_write = now

    def _maybe_publish_recording_status(self) -> None:
        if not self.recorder or self.recorder.state.value == "idle":
            return
        now = time.monotonic()
        if now - self._last_recording_status_write > 1.0:
            self.recorder.publish_status()
            self._last_recording_status_write = now

    def _poll_recording(self) -> None:
        if not self.recorder:
            return
        command = consume_recording_command(self.paths)
        if not command:
            return
        action = str(command.get("action", "")).lower()
        if action == "snapshot":
            self._handle_snapshot(str(command.get("name", "Foto")))
            return
        self.recorder.handle_command(command)

    def _poll_drive(self) -> None:
        command = consume_drive_command(self.paths)
        if command is not None:
            self.drive_controller.set_speeds(
                float(command.get("left", 0.0)),
                float(command.get("right", 0.0)),
            )
        now = time.monotonic()
        if now - self._last_drive_status_write > 0.5:
            write_drive_status(self.paths, self.drive_controller.status_dict())
            self._last_drive_status_write = now

    def _handle_snapshot(self, name: str) -> None:
        if self.recorder.state != RecordingState.IDLE:
            write_recording_status(
                self.paths,
                {
                    **self.recorder.status_dict(),
                    "error": "Während Videoaufnahme kein Einzelfoto möglich",
                },
            )
            return
        if not self._last_frame or not self._last_frame.data:
            write_recording_status(
                self.paths,
                {**default_recording_status(), "error": "Kein Kamerabild verfügbar"},
            )
            return
        try:
            result = register_snapshot_session(
                self.paths,
                self.db,
                name,
                self._last_frame.data,
            )
            write_recording_status(
                self.paths,
                {
                    "state": RecordingState.IDLE.value,
                    "session_name": result["name"],
                    "frame_count": 1,
                    "session_id": result["id"],
                    "error": None,
                },
            )
            logger.info("Training snapshot saved as session %s", result["id"])
            # #region agent log
            try:
                import json as _json
                from pathlib import Path as _Path

                _Path("debug-bc4e4e.log").open("a", encoding="utf-8").write(
                    _json.dumps(
                        {
                            "sessionId": "bc4e4e",
                            "runId": "core",
                            "hypothesisId": "H3",
                            "location": "core/main.py:_handle_snapshot",
                            "message": "snapshot session registered",
                            "data": {"session_id": result["id"], "name": result["name"]},
                            "timestamp": int(time.time() * 1000),
                        }
                    )
                    + "\n"
                )
            except OSError:
                pass
            # #endregion
        except Exception as exc:
            logger.exception("Training snapshot failed")
            write_recording_status(
                self.paths,
                {**default_recording_status(), "error": str(exc)},
            )

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

    def _preview_tick(self) -> None:
        """Drive-only nodes: read camera at preview rate, no detection."""
        if not self._preview_camera:
            return
        now = time.monotonic()
        if now - self._last_preview_write < self._preview_interval_s:
            return
        frame = self._preview_camera.read()
        if not frame or not frame.data:
            return
        self._last_frame = frame
        self.health.record_frame(frame.timestamp_ms)
        try:
            self.paths.preview_path.write_bytes(frame.data)
        except OSError:
            logger.warning("Failed to write camera preview")
        self._last_preview_write = now

    def run(self) -> None:
        if self.node.runs_drive:
            self.drive_controller.start()
            write_drive_status(self.paths, self.drive_controller.status_dict())

        self._preview_camera = None
        if self.node.runs_vision:
            self.spray_controller.start()
            camera = create_camera(self.config, force_mock=self.force_mock)
            detector = create_detector(self.config, force_mock=self.force_mock)
            self.pipeline = VisionPipeline(camera, detector, self._on_detections)
            self.pipeline.start()
        else:
            camera = create_camera(self.config, force_mock=self.force_mock)
            try:
                camera.start()
                self._preview_camera = camera
            except Exception:
                logger.exception("Kamera-Start fehlgeschlagen — Vorschau deaktiviert")

        fps = int(self.config.get("camera", {}).get("fps", 30))
        logger.info(
            "Core started (role=%s, test_mode=%s, force_mock=%s)",
            self.node.role,
            self.health.test_mode,
            self.force_mock,
        )

        while True:
            self.reload_config_if_changed()
            self._poll_recording()
            if self.node.runs_drive:
                self._poll_drive()
            if self.pipeline:
                if not self.pipeline.process_one():
                    time.sleep(0.01)
                else:
                    interval = 1.0 / max(fps, 1)
                    time.sleep(max(0.0, interval - 0.001))
            else:
                self._preview_tick()
                now = time.monotonic()
                if now - self._last_status_write > 2.0:
                    self._write_status(self.health.build_status())
                    self._last_status_write = now
                # Fast cadence so drive commands are consumed promptly
                time.sleep(0.02)

    def shutdown(self) -> None:
        if self.pipeline:
            self.pipeline.stop()
        if self._preview_camera:
            self._preview_camera.stop()
        if self.recorder:
            self.recorder.shutdown()
        if self.node.runs_vision:
            self.spray_controller.stop()
        if self.node.runs_drive:
            self.drive_controller.stop()
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
