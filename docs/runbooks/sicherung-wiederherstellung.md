# Runbook: Sicherung, Prüfung, Wiederherstellung, Export

Grundlage: [ADR-0016](../adr/0016-sicherung-wiederherstellung-export.md).
Dieses Runbook beschreibt den Betrieb einer **gehosteten** Installation mit
mehreren Kunden. Für eine Einzelinstallation gilt Abschnitt 8.

## 0 · Wer darf was, und warum umständlich

Die Schlüsseltrennung aus ADR-0016 D2 entscheidet, welcher Schritt auf welcher
Maschine läuft. Das ist kein Organigramm, sondern der eigentliche Schutz: wer
den Anwendungsserver übernimmt, soll alte Sicherungen **nicht** lesen können.

| Schritt | Läuft auf | Braucht |
|---|---|---|
| Sicherung schreiben | Anwendungsserver (Konsole) | öffentlicher age-Schlüssel |
| Prüfsumme nachrechnen | Anwendungsserver oder Fileserver | nichts |
| Prüf-Wiederherstellung | **Backup-Host** | privater age-Schlüssel |
| Wiederherstellung | **Backup-Host** | privater age-Schlüssel |
| Export erstellen | Anwendungsserver (Konsole) | nichts |
| Alte Dumps löschen | **Fileserver**, eigenes Konto | Löschrecht auf dem Share |

Die Konsole hat den privaten Schlüssel nie. Ihre Endpunkte für
Wiederherstellung und Prüfung **erfassen** einen Auftrag und **nehmen ein
Ergebnis entgegen** — sie führen nichts aus.

## 1 · Einrichtung, einmal

### 1.1 Backup-Schlüsselpaar

Auf dem **Backup-Host**, nicht auf dem Anwendungsserver:

```bash
age-keygen -o /etc/magister/backup-identity.txt
chmod 600 /etc/magister/backup-identity.txt
# Ausgabe: "Public key: age1..."
```

Der **öffentliche** Teil geht in die Konsole:

```
COCKPIT_BACKUP_AGE_RECIPIENT=age1...
COCKPIT_BACKUP_SHARE_ROOT=/mnt/magister-backup
```

Für den privaten Teil gibt es **keine** Einstellung auf dem Anwendungsserver.
Das ist Absicht. Er wird an denselben zwei Orten verwahrt wie der
Plattform-CA-Schlüssel (siehe [platform-ca.md](platform-ca.md)) — sonst hat
man verschlüsselte Sicherungen und keinen Weg zurück.

### 1.2 Share-Rechte

Das Dienstkonto der Konsole bekommt auf `/mnt/magister-backup`
**Erstellen/Schreiben, kein Löschen**. Prüfen:

```bash
sudo -u magister touch /mnt/magister-backup/probe && \
  sudo -u magister rm /mnt/magister-backup/probe && \
  echo "FEHLER: das Dienstkonto darf löschen" || echo "ok: kein Löschrecht"
```

Das Aufräumen läuft als eigener Cron-Job **auf dem Fileserver**, mit eigenem
Konto (ADR-0016 D2). Nicht auf dem Anwendungsserver.

### 1.3 Exportverzeichnis

```
COCKPIT_EXPORT_ROOT=/var/lib/magister-exports
COCKPIT_EXPORT_TTL_DAYS=7
```

Ausdrücklich **nicht** der Backup-Share: hier liegen Kundendaten im Klartext.
Das Verzeichnis wird mit `0700` angelegt, die Dateien mit `0600`.

## 2 · Täglich: Sicherung

Pro Kunde ein Aufruf. In einer Cron-Zeile auf dem Anwendungsserver, gegen den
Management-Listener:

```bash
curl -sS --cert /etc/magister/ops.pem --key /etc/magister/ops-key.pem \
  -H "X-Magister-Management: $COCKPIT_MANAGEMENT_MARKER" \
  -H "Authorization: Bearer $COCKPIT_BOOTSTRAP_TOKEN" \
  -H 'Content-Type: application/json' -d '{"kind":"daily"}' \
  https://10.0.0.5:4444/api/tenants/$TENANT_ID/backups
```

Die Antwort ist auch bei einem Fehlschlag **201** und trägt
`status: "failed"` samt Grund. Zu überwachen ist also nicht der HTTP-Code,
sondern das Feld:

