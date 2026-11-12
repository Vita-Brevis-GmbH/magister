# Runbook · Betrieb im Grossen

> Was ab mehreren Kunden auf einer Installation dazukommt: Lastgrenzen pro
> Kunde, Überwachung der Connector-Flotte und der Umzug eines Kunden auf eine
> eigene Datenbank oder einen eigenen Cluster
> ([ADR-0021](../adr/0021-betrieb-im-grossen.md)).
> Die Migrations-Wellen stehen in
> [mandanten-schema-umzug.md](mandanten-schema-umzug.md); sie gab es schon.
> Status: **gebaut, gegen echtes Postgres geprüft.**

## 1 · Lastgrenzen pro Kunde

### 1.1 Was gilt und wo es gilt

Drei Grenzen hängen an der **Mandantenrolle** in Postgres, gesetzt bei der
Bereitstellung:

| Grenze | Vorgabe | Was sie verhindert |
|---|---|---|
| `statement_timeout` | 30 s | Eine entgleiste Abfrage, die eine Verbindung stundenlang hält. |
| `idle_in_transaction_session_timeout` | 60 s | Eine offene Transaktion, die Sperren hält und Migrationen blockiert. |
| `CONNECTION LIMIT` | 40 | Dass ein Kunde alle Verbindungen des Clusters aufbraucht — dann fallen **alle** aus. Mit Grenze fällt nur er aus. |

An der Rolle und nicht im Anfragepfad, und das ist der Punkt: eine
Rollen-Einstellung gilt auch für das CLI, für den Abgleich, für eine
Wiederherstellung und für den Codepfad, den jemand vergisst.

Nachsehen, was wirklich gilt — die Spalten in der Konsole sind nur, was sie
dorthin geschrieben hat:

```sql
-- Im Magister-Cluster, als Verwaltungsrolle.
SELECT r.rolname, r.rolconnlimit, s.setconfig
  FROM pg_roles r
  LEFT JOIN pg_db_role_setting s ON s.setrole = r.oid
 WHERE r.rolname LIKE 'r_%'
 ORDER BY 1;
```

### 1.2 Eine Grenze ändern

```bash
curl -sS -X PUT https://<management>:4444/api/tenants/<id>/limits \
  -H "X-Magister-Management: $COCKPIT_MANAGEMENT_MARKER" \
  -H 'Content-Type: application/json' \
  --cert operator.pem --key operator-key.pem \
  -d '{"statement_timeout_ms": 60000,
       "idle_in_transaction_ms": 60000,
       "connection_limit": 40,
       "reason": "Jahresauswertung des Kunden braucht länger"}'
```

Alle drei Werte sind Pflicht: wer eine behalten will, schickt ihren aktuellen
Wert mit. Ein Formular, in dem weggelassene Felder etwas anderes heissen als
leere, ist eines, in dem man aus Versehen eine Grenze aufhebt.

**Es gibt kein „unbegrenzt“.** Die Untergrenzen sind nicht Bürokratie: ein
`connection_limit` unter zehn liegt unter Pool plus Overflow eines einzigen
Anwendungsprozesses und sperrt den Kunden im Normalbetrieb aus.

Und: **beides oder keines.** Scheitert das `ALTER ROLE`, wird die Änderung
nicht gespeichert und die Antwort ist ein 503 mit Begründung. Eine Zeile, die
eine Grenze behauptet, die in Postgres nicht gilt, wäre schlechter als keine
Angabe.

### 1.3 Die Decke in der Anwendung

Zusätzlich hat jeder Kunde eine **Decke für gleichzeitige Anfragen je
Prozess**: darüber gibt es 503 mit `Retry-After: 2` — für ihn, nicht für die
anderen. Die Vorgabe ist abgeleitet (`tenant_pool_size + tenant_max_overflow`
plus Spielraum) und mit `MAGISTER_TENANT_MAX_CONCURRENT` überschreibbar.

Bei mehreren Containern ist die wirksame Grenze ein Vielfaches davon — eine
prozessübergreifende Zählung bräuchte gemeinsamen Zustand (Redis), und den
will der Anfragepfad nicht.

| Symptom | Ursache | Antwort |
|---|---|---|
| Einzelne Anfragen eines Kunden enden in 503 `too_busy` | Decke erreicht | Im Log steht `über der Nebenläufigkeits-Decke`. Passiert es regelmässig, ist entweder die Decke zu niedrig **oder** dieser Kunde braucht eine eigene Datenbank (Abschnitt 3). |
| Abfragen brechen nach 30 s ab | `statement_timeout` | Für diesen Kunden heben (1.2) — aber erst nachsehen, **welche** Abfrage. Ein Timeout ist selten die Ursache. |
| „too many connections for role“ | `CONNECTION LIMIT` | Pool-Grössen mal Prozesse rechnen; entweder Grenze hoch oder Pools runter. |

