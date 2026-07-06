"""Tests for node roles (multi-device split) and camera factory selection."""

import pytest

from maehbot.node import NodeConfig
from vision.camera import MockCamera, create_camera


def test_default_role_is_all():
    node = NodeConfig({})
    assert node.role == "all"
    assert node.runs_drive is True
    assert node.runs_vision is True
    assert node.has_vision_peer is False


def test_drive_role_without_peer():
    node = NodeConfig({"node": {"role": "drive"}})
    assert node.runs_drive is True
    assert node.runs_vision is False
    assert node.has_vision_peer is False


def test_drive_role_with_peer_url_stripped():
    node = NodeConfig(
        {"node": {"role": "drive", "peers": {"vision_url": "http://pi5:8080/ "}}}
    )
    assert node.has_vision_peer is True
    assert node.vision_url == "http://pi5:8080"


def test_vision_role_ignores_peer():
    node = NodeConfig(
        {"node": {"role": "vision", "peers": {"vision_url": "http://x:1"}}}
    )
    assert node.runs_vision is True
    assert node.has_vision_peer is False


def test_invalid_role_raises():
    with pytest.raises(ValueError):
        NodeConfig({"node": {"role": "gibberish"}})


def test_camera_factory_mock_source_and_size():
    cam = create_camera(
        {"camera": {"source": "mock", "width": 320, "height": 240, "fps": 5}},
        force_mock=True,
    )
    assert isinstance(cam, MockCamera)
    assert cam.width == 320
    assert cam.height == 240


def test_core_drive_role_skips_vision(tmp_path):
    from core.main import CoreApplication
    from maehbot.config_loader import save_local_config

    # Isolate config writes away from the repo config dir
    import maehbot.config_loader as cl

    cfg = {
        "node": {"role": "drive"},
        "storage": {"root_path": str(tmp_path / "data")},
        "camera": {"source": "mock", "fps": 5},
    }
    orig_load = cl.load_config

    def patched_load(*args, **kwargs):
        merged = orig_load(*args, **kwargs)
        merged.update(cfg)
        return merged

    import core.main as core_main

    core_main.load_config = patched_load
    try:
        app = CoreApplication(force_mock=True)
        assert app.node.role == "drive"
        assert app.recorder is None
        assert app.pipeline is None
        assert app.drive_controller is not None
    finally:
        core_main.load_config = orig_load
        app.writer.stop()
        app.gpio_backend.close()