```bash
... | jq -e '.status == "written"' >/dev/null || echo "Sicherung gescheitert"
```

Bleibt eine Zeile länger als eine Stunde auf `running`, ist der Prozess
mittendrin abgebrochen. Die Zeile bleibt stehen — sichtbar und richtig; ein
stilles Verschwinden wäre schlimmer. Die Datei mit der Endung `.partial` auf
dem Share ist der halbe Dump und kann weg (auf dem Fileserver).

## 3 · Wöchentlich: Prüf-Wiederherstellung

Auf dem **Backup-Host**. Ein Backup gilt erst als Backup, wenn es eingespielt
wurde (ADR-0016 D4).

```bash
python -m cockpit_api.cli.verify_backup \
  --admin-dsn "postgresql+asyncpg://mgadmin:***@db:5432/magister" \
  --dump /mnt/magister-backup/musterstadt/musterstadt-20260909T031500Z-daily.dump.age \
  --identity /etc/magister/backup-identity.txt \
  --slug musterstadt --schema t_musterstadt \
  --expected-schema-version 0044_local_admin_totp \
  --checksum <sha256 aus der Konsole> \
  --console https://10.0.0.5:4444 --backup-id <uuid>
```

Was geprüft wird:

* die Prüfsumme der **verschlüsselten** Datei — weicht sie ab, ist das ein
  Vorfall und kein Wiederherstellungsproblem: nicht einspielen, melden;
* die erwarteten Tabellen sind vorhanden;
* die Alembic-Version passt;
* die Zeilenzahlen liegen in plausibler Grössenordnung (nicht auf Gleichheit —
  zwischen Sicherung und Prüfung liegen Stunden produktiver Arbeit);
* `audit_events` ist lesbar und die Payloads sind **nicht** im Klartext.

Der letzte Punkt ist die abgespeckte Fassung des ADR-Kriteriums „ein
Audit-Payload lässt sich mit dem Kundenschlüssel entschlüsseln": den
Kundenschlüssel hat der Backup-Host nicht. Was er zeigen kann, ist das
Gegenteil und fast so nützlich — dass die Payloads verschlüsselt vorliegen.
Ein Dump mit Klartext-Payloads wäre ein Fehler, den man sofort sehen will.

Danach wird die Wegwerf-Datenbank verworfen. Das Ergebnis meldet das Werkzeug
an die Konsole (`verified_at` und `verify_detail`); ohne `--console` gibt es
nur die Ausgabe auf dem Terminal, und die Konsole zeigt weiter „nie geprüft".

## 4 · Wiederherstellung eines Kunden

### 4.1 Erfassen (Konsole)

```bash
curl ... -d '{"backup_id":"<uuid>","reason":"Ticket VB-4711: Klassen-Promotion verunglückt","requested_by":"matthias"}' \
  https://10.0.0.5:4444/api/tenants/$TENANT_ID/restore-jobs
```

Grund oder Ticket ist Pflicht. Der Auftrag nennt eine Ziel-Datenbank
`r_<slug>_<zeitstempel>`.

### 4.2 Einspielen (Backup-Host)

```bash
python -m cockpit_api.cli.restore_backup \
  --admin-dsn "..." --dump <pfad> --identity /etc/magister/backup-identity.txt \
  --target-database r_musterstadt_20260909104500 \
  --checksum <sha256> \
  --console https://10.0.0.5:4444 --job-id <uuid>
```

Das Produktivschema wird dabei **nicht geöffnet**. Es steht in einer anderen
Datenbank.

### 4.3 Hineinsehen, ohne umzuschalten

Der häufigere Fall in der Praxis: es fehlt eine Tabelle, eine Klasse, ein
Benutzer. Dafür braucht es kein Umschalten — die wiederhergestellte Datenbank
ist lesbar:

```sql
-- in r_musterstadt_20260909104500
SELECT * FROM t_musterstadt.classes WHERE name = '3a';
```

Einzelne Zeilen werden von dort in die Produktion zurückgeschrieben, mit
Audit-Ereignis wie jede andere Änderung.

### 4.4 Umschalten (zwei Personen)

Nur wenn der **ganze** Stand zurück soll. Erst freigeben:

