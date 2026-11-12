# Runbook · Schema-Umzug und Mandanten-Migrationen

> Zieht eine bestehende Installation von `public` in ein Mandantenschema um
> und beschreibt danach den laufenden Betrieb: wie Migrationen pro Kunde
> laufen ([ADR-0013](../adr/0013-mandantenfaehigkeit-control-plane.md) D1/D7,
> [ADR-0016](../adr/0016-sicherung-wiederherstellung-export.md) D6).
> Status: **Verfahren gebaut und gegen echtes Postgres geprüft.**

## 1 · Was der Umzug ist und was nicht

`ALTER TABLE ... SET SCHEMA` verschiebt eine Tabelle mitsamt Inhalt, Indizes
und Constraints. Es werden **keine Daten kopiert** — der Umzug ist deshalb
schnell und von der Datenmenge unabhängig. Er braucht aber eine exklusive
Sperre auf jede Tabelle, also einen Moment ohne laufende Anwendung. Rechne mit
Sekunden, plane eine Wartungsminute.

Was der Umzug **nicht** tut: die Rolle anlegen, das Schema anlegen, die Rechte
der Nachbarschemas entziehen. Das ist Onboarding
([kunden-onboarding.md](kunden-onboarding.md)) und bleibt dort, damit ein
Tippfehler im Umzug ein Fehler ist und nicht ein neues leeres Schema.

## 2 · Umzug einer bestehenden Installation

### 2.1 Vorher

```bash
# 1. Dump. Von Hand, weil der Runner die Registry braucht und die gibt es
#    vor dem Umzug noch nicht.
pg_dump --format=custom --file=vor-umzug.dump magister

# 2. Anwendung stoppen. Der Umzug sperrt jede Tabelle exklusiv.
docker compose -f deploy/compose/docker-compose.yml stop api
```

### 2.2 Rolle und Schema anlegen

```sql
-- Eigene Anmelderolle. Das ist die Trennlinie, nicht SET ROLE (ADR-0013 D1).
CREATE ROLE r_default LOGIN PASSWORD '<aus dem Passwort-Safe>';
CREATE SCHEMA t_default AUTHORIZATION r_default;
REVOKE ALL ON SCHEMA t_default FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA t_default TO r_default;

-- pgcrypto bleibt in public: das ist das Erweiterungsschema. Dort darf
-- danach keine Anwendungstabelle mehr liegen.
```

### 2.3 Umziehen

```bash
psql -d magister -v ON_ERROR_STOP=1 \
     -v schema=t_default -v role=r_default \
     -f scripts/schema-move-to-tenant.sql
```

Das Skript läuft in **einer** Transaktion und prüft vorher wie nachher:

| Prüfung | Warum |
|---|---|
| Rolle und Schema existieren | sonst wäre der Umzug ein stiller Neuanfang |
| Ziel-Schema ist leer | ein halb gelaufener zweiter Versuch würde zwei Bestände vermischen |
| `public.alembic_version` existiert | Beleg, dass hier überhaupt eine Magister-Installation liegt |
| nach dem Umzug: `public` enthält keine Tabelle | sonst könnte eine im Mandantenschema fehlende Tabelle über den `search_path` still auf den Rest zurückfallen |

Eigentum geht dabei an `r_default` über. Ohne diesen Schritt gehören die
Tabellen weiter dem Migrationsbenutzer und die Mandantenrolle bekommt beim
ersten Query `permission denied for table` — nachgemessen, nicht vermutet.
Spaltengebundene Sequenzen (`serial`, `identity`) werden dabei ausgelassen:
Postgres lehnt für sie einen eigenen Eigentümer ab, sie folgen ihrer Tabelle.

### 2.4 Registry setzen und starten

```bash
# in deploy/compose/.env
MAGISTER_TENANTS='[{"slug":"default","name":"<Gemeinde>",
  "hostname":"<gemeinde>.magister.ch",
  "dsn":"postgresql+asyncpg://r_default:<pw>@postgres:5432/magister",
  "db_role":"r_default","schema_name":"t_default",
  "schema_version":"<Kopf-Revision>"}]'
MAGISTER_EXTENSION_SCHEMA=public
```

`schema_version` muss der Konstante in `magister_api/tenancy/version.py`
entsprechen. Ein abweichender Wert bedient diesen Kunden mit **503 Wartung** —
das ist der Zweck (ADR-0013 D7): lieber Wartung als eine plausibel falsche
Antwort aus einem Schema, dem eine Spalte fehlt. Ein **leerer** Wert heisst
„noch nie über den Runner migriert" und wird bedient, damit eine bestehende
Installation nach dem Update nicht stillsteht.

### 2.5 Nachher prüfen

```bash
docker compose ... start api
# Auflösung, Zusicherung und Repository in einem Aufruf:
curl -s -H "Host: <gemeinde>.magister.ch" http://localhost:8000/auth/capabilities
# Muss 404 geben — unbekannter Hostname:
curl -s -o /dev/null -w '%{http_code}\n' -H "Host: fremd.test" \
     http://localhost:8000/auth/capabilities
```

