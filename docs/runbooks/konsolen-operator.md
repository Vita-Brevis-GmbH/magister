# Runbook · Einen Operator für die Konsole einrichten

**Umgezogen (2026-11):** Dieses Runbook gehört zur Konsole und liegt im Repo
`Vita-Brevis-GmbH/vitabrevis-cockpit` unter `docs/runbooks/konsolen-operator.md` – auf den Hosts
`/opt/cockpit/src/docs/runbooks/konsolen-operator.md`.

Inhalt dort: Operatoren der Konsole: anlegen, erstes Anmelden, Widerruf, zweiter Faktor.

Der Befehl bleibt auch über Magister:

```bash
./scripts/plattform-aufbau.sh operator --upn vorname.nachname@vitabrevis.ch --name "Vorname Nachname" --set-password
```

`plattform-aufbau.sh` reicht `operator` und `totp` an `scripts/cockpit.sh` der Konsole weiter.
