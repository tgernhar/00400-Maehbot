"""Node role configuration for multi-device deployments.

A Maehbot installation can be split across devices ("nodes"):
- role "drive": motor control + camera preview (teleoperation node)
- role "vision": detection, spray, training (weed-control node)
- role "all": single-device setup, everything on one Pi (default)

Roles are pure configuration (config/local.yaml) so a node's hardware can be
replaced by a newer Pi without code changes.
"""

from __future__ import annotations

from typing import Any

VALID_ROLES = ("all", "drive", "vision")


class NodeConfig:
    def __init__(self, config: dict[str, Any]) -> None:
        node = config.get("node", {}) or {}
        role = str(node.get("role", "all")).strip().lower()
        if role not in VALID_ROLES:
            raise ValueError(
                f"Ungültige node.role '{role}' — erlaubt: {', '.join(VALID_ROLES)}"
            )
        self.role = role
        peers = node.get("peers", {}) or {}
        self.vision_url = str(peers.get("vision_url", "") or "").strip().rstrip("/")

    @property
    def runs_drive(self) -> bool:
        return self.role in ("all", "drive")

    @property
    def runs_vision(self) -> bool:
        return self.role in ("all", "vision")

    @property
    def has_vision_peer(self) -> bool:
        return not self.runs_vision and bool(self.vision_url)