```sql
-- Läuft die Anwendung wirklich als Mandantenrolle?
SELECT DISTINCT tableowner FROM pg_tables WHERE schemaname = 't_default';
-- Erwartet: r_default. Steht dort der Migrationsbenutzer, fehlt 2.3.
```

## 3 · Rückweg

Dasselbe Skript mit `-v schema=public`, dann `MAGISTER_TENANTS` leeren. Der
Rückweg ist genauso schnell wie der Hinweg, weil auch er nur verschiebt. Er
kommt nur infrage, solange **keine** Migration im neuen Schema gelaufen ist;
danach ist der Dump aus 2.1 der Rückweg.

## 4 · Laufender Betrieb: Migrationen pro Kunde

```bash
cd apps/api

# Der Vor-Migrations-Dump wird verschlüsselt (ADR-0021 D1). Ohne gültigen
# öffentlichen age-Schlüssel bricht der Runner ab, bevor er einen Kunden
# anfasst — und schreibt keinen Klartext-Dump. Derselbe Wert wie
# COCKPIT_BACKUP_AGE_RECIPIENT; der private Teil liegt auf dem Backup-Host.
export MAGISTER_BACKUP_AGE_RECIPIENT=age1…

# Was steht in der Registry, und wer hängt hinterher?
uv run ../../scripts/magister-cli tenants list

# Erst nur der Kanarienvogel:
uv run ../../scripts/magister-cli tenants migrate \
    --dump-dir /srv/backup/magister/pre-migration --canary-only

# Nach der Prüfung der Rest:
uv run ../../scripts/magister-cli tenants migrate \
    --dump-dir /srv/backup/magister/pre-migration
```

Der Runner macht pro Kunde drei Dinge in dieser Reihenfolge:

1. **Dump ziehen, verschlüsselt** (`pg_dump --schema | age -r …`). Die
   Rückfahrkarte aus ADR-0016 D6. Schlägt der Dump fehl, wird dieser Kunde
   **nicht** migriert. Überspringen geht nur mit `--no-dump`, und das sagt es
   laut. Die Datei heisst `<slug>-<zeit>-pre-migration.dump.age` — ohne
   privaten Schlüssel ist sie nicht lesbar, und der liegt nicht hier.
2. **Kanarienvogel zuerst.** Scheitert er, bleiben alle übrigen unangetastet —
   `--keep-going` gilt für ihn ausdrücklich nicht.
3. **Migrieren mit der Anmelderolle des Kunden**, damit die neuen Tabellen ihm
   gehören.

Reihenfolge des Rollouts: erst migrieren, dann Code ausrollen. Migrationen sind
pro Release **nur erweiternd** (expand/contract über zwei Releases), damit
zwischen den beiden Schritten beide Codestände auf beiden Schemastände laufen.

| Situation | Antwort |
|---|---|
| Kunde hängt eine Revision zurück | Er wird mit 503 bedient. `tenants migrate --only <slug>`. |
| Runner bricht beim dritten von zwanzig ab | Die ersten zwei sind migriert, die restlichen siebzehn unangetastet. Ursache beheben, Runner erneut starten — die bereits migrierten meldet er als „schon auf dem Kopfstand". |
| `pg_dump` fehlt im Container | Der Runner sagt es und migriert nicht. `postgresql-client` nachinstallieren, nicht `--no-dump` nehmen. |
| Migration im Kundenschema gescheitert | Dump aus dem `--dump-dir` zurückspielen, und zwar **in ein neues Schema**, nie über die Produktion (ADR-0016 D7). Er ist age-verschlüsselt: `age -d -i <identity> <datei> \| pg_restore …`, also auf dem Backup-Host, wo der private Schlüssel liegt. |
| `age` fehlt oder der Empfänger ist nicht gesetzt | Der Runner bricht ab, bevor er einen Kunden anfasst, und schreibt **keinen** unverschlüsselten Dump. `age` nachinstallieren beziehungsweise `MAGISTER_BACKUP_AGE_RECIPIENT` setzen. |

## 5 · Was noch fehlt

- **Registry aus der Konsole** statt aus `MAGISTER_TENANTS` (Phase 2). Bis
  dahin ist ein neuer Kunde ein Eintrag in der Env und ein Neustart.
- **`schema_version` automatisch nachführen:** der Runner migriert, schreibt
  den neuen Stand aber nicht in die Registry zurück — die liegt in der
  Umgebung und ist von aussen gesetzt. Heute also von Hand mitpflegen; mit der
  Konsolen-Registry macht der Runner es selbst. Bis dahin ist der leere Wert
  der sichere Default, weil er bedient statt zu sperren.
- **Automatische Prüfung des Erweiterungsschemas** im laufenden Betrieb: der
  Umzug prüft einmal, dass in `public` keine Anwendungstabelle liegt; eine
  wiederkehrende Kontrolle dafür gehört in die Konsole.
