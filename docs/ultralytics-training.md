# Ultralytics YOLO — Schritt-für-Schritt-Anleitung (Maehbot)

Diese Anleitung beschreibt, wie du aus den in Maehbot exportierten Trainingsdaten ein YOLO-Modell mit [Ultralytics](https://docs.ultralytics.com/) trainierst. Das Training läuft **auf einem PC** (Windows oder Linux), nicht auf dem Raspberry Pi.

Anschließend siehe [model-deployment.md](model-deployment.md) für das Deployen auf die IMX500-Kamera.

---

## Überblick

```
Maehbot (Pi)                    PC (Ultralytics)                 Pi (später)
─────────────                   ────────────────                 ────────────
Fotos/Video                     Dataset kopieren
  → Annotationen                  → train/val aufteilen
  → YOLO exportieren              → dataset.yaml
                                  → yolo train
                                  → best.pt
                                                                    → IMX500 deploy
```

---

## Schritt 1 — Voraussetzungen

| Was | Empfehlung |
|-----|------------|
| Maehbot | Core + Web laufen, mindestens eine annotierte Session |
| PC | Python 3.10–3.12, optional NVIDIA-GPU |
| Speicher | Pro Session wenige MB bis GB (Video) |
| Internet | Für `pip install ultralytics` und Download des Basis-Modells |

Auf dem PC (virtuelle Umgebung empfohlen):

```bash
python -m venv .venv

# Windows (PowerShell)
.\.venv\Scripts\Activate.ps1

# Linux / macOS
source .venv/bin/activate

pip install --upgrade pip ultralytics
```

Prüfen:

```bash
yolo version
```

### PEP 668 — „externally-managed-environment“ (Pi / Debian)

Raspberry Pi OS und neuere Debian-Installationen erlauben **kein** `pip install` ins System-Python. Die Meldung ist normal — **kein** `--break-system-packages` verwenden.

Stattdessen virtuelle Umgebung anlegen:

```bash
# Einmalig (falls venv fehlt)
sudo apt update
sudo apt install -y python3-venv python3-full

# Venv für YOLO-Training (z. B. im Home-Verzeichnis)
python3 -m venv ~/yolo-venv
source ~/yolo-venv/bin/activate

pip install --upgrade pip
pip install ultralytics

yolo version
```

Bei jedem neuen Terminal vor dem Training:

```bash
source ~/yolo-venv/bin/activate
```

**Hinweis:** Training auf dem **Pi 5** ist möglich, aber ohne NVIDIA-GPU **sehr langsam**. Besser: Dataset per `scp` auf einen Windows/Linux-PC mit GPU kopieren und dort trainieren (siehe Schritt 3). Auf dem Pi reicht die venv, wenn du nur kurz testen willst.

---

## Schritt 2 — Daten in Maehbot vorbereiten

1. Browser: `http://<pi-ip>:8080/training`
2. Fotos aufnehmen (Livebild + 📷) oder Anlernfahrt/Upload
3. Session auswählen, Unkraut mit Rechteck markieren, Klasse wählen
4. Oben prüfen: **≥ 1 Annotation(en)** und farbige Rechtecke sichtbar
5. **YOLO exportieren** klicken — Meldung mit Pfad notieren, z. B.  
   `/var/lib/maehbot/exports/yolo/session_3/`

Mehrere Sessions: je Session einmal exportieren; Ordner später zusammenführen (Schritt 4).

### Export-Layout (vom Maehbot erzeugt)

```
session_3/
  classes.txt
  images/train/     ← JPG-Dateien
  labels/train/     ← passende .txt-Labels (YOLO-Format)
```

`classes.txt` entspricht der Reihenfolge in `config/defaults.yaml`:

| Index | Klassen-ID |
|-------|------------|
| 0 | grass |
| 1 | clover |
| 2 | dandelion |
| 3 | unknown_weed |

**Wichtig:** Diese Reihenfolge darf in `dataset.yaml` nicht vertauscht werden.

### Kurzanleitung: Export in der UI (Pi)

1. Im Browser öffnen: `http://10.233.159.212:8080/training` (IP ggf. anpassen)
2. Links in der Liste die **Session** anklicken (Foto oder Anlernfahrt)
3. Prüfen: **„N Annotation(en)“** ≥ 1, Markierungen auf dem Bild sichtbar
4. Button **„YOLO exportieren“** klicken
5. Grüne Meldung ablesen, z. B.:  
   `Export OK: 3 Bild(er), 5 Annotation(en). Gespeichert unter /var/lib/maehbot/exports/yolo/session_3`
6. **Session-Nummer merken** (`session_3` → ID ist **3**)

Optional per SSH auf dem Pi prüfen:

```bash
ls -la /var/lib/maehbot/exports/yolo/
ls /var/lib/maehbot/exports/yolo/session_3/images/train/
ls /var/lib/maehbot/exports/yolo/session_3/labels/train/
cat /var/lib/maehbot/exports/yolo/session_3/classes.txt
```

Falls der Ordner fehlt: in der UI erneut exportieren oder Meldung/Fehlertext beachten (z. B. „Keine Annotationen“).

---

## Schritt 3 — Dataset vom Pi auf den PC kopieren

### Voraussetzung Windows

- Pi und PC im **selben Netzwerk**
- **OpenSSH Client** unter Windows (Einstellungen → Apps → Optionale Features → „OpenSSH-Client“)
- Login wie beim SSH: Benutzer `tgernhar`, Passwort oder SSH-Key

### Kopieren mit scp (PowerShell auf dem Windows-PC)

**Nicht** auf dem Pi ausführen — in **PowerShell auf Windows** (z. B. `Win + X` → Terminal):

```powershell
# 1) Zielordner anlegen
mkdir C:\Thomas\maehbot-dataset -Force

# 2) Session-ID einsetzen (aus Export-Meldung oder ls auf dem Pi)
$SESSION = 3
$PI = "tgernhar@10.233.159.212"

# 3) Gesamten Export-Ordner kopieren
scp -r "${PI}:/var/lib/maehbot/exports/yolo/session_${SESSION}" C:\Thomas\maehbot-dataset\
```

Beim ersten Mal: Fingerprint mit `yes` bestätigen, dann Pi-Passwort eingeben.

**Alle Sessions auf einmal:**

```powershell
scp -r tgernhar@10.233.159.212:/var/lib/maehbot/exports/yolo C:\Thomas\maehbot-dataset\
```

### Alternative: WinSCP (grafisch)

1. [WinSCP](https://winscp.net/) installieren
2. Verbindung: SFTP, Host `10.233.159.212`, Benutzer `tgernhar`
3. Rechts navigieren zu `/var/lib/maehbot/exports/yolo/session_3`
4. Ordner nach links ziehen nach `C:\Thomas\maehbot-dataset\`

### Kontrolle auf dem PC

```powershell
dir C:\Thomas\maehbot-dataset\session_3\images\train
dir C:\Thomas\maehbot-dataset\session_3\labels\train
type C:\Thomas\maehbot-dataset\session_3\classes.txt
```

Jede `.jpg` in `images/train/` sollte eine gleichnamige `.txt` in `labels/train/` haben (z. B. `frame_0.jpg` ↔ `frame_0.txt`).

Danach auf dem PC mit Ultralytics weiter (Schritt 4: train/val aufteilen, `dataset.yaml`, `yolo train`).

Linux/macOS:

```bash
scp -r tgernhar@10.233.159.212:/var/lib/maehbot/exports/yolo/session_3 ~/maehbot-dataset/
```

---

## Schritt 4 — Train/Val-Aufteilung anlegen

Ultralytics erwartet typischerweise **train** und **val**. Maehbot exportiert nur `train/` — du teilst die Daten selbst auf (ca. 80 % train, 20 % val).

### Zielstruktur

```
maehbot-yolo/
  dataset.yaml
  images/
    train/    ← 80 % der Bilder
    val/      ← 20 % der Bilder
  labels/
    train/    ← Labels zu train-Bildern
    val/      ← Labels zu val-Bildern
```

### Aufteilung mit Python (empfohlen)

Im Ordner `maehbot-dataset` eine Datei `split_dataset.py` anlegen und ausführen:

```python
"""Split Maehbot YOLO export into train/val for Ultralytics."""
import random
import shutil
from pathlib import Path

SOURCE = Path(r"C:\Thomas\maehbot-dataset\session_3")  # anpassen
DEST = Path(r"C:\Thomas\maehbot-dataset\maehbot-yolo")
VAL_RATIO = 0.2
SEED = 42

random.seed(SEED)
images_src = SOURCE / "images" / "train"
labels_src = SOURCE / "labels" / "train"
pairs = [
    (p, labels_src / f"{p.stem}.txt")
    for p in images_src.glob("*.jpg")
    if (labels_src / f"{p.stem}.txt").is_file()
]
random.shuffle(pairs)
n_val = max(1, int(len(pairs) * VAL_RATIO))
val_pairs = pairs[:n_val]
train_pairs = pairs[n_val:]

for split, subset in ("train", train_pairs), ("val", val_pairs):
    img_dir = DEST / "images" / split
    lbl_dir = DEST / "labels" / split
    img_dir.mkdir(parents=True, exist_ok=True)
    lbl_dir.mkdir(parents=True, exist_ok=True)
    for img, lbl in subset:
        shutil.copy2(img, img_dir / img.name)
        shutil.copy2(lbl, lbl_dir / lbl.name)

print(f"train: {len(train_pairs)}, val: {len(val_pairs)}")
```

```bash
python split_dataset.py
```

Bei **sehr wenigen Bildern** (< 10): alle in `train/` lassen und dieselben Bilder auch nach `val/` kopieren (nur zum Starten — Ergebnis ist dann optimistisch).

### Mehrere Sessions zusammenführen

Exports `session_1`, `session_2`, … nach `images/train` und `labels/train` kopieren (Dateinamen müssen eindeutig sein, z. B. `s1_frame_0.jpg`). Danach einmal `split_dataset.py` mit einem gemeinsamen Quellordner ausführen.

---

## Schritt 5 — `dataset.yaml` erstellen

Datei `C:\Thomas\maehbot-dataset\maehbot-yolo\dataset.yaml`:

```yaml
# Pfad zum Dataset-Root (absolut oder relativ zum Aufrufort)
path: C:/Thomas/maehbot-dataset/maehbot-yolo

train: images/train
val: images/val

# Reihenfolge = Index in Label-Dateien (wie Maehbot classes.txt)
names:
  0: grass
  1: clover
  2: dandelion
  3: unknown_weed
```

Unter Linux Pfade mit `/` statt `\` verwenden.

---

## Schritt 6 — Training starten

Im Terminal (venv aktiv), zum Dataset-Ordner wechseln oder absoluten Pfad nutzen:

```bash
cd C:\Thomas\maehbot-dataset\maehbot-yolo

# Kleines Modell, gut für wenig Daten und spätere Konvertierung
yolo detect train data=dataset.yaml model=yolov8n.pt epochs=100 imgsz=640 batch=8

# Mit GPU (falls CUDA installiert)
yolo detect train data=dataset.yaml model=yolov8n.pt epochs=100 imgsz=640 device=0
```

### Parameter kurz erklärt

| Parameter | Bedeutung |
|-----------|-----------|
| `model=yolov8n.pt` | Kleinstes YOLOv8 — Startpunkt; bei mehr Daten `yolov8s.pt` |
| `epochs=100` | Durchläufe; bei wenig Daten ggf. 50–200 testen |
| `imgsz=640` | Eingabegröße; an Kameraauflösung anpassen |
| `batch=8` | Bei GPU-Speicherfehler auf `4` oder `2` reduzieren |
| `patience=20` | Early stopping (Standard) |

Training-Log und Metriken erscheinen in der Konsole; Ausgabe unter `runs/detect/train/` (Nummer erhöht sich bei jedem Lauf).

---

## Schritt 7 — Ergebnis prüfen

### Gewichtsdatei

Bestes Modell:

```
runs/detect/train/weights/best.pt
```

Letzter Lauf ggf. `runs/detect/train2/`, `train3/`, …

### Validierung

```bash
yolo detect val model=runs/detect/train/weights/best.pt data=dataset.yaml
```

Metriken: `mAP50`, Precision, Recall — bei wenigen Bildern nur grobe Orientierung.

### Test auf Einzelbildern

```bash
yolo detect predict model=runs/detect/train/weights/best.pt source=images/val imgsz=640 save=True
```

Ergebnisse: `runs/detect/predict/` mit eingezeichneten Boxen.

---

## Schritt 8 — Typische Probleme

| Problem | Lösung |
|---------|--------|
| „Keine Annotationen“ beim Export | In Maehbot erst markieren, dann exportieren |
| Leeres `labels/train/` | Klassen in UI müssen in `defaults.yaml` existieren |
| CUDA out of memory | `batch=2`, kleineres `model=yolov8n.pt` |
| Sehr schlechte mAP | Mehr Bilder, verschiedene Licht/Wetter, mehr Klassen-Beispiele |
| Nur 1–2 Bilder | Minimum für sinnvolles Training: eher 50+ pro Klasse anstreben |

---

## Schritt 9 — Nächster Schritt: Modell auf dem Mäher nutzen

1. `best.pt` ist **noch nicht** direkt auf dem IMX500 lauffähig.
2. Konvertierung + Deploy über Sony/Raspberry-Pi IMX500-Toolchain → [model-deployment.md](model-deployment.md)
3. Danach Core neu starten: `sudo systemctl restart maehbot-core`
4. Erkennung testen: Web **Review** (`/`), Testmodus in Einstellungen **an**

Bis das IMX500-Modell deployed ist, nutzt der Core weiterhin den Mock-Detektor in `vision/detector.py`.

---

## Kurz-Checkliste

- [ ] Maehbot: Session annotiert, YOLO exportiert
- [ ] Dataset per `scp` auf PC
- [ ] `images/val` + `labels/val` angelegt
- [ ] `dataset.yaml` mit korrekter Klassen-Reihenfolge
- [ ] `pip install ultralytics`, `yolo detect train …`
- [ ] `best.pt` mit `predict`/`val` geprüft
- [ ] IMX500-Deploy laut model-deployment.md

---

## Referenzen

- [Ultralytics Train docs](https://docs.ultralytics.com/modes/train/)
- [YOLO dataset format](https://docs.ultralytics.com/datasets/detect/)
- Maehbot: [model-deployment.md](model-deployment.md), [deploy.md](deploy.md)