## 2 · Die Connector-Flotte überwachen

### 2.1 Der Alarm ist ein Exit-Code

Magister alarmiert nicht selbst — kein SMTP, keine Webhooks. Eine zweite
Alarmierung neben der, die im Betrieb schon läuft, ist eine, die niemand
pflegt und die dann in der Nacht schweigt, in der sie zählt.

```bash
# Auf dem Konsolen-Host. 0 = in Ordnung, 1 = Warnung, 2 = kritisch.
cd /opt/cockpit/src/cockpit/api
uv run python -m cockpit_api.cli.fleet_check
```

In die Überwachung (Icinga, Zabbix, Nagios — alle lesen diese Codes):

```
# /etc/cron.d/magister-fleet-check  — oder als Check-Kommando
*/15 * * * * cockpit cd /opt/cockpit/src/cockpit/api && \
  uv run python -m cockpit_api.cli.fleet_check --quiet
```

`--json` für maschinenlesbare Ausgabe, `--quiet` für nur die
Zusammenfassung. Die Zusammenfassung steht **zuerst**: viele
Überwachungssysteme schneiden nach der ersten Zeile ab.

Dieselben Befunde zeigt die Konsole oben in der Flotten-Ansicht, und
`GET /api/fleet/findings` liefert sie mit demselben `worst`-Wert.

### 2.2 Was einen Befund auslöst

| Befund | Schwelle | Warum diese Schwelle |
|---|---|---|
| `renewal_overdue` | Zertifikat läuft in ≤ 28 Tagen ab | Der Agent erneuert **30 Tage** vorher und prüft täglich. Weniger als 28 Tage heisst nicht „läuft bald ab“, sondern **die Erneuerung findet nicht statt**. Ab 7 Tagen kritisch. |
| `certificate_expired` | abgelaufen | Der Agent kommt nicht mehr herein; Passwort-Resets bei diesem Kunden scheitern. Neu anmelden mit Einmal-Token. |
| `agent_silent` | > 1 Stunde still (> 24 h kritisch) | Der Agent meldet sich im Minutentakt. Die 5 Minuten aus `STALE_AFTER` sind für das Wartungsbanner der Anwendung — als Alarmschwelle wären sie zu zappelig, ein Neustart des Kundenservers würde nachts wecken. |
| `agent_never_seen` | > 36 h nach dem Anlegen kein Kontakt | Das Einmal-Token verfällt nach 24 Stunden. Danach ist es ein Onboarding, das hängen blieb: Paket nicht installiert, oder TCP 46200 ist zu. |
| `agent_version_behind` | hinter dem höchsten Stand der Flotte | Updates laufen automatisch (Entscheid E10). Wer zurückhängt, während die anderen weiter sind, hat ein stehen gebliebenes Update. Verglichen wird gegen die **eigene Flotte** und nicht gegen eine konfigurierte Sollversion — eine zweite Zahl würde mit der Wahrheit auseinanderlaufen. |
| `tenant_without_agent` | aktiver Kunde ohne Agenten | Bei ihm ist kein Passwort-Reset möglich. |

Widerrufene Agenten erzeugen keine Befunde: ein widerrufenes Zertifikat läuft
ab, ohne dass es jemanden angeht, und ein widerrufener Agent, der still ist,
ist die Absicht.

## 3 · Ein Kunde zieht um (eigene Datenbank, eigener Cluster)

**Es gibt keinen Umzugs-Knopf, und das ist ein Entscheid** (ADR-0021 D5): ein
Assistent müsste zwei Cluster, ein Wartungsfenster, eine Prüfung und einen
Rückweg in sich tragen — und wäre der Knopf, der ein halb umgezogenes Schema
hinterlässt. Der Umzug ist selten und teuer; was er braucht, ist eine geübte
Anleitung.

Was die Konsole dazu kann, ist **eine** Sache: den Verweis ändern.

### 3.1 Vorher

- Zielcluster steht, `pgcrypto` ist dort vorhanden, die Verwaltungsrolle hat
  `CREATEROLE` und `CREATE`.
