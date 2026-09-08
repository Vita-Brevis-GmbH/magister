# Runbook · Kunden über die Konsole anlegen

> Der Bereitstellungs-Auftrag der Konsole
> ([ADR-0013](../adr/0013-mandantenfaehigkeit-control-plane.md) D2): fünf
> Schritte, wiederaufnehmbar, nie halb angelegt.
> Status: **API fertig und gegen echtes Postgres geprüft; Oberfläche folgt.**

## 1 · Voraussetzungen der Konsole

```bash
# in cockpit/deploy/.env
# Verwaltungszugang in den Magister-Cluster: eine Rolle mit CREATEROLE und
# CREATE auf der Datenbank. NICHT eine Mandantenrolle.
COCKPIT_TENANT_ADMIN_DSN=postgresql+asyncpg://magister_admin:<pw>@db:5432/magister
# Alembic-Verzeichnis der Datenebene, für den Migrationsschritt.
COCKPIT_MAGISTER_API_DIR=/opt/magister/apps/api
# Schema mit den Erweiterungen (pgcrypto).
COCKPIT_TENANT_EXTENSION_SCHEMA=public
# Kopf-Revision, auf die ein neuer Kunde gesetzt wird. Muss zu
# magister_api/tenancy/version.py passen.
COCKPIT_EXPECTED_SCHEMA_VERSION=<Kopf-Revision>
```

Fehlt `COCKPIT_TENANT_ADMIN_DSN`, kann die Konsole Kunden **verwalten**, aber
keinen bereitstellen — der Auftrag scheitert im ersten Schritt und sagt das.

## 2 · Kunden anlegen

```bash
curl -sS --cert operator.pem --key operator-key.pem \
     --cacert certs/platform-ca.pem \
     -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
     https://console.magister.ch:4444/api/tenants \
     -d '{"slug":"musterstadt","name":"Gemeinde Musterstadt",
          "hostname":"musterstadt.magister.ch","profile":"school"}'
```

Antwort **201** heisst: alle fünf Schritte durch, Kunde `active`.
Antwort **202** heisst: angelegt, aber der Auftrag ist nicht durch — der Kunde
steht auf `provisioning` und ist **nicht erreichbar**. Das ist die Zusage: nie
halb bedient. `job.last_error` nennt den Grund, `next_step` den nächsten Schritt.

Im Ergebnis steht **einmal** `role_password`. Danach nie wieder: die Konsole
speichert es nicht — nicht in der Datenbank, nicht im Auftragsprotokoll, nicht
im Log. Sofort in den Geheimnisspeicher der Datenebene:

```bash
# in deploy/compose/.env der Datenebene
MAGISTER_TENANT_DSN_TENANT_MUSTERSTADT=postgresql+asyncpg://r_musterstadt:<pw>@db:5432/magister
```

Der Variablenname ist `MAGISTER_TENANT_DSN_` plus der `dsn_ref` aus der Antwort
in Grossbuchstaben. Verloren? `POST /api/tenants/{id}/rotate-role-password`
setzt ein neues — danach **muss** der Geheimnisspeicher nachgezogen werden,
sonst verliert der Kunde die Verbindung.

## 3 · Abgebrochenen Auftrag weiterführen

```bash
curl -sS ... -X POST https://console.magister.ch:4444/api/tenants/$ID/provisioning/resume
```

Macht ab der Abbruchstelle weiter, nicht von vorn. Die Schritte sind trotzdem
alle idempotent — ein Wiederaufnehmen scheitert nicht daran, dass Rolle oder
Schema schon existieren.

Kennt niemand mehr das Rollenpasswort (weil der erste Lauf vor dem
Migrationsschritt abbrach), dreht der Migrationsschritt es neu und gibt es
zurück, statt zu raten. Das Protokoll sagt es: `„… (Passwort neu gesetzt)"`.

## 4 · Sperren und Entsperren

```bash
curl ... -X POST .../api/tenants/$ID/suspend -d '{"reason":"Rechnung offen, Ticket 4711"}'
curl ... -X POST .../api/tenants/$ID/unsuspend
```

Der Grund ist **Pflichtfeld** und für den Kunden sichtbar; Sperren ohne
Begründung ist der Anfang von Willkür. In der Datenbank passiert dabei
**nichts**: Rolle, Schema und Daten bleiben stehen. Sperren ist eine Aussage
über die Bedienung, nicht über den Bestand — sonst wäre Entsperren eine
Wiederherstellung.