```bash
curl ... -d '{"approved_by":"rolf"}' \
  https://10.0.0.5:4444/api/restore-jobs/$JOB_ID/approve
```

Die freigebende Person muss eine andere sein als die bestellende (ADR-0016
D5). Dann einer von zwei Wegen:

**Weg A — Registry umbiegen (bevorzugt).** Der Kunde zeigt auf die andere
Datenbank:

1. Kunde in der Konsole sperren (`POST /api/tenants/{id}/suspend`), damit
   niemand in den alten Stand schreibt.
2. Auf dem Anwendungsserver eine neue Umgebungsvariable setzen und
   `dsn_ref` des Kunden darauf zeigen lassen:
   `MAGISTER_TENANT_DSN_MUSTERSTADT_R1=postgresql+asyncpg://r_musterstadt:***@db/r_musterstadt_20260909104500`
3. Rolle und Rechte in der neuen Datenbank herstellen (`GRANT`, Eigentum), wie
   in [mandanten-schema-umzug.md](mandanten-schema-umzug.md) beschrieben.
4. Anwendungsserver neu starten, Kunde entsperren, umschalten vermerken:
   `POST /api/restore-jobs/{id}/switched`.

Kosten: eine Umgebungsänderung und ein Neustart. Nutzen: das alte
Produktivschema wird **nicht angefasst** und steht unverändert als Rückweg.

**Weg B — Stand über das Produktivschema legen.** Wenn eine
Umgebungsänderung nicht in Frage kommt:

1. Kunde sperren.
2. Im Produktivcluster: `ALTER SCHEMA t_musterstadt RENAME TO t_musterstadt_alt_20260909;`
3. Aus der wiederhergestellten Datenbank dumpen und in die Produktion
   einspielen — der Dump enthält `CREATE SCHEMA t_musterstadt`, also entsteht
   das Schema unter dem ursprünglichen Namen neu.
4. Eigentum und Rechte für `r_musterstadt` herstellen.
5. Kunde entsperren, umschalten vermerken.

Kosten: das Produktivschema wird umbenannt, also angefasst. Es bleibt
vollständig erhalten — ein `RENAME` ist kein `DROP` —, aber die Zusage
„daneben, nie darüber" ist hier weicher als bei Weg A. Das umbenannte Schema
bleibt mindestens 10 Tage stehen.

**Nie:** `DROP SCHEMA ... CASCADE` auf ein Produktivschema. Nicht als
Aufräumschritt, nicht „weil der Restore ja geklappt hat".

## 5 · Export für den Kunden

```bash
curl ... -d '{"requested_by":"matthias"}' \
  https://10.0.0.5:4444/api/tenants/$TENANT_ID/exports
# -> {"state":"ready","expires_at":"...","checksum_sha256":"..."}
curl -sS -o export.zip ... https://10.0.0.5:4444/api/exports/$EXPORT_ID/download
```

Der Download läuft nach `COCKPIT_EXPORT_TTL_DAYS` ab; danach antwortet der
Endpunkt mit **410** und der Export muss neu bestellt werden. Vor der
Weitergabe an den Kunden die Prüfsumme nennen — er kann sie mit
`sha256sum export.zip` gegenprüfen.

Im Archiv: `MANIFEST.json` (jede Datei, jede Spalte, und was **nicht** drin
ist und warum), `README.txt`, `daten/*.csv`, `vorlagen/*.html`,
`PRUEFSUMMEN.sha256`. Die CSV-Dateien haben Semikolon als Trennzeichen und
UTF-8 mit BOM — in Excel unter Windows genügt ein Doppelklick.

Nicht enthalten sind Anmeldesitzungen, der Notfallzugang, die Konfiguration
der Installation und die verschlüsselten Audit-**Inhalte** (die Ereignisse
selbst — wer, wann, was — sind enthalten). Das steht auch im Manifest, damit
der Kunde die Lücke sieht statt sie zu vermuten.

Alte Exporte aufräumen ist Pflicht, nicht Kür:

```bash
find /var/lib/magister-exports -name '*-export-*.zip' -mtime +7 -delete
```

## 6 · Offboarding

Reihenfolge, und jeder Schritt weigert sich, wenn der vorherige fehlt:

