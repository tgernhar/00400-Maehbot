"""File-based IPC for servo commands (web → core) and status (core → web).

Mirrors drive/command.py: the web process never touches GPIO. It queues a
small JSON command file that the core process consumes in its main loop.

Commands:
    {"action": "home"}
    {"action": "test", "angles": {"position": 90, "tension": 120, "trigger": 30}}
    {"action": "sweep", "servo": "tension"}
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from storage.paths import StoragePaths

logger = logging.getLogger(__name__)


def default_servo_status() -> dict[str, Any]:
    return {
        "state": "idle",
        "angles": {"position": None, "tension": None, "trigger": None},
        "error": None,
        "updated_at": 0.0,
    }


def read_servo_status(paths: StoragePaths) -> dict[str, Any]:
    path = paths.servo_status_path
    if not path.exists():
        return default_servo_status()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {**default_servo_status(), **data}
    except (json.JSONDecodeError, OSError):
        return default_servo_status()


def write_servo_status(paths: StoragePaths, status: dict[str, Any]) -> None:
    paths.servo_status_path.write_text(
        json.dumps(status, ensure_ascii=False),
        encoding="utf-8",
    )


def queue_servo_command(
    paths: StoragePaths,
    action: str,
    angles: dict[str, float] | None = None,
    servo: str | None = None,
) -> None:
    payload: dict[str, Any] = {"action": action, "ts": time.time()}
    if angles is not None:
        payload["angles"] = {k: float(v) for k, v in angles.items()}
    if servo is not None:
        payload["servo"] = servo
    paths.servo_command_path.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )


def consume_servo_command(paths: StoragePaths) -> dict[str, Any] | None:
    path = paths.servo_command_path
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        path.unlink(missing_ok=True)
        return data
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Invalid servo command file: %s", exc)
        path.unlink(missing_ok=True)
        return None
