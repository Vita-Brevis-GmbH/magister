# Installation: Vita Brevis Cockpit (Konsole)

**Umgezogen (2026-11):** Dieses Runbook gehört zur Konsole und liegt im Repo
`Vita-Brevis-GmbH/vitabrevis-cockpit` unter `docs/runbooks/install-cockpit.md` – auf den Hosts
`/opt/cockpit/src/docs/runbooks/install-cockpit.md`.

Inhalt dort: Installation und Update der Konsole.

Kurz, für den Normalfall auf dem Magister-Host:

```bash
cd /opt/magister && ./scripts/plattform-aufbau.sh up          # beide Stacks
cd /opt/cockpit/src && git pull && scripts/cockpit.sh update  # nur die Konsole
```

Die Konsole baut sich seit 2026-11 selbst auf (`scripts/cockpit.sh` in vitabrevis-cockpit,
ADR 0009 dort); `plattform-aufbau.sh` ruft dieses Skript auf und übergibt Plattform-CA, Netz und
Zugang zur Datenebene. Die Sicherung der Konsole selbst (Datenbank und `.env`, mit age) steht dort
in `docs/runbooks/sicherung-konsole.md`; der frühere Cron-Job aus §10 dieser Seite sicherte
unverschlüsselt und wird beim Einrichten abgeschaltet.