Ein Kunde auf `provisioning` lässt sich nicht sperren (409): er ist ohnehin
nicht erreichbar.

## 5 · Wie die Datenebene davon erfährt

```bash
# in deploy/compose/.env der Datenebene
MAGISTER_CONSOLE_REGISTRY_URL=https://console.magister.ch:4444/api/tenants/registry
MAGISTER_CONSOLE_REGISTRY_TOKEN=<Service-Token der Konsole>
MAGISTER_CONSOLE_MANAGEMENT_MARKER=<derselbe Marker wie in der Konsole>
MAGISTER_CONSOLE_REGISTRY_INTERVAL_S=300
```

Die Datenebene holt die Liste beim Start und danach im Intervall und hält sie
im Speicher. **Kein Kunden-Request liest je die Konsolen-Datenbank.**

Die Liste enthält **keine DSNs**, nur Verweise. Ein Abruf gibt also niemandem
Datenbankzugang — auch nicht, wenn Token oder Kanal kompromittiert sind.

Ist die Konsole nicht erreichbar, bleibt der letzte gute Stand gültig und jeder
Kunde läuft weiter. Sichtbar wird es als `WARNING` im Log der Datenebene:

```
Konsolen-Registry nicht übernommen, letzter guter Stand bleibt: <Grund>
```

Das ist kein Betriebsfehler, aber es muss auffallen: bis zur Behebung kommt ein
**neu angelegter** Kunde nicht durch.

Ein Kunde ohne hinterlegten DSN wird beim Übersetzen übersprungen und gemeldet,
nicht als Fehler behandelt — sonst hielte ein unfertiger Eintrag die ganze
Installation an. Er antwortet danach mit 404, was zutrifft: erreichen könnte
man ihn ohnehin nicht.

## 6 · Abnahme eines neuen Kunden

```sql
-- Erwartet: r_<slug>. Steht dort die Verwaltungsrolle, gehören die Tabellen
-- ihr und der Kunde bekommt beim ersten Query "permission denied for table".
SELECT DISTINCT tableowner FROM pg_tables WHERE schemaname = 't_<slug>';

-- Erwartet: false. Ohne dieses REVOKE darf jede Rolle über PUBLIC hineinsehen.
SELECT has_schema_privilege('public', 't_<slug>', 'USAGE');
```

```bash
# Erwartet: 200 mit JSON
curl -s -H "Host: <slug>.magister.ch" https://<plattform>/auth/capabilities
# Erwartet: 404 — unbekannter Hostname verrät nicht die Kundenliste
curl -s -o /dev/null -w '%{http_code}\n' -H "Host: fremd.magister.ch" https://<plattform>/auth/capabilities
```

Der Bereitstellungsschritt prüft `has_schema_privilege` selbst nach und bricht
ab, wenn PUBLIC nach dem `REVOKE` noch Zugriff hat. Die Abfrage hier ist die
Gegenprobe von aussen.

## 7 · Was noch fehlt

- **Anmeldung via OIDC mit Hardware-Schlüssel** (ADR-0013 D2). Braucht eine
  App-Registrierung im Entra-Tenant von Vita Brevis. Bis dahin schützt den
  Zugang der Konsolen-Listener mit Client-Zertifikat
  ([console-listener.md](console-listener.md)) plus Bootstrap- oder
  Service-Token.
- **Eigener Datenschlüssel pro Kunde** (ADR-0013 D9). Der Auftragsschritt
  `data_key` existiert, sagt aber ausdrücklich, dass er übersprungen wird und
  bis auf Weiteres der installationsweite `MAGISTER_AUDIT_KEY` gilt. Kommt mit
  `tenant_secrets`.
- **Die Oberfläche.** Endpunkte und Mockup stehen, die React-Seiten fehlen.
- **`schema_version` nachführen nach einer Migration**: der Runner der
  Datenebene schreibt den neuen Stand nicht in die Konsole zurück. Bis dahin
  nach einem Fleet-Upgrade `COCKPIT_EXPECTED_SCHEMA_VERSION` setzen und die
  Kunden neu bereitstellen bzw. den Wert von Hand pflegen.

## Querverweise

- [ADR-0013](../adr/0013-mandantenfaehigkeit-control-plane.md) — D1, D2, D4, D7
- [console-listener.md](console-listener.md) — der Zugang zur Konsole
- [mandanten-schema-umzug.md](mandanten-schema-umzug.md) — Migrationen im laufenden Betrieb
- [kunden-onboarding.md](kunden-onboarding.md) — der ganze Ablauf mit dem Kunden
