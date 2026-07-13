# Karte & Navigation (LiDAR-SLAM)

Der Fahr-Knoten erstellt aus den LiDAR-Scans eine Umgebungskarte (SLAM mit
[BreezySLAM](https://github.com/simondlevy/BreezySLAM), tinySLAM/CoreSLAM) und
bestimmt darauf laufend die eigene Position. Die Web-UI zeigt die Karte auf der
Seite **„Karte"**:

- **Ziel wählen:** Klick auf die Karte → der Roboter plant einen Weg (A* auf dem
  Belegungsgitter) und fährt hin.
- **Zone zeichnen:** Rechteck aufziehen, Name und **Bearbeitungsrichtung** (Winkel
  in Grad) festlegen. „Zone mähen" fährt die Zone in parallelen Bahnen ab
  (Boustrophedon), Bahnabstand über die Navigationsparameter einstellbar.
- **Karte speichern / zurücksetzen:** Die gespeicherte Karte wird beim nächsten
  Start des Core-Prozesses wieder geladen.

## Installation von BreezySLAM (auf dem Fahr-Knoten)

BreezySLAM ist nicht auf PyPI und enthält eine C-Extension. Einmalig auf dem Pi:

```bash
sudo apt install -y build-essential python3-dev
cd ~
git clone https://github.com/simondlevy/BreezySLAM
source ~/pi/maehbot/.venv/bin/activate   # das Maehbot-venv aktivieren
pip install ./BreezySLAM/python
sudo systemctl restart maehbot-core
```

Ohne BreezySLAM startet der Core normal, aber die Kartierung ist deaktiviert —
die Karten-Seite zeigt dann einen entsprechenden Hinweis.

## Architektur

```
LidarReader (360°-Scan) ──► SlamMapper-Thread (BreezySLAM, ~5 Hz)
Core-Loop (Track-Speeds) ──► Odometrie (Zeit-Kalibrierung) ──┘
                              │
                              ├─► Pose (x, y, θ) + Belegungsgitter
                              ├─► map.png + map_meta.json (Web-UI)
                              ▼
Navigator (goto / mow_zone) ──► A*-Planner ──► Wegpunkte
        │ tick() ~50 Hz: drehen → fahren mit Kurskorrektur
        ▼
DriveController.set_speeds()
```

- **Odometrie:** Ohne Drehgeber wird die Bewegung aus den kommandierten
  Kettengeschwindigkeiten und den Kalibrierwerten `speed_m_s` / `pivot_deg_s`
  (Sektion `coverage`) geschätzt und als Startwert an das Scan-Matching
  übergeben. Später können Encoder oder RTK-GPS dieselbe Schnittstelle
  (`SlamMapper.report_motion`) mit besseren Werten füttern.
- **IPC:** wie bei der Bereichsfahrt über JSON-Dateien im Storage-Root:
  `nav_command.json` (Web → Core), `nav_status.json` (Core → Web),
  `zones.json` (Zonen), `map.png` / `map_meta.json` (Karte),
  `map_saved.png` (persistierte Karte).

## Konfiguration (`config/defaults.yaml`)

| Sektion | Schlüssel | Bedeutung |
|---|---|---|
| `mapping` | `map_size_pixels` / `map_size_meters` | Auflösung und Kantenlänge der Karte; Roboter startet in der Mitte |
| `mapping` | `map_quality`, `hole_width_mm` | tinySLAM-Parameter (Integrationsgeschwindigkeit, Wandbreite) |
| `mapping` | `update_rate_hz` | SLAM-Updaterate (eigener Thread) |
| `mapping` | `localize_only` | `true` = gespeicherte Karte fixieren, nur Position bestimmen |
| `navigation` | `waypoint_tolerance_m`, `heading_tolerance_deg` | Regel-Toleranzen des Wegpunktfolgers |
| `navigation` | `robot_radius_m` | Hindernis-Aufblähung für die Pfadplanung |
| `navigation` | `line_spacing_m` | Bahnabstand beim Zonen-Mähen |
| `navigation` | `obstacle_stop_m`, `max_replans` | Hindernis-Stopp und maximale Neuplanungen |

## Grenzen / Erwartungen

Ohne Rad-Encoder hängt die Kartenqualität am LiDAR-Scan-Matching. In
strukturierter Umgebung (Wände, Hecken, Möbel in ≤ 12 m Reichweite)
funktioniert tinySLAM gut; auf offenem Rasen ohne Strukturen kann die
Position driften. Die Kalibrierwerte `speed_m_s` / `pivot_deg_s` sollten
möglichst genau vermessen sein, da sie das Scan-Matching stützen.