```bash
# 1. Kündigung erfassen. Der Kunde wird ab sofort nicht mehr bedient (503).
curl ... -d '{"reason":"Kündigung per 31.12., Ticket VB-4711","requested_by":"matthias","grace_days":30}' \
  https://10.0.0.5:4444/api/tenants/$TENANT_ID/offboarding

# 2. Letzten Stand sichern.
curl ... -d '{"kind":"offboarding"}' .../tenants/$TENANT_ID/backups

# 3. Export erstellen, herunterladen, dem Kunden zustellen.
curl ... -d '{"requested_by":"matthias"}' .../tenants/$TENANT_ID/exports

# 4. Zustellung vermerken — hieran hängt die Löschsperre.
curl ... -X POST .../tenants/$TENANT_ID/offboarding/export/$EXPORT_ID

# --- Karenzzeit abwarten (30 Tage). Vorher weigert sich Schritt 5. ---

# 5. Schema und Rolle löschen. Zwei verschiedene Personen. Unwiderruflich.
curl ... -d '{"dropped_by":"matthias","approved_by":"rolf"}' \
  .../tenants/$TENANT_ID/offboarding/drop

# 6. Kundenschlüssel auf dem Anwendungsserver vernichten:
#    MAGISTER_TENANT_AUDIT_KEY_<REF> aus der Umgebung entfernen, Prozess neu
#    starten, und den Wert aus dem Passwortspeicher löschen.
#    DANACH bestätigen:
curl ... -d '{"confirmed_by":"matthias"}' \
  .../tenants/$TENANT_ID/offboarding/key-destroyed
# -> purge_due_at: das Datum, das dem Kunden zugesagt wird.

# --- Aufbewahrungsfrist abwarten (10 Tage). ---

# 7. Fristablauf vermerken. Vorher weigert sich der Endpunkt.
curl ... -X POST .../tenants/$TENANT_ID/offboarding/purged
```

Zu Schritt 6, ausgeschrieben: **die Konsole kann den Schlüssel nicht
vernichten und prüft es auch nicht.** Sie hält fest, dass ein Mensch es getan
hat. Wer hier bestätigt, bestätigt eine eigene Handlung. Was die Konsole
dagegen nachprüft, ist Schritt 5: sie fragt nach dem Löschen
`information_schema.schemata` und `pg_roles` ab und vermerkt „gelöscht" nur,
wenn beides weg ist.

Und was dem Kunden zugesagt wird, in dieser Formulierung:

> Mit der Vernichtung des Kundenschlüssels sind Ihre Audit-Inhalte und
> gespeicherten Passwörter sofort und endgültig unlesbar — auch in allen
> bereits geschriebenen Sicherungen. Die übrigen Daten (Namen, Klassen,
> Zuordnungen) liegen in Sicherungen, aus denen einzelne Zeilen technisch
> nicht herausgeschnitten werden können; sie laufen am **<purge_due_at>** ab.

Nicht „wir löschen sofort alles". Das hält die Technik nicht.

Ein Widerruf ist möglich, solange nichts gelöscht ist
(`POST .../offboarding/abort` mit Begründung). Nach Schritt 5 nicht mehr —
und der Endpunkt sagt das, statt einen Rückweg vorzutäuschen.

## 7 · Was regelmässig zu prüfen ist

| Was | Wie oft | Woran man den Fehler merkt |
|---|---|---|
| Jeder Kunde hat eine Sicherung von heute | täglich | `GET /api/tenants/{id}/backups`, `started_at` |
| Jeder Kunde hat eine **geprüfte** Sicherung | wöchentlich | `verified_at` älter als 8 Tage |
| Das Dienstkonto darf nicht löschen | quartalsweise | der Test aus 1.2 |
| Der private Backup-Schlüssel ist an beiden Orten | jährlich | Testentschlüsselung eines alten Dumps |
| Alte Exporte sind weg | monatlich | `find` aus Abschnitt 5 |
| Jeder Mandant hat seinen Kundenschlüssel | bei jedem Ausrollen | der Mandant antwortet mit 503 |

