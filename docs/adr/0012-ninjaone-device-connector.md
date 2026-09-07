# ADR-0012 — NinjaOne-Geräte-Connector (Daten lesen + Scripts starten)

- **Status:** Accepted (Phase A + B umgesetzt; Phase C — Frontend — offen)
- **Datum:** 2026-09-07
- **Kontext-Modul:** `devices`

> **Nachtrag (Vorgaben des Auftraggebers):** NinjaOne-**Daten** werden **nie
> persistiert** — sie erscheinen **nur live in der Geräte-Detailansicht**, und
> **nur dort** lassen sich Scripts starten. Deshalb: **keine**
> `ninja_device_id`-Spalte, **kein** gespeichertes Matching. Das Matching läuft
> pro Detailaufruf; das Ergebnis geht nur in die Antwort.
>
> Die Connector-**Credentials** hingegen werden — wie **Entra ID (OIDC)** und
> die AD-Bind-Daten — in der **Admin-Settings-Oberfläche** gepflegt und
> **verschlüsselt in `app_settings`** abgelegt (pgcrypto, wie
> `oidc_client_secret`/`ad_bind_password`); nicht mehr in Env-Vars. Der
> Client-Secret verlässt den Server nie und wird nie zurückgegeben (nur ein
> `…_set`-Flag).

## Kontext

Die von Magister verwalteten Geräte (`devices`-Tabelle, aus der AD-Computer-OU
importiert) sollen mit **NinjaOne** (RMM) verknüpft werden, um pro Gerät
(1) Live-Status/Inventar zu **lesen** und (2) hinterlegte **Scripts/Automationen
zu starten**.

NinjaOne bietet dafür eine ausgereifte **Public API v2**:

