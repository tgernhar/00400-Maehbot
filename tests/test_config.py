"""Tests for config loading."""

from maehbot.config_loader import load_config, is_class_sprayable


def test_load_config_has_defaults():
    config = load_config()
    assert config["spray"]["camera_to_nozzle_mm"] == 20
    assert config["mode"]["test_mode"] is True


def test_grass_not_sprayable():
    config = load_config()
    assert not is_class_sprayable(config, "grass")
    assert is_class_sprayable(config, "clover")
