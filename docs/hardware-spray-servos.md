# Sprüh-Servos: Anschlussbelegung und Kalibrierung

Drei Hobby-Servos steuern den Sprühmechanismus. Sie werden per 50-Hz-PWM
(`lgpio.tx_pwm`) angesteuert — identisch auf Raspberry Pi 4 und Pi 5.

## Anschlussbelegung (BCM / physischer Pin)

| Servo | Funktion | Winkelbereich | Signal (BCM) | Physischer Pin |
|-------|----------|---------------|--------------|----------------|
| 1 | Positionierung (Düse drehen) | -180° bis +180° | GPIO 18 | Pin 12 |
| 2 | Spannservo (Sprühdruck) | -45° bis +180° | GPIO 19 | Pin 35 |
| 3 | Betätigungsmechanismus | 0° bis 45° | GPIO 20 | Pin 38 |

**GND:** Alle Servo-Masseleitungen mit Pi-GND verbinden, z. B. physischer
Pin 39 (direkt neben Pin 38) oder Pin 6.

Die Pins kollidieren nicht mit den bereits belegten Pins:

- Motor (TB6612FNG): BCM 5, 6, 12, 13, 16, 25, 26
- Sprühen (Ventil/Pumpe/Tank): BCM 17, 27, 22, 23

## Stromversorgung — wichtig

- Servos **niemals** aus den 5-V-Pins des Raspberry Pi versorgen. Unter Last
  ziehen Servos kurzzeitig mehrere Ampere — der Pi bricht ein oder startet neu.
- Externes Netzteil oder Akku mit 5–6 V verwenden (je nach Servotyp).
- **Masse des Netzteils mit Pi-GND verbinden** (gemeinsames Bezugspotential),
  sonst ist das PWM-Signal undefiniert.

```text
Servo rot     → externe 5–6 V
Servo braun   → externe GND  ──┬── Pi GND (Pin 39 oder 6)
Servo orange  → Pi GPIO 18 / 19 / 20 (Signal)
```

## Ablauf

**Grundstellung** (automatisch beim Core-Start und nach jedem Testlauf):

1. Servo 3 (Betätigung) auf 0°
2. Servo 2 (Spannservo) auf -45°
3. Servo 1 (Positionierung) auf 0°
4. Servo 2 auf 0°
5. Servo 3 auf 0°

**Testlauf** (Seite "Sprühen", Button "Testen"):

1. Servo 2 auf den eingestellten Wert von Regler 2
2. Servo 1 auf den eingestellten Wert von Regler 1
3. Servo 3 auf den eingestellten Wert von Regler 3
4. Zurück in die Grundstellung

Zwischen den Schritten wartet der Ablauf `servo.step_delay_ms`
(Standard 800 ms), damit die Servos ihre Position erreichen.

## Kalibrierung

Standardwerte stehen in `config/hardware.yaml` (Sektion `servo`). Abweichende
Servotypen (z. B. 270°- oder 360°-Servos) über `config/local.yaml` kalibrieren:

```yaml
servo:
  step_delay_ms: 800
  position:
    pin: 18
    min_angle: -180      # Winkel bei min_pulse_us
    max_angle: 180       # Winkel bei max_pulse_us
    min_pulse_us: 500    # Pulsbreite am Anschlag min_angle
    max_pulse_us: 2500   # Pulsbreite am Anschlag max_angle
```

Hinweise:

- `min_pulse_us` / `max_pulse_us` an das Datenblatt des Servos anpassen
  (üblich: 500–2500 µs oder 1000–2000 µs).
- Servo 1 mit ±180° (360° Gesamtbereich) ist kein Standard-180°-Servo — der
  konfigurierte Winkelbereich muss zum tatsächlichen Stellbereich des Servos
  bei der jeweiligen Pulsbreite passen.
- Der Testlauf funktioniert ohne Kamera: Auf dem Pi 4 einfach Core + Web
  starten, die Kamera fällt automatisch auf einen Mock zurück.

## Architektur

Der Web-Prozess steuert kein GPIO. Die Seite "Sprühen" queued ein Command
(`servo_command.json`), der Core-Prozess konsumiert es in der Hauptschleife
und führt die Sequenz in einem Worker-Thread aus. Der Status steht in
`servo_status.json` und wird per `GET /api/servo/status` abgefragt.
