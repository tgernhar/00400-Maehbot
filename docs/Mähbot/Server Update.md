
# Mit dem Pi verbinden
ssh tgernhar@10.233.159.212


## Stand auf den Pi bringen (über Git)

1. Auf dem Windows-PC – Änderungen committen und pushen:

git add -A

git commit -m "deine Nachricht"

git push

2. Auf dem Pi (SSH-Session läuft schon) – ins Projekt wechseln und ziehen:

cd ~/pi/maehbot

git pull

3. Falls sich Python-Abhängigkeiten geändert haben (z. B. `requirements.txt`):

source .venv/bin/activate

pip install -r requirements.txt

pip install -e .

4. Dienste neu starten, damit der neue Stand läuft:
# Native core (systemd), falls so eingerichtet:

sudo systemctl restart maehbot-core

# Web-UI im Docker:

cd ~/pi/maehbot/docker && docker compose up -d --build web

## Wichtige Hinweise

- `config/local.yaml` ist gitignored und liegt nur auf dem Pi – die wird beim `git pull` nicht überschrieben (gut so, da Pi-spezifische Pins/Pfade).
- Wenn `git pull` über lokale Änderungen am Pi meckert: `git stash` → `git pull` → ggf. `git stash pop`.

---

Alternativ ohne Git (direkt vom PC kopieren), falls du etwas Ungetestetes/Uncommittetes schnell rüberschieben willst:

scp -r . tgernhar@10.233.159.212:/home/tgernhar/pi/maehbot

Empfehlung: Den Git-Weg nutzen – sauber nachvollziehbar und `config/local.yaml` bleibt unangetastet.

Soll ich diese Kurzanleitung als Abschnitt „Update auf den Pi“ in `docs/deploy.md` ergänzen?


Terminal 1 Starten

cd ~/maehbot && source .venv/bin/activate
python -m core.main

Terminal 2 Starten
cd ~/maehbot && source .venv/bin/activate
python -m web.backend.app

