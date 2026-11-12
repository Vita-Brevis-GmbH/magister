# CI: Konsole (vitabrevis-cockpit) für die Abgleichstests

Die Konsole lebt seit PR #60 im eigenen Repo `Vita-Brevis-GmbH/vitabrevis-cockpit`. Einige
Zusagen tragen beide Seiten. Die Abgleichstests in `apps/api` lesen deshalb Dateien der Konsole:

- Versiegeln (`tests/integration/test_reconcile_operations.py`, `services/sealing.py`);
- Präfix der Operator-Assertion (`tests/unit/test_operator_assertion.py`);
- Policy-Keys (`tests/unit/test_reconciler.py`, `services/settings.py`).

Die `backend-ci` holt die Konsole dafür mit einem **Deploy-Key nur zum Lesen**. Fehlt er, läuft
die CI trotzdem: die drei Tests überspringen sich, und die CI meldet die Lücke als Warnung und in
der Zusammenfassung. Gegenstück im Cockpit: `docs/runbooks/ci.md` (Secret `MAGISTER_DEPLOY_KEY`).

## Einrichten (einmal)

Den Schlüssel auf Ihrem Rechner erzeugen, nicht auf einem Server. Der private Teil gehört nur in
das Secret von GitHub, nie in den Chat oder in ein Repo.

1. Schlüssel erzeugen:

   ```bash
   ssh-keygen -t ed25519 -N "" -C "magister CI (vitabrevis-cockpit lesen)" -f ./cockpit-ci
   ```

2. **Öffentlichen Teil beim Cockpit hinterlegen:**
   1. `Vita-Brevis-GmbH/vitabrevis-cockpit` → Settings → Deploy keys → Add deploy key;
   2. Titel `magister CI (nur lesen)`, Inhalt von `cockpit-ci.pub`;
   3. **„Allow write access“ nicht anhaken.**
3. **Privaten Teil als Secret in Magister hinterlegen:**
   1. `Vita-Brevis-GmbH/magister` → Settings → Secrets and variables → Actions → New repository
      secret;
   2. Name `COCKPIT_DEPLOY_KEY`, Inhalt die ganze Datei `cockpit-ci`, mit der ersten und der
      letzten Zeile.
4. Beide Dateien auf dem Rechner löschen: `rm cockpit-ci cockpit-ci.pub`.
5. Den letzten Lauf der `backend-ci` neu starten (Actions → Lauf → „Re-run all jobs“). In der
   Zusammenfassung des Jobs `test` steht dann `Konsole (vitabrevis-cockpit): <commit>`, und die
   Warnung ist weg.

Ein Schlüssel je Richtung: GitHub nimmt denselben Deploy-Key nicht in zwei Repos an.

## Gegen welchen Stand

Die CI prüft gegen `main` der Konsole. Ändert sich ein gemeinsamer Vertrag, kommt die Änderung
zuerst in Magister, dann in die Konsole (`CLAUDE.md` im Cockpit, „Gleichlauf mit Magister“). Ein
roter Abgleichstest hier heisst dann: die Konsole hinkt nach.

## Lokal

```bash
cd apps/api
MAGISTER_TEST_KONSOLE_DIR=/pfad/zu/vitabrevis-cockpit uv run pytest -q tests/unit/test_reconciler.py
```

Ohne die Variable suchen die Tests einen Ordner `vitabrevis-cockpit` im Repo oder daneben
(`apps/api/tests/konsole.py`).
