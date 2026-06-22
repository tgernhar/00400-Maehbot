# Live Spray Freigabe-Checkliste

Vor dem ersten echten Sprühen im Feld:

- [ ] **Testmodus** erfolgreich: Erkennungen werden gespeichert, GPIO bleibt aus
- [ ] **Tank-Sensoren** geprüft: `tank_full` / `tank_empty` GPIO korrekt
- [ ] **Travel-Time** kalibriert: Abstand Kamera–Düse (mm) und reale Geschwindigkeit (mm/s)
- [ ] **Verzögerung / Dauer** im Feld getestet (Spray-Einstellungen UI)
- [ ] **min_confidence** auf Testdaten getunt
- [ ] **Latenz** im Core-Log ≤ 10 ms (Schedule-Entscheidung)
- [ ] **Testmodus deaktiviert** nur bewusst (`test_mode: false`)
- [ ] **Not-Aus / Strom** dokumentiert (eigener Akku, Pumpenabschaltung)

Nach Freigabe: erste Sprühversuche mit minimalem Tankinhalt und bereitem Abstellbereich.
