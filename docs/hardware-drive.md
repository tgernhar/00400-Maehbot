# Fahrwerk: Makeblock Ranger Tank-Chassis mit TB6612FNG

Ansteuerung der beiden Ketten (links/rechts) des Tank-Chassis über einen
Raspberry Pi 5 und den Doppel-Motortreiber TB6612FNG.

## Komponenten

| Komponente | Funktion |
|---|---|
| Raspberry Pi 5 | Logik, Web-UI, GPIO-Steuerung |
| TB6612FNG | Doppel-H-Brücke, treibt beide DC-Getriebemotoren |
| 5-V-Step-Down-Wandler (≥ 5 A) | Versorgt den Pi 5 stabil (Pi 5 zieht Lastspitzen) |
| Fahrakku | Versorgt die Motoren (VM des TB6612FNG) |

Die beiden Motoren des Ranger-Chassis = **Kette links** (Kanal A) und
**Kette rechts** (Kanal B).

## Stromversorgung (wichtig)

- **Getrennte Pfade:** Der Step-Down (5 V / ≥ 5 A) versorgt **nur den Pi 5**.
  Die Motoren laufen über `VM` direkt aus dem Fahrakku (nicht über den Pi-5-V-Rail).
- **Gemeinsame Masse:** GND von Pi, TB6612FNG und Akku müssen verbunden sein.
- `VM` = Motorspannung (Fahrakku, je nach Ranger-Motoren typ. 6–12 V).
- `VCC` = Logikspannung des TB6612FNG → an **3V3** des Pi (Logikpegel passend zu den 3,3-V-GPIOs).

## Pin-Belegung

GPIO-Nummern sind **BCM** (konfigurierbar in `config/hardware.yaml` → `motor:`).
Die physischen Pin-Nummern beziehen sich auf die 40-polige Pi-Stiftleiste.

| TB6612FNG | Funktion | Pi BCM (GPIO) | Pi physisch |
|---|---|---|---|
| STBY | Standby (HIGH = aktiv) | 25 | 22 |
| AIN1 | Richtung links | 5 | 29 |
| AIN2 | Richtung links | 6 | 31 |
| PWMA | Tempo links (PWM) | 12 | 32 |
| BIN1 | Richtung rechts | 16 | 36 |
| BIN2 | Richtung rechts | 26 | 37 |
| PWMB | Tempo rechts (PWM) | 13 | 33 |
| VCC | Logik 3,3 V | 3V3 | 1 oder 17 |
| GND | Masse (gemeinsam) | GND | z. B. 6, 9, 14, 20, 25, 30, 34, 39 |
| VM | Motorakku + | – (Fahrakku) | – |
| AO1/AO2 | Motor Kette links | – | – |
| BO1/BO2 | Motor Kette rechts | – | – |

Die Spray-Pins (Düse 17, Pumpe 27, Tank 22/23) und Servo-Signale (18, 19, 20)
bleiben frei von Motor- und Encoder-Belegungen.

## Rad-Encoder (Quadratur, links + rechts)

Jeder Encoder am Rad hat **fünf Adern** (typische Farbcodierung):

| Ader | Bezeichnung | Funktion |
|---|---|---|
| Rot | Vcc | Versorgung Plus |
| Schwarz | 0V | Signal-Masse |
| Weiß | A+ | Quadratur-Kanal A |
| Grün | B+ | Quadratur-Kanal B |
| Schirm | Shield GND | Kabelschirm → Masse |

**Gemeinsame Versorgung:** Rot aller Encoder an **5 V** (Pin 2 oder 4) oder **3V3**
(Pin 1 oder 17), je nach Encoder-Datenblatt. Schwarz und Schirm an **GND**
(gemeinsam mit TB6612FNG und Akku-Minus).

**GPIO-Pegel:** Pi-Eingänge vertragen max. **3,3 V**. Liefert der Encoder 5-V-Signale
auf A+/B+, Pegelwandler oder 3,3-V-kompatible Encoder verwenden.

### Encoder links (Kette links)

| Ader | Pi BCM (GPIO) | Pi physisch |
|---|---|---|
| Weiß (A+) | 21 | 40 |
| Grün (B+) | 24 | 18 |
| Rot (Vcc) | 5 V oder 3V3 | 2/4 oder 1/17 |
| Schwarz (0V) | GND | z. B. 6, 9, 14, 20, 25, 30, 34, 39 |
| Schirm (GND) | GND | am Pi-Ende mit Masse verbinden |

### Encoder rechts (Kette rechts)

| Ader | Pi BCM (GPIO) | Pi physisch |
|---|---|---|
| Weiß (A+) | 14 | 8 |
| Grün (B+) | 15 | 10 |
| Rot (Vcc) | 5 V oder 3V3 | 2/4 oder 1/17 (gemeinsamer Rail) |
| Schwarz (0V) | GND | wie links |
| Schirm (GND) | GND | wie links |

