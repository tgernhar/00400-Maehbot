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

echo "Setup complete."
echo "  Activate:  source $ROOT/.venv/bin/activate"
echo "  Test core: python -m core.main"
echo ""
echo "Stopping Docker core (use native core on host)..."
if [[ -d "$ROOT/docker" ]]; then
  (cd "$ROOT/docker" && docker compose stop core 2>/dev/null) || true
fi
echo ""
echo "Install systemd (optional):"
echo "  sudo cp $ROOT/deploy/maehbot-core.service /etc/systemd/system/"
echo "  # edit User/ paths if needed, then:"
echo "  sudo systemctl daemon-reload && sudo systemctl enable --now maehbot-core"
echo ""
echo "Web UI only in Docker:"
echo "  cd $ROOT/docker && docker compose up -d web"