- **Auth:** OAuth 2.0 **client_credentials** (App-Typ „API Services /
  machine-to-machine"). Token: `POST https://{region}.ninjarmm.com/ws/oauth/token`.
- **Scopes:** `monitoring` (read-only), `management` (schreibend, **inkl.
  Scripts ausführen**), `control` (Remote-Access, nicht benötigt).
- **Regionen:** eigene Hosts pro Instanz (US/US2/EU/CA/OC). CH-Tenant i.d.R.
  **EU = `eu.ninjarmm.com`** — Token *und* REST teilen den Host.
- **Daten:** `GET /v2/devices` (paginiert), `GET /v2/device/{id}`,
  Device-Custom-Fields, Orgs/Standorte, Webhooks.

## Entscheidung

Ein isolierter Connector im `devices`-Kontext, der genau die AD-Grenze spiegelt:

1. **Nur ein Modul spricht mit NinjaOne** (`magister_api/ninja/`). Credentials
   (`client_id`/`client_secret`) liegen in **Env-Vars** (`config.py`) und
   verlassen den Server nie; nichts davon wird geloggt. HTTP über
   `httpx.AsyncClient` mit `transport`-Injektionsnaht für Tests (gleiches Muster
   wie `AdRpcClient`).
2. **Kein persistentes Matching.** Pro Detailaufruf matcht der
   `NinjaConnectorService` das Magister-Gerät live gegen die NinjaOne-Geräte; das
   Ergebnis (Status + Script-Bibliothek) geht **nur** in die Antwort.
3. **Matching:** Hostname zuerst (`Device.name` ↔ `systemName`/`dnsName`,
   Domain-Suffix entfernt, case-insensitiv), dann Seriennummer. Ein Treffer auf
   **mehrere** Ninja-Geräte gilt als **ambig** → kein Link.
4. **Read-only bleibt read-only** (`GET /devices/{id}/ninja`). Script-Start
   (`POST /devices/{id}/ninja/run-script`) ist eine schreibende Operation →
   **Audit-Event Pflicht** (Script-Inhalt/Parameter werden nicht geloggt), RBAC
   am Endpoint (`require_smi`), `school_id`-Scope. Der NinjaOne-Zielrechner wird
   **serverseitig neu gematcht** — der Client gibt nie eine Ninja-ID vor, ein
   Script kann also nur das tatsächlich zugeordnete Gerät treffen.
5. Ausgeführt werden **Bibliotheks-Scripts** aus dem NinjaOne-Katalog, kein
   Ad-hoc-Code-Upload (NinjaOne-Sicherheitsmodell).

## Phasen

- **Phase A (umgesetzt):** `ninja/client.py` (OAuth-Token-Cache, `list_devices`,
  `get_device`, `list_scripts`, `run_script`) + `ninja/match.py` (Hostname→Serial),
  voll unit-getestet mit `httpx.MockTransport` — keine echte Instanz nötig.
- **Phase B (umgesetzt):** Env-Config (`config.py` `ninja_*` + `ninja_is_configured`);
  `NinjaConnectorService` (live `status` inkl. Script-Bibliothek + serverseitig
  neu-matchender `run_script`), DB-frei und client-injizierbar; Router-Endpoints
  `GET /devices/{id}/ninja` + `POST /devices/{id}/ninja/run-script` mit Audit;
  Unit-Tests (Client, Matching, Connector) mit gemocktem HTTP.
- **Phase C (umgesetzt):** Frontend — Ninja-Status-Panel + Aktion „Script
  ausführen" ausschliesslich auf der Geräte-Detailseite.
- **Konfiguration (umgesetzt):** Credentials in der Admin-Settings-UI,
  verschlüsselt in `app_settings` (wie Entra ID/AD), Alembic 0043.

## Tests

- **Unit** (laufen immer): `test_ninja_client` (Token-Cache/-Refresh, Read, Run,
  Fehler-Mapping, Region-/Config-Guards), `test_ninja_match` (Hostname-Vorrang,
  Serial-Fallback, Ambiguität), `test_ninja_connector` (`resolve_ninja_config`,
  Status-Match, Re-Match-Security beim Run, weicher Ausfall, disabled/unlinked),
  `test_app_settings_schema` (Region-Validator).
- **Integration** (Postgres-gated): `test_device_ninja` (Endpoints: require_smi
  403, 404, disabled→`enabled:false`, Status-Match, Script-Run + Audit ohne
  Klartext, unmatched→409) und `test_app_settings_service::TestNinjaConnector`
  (Verschlüsselung/Redaction/Audit der Credentials). Der Ninja-HTTP-Layer wird
  per `httpx.MockTransport` injiziert — kein echter Tenant nötig.

## Bekannte Punkte / offene Verifikation

Keine Korrektheits-Bugs bekannt; folgende Punkte sind bewusst so und/oder gegen
den echten Tenant zu verifizieren:

1. **Script-Run-Pfad/-Body + `list_scripts`-Pfad** sind unbestätigt (isoliert in
   `ninja/client.py`, siehe oben). `list_scripts` ist best-effort: schlägt der
   Pfad fehl, zeigt das UI ein manuelles Script-ID-Feld statt der Auswahl.
2. **Feld-Einheiten**: `lastContact` wird als Epoch-**Sekunden** interpretiert;
   je nach API-Version könnten es Millisekunden sein — beim ersten echten Abruf
   prüfen.
3. **Performance grosser Tenants**: `status` und `run_script` holen je die volle
   Geräteliste (`GET /v2/devices`) und bauen pro Request einen frischen Client
   (eigener Token-Abruf) — kein Caching über Requests. Für sehr grosse Tenants
   wäre eine Hostname-gefilterte Abfrage (`df`) bzw. ein versionierter Client-
   Cache auf `app.state` (wie beim OIDC/AD-Client) die Optimierung. Bewusst
   zurückgestellt, bis die API-Details bestätigt sind.
4. **Audit-Reihenfolge**: Der Audit-Event für einen Script-Run wird **nach** dem
   erfolgreichen externen Aufruf geschrieben. Bei einem sehr seltenen
   Commit-Fehler danach liefe das Script, ohne dass der Event persistiert wird —
   für eine externe Seiteneffekt-Operation die pragmatische Wahl.

## ⚠️ Gegen den Tenant zu bestätigen

Zwei schreibende Details können je nach API-Version abweichen und sind an *einer*
Stelle in `ninja/client.py` isoliert (`_RUN_SCRIPT_PATH`, `_run_script_body`):

- Pfad `POST /v2/device/{id}/script/run`
- Body-Feldnamen (`id`/`uid`, `runAs`/`credentialId`, `type`)

Token-Endpoint und Geräte-Read (`/v2/devices`, `/v2/device/{id}`) sind stabil.
**Vor Produktiv-Go-live** einmal gegen die echte NinjaOne-Instanz verifizieren.

## Konsequenzen

- **+** Geräte-Detailseite zeigt Live-Status; gezielter Script-Start ohne
  Ninja-Konsole; saubere, testbare Grenze; passt in den strikten Container-Split
  (Connector lebt im `devices`-Container).
- **−** Abhängigkeit von einer externen API (Rate-Limits, Ausfälle) — Reads sind
  best-effort, Fehler werden als `502`-artige Zustände sauber gemeldet.
- **Voraussetzung:** Geräte müssen in NinjaOne enrolled sein und Hostname/Serie
  müssen zwischen AD und NinjaOne übereinstimmen, sonst manuelles Verknüpfen.
