# ADR 0003: Vita Brevis Cockpit als separates Ops-Tool

**Status:** Akzeptiert · 2026-06-02
**Kontext:** M4 — Scale & Operations Maturity

## Problem

Mit wachsender Zahl an Schulträgern braucht das Ops-Team von Vita Brevis einen zentralen Überblick: Welche Instanz läuft? Welche Version ist deployed? Welche braucht ein Update? Heute manuell per SSH und Browser — skaliert nicht über ~5 Instanzen hinaus.

## Entscheidung

Wir bauen ein separates Tool **Vita Brevis Cockpit**:

1. **Eigenes Code-Subtree** unter `cockpit/` im Magister-Repo, später extrahiert nach `github.com/vita-brevis-gmbh/vita-brevis-cockpit` via `git subtree split` sobald GitHub-Org-Permissions für API-basierte Repo-Erstellung verfügbar sind.
2. **Eigener Stack** (FastAPI + React + Postgres), aber identische Konventionen wie Magister — Onboarding-Reibung minimal.
3. **Bootstrap-Token-Auth** (nicht OIDC) — Cockpit läuft hinter VPN/Tailscale, max. 5 Ops-User. Pragmatischer als Full-OIDC-Setup.
4. **Read-mostly auf Magister-Daten** — Cockpit ruft nur `/api/healthz` (liefert Status + Version) der Magister-Instanzen ab. **Kein** direkter DB-Zugriff zu Magister-Postgres-Instanzen.

## Konsequenzen

**Positiv:**
- Klare Trennung Ops-Tool vs. Schul-Tool (keine RBAC-Vermischung)
- Cockpit-Crash bringt keine Magister-Instanz herunter
- Schulträger sehen das Cockpit nie

**Negativ:**
- Zwei Codebases zu pflegen
- Cross-Repo Versions-Bumps brauchen Koordination (in M4.3 lösen wir das via signiertem Manifest)

## Alternativen verworfen

- **Cockpit als Magister-Subapp**: würde RBAC-Modell aufweichen (Vita-Brevis-Ops vs. Schulleitung in derselben App)
- **Grafana + Custom-Plugin**: zu schwergewichtig für 5 Instanzen, schlechte UX für Update-Trigger

## Nachtrag 2026-11-12 · Im eigenen Repo

Seit 2026-11 im eigenen Repo `vitabrevis-cockpit` (mit Verlauf herausgelöst, auf den Hosts
`/opt/cockpit/src`); `cockpit/` ist aus Magister entfernt. Den Umzug eines laufenden Cockpits
beschreibt dort `docs/runbooks/umzug-aus-magister.md`, in Magister
`docs/runbooks/plattform-auf-einem-host.md` §2.3.

## Nachtrag 2026-11-13 · Aufbau aus dem eigenen Repo

Die Konsole baut sich selbst auf (vitabrevis-cockpit ADR 0009, P1 „Eigenständig (E7)“):
`scripts/cockpit.sh` dort legt ihre `.env` an und führt sie nach, stellt ihr Zertifikat aus der
Plattform-CA aus, baut die Oberfläche, startet, migriert, verwaltet Operatoren und sichert die
Datenbank der Konsole selbst (age, systemd-Timer). `plattform-aufbau.sh` enthält keinen
Compose-Aufruf der Konsole mehr und ruft nur noch dieses Skript auf; Bedienung und Ergebnis von
`./scripts/plattform-aufbau.sh up` bleiben gleich.

- **Gemeinsam, mit einem Besitzer:** Plattform-CA, Netz `magister-plattform` und das
  Rollenpasswort der Datenebene gehören Magister; Bootstrap-Token und Management-Marker der
  Konsole. Übergeben wird über die Schnittstelle Fassung 1 (Umgebung `KONSOLE_SETZEN`,
  `KONSOLE_STARTWERTE`, `MAGISTER_DIR`; Befehle `wert`, `pruefen`, `operatoren-zahl`,
  `status --kurz`, `anlegen`, `kunden-sicherungen-pruefen`, `purge --ja`). Magister prüft die
  Fassung (`cockpit.sh schnittstelle`) und bricht mit dem Befehl zum Aktualisieren ab, wenn der
  Checkout der Konsole zu alt ist.
- **Schutz der `.env`** (PR #61) hält jetzt die Konsole (`cockpit.sh pruefen`, auch in ihrem `up`
  und `restart`); `plattform-aufbau.sh` fragt ihn vor jedem Start. Die Prüfungen zum Umzug aus
  `cockpit/` bleiben hier.
- `plattform-backup-pruefer.sh` startet den Prüfer der Kundensicherungen über
  `cockpit.sh kunden-sicherungen-pruefen`; `scripts/bootstrap-cockpit-token.sh` reicht an das
  Skript der Konsole weiter.
- Die Runbooks `install-cockpit.md`, `console-listener.md`, `konsolen-operator.md`,
  `kunde-anlegen-konsole.md` und `cockpit-update-runner.md` liegen in vitabrevis-cockpit; hier
  bleibt je ein Verweis.
- Test der Schnittstelle von dieser Seite: `scripts/tests/plattform-konsole.test.sh` (mit dem
  echten `cockpit.sh`, wenn ein Checkout da ist; `scripts-ci` holt ihn mit `COCKPIT_DEPLOY_KEY`).
