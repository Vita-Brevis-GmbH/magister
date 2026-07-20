# Runbook: Neustart & Update über das WebUI (ops-agent)

Unter **Einstellungen → System** kann ein Admin den Container-**Neustart** und
ein **Update** (git pull + rebuild) auslösen. Aus Sicherheitsgründen führt die
Applikation das **nicht selbst** aus: der API-Container ist unprivilegiert und
hat keinen Docker-Zugriff. Er schreibt nur eine Anfrage-Datei; ein
**privilegierter Host-Watcher** (systemd-Timer) führt sie aus.

```
WebUI ──POST /admin/system/{restart,update}──▶ API
API ──schreibt──▶ /ops/requests/<id>.json        (unprivilegiert)
ops-agent (Host, systemd) ──liest──▶ Request
   restart │ docker compose restart
   update  │ git pull --ff-only && docker compose build && up -d
ops-agent ──streamt Output──▶ /ops/last.log (live)
ops-agent ──schreibt──▶ /ops/status.json ──gelesen von der API──▶ WebUI (inkl. Log)
```

Ein kompromittiertes WebUI kann damit höchstens einen Neustart/Update anstossen
— niemals beliebige Host-Befehle ausführen (der Agent kennt nur die zwei fixen
Aktionen).

> **Kein Container:** In dieser (sichersten) Variante ist der ops-agent ein
> **systemd-Dienst auf dem Host**, kein Docker-Container. So bekommt die Web-App
> nie Docker-Zugriff. Eine optionale Container-Variante ist unten beschrieben.

## Einrichtung (einmalig, auf dem Host)

Annahmen (Pfade an die eigene Umgebung anpassen):

- Repo/Checkout: `/opt/magister/magister`
- Compose-Stack: `/opt/magister/magister/deploy/compose/docker-compose.yml`
- `.env` daneben: `/opt/magister/magister/deploy/compose/.env`
- Der API-Container läuft als User `magister` (**uid 1000**) — wichtig für die
  Verzeichnisrechte in Schritt 2.

### Schritt 1 — Code auf dem Server holen

Für „Update" (git pull + build) muss auf dem Server ein **Git-Checkout** liegen,
aus dem gebaut wird:

```bash
sudo mkdir -p /opt/magister
sudo git clone https://github.com/Vita-Brevis-GmbH/magister.git /opt/magister/magister
cd /opt/magister/magister
```

Betreibst du den Stack schon aus einem anderen Verzeichnis, verwende dessen Pfad
überall unten statt `/opt/magister/magister`.

### Schritt 2 — geteiltes ops-Verzeichnis anlegen

Der API-Container legt hier Anfragen ab; er schreibt als **uid 1000**, also muss
das Verzeichnis dieser uid gehören:

```bash
sudo mkdir -p /opt/magister/ops/requests
sudo chown -R 1000:1000 /opt/magister/ops
```

(Alternativ, falls uid 1000 auf dem Host anderweitig belegt ist:
`sudo chmod -R 0777 /opt/magister/ops` — funktional gleichwertig, aber weniger
restriktiv.)

### Schritt 3 — Compose auf das Verzeichnis zeigen lassen

In `deploy/compose/.env` ergänzen:

```bash
echo 'MAGISTER_OPS_HOST_DIR=/opt/magister/ops' \
  | sudo tee -a /opt/magister/magister/deploy/compose/.env
```

Der Compose-Eintrag ist bereits vorhanden: er mountet `${MAGISTER_OPS_HOST_DIR}`
in den API-Container als `/ops` und setzt `MAGISTER_OPS_DIR=/ops`. (Ohne die
Variable wird `./ops` neben dem Compose-File verwendet.) API-Container einmal neu
erzeugen, damit der Mount greift, und prüfen:

```bash
cd /opt/magister/magister/deploy/compose
docker compose up -d magister-api
docker compose exec magister-api ls -la /ops
```

### Schritt 4 — ops-agent + Timer installieren

Die drei Dateien liegen im Repo unter `deploy/ops-agent/`:

```bash
cd /opt/magister/magister
sudo chmod +x deploy/ops-agent/magister-ops-agent.sh
sudo cp deploy/ops-agent/magister-ops-agent.service /etc/systemd/system/
sudo cp deploy/ops-agent/magister-ops-agent.timer   /etc/systemd/system/
```

**Pfade in der Unit prüfen.** In `/etc/systemd/system/magister-ops-agent.service`
müssen die `Environment=`-Zeilen zu deinen Pfaden passen:

```ini
Environment=OPS_DIR=/opt/magister/ops
Environment=REPO_DIR=/opt/magister/magister
Environment=COMPOSE_FILE=/opt/magister/magister/deploy/compose/docker-compose.yml
Environment=COMPOSE_ENV=/opt/magister/magister/deploy/compose/.env
```

