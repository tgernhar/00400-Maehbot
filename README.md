# Maehbot

Weed detection on a lawn mower robot using Raspberry Pi 5 + Sony IMX500 AI camera.
Triggers a micro-dosing nozzle aligned with the camera when sprayable plants are detected.

## Architecture

- **core** — real-time vision + spray loop (no HTTP in hot path)
- **web** — FastAPI REST API + React browser UI

## Quick start (PC development)

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
pip install -e .

# Run core with mocks (test mode, no GPIO)
python -m core.main

# Run API
python -m web.backend.app
```

Frontend dev server:

```bash
cd web/frontend
npm install
npm run dev
```

## Configuration

Layered YAML in `config/`:

1. `defaults.yaml` — project defaults
2. `hardware.yaml` — GPIO pin template
3. `local.yaml` — machine overrides (copy from `local.yaml.example`, gitignored)

On PC dev, set in `config/local.yaml`:

```yaml
storage:
  root_path: ./data/maehbot
```

## Raspberry Pi deployment

See [docs/deploy.md](docs/deploy.md) and [docker/docker-compose.yml](docker/docker-compose.yml).

```bash
docker compose -f docker/docker-compose.yml up -d
```

Web UI: `http://<pi-ip>:8080`

## Tests

```bash
pytest
pytest -m pi   # on Raspberry Pi with hardware
```

## Safety

Default `test_mode: true` — detections only, no spray. Enable live spray only after field calibration.
