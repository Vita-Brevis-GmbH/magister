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
ops-agent ──schreibt──▶ /ops/status.json ──gelesen von der API──▶ WebUI
```

Ein kompromittiertes WebUI kann damit höchstens einen Neustart/Update anstossen
— niemals beliebige Host-Befehle ausführen (der Agent kennt nur die zwei fixen
Aktionen).

## Einrichtung (einmalig, auf dem Host)

Annahme: Repo liegt unter `/opt/magister/magister`, Compose-Stack darin.

1. **Ops-Verzeichnis anlegen** (gemeinsam zwischen API-Container und Host):

   ```bash
   sudo mkdir -p /opt/magister/ops/requests
   # Muss vom API-Container-User beschreibbar sein. Einfachste Variante:
   sudo chmod -R 0777 /opt/magister/ops
   ```

2. **Compose auf das Verzeichnis zeigen lassen** — in `deploy/compose/.env`:

   ```
   MAGISTER_OPS_HOST_DIR=/opt/magister/ops
   ```

   (Ohne diese Variable wird `./ops` neben dem Compose-File verwendet.)

3. **ops-agent + Timer installieren:**

   ```bash
   sudo cp deploy/ops-agent/magister-ops-agent.service /etc/systemd/system/
   sudo cp deploy/ops-agent/magister-ops-agent.timer   /etc/systemd/system/
   # Pfade in der .service ggf. anpassen (OPS_DIR/REPO_DIR/COMPOSE_FILE).
   sudo systemctl daemon-reload
   sudo systemctl enable --now magister-ops-agent.timer
   ```

   Der Timer läuft alle 30 s und arbeitet offene Anfragen ab.

4. **Prüfen:**

   ```bash
   systemctl status magister-ops-agent.timer
   # Nach einem WebUI-Klick:
   cat /opt/magister/ops/status.json
   journalctl -u magister-ops-agent.service --no-pager | tail
   ```

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