Die letzte Zeile ist der häufigste Fehler nach dem Anlegen eines Kunden: der
Schlüssel aus dem `data_key`-Schritt wurde nicht in die Umgebung des
Anwendungsservers eingetragen. Der Kunde antwortet dann mit 503, und im
Protokoll steht, welche Variable fehlt.

## 8 · Einzelinstallation (on-prem)

Die Sidecar schreibt `/var/backups/magister/<db>-<stamp>.dump.age` und hängt
die Prüfsumme an `PRUEFSUMMEN.sha256` im selben Verzeichnis (mit relativem
Namen, damit `sha256sum -c` auch dann funktioniert, wenn das Volume auf dem
Backup-Host anders gemountet ist).

Prüfen, wöchentlich:

```bash
cd /opt/magister/apps/api
uv run ../../scripts/magister-cli backup verify \
  --dump "$(ls -t /var/backups/magister/*.dump.age | head -1)" \
  --identity /etc/magister/backup-identity.txt \
  --expected-schema-version "$(uv run python -c \
      'from magister_api.tenancy.version import HEAD_REVISION; print(HEAD_REVISION)')"
```

`--expected-schema-version` ist freiwillig, aber nützlich: ohne sie fällt ein
Dump aus einer älteren Codefassung nicht auf, und beim Einspielen im Ernstfall
merkt man erst dann, dass der passende Codestand ein anderer ist.

Rückgabewert **1** heisst: diese Sicherung ist unbrauchbar. **2** heisst: die
Prüfung konnte nicht laufen (kein `age`, kein Dump, kein DSN) — auch das
gehört in die Post, denn eine Prüfung, die nicht läuft, prüft nichts.



Bleibt bei der `pg-backup`-Sidecar und einem Volume (ADR-0016 D9). Erweitert
um:

* Verschlüsselung mit dem `age`-Public-Key des Betreibers,
* eine wöchentliche Prüf-Wiederherstellung,
* `magister-cli backup verify`.

Kein pgBackRest, keine Konsole, kein Share. Eine Gemeinde mit einem Server
bekommt keinen Plattform-Betrieb aufgezwungen.

## 9 · Was dieses Runbook nicht abdeckt

* **Cluster-PITR (ADR-0016 D1, Ebene 1).** WAL-Archivierung und Basebackup mit
  pgBackRest oder WAL-G sind noch nicht eingerichtet. Ohne sie gibt es keinen
  Weg auf „gestern 14:37" und keinen Weg zurück nach einer beschädigten
  Datenbank — nur den logischen Dump von heute Nacht. Das ist die grösste
  offene Lücke in diesem Bereich.
* **Die zwölf monatlichen Kopien** (Entscheid E15, ADR-0016 D3) sind
  vorgesehen, aber nicht entschieden. Ohne sie ist ein Fehler, der erst nach
  zwei Wochen auffällt, nicht rückholbar — bei Schulen ein realistisches
  Muster, weil etwas am Quartalsende auffällt und nicht am nächsten Tag.
* **Ein Zeitplaner.** Die Aufrufe in 2 und 3 gehören in Cron-Zeilen; einen
  eigenen Scheduler in der Konsole gibt es (noch) nicht.

## 10 · Die Cron-Zeilen, zum Kopieren

Auf dem **Anwendungsserver** (`/etc/cron.d/magister-backup`):

```cron
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
MAILTO=ops@vitabrevis.ch

# Tägliche Sicherung, 02:15. Pro Kunde ein Aufruf; die Kundenliste kommt aus
# der Registry-Auskunft der Konsole.
15 2 * * * magister . /etc/magister/ops.env && /opt/magister/scripts/backup-all.sh
```

Auf dem **Backup-Host** (`/etc/cron.d/magister-verify`):

```cron
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
MAILTO=ops@vitabrevis.ch

# Wöchentliche Prüf-Wiederherstellung, Sonntag 04:00. Hier liegt der private
# Schlüssel — deshalb hier und nicht auf dem Anwendungsserver.
0 4 * * 0 magister . /etc/magister/ops.env && /opt/magister/scripts/verify-all.sh
```