GPIO 14/15 sind UART-Pins; sie bleiben frei, solange LiDAR per USB (`/dev/ttyUSB0`)
läuft und kein UART-LiDAR an Pin 8/10 hängt.

### Software (Bereichsfahrt mit Encodern)

Bei aktivierten und kalibrierten Encodern misst die Bereichsfahrt die
tatsächlich gefahrene Strecke statt per Zeit zu schätzen
(`EncoderMotionExecutor` in `navigation/motion.py`):

- **Gerade Strecken** enden bei der gemessenen Distanz (Mittel beider Ketten);
  eine leichte Korrektur bremst die schnellere Kette, damit der Roboter
  geradeaus fährt.
- **Drehungen** enden bei der gemessenen Bogenlänge:
  `track_width_mm / 2 × Winkel` pro Kette.
- **Sicherheits-Timeout:** Dauert ein Segment 3× länger als kalibriert
  (Rad blockiert, keine Impulse), wird es abgebrochen.

Aktivierung in `config/local.yaml`:

```yaml
encoder:
  enabled: true
  pulses_per_rev: 44        # Quadratur-Zählungen pro Radumdrehung (PPR × 4)
  wheel_diameter_mm: 65     # gemessener Rad-/Antriebsrad-Durchmesser
  track_width_mm: 200       # Abstand der Kettenmittelpunkte
```

Ohne Encoder (oder unkalibriert) fällt die Software automatisch auf die
zeitbasierte Steuerung (`TimedMotionExecutor`) zurück; das Core-Log zeigt beim
Start, welcher Modus aktiv ist.

### Übersicht aller Fahr-Pins (BCM)

| Funktion | BCM | Physisch |
|---|---|---|
| Motor links Richtung | 5, 6 | 29, 31 |
| Motor links PWM | 12 | 32 |
| Motor rechts Richtung | 16, 26 | 36, 37 |
| Motor rechts PWM | 13 | 33 |
| Motor STBY | 25 | 22 |
| **Encoder links A/B** | **21, 24** | **40, 18** |
| **Encoder rechts A/B** | **14, 15** | **8, 10** |

Pins in `config/hardware.yaml` → `encoder:` und `motor:`. Für die Bereichsfahrt
`encoder.enabled: true` setzen und kalibrieren (siehe Software-Abschnitt unten).

```text
                    Raspberry Pi 5 (Fahr-Pi)
                    ────────────────────────
Encoder LINKS                    Encoder RECHTS
  Weiß  A+  ──► GPIO21 (Pin 40)    Weiß  A+  ──► GPIO14 (Pin 8)
  Grün  B+  ──► GPIO24 (Pin 18)    Grün  B+  ──► GPIO15 (Pin 10)
  Rot   Vcc ──┬─► 5V Pin 2/4       Rot   Vcc ──┘   (gemeinsam)
  Schwarz 0V ─┴─► GND Pin 6        Schwarz 0V ───► GND Pin 6
  Shield GND ───► GND              Shield GND ───► GND
```

## Wiring-Diagramm

```mermaid
flowchart LR
    subgraph BAT["Fahrakku (z. B. 6-12 V)"]
        BATP["+"]
        BATM["- (GND)"]
    end

    subgraph SD["Step-Down 5 V / >=5 A"]
        SDIN["IN +"]
        SDING["IN -"]
        SDOUT["OUT 5 V"]
        SDOUTG["OUT GND"]
    end

    subgraph PI["Raspberry Pi 5 (BCM-GPIO)"]
        PI5V["5V (Pin 2/4 oder USB-C)"]
        PIGND["GND (Pin 6/9/...)"]
        PI3V3["3V3 (Pin 1)"]
        G25["GPIO25 (Pin22)"]
        G5["GPIO5 (Pin29)"]
        G6["GPIO6 (Pin31)"]
        G12["GPIO12 (Pin32)"]
        G16["GPIO16 (Pin36)"]
        G26["GPIO26 (Pin37)"]
        G13["GPIO13 (Pin33)"]
    end

    subgraph TB["TB6612FNG"]
        VM["VM (Motor +)"]
        VCC["VCC (Logik 3V3)"]
        TGND["GND"]
        STBY["STBY"]
        AIN1["AIN1"]
        AIN2["AIN2"]
        PWMA["PWMA"]
        BIN1["BIN1"]
        BIN2["BIN2"]
        PWMB["PWMB"]
        AO1["AO1"]
        AO2["AO2"]
        BO1["BO1"]
        BO2["BO2"]
    end

    ML["Motor Kette LINKS"]
    MR["Motor Kette RECHTS"]

    %% Strom
    BATP -->|"+"| SDIN
    BATM -->|"GND"| SDING
    BATP -->|"Motorspannung"| VM
    SDOUT -->|"5 V"| PI5V
    SDOUTG -->|"GND"| PIGND

    %% Gemeinsame Masse
    BATM -.->|"common GND"| TGND
    PIGND -.->|"common GND"| TGND

    %% Logik
    PI3V3 -->|"3V3"| VCC
    G25 -->|"Standby"| STBY
    G5 -->|"Richtung L"| AIN1
    G6 -->|"Richtung L"| AIN2
    G12 -->|"PWM L"| PWMA
    G16 -->|"Richtung R"| BIN1
    G26 -->|"Richtung R"| BIN2
    G13 -->|"PWM R"| PWMB

    %% Motoren
    AO1 --> ML
    AO2 --> ML
    BO1 --> MR
    BO2 --> MR
```

