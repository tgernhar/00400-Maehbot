# Zwei-Knoten-Konzept: Fahr-Knoten + Vision-Knoten

Das Projekt kann auf mehrere Raspberry Pis aufgeteilt werden. Die Rolle eines
Geräts ist **reine Konfiguration** (`config/local.yaml`) – dadurch lässt sich
jeder Knoten später durch einen neueren Pi ersetzen, ohne Code zu ändern:
Repo klonen, `local.yaml` mit derselben Rolle anlegen, Dienste starten.

## Rollen

| Rolle | Aufgaben | Hardware-Beispiel |
|---|---|---|
| `all` (Default) | alles auf einem Gerät | Pi 5 + IMX500 + TB6612FNG |
| `drive` | Motoren (TB6612FNG) + Kamera-Vorschau | Pi 1 B+ / beliebiger Pi mit Kamera |
| `vision` | Erkennung, Sprühen, Training | Pi 5 + IMX500 + Düse |

Konfiguration je Gerät in `config/local.yaml`:

```yaml
# Fahr-Knoten (z. B. Pi 1 B+ mit CSI-Kamera)
node:
  role: drive
  peers:
    vision_url: ""          # später: http://maehbot-vision.local:8080
camera:
  source: picamera2         # auto | picamera2 | usb | mock
  width: 320                # niedrig halten auf schwacher Hardware
  height: 240
  fps: 5
  preview_fps: 2
```

```yaml
# Vision-Knoten (Pi 5)
node:
  role: vision
```

## Eine Webseite für beide Knoten

Die Web-UI läuft auf dem Fahr-Knoten. Sobald `peers.vision_url` gesetzt ist,
leitet dessen Backend alle Vision-Endpunkte (`/api/detections`, `/api/training`,
`/api/config/spray`, `/api/config/mode`, `/api/classes`) transparent an den
Vision-Knoten weiter. Der Browser spricht immer nur eine Adresse an.

- Fahren + Kamera-Vorschau: lokal auf dem Fahr-Knoten (`/api/camera/preview`)
- Sprühen/Review/Training: Vision-Kamera vom Sprüh-Pi (`/api/camera/preview/vision`, per Proxy)
- Status-Banner: zeigt Rolle und „Vision-Knoten nicht verbunden“, solange kein
  Peer erreichbar ist; Tank/Testmodus kommen vom Vision-Knoten dazu

Ohne konfigurierten Peer bleiben die Vision-Seiten leer bzw. melden
„Vision-Knoten nicht erreichbar“ (HTTP 502) – die Fahrfunktion ist davon
unabhängig.

## Verhalten je Rolle im Core-Prozess

- `drive`: startet nur `DriveController` + leichten Vorschau-Loop
  (schreibt `preview.jpg`, keine Detection, kein Spray, keine Tank-Sensorik).
  Schnelle Befehlsabtastung (~50 Hz) für geringe Fahr-Latenz.
- `vision`: startet Vision-Pipeline + Spray + Anlernfahrt; kein Drive.
- `all`: bisheriges Verhalten (alles in einem Prozess).

Ein Rollenwechsel erfordert einen Neustart von `maehbot-core`.

## Deployment auf älteren Pis (z. B. Pi 1 B+, armv6)

Docker scheidet auf armv6 aus – nativ per systemd + venv installieren:

```bash
sudo apt install -y python3-venv python3-picamera2 git
git clone https://github.com/tgernhar/00400-Maehbot ~/pi/maehbot
cd ~/pi/maehbot
python3 -m venv --system-site-packages .venv   # picamera2 aus apt nutzen
.venv/bin/pip install -e ".[web]" lgpio
# config/local.yaml anlegen (siehe oben, Rolle drive)
sudo cp deploy/maehbot-core.service deploy/maehbot-web.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now maehbot-core maehbot-web
```

Hinweise für den Pi 1 B+:

- Python **3.11** (Bookworm) reicht; das Projekt unterstützt >= 3.11.
- Frontend **nicht** auf dem B+ bauen – auf dem PC `npm run build` ausführen
  und `web/frontend/dist` mitkopieren (oder einchecken).
- Kameraauflösung klein halten (320×240, 2–5 fps), sonst ist der
  Single-Core überlastet.
- Die TB6612FNG-Pinbelegung (BCM 5, 6, 12, 13, 16, 25, 26) ist auf allen
  Pis mit 40-Pin-Header identisch → Verdrahtung unverändert übernehmen
  (siehe `docs/hardware-drive.md`).

## Später: Pi 5 als Vision-Knoten anbinden

1. Pi 5 wie gehabt aufsetzen (Docker oder systemd), `node.role: vision`.
2. Auf dem Fahr-Knoten in `config/local.yaml` eintragen:
   `node.peers.vision_url: http://<pi5-adresse>:8080`
3. `maehbot-web` auf dem Fahr-Knoten neu starten – Review/Training/Spray
   erscheinen automatisch in der gemeinsamen Oberfläche.

## Knoten austauschen (z. B. B+ → neuer Pi)

1. Neuen Pi aufsetzen (Repo, venv, Dienste wie oben).
2. `config/local.yaml` vom alten Knoten übernehmen (Rolle, Pins, Kamera).
3. Verdrahtung 1:1 umstecken (40-Pin-Header identisch).
4. Alte IP/Hostname übernehmen oder `vision_url`/Browser-Adresse anpassen.