- Wartungsfenster abgestimmt. Rechne mit der Dauer eines Dumps plus einer
  Wiederherstellung — bei einem Schulschema Minuten, nicht Stunden.
- Der **private** Backup-Schlüssel liegt auf dem Backup-Host; dort läuft die
  Wiederherstellung (ADR-0016 D2). Nicht auf dem Anwendungsserver.

### 3.2 Ablauf

```bash
# 1. Sperren. Die Datenebene bedient den Kunden danach mit 503 und einem
#    Grund, den er sieht.
curl -sS -X POST .../api/tenants/<id>/suspend \
  -d '{"reason":"Umzug auf eigenen Cluster, heute 22:00-23:00"}'

# 2. Sichern — die normale Sicherung, verschlüsselt.
curl -sS -X POST .../api/tenants/<id>/backups -d '{"kind":"manual"}'

# 3. Im Zielcluster Rolle und Schema anlegen (wie im Onboarding) und den
#    Dump einspielen. Auf dem BACKUP-HOST, dort liegt der private Schlüssel:
age -d -i /etc/magister/backup-identity.txt <datei>.dump.age \
  | pg_restore --no-owner --no-privileges --exit-on-error \
      --dbname=postgresql://mgadmin@ziel/magister

# 4. Grenzen im Ziel setzen (sie hängen an der Rolle, und die ist neu):
curl -sS -X PUT .../api/tenants/<id>/limits \
  -d '{"statement_timeout_ms":30000,"idle_in_transaction_ms":60000,
       "connection_limit":40,"reason":"neu angelegte Rolle im Zielcluster"}'

# 5. Den DSN des neuen Verweises in der Datenebene hinterlegen — dort und
#    nur dort: MAGISTER_TENANT_DSN_<REF> in der .env des Anwendungsservers.

# 6. Verweis umstellen. Nur bei GESPERRTEM Kunden; die Route weist einen
#    aktiven ab.
curl -sS -X POST .../api/tenants/<id>/relocate \
  -d '{"dsn_ref":"zielcluster","isolation_mode":"cluster",
       "reason":"Kunde wächst, eigener Cluster"}'

# 7. Anwendungsserver neu starten (oder auf den Registry-Abruf warten) und
#    migrieren, damit der Stand gemeldet wird:
cd apps/api && export MAGISTER_BACKUP_AGE_RECIPIENT=age1…
uv run ../../scripts/magister-cli tenants migrate \
    --dump-dir /srv/backup/magister/pre-migration --only <slug>

# 8. Entsperren.
curl -sS -X POST .../api/tenants/<id>/unsuspend
```

### 3.3 Woran man sieht, dass es angekommen ist

Der Umzug **löscht den gemeldeten Schemastand** in der Konsole. Das ist
Absicht: er war eine Messung an der alten Ablage. Die nächste Meldung der
Datenebene (Schritt 7) ist damit der Beleg, dass der Umzug wirklich
angekommen ist — bis dahin steht in der Konsole ehrlich „nie gemeldet“.

```sql
-- In der Konsolen-Datenbank.
SELECT slug, dsn_ref, isolation_mode, schema_version, schema_version_reported_at
  FROM tenants WHERE slug = '<slug>';
```

Steht dort nach Schritt 7 eine Revision **und** ein Zeitstempel, ist der
Kunde im Ziel. Steht dort `NULL`, hat die Datenebene den neuen Verweis nicht
auflösen können — dann fehlt Schritt 5.

### 3.4 Der Rückweg

Die alte Ablage wird **nicht** sofort gelöscht. Schema und Rolle im
Quellcluster bleiben mindestens bis zur nächsten geprüften Sicherung im Ziel
stehen; der Rückweg ist dann derselbe Ablauf mit vertauschten Enden
(Verweis zurückstellen, alte `.env`-Zeile wieder aktiv).

Erst danach im Quellcluster aufräumen — und dann über den Offboarding-Weg
(ADR-0016 D7), nicht mit `DROP SCHEMA` von Hand.

## 4 · Was noch offen ist

- **Wellen von Wellen.** Der Kanarienvogel-Halt verlangt einen Menschen. Bei
  zwanzig Kunden ist das richtig, bei zweihundert braucht es Gruppen — und
  das ist dann ein neuer Entscheid (ADR-0021, Preis).
- **Ein Betriebswert, keine Technik:** wie viele Verbindungen ein Kunde
  tatsächlich braucht. Die Vorgabe 40 trägt acht Anwendungsprozesse; ob das
  passt, zeigt der erste Monat mit mehreren Kunden.