Dann laden und Timer starten:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now magister-ops-agent.timer
```

Der Timer läuft alle 30 s und arbeitet offene Anfragen ab.

### Schritt 5 — testen

In der WebUI **Einstellungen → System** auf „Neustart" oder „Update holen"
klicken, dann auf dem Host beobachten:

```bash
systemctl status magister-ops-agent.timer
cat  /opt/magister/ops/status.json          # letzter Zustand (running/success/error)
tail -f /opt/magister/ops/last.log          # Live-Log der Ausführung
journalctl -u magister-ops-agent.service -f    # Agent-Läufe
```

### Komponenten-Übersicht

| Datei | Ort | Zweck |
|---|---|---|
| `deploy/ops-agent/magister-ops-agent.sh` | Host (Repo) | führt `restart`/`update` aus, schreibt `status.json` + `last.log` |
| `magister-ops-agent.service` | `/etc/systemd/system/` | ruft das Skript einmal auf (oneshot) |
| `magister-ops-agent.timer` | `/etc/systemd/system/` | löst den Dienst alle 30 s aus |
| `/opt/magister/ops/requests/*.json` | geteiltes Volume | Anfragen der Web-App (uid 1000) |
| `/opt/magister/ops/status.json` + `last.log` | geteiltes Volume | Ergebnis/Log (vom Host geschrieben) |

Fehler „System nicht konfiguriert" in der WebUI = der `/ops`-Mount fehlt
(Schritt 3); die Buttons bleiben dann deaktiviert.

## Verhalten

- **Neustart**: `docker compose restart` (alle Services).
- **Update**: `git pull --ff-only` im Repo, dann `docker compose build` und
  `up -d`. Schlägt der Fast-Forward-Pull fehl (lokale Änderungen), bricht das
  Update ab und `status.json` zeigt `state: error` mit der Meldung.
- Der WebUI-Status zeigt: konfiguriert ja/nein, offene Anfragen, letzte Aktion
  mit Zustand (`running`/`success`/`error`), Meldung und aktueller Git-Kurz-SHA.

## Sicherheit / Betrieb

- Kein Docker-Socket im API-Container; der Agent läuft als eigener Host-Dienst.
- Der Agent interpretiert aus der Anfrage nur das Feld `action` und nur die
  Werte `restart`/`update` (Whitelist). Alles andere wird als Fehler verworfen.
- Jede Anfrage wird serverseitig auditiert (`system_command_requested`).
- Ist `MAGISTER_OPS_DIR` (bzw. der Mount) nicht gesetzt, liefert die API `503`
  und die Buttons im WebUI sind deaktiviert.
- **Update = laufender Container aktualisiert sich selbst**: `up -d` ersetzt
  auch den API-Container; die laufende Anfrage kann dadurch abgeschnitten werden
  — das ist erwartet. Der Status wird vom Host-Agenten geschrieben, nicht vom
  (neu startenden) Container, bleibt also erhalten.

## Optional: als Container statt Host-Dienst

Wer den Agenten lieber im Compose-Stack „mitliefern" möchte, kann ihn als
Container betreiben. **Trade-off:** bequemer, aber der Docker-Socket liegt dann
in einem Container statt nur auf dem Host — etwas grössere Angriffsfläche als die
reine Host-Variante oben. Der Container bleibt minimal (nur Docker-CLI + Git +
das Skript) und hängt an keinem Port.

Service in `deploy/compose/docker-compose.yml` ergänzen:

```yaml
  ops-agent:
    image: docker:27-cli
    restart: unless-stopped
    entrypoint: ["/bin/sh", "-c"]
    command:
      - |
        apk add --no-cache git bash >/dev/null
        while true; do
          bash /repo/deploy/ops-agent/magister-ops-agent.sh
          sleep 30
        done
    environment:
      OPS_DIR: /ops
      REPO_DIR: /repo
      COMPOSE_FILE: /repo/deploy/compose/docker-compose.yml
      COMPOSE_ENV: /repo/deploy/compose/.env
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock   # ← die privilegierte Stelle
      - /opt/magister/magister:/repo                # Git-Checkout (für update)
      - ${MAGISTER_OPS_HOST_DIR:-./ops}:/ops        # dieselbe geteilte ops-Dir
    networks: [internal]
```

Danach:

```bash
cd /opt/magister/magister/deploy/compose
docker compose up -d ops-agent
docker compose logs -f ops-agent
```

Wenn du diese Variante nutzt, **den systemd-Dienst NICHT zusätzlich** aktivieren
(sonst laufen zwei Agenten auf derselben ops-Dir). Beide Wege verwenden dasselbe
`magister-ops-agent.sh` und dieselbe `/ops`-Dir — es ist also nur ein
Entweder/Oder bei der Ausführung.
