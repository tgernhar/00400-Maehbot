"""Tests for safety guards."""

from maehbot.config_loader import load_config
from maehbot.types import BBox, Detection, SystemStatus
from spray.safety import evaluate_spray_allowed, tank_ok_from_gpio


def _det(confidence: float = 0.9, class_id: str = "clover") -> Detection:
    return Detection(
        class_id=class_id,
        confidence=confidence,
        bbox=BBox(x=10, y=10, width=50, height=50),
        frame_timestamp_ms=1000.0,
        image_width=640,
        image_height=480,
    )


def test_test_mode_blocks_spray():
    config = load_config()
    status = SystemStatus(test_mode=True, camera_healthy=True)
    allowed, reason = evaluate_spray_allowed(_det(), config, status)
    assert not allowed
    assert reason == "test_mode"


def test_low_confidence_blocks():
    config = load_config()
    status = SystemStatus(test_mode=False, camera_healthy=True)
    allowed, reason = evaluate_spray_allowed(_det(confidence=0.1), config, status)
    assert not allowed
    assert reason == "low_confidence"


def test_grass_not_sprayable():
    config = load_config()
    status = SystemStatus(test_mode=False, camera_healthy=True)
    allowed, reason = evaluate_spray_allowed(_det(class_id="grass"), config, status)
    assert not allowed
    assert reason == "class_not_sprayable"


def test_tank_empty_blocks():
    config = load_config()
    status = SystemStatus(test_mode=False, camera_healthy=True, tank_empty=True)
    allowed, reason = evaluate_spray_allowed(_det(), config, status)
    assert not allowed
    assert reason == "tank_empty"


def test_allowed_when_ok():
    config = load_config()
    status = SystemStatus(test_mode=False, camera_healthy=True, tank_empty=False)
    allowed, reason = evaluate_spray_allowed(_det(), config, status)
    assert allowed
    assert reason is None


def test_tank_ok_from_gpio():
    assert not tank_ok_from_gpio(tank_empty=True, tank_full=False)
    assert tank_ok_from_gpio(tank_empty=False, tank_full=True)
