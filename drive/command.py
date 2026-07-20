"""File-based IPC for drive commands (web → core) and status (core → web).

The web process never touches GPIO. It queues a small JSON command file that
the core process consumes in its main loop, mirroring the learning-drive
recording IPC. Track speeds are signed fractions in -1..1 (left, right).
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from storage.paths import StoragePaths

logger = logging.getLogger(__name__)


def default_drive_status() -> dict[str, Any]:
    return {
        "left": 0.0,
        "right": 0.0,
        "enabled": True,
        "moving": False,
        "max_speed": 1.0,
        "error": None,
        "encoder_enabled": False,
        "encoder_left_m": None,
        "encoder_right_m": None,
    }


def read_drive_status(paths: StoragePaths) -> dict[str, Any]:
    path = paths.drive_status_path
    if not path.exists():
        return default_drive_status()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {**default_drive_status(), **data}
    except (json.JSONDecodeError, OSError):
        return default_drive_status()


def write_drive_status(paths: StoragePaths, status: dict[str, Any]) -> None:
    paths.drive_status_path.write_text(
        json.dumps(status, ensure_ascii=False),
        encoding="utf-8",
    )


def queue_drive_command(paths: StoragePaths, left: float, right: float) -> None:
    payload = {
        "left": max(-1.0, min(1.0, float(left))),
        "right": max(-1.0, min(1.0, float(right))),
        "ts": time.time(),
    }
    paths.drive_command_path.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )


def consume_drive_command(paths: StoragePaths) -> dict[str, Any] | None:
    path = paths.drive_command_path
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        path.unlink(missing_ok=True)
        return data
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Invalid drive command file: %s", exc)
        path.unlink(missing_ok=True)
        return None