> Durchgezogene Linien = Verdrahtung, gestrichelte Linien = gemeinsame Masse
> (Pi GND, Treiber GND und Akku-Minus müssen verbunden sein).

## Logik (TB6612FNG-Wahrheitstabelle pro Kanal)

| IN1 | IN2 | PWM | Verhalten |
|---|---|---|---|
| 1 | 0 | Tempo | vorwärts |
| 0 | 1 | Tempo | rückwärts |
| 0 | 0 | – | Leerlauf/Stopp |
| 1 | 1 | – | Bremse |

Geschwindigkeit = PWM-Tastgrad (0–100 %), Standard-PWM-Frequenz 1 kHz
(`motor.pwm_frequency_hz`).

## Software-Architektur

Gemäß Projektregeln steuert **nur der Core-Prozess** die GPIOs; die Web-UI löst
nie direkt Motoren aus, sondern legt Befehle als Datei ab (`drive_command.json`),
analog zur Anlernfahrt-Aufnahme.

```
Web-UI (DrivePage)
  └─ POST /api/drive/command {left, right}        # -1..1 je Kette
       └─ drive_command.json  (Shared Volume)
            └─ core: _poll_drive() → DriveController.set_speeds()
                 └─ MotorDriver → TB6612FNG GPIO/PWM
core: drive_status.json ← DriveController.status_dict()
  └─ GET /api/drive/status → DrivePage (Live-Anzeige)
```

### Sicherheit: Totmann-Watchdog

Der `DriveController` läuft in einem Worker-Thread und stoppt die Motoren
automatisch, wenn innerhalb von `drive.watchdog_timeout_ms` (Standard 1000 ms)
kein neuer Befehl eintrifft. Die Web-UI sendet daher alle ~300 ms einen
Keepalive, solange ein Richtungsknopf gehalten wird; beim Loslassen wird sofort
gestoppt.

## Konfiguration

`config/defaults.yaml`:

```yaml
drive:
  enabled: true
  max_speed: 1.0            # globale Tempo-Begrenzung (0..1)
  watchdog_timeout_ms: 1000
  invert_left: false        # umkehren, falls eine Kette verkehrt läuft
  invert_right: false
```

Pin-Anpassungen pro Gerät in `config/local.yaml` (gitignored), z. B.:

```yaml
motor:
  left_in1: 5
  left_in2: 6
  left_pwm: 12
  right_in1: 16
  right_in2: 26
  right_pwm: 13
  standby: 25

encoder:
  left:
    channel_a: 21
    channel_b: 24
  right:
    channel_a: 14
    channel_b: 15
  supply_v: 5
  pulses_per_rev: 44   # example: 11 PPR × 4 (quadrature)
```

## Inbetriebnahme

1. Verdrahtung nach Tabelle (Motor + Encoder), gemeinsame Masse prüfen.
2. Encoder-Versorgungsspannung am Datenblatt prüfen (5 V vs. 3,3 V).
3. `drive.enabled: true` setzen.
4. In der Web-UI unter **Fahren** zunächst mit geringer Geschwindigkeit testen.
5. Läuft eine Kette falsch herum: `invert_left`/`invert_right` umschalten.
6. Dreht der Roboter bei „vorwärts“ statt geradeaus, sind die Kanäle/Motoren
   vertauscht → Verdrahtung oder Invert-Flags anpassen.
7. Encoder: Impulse pro Umdrehung messen, `encoder.pulses_per_rev` setzen;
   Richtung prüfen (`encoder.invert_left` / `invert_right`).
8. Encoder-Kalibrierung testen: kurze Bereichsfahrt (z. B. 1 × 1 m) starten und
   gefahrene Strecke nachmessen; bei Abweichung `wheel_diameter_mm` anpassen,
   bei ungenauen 90°-Drehungen `track_width_mm`.
