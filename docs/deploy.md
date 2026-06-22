# Maehbot Deployment

## Docker Compose (recommended)

On the Raspberry Pi:

```bash
cd docker
docker compose up -d --build
```

Web UI: `http://<pi-ip>:8080`

### Services

- **core** — realtime vision + spray loop (privileged, GPIO + camera)
- **web** — FastAPI + React UI

Shared volume `maehbot-data` maps to `/var/lib/maehbot`.

## Configuration on Pi

Create `config/local.yaml` (not in git):

```yaml
storage:
  root_path: /var/lib/maehbot
gpio:
  nozzle_valve: 17
  pump: 27
  tank_full: 22
  tank_empty: 23
```

The web service mounts `config/` writable so API changes persist to `local.yaml`.
Core reads `local.yaml` on change (mtime watch).

## Deploy from Windows PC

```powershell
scp -r . pi@<pi-ip>:/home/pi/maehbot
ssh pi@<pi-ip> "cd maehbot/docker && docker compose up -d --build"
```

Or use git pull on the Pi if the repo is hosted remotely.

## systemd fallback for core

If Docker cannot access GPIO or camera reliably, run core on the host:

```ini
# /etc/systemd/system/maehbot-core.service
[Unit]
Description=Maehbot Core
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/maehbot
ExecStart=/home/pi/maehbot/.venv/bin/python -m core.main
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

Keep **web** in Docker with shared `/var/lib/maehbot`.

## Safety checklist before live spray

1. Test mode runs successfully (`test_mode: true`)
2. Tank sensors verified (full/empty GPIO)
3. Travel time calibrated (camera–nozzle distance, real speed)
4. `min_confidence` tuned on field data
5. Set `test_mode: false` only deliberately in UI or config
