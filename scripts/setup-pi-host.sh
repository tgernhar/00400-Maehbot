#!/usr/bin/env bash
# Native Maehbot core on Raspberry Pi OS (PEP 668 safe: venv + apt for picamera2/lgpio).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> Creating shared data directory (native core + Docker web)..."
sudo mkdir -p /var/lib/maehbot
sudo chown "$(whoami):$(whoami)" /var/lib/maehbot

echo "==> Installing system packages (picamera2, lgpio, venv)..."
sudo apt-get update
sudo apt-get install -y python3-venv python3-picamera2 python3-lgpio

echo "==> Creating venv with system site packages (for apt picamera2/lgpio)..."
python3 -m venv .venv --system-site-packages

# shellcheck disable=SC1091
source .venv/bin/activate

echo "==> Installing Maehbot into venv..."
pip install --upgrade pip
pip install -r requirements.txt
pip install -e .

echo ""
echo "Setup complete."
echo "  Activate:  source $ROOT/.venv/bin/activate"
echo "  Test core: python -m core.main"
echo "  systemd:   see docs/deploy.md (ExecStart=$ROOT/.venv/bin/python -m core.main)"