Die beiden Skripte liegen im Repository (`scripts/backup-all.sh`,
`scripts/verify-all.sh`). Sie holen die Kundenliste aus der
Registry-Auskunft der Konsole — die enthält bewusst keine DSN, nur Verweise
(ADR-0013 D4), ein Abruf gibt also niemandem Datenbankzugang. `ops.env` trägt
die Zugangsdaten (`COCKPIT_URL`, `COCKPIT_BOOTSTRAP_TOKEN`,
`COCKPIT_MANAGEMENT_MARKER`, das Operator-Zertifikat und auf dem Backup-Host
zusätzlich `MAGISTER_BACKUP_IDENTITY`, `MAGISTER_BACKUP_SHARE`,
`MAGISTER_ADMIN_DSN`); sie gehört mit `0600` dem Dienstkonto. `jq` wird
gebraucht.

`MAGISTER_PSQL_DSN` in `ops.env` auf dem Backup-Host ist optional, aber
empfohlen: damit holt `verify-all.sh` die Zeilenzahlen aus der Produktion und
gibt sie als Referenz mit. Ohne sie prüft der Lauf nur, dass der Dump
**einspielbar** ist — und ein Dump mit drei statt dreihundert Schülern spielt
tadellos ein.

`PATH` steht ausdrücklich in der Datei: im Cron ist er sonst kurz, und
`age: command not found` um 04:00 sieht aus wie ein kaputtes Backup und ist
eine fehlende Zeile hier. (Das Python-Werkzeug löst `age` und `pg_restore`
selbst über `which` auf und meldet ein fehlendes Werkzeug als solches — die
Zeile ist der Gürtel dazu.)

`MAILTO` ist nicht Zierde: ein Cron-Job, dessen Ausgabe niemand liest, ist ein
Cron-Job, von dem niemand weiss, dass er seit sechs Wochen scheitert. Die
Werkzeuge geben **1** zurück, wenn eine Sicherung unbrauchbar ist, und **2**,
wenn die Prüfung selbst nicht laufen konnte — beides erzeugt Post.

Für eine **Einzelinstallation** genügt eine Zeile, weil die Sidecar die
Sicherung selbst fährt:

```cron
# Wöchentliche Prüf-Wiederherstellung der Einzelinstallation.
0 4 * * 0 magister cd /opt/magister/apps/api && \
    uv run ../../scripts/magister-cli backup verify \
      --dump "$(ls -t /var/backups/magister/*.dump.age | head -1)" \
      --identity /etc/magister/backup-identity.txt
```

## 11 · Wenn etwas schiefgeht

| Symptom | Wahrscheinliche Ursache |
|---|---|
| Sicherung bleibt auf `running` | Der Prozess ist mittendrin abgebrochen. `.partial` auf dem Share entfernen (auf dem Fileserver), Zeile in der Konsole bleibt als Spur stehen. |
| `status: failed`, „age-Schlüssel“ im Grund | `COCKPIT_BACKUP_AGE_RECIPIENT` fehlt oder ist falsch geformt. Es wurde **nichts** geschrieben — richtig so. |
| `status: failed`, „pg_dump: …“ | Verwaltungszugang oder Schema. `COCKPIT_TENANT_ADMIN_DSN` prüfen. |
| Prüfung meldet „Prüfsumme weicht ab“ | **Vorfall**, nicht Betriebsstörung. Nicht einspielen. Wer hat Schreibzugriff auf den Share? |
| Prüfung meldet „Tabellen fehlen: alembic_version“ | Der Dump kommt aus einer Datenbank ohne Alembic — bei Testumgebungen normal, in Produktion nie. |
| Prüfung meldet „N Audit-Payloads liegen im Klartext vor“ | Sofort nachgehen: der Kundenschlüssel wurde irgendwann nicht angewandt. |
| Export `state: failed`, „UndefinedColumn“ | Die Export-Allowlist passt nicht zum Schema. Der Test `test_every_exported_column_exists` hätte das gefangen — er läuft nur mit `COCKPIT_TEST_MAGISTER_API_DIR`. |
| Mandant antwortet mit 503 nach dem Anlegen | `MAGISTER_TENANT_AUDIT_KEY_<REF>` fehlt auf dem Anwendungsserver. Das Protokoll nennt die Variable. |
| `/offboarding/drop` gibt 409 | Eine der vier Schranken: Export nicht vermerkt, Karenzzeit läuft, zwei gleiche Personen, Kunde nicht im Offboarding. Der Text nennt welche. |
