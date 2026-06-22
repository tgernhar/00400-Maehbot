"""Load and merge YAML configuration: defaults → hardware → local."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_DIR = _PROJECT_ROOT / "config"


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data if isinstance(data, dict) else {}


def get_project_root() -> Path:
    return _PROJECT_ROOT


def get_config_dir() -> Path:
    return _CONFIG_DIR


def load_config(
    config_dir: Path | None = None,
    reload: bool = False,
) -> dict[str, Any]:
    """Merge defaults.yaml, hardware.yaml, and local.yaml (if present)."""
    cfg_dir = config_dir or _CONFIG_DIR
    merged = _load_yaml(cfg_dir / "defaults.yaml")
    merged = _deep_merge(merged, _load_yaml(cfg_dir / "hardware.yaml"))
    merged = _deep_merge(merged, _load_yaml(cfg_dir / "local.yaml"))
    return merged


def save_local_config(updates: dict[str, Any], config_dir: Path | None = None) -> Path:
    """Merge updates into local.yaml and write file."""
    cfg_dir = config_dir or _CONFIG_DIR
    local_path = cfg_dir / "local.yaml"
    current = _load_yaml(local_path)
    merged = _deep_merge(current, updates)
    with local_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(merged, f, default_flow_style=False, allow_unicode=True)
    return local_path


def get_class_by_id(config: dict[str, Any], class_id: str) -> dict[str, Any] | None:
    for cls in config.get("classes", []):
        if cls.get("id") == class_id:
            return cls
    return None


def is_class_sprayable(config: dict[str, Any], class_id: str) -> bool:
    cls = get_class_by_id(config, class_id)
    return bool(cls and cls.get("sprayable"))
