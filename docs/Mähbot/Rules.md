## Was ich aus deiner Beschreibung ableite

|Bereich|Kernaufgabe|
|---|---|
|Vision|IMX500 erkennt beim Fahren Unkraut vs. Gras auf dem Rasen|
|Aktorik|Micro-Dosierdüse, zeitversetzt (Verzögerung + Dauer in ms)|
|Training|Anlernfahrt: Pflanzen manuell aus Video markieren|
|Review|WLAN-Web-UI: letzte 100 Erkennungen prüfen|
|Bedienung|Alles im Browser|

Das sind mindestens 4 getrennte Domänen — dafür empfehle ich mehrere kleine Rules (je unter ~50 Zeilen), nicht eine große.

---

## Was du mir liefern solltest (Checkliste)

### 1. Technologie-Entscheidungen (wichtigste Lücke)

| Thema              | Optionen / Frage                                    | Antwort                                                                                                                                         |
| ------------------ | --------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| Programmiersprache | Python auf dem Pi? (sehr wahrscheinlich mit IMX500) | Python auf dem Pi                                                                                                                               |
| Web-Backend        | FastAPI, Flask, oder alles in einem Python-Prozess? | Wähle Du, es muss schnell sein damit die Reaktionszeit der Kamera zur Düse funktioniert                                                         |
| Frontend           | React, Vue, oder schlichtes HTML/JS?                | React                                                                                                                                           |
| Datenbank          | SQLite lokal? Nur Dateisystem?                      | Wähle Du, es muss schnell sein damit die Reaktionszeit der Kamera zur Düse funktioniert                                                         |
| Deployment         | systemd-Services, Docker, oder manuell?             | Ich würde docker bevorzugen wenn das auf dem Pi geht, aber nur wenn das keine Probleme mit der Reaktionszeit bei der Kamera zu der Düse bringt. |

Ohne diese Punkte rät der Agent bei jedem Schritt neu.

---

### 2. Hardware & Physik (kritisch für korrekten Code)

- Wie wird die Düse angesteuert? GPIO, PWM, Relais, UART, I²C?                         Antwort:  GPIO
- Abstand Kamera ↔ Düse und Montagewinkel (für Verzögerungsberechnung)  Antwort:  20mm (anpassbar gestalten)
- Typische Fahrgeschwindigkeit des Mähers (m/s oder km/h)                               Antwort:  0,1m/s (anpassbar gestalten)
- Auflösung / FPS der Kamera beim Fahren                                                           Antwort: 30fps (anpassbar gestalten)
- Tank / Pumpe: aktiv gepumpt oder nur Schwerkraft-Dosierung?                      Antwort: aktiv gepumpt
- Stromversorgung: Pi + Düse vom Mäher-Akku?                                             Antwort eigener Akku

→ Das gehört in eine Rule wie `hardware-gpio.mdc` mit festen Konstanten und Timing-Formeln.

---

### 3. IMX500 / KI-Pipeline

- Erkennungsmodell: Sony-Firmware-Modell, eigenes ONNX/TFLite, oder beides? Antwort: Beides
- Klassen: nur „Gras / Unkraut“ oder mehr (z. B. Klee, Löwenzahn, Moos)?               Antwort: Klee, Grass usw.
- Inferenz: on-device auf IMX500 oder zusätzlich auf dem Pi-CPU?              Antwort: Geplant auf dem IMX500, falls erforderlich auf PI-CPU.
- Confidence-Schwelle und gewünschtes Verhalten bei Unsicherheit (nicht sprühen vs. trotzdem sprühen) Antwort die Schwelle initial setzen, weiteres folgt nach den Tests

→ Rule: `vision-imx500.mdc`

---

### 4. Echtzeit & Sicherheit

- Max. tolerierte Latenz Kamera → Auslösung (ms)   Antwort: 10ms
- Fail-safe: Was passiert bei Kamera-Ausfall, WLAN weg, leerem Tank?  Antwort: Der Tank bekommt 2 Füllstandssensoren 1x Stand Tank Voll, 1x Stand Tank Leer als Digitales signal für GPIO
- Sicherheitsregel: z. B. „nie sprühen ohne gültige Bounding Box + Mindest-Confidence“ Antwort: Ja nie sprühen ohne ültige Bounding Box + Mindest-Confidence“
- Rechtliches / Pflanzenschutz: nur zur Info — ob du das in Rules als „nur markieren, nicht automatisch sprühen im Testmodus“ willst Antwort: Im Testmodus nur Markieren, nicht sprühen

→ Rule: `safety-realtime.mdc` (alwaysApply oder für `**/spray*.py`, `**/trigger*.py`)

---

### 5. Web-UI & API

- Nur lokales WLAN oder auch von außen erreichbar? Antwort: Nur Lokales WLAN verwenden
- Login / Auth nötig? Antwort:  Ja bitte implementieren, Am Anfang aber überspringen zum Testen
- API-Stil: REST, WebSocket für Live-Bild? Antwort:REST verwenden
- Review-UI: nur Thumbnail + Label oder auch Bounding Box im Bild? Antwort: Auch Bounding Box im Bild 
- Anlern-UI: Video-Frames scrubben, Rechteck zeichnen, Klasse zuweisen — reicht das? Antwort zu beginn ja

→ Rules: `api-conventions.mdc`, `frontend-ui.mdc`

---

### 6. Daten & Speicher

- Wo liegen Bilder/Videos? (`/var/lib/maehbot/…`?)  Antwort: Ja hier ablegen
- Retention: nur 100 Erkennungen oder auch ältere archivieren? Antwort maximal 1000 Bilder archivieren
- Trainingsdaten-Format: COCO, YOLO, eigenes JSON?  Antwort wähle Du das passendste dazu 
- SD-Karten-Größe und Speicherlimit   Antwort: Speicherlimit  10 GB

→ Rule: `data-storage.mdc`

---

### 7. Projektstruktur & Konventionen

- Ordnerstruktur (Vorschlag zum Diskutieren):

maehbot/

vision/ # Kamera, IMX500, Detection

spray/ # Düse, Timing, GPIO

training/ # Anlernfahrt, Annotation

web/ # API + Frontend

config/ # YAML/JSON Einstellungen

tests/

- Sprache in Code/Kommentaren: Deutsch oder Englisch? Antwort Englisch Kommentieren
- Kommunikation mit Agent: Deutsch (wie in deinen User Rules)

→ Rule: `project-overview.mdc` mit `alwaysApply: true`

---

### 8. Entwicklungs-Workflow

- Entwickelst du am PC und deployest auf den Pi, oder direkt auf dem Pi? Antwort: ich entwickle auf dem PC und deploye auf dem Pi
- Python-Version auf dem Pi (3.11 / 3.12)? Antwort: muss ich prüfen, ich habe diese aktuell installiert, daher voraussichtlich 3.12
- Git / Commits: nur du, oder später Team? Antwort: Git Commits nur ich 
- Tests: Unit-Tests auf PC, Integration nur auf Hardware? Antwort Unit Tests auf PC und auf dem Pi

→ Rule: `dev-workflow.mdc`


PS C:\Thomas\Cursor\00400 Maehbot> ssh tgernhar@10.233.159.212
The authenticity of host '10.233.159.212 (10.233.159.212)' can't be established.
ED25519 key fingerprint is SHA256:CSpPEPVfZRv0JCiFgFNNCGNoB+hBsphFEbNN1BhpmuY.
This key is not known by any other names.