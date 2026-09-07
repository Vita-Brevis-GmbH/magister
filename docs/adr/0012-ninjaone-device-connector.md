# ADR-0012 — NinjaOne-Geräte-Connector (Daten lesen + Scripts starten)

- **Status:** Accepted (Phase A umgesetzt; Phase B/C offen)
- **Datum:** 2026-09-07
- **Kontext-Modul:** `devices`

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
   (`client_id`/`client_secret`) liegen **verschlüsselt in `app_settings`**
   (pgcrypto, wie `ad_bind_password`) und verlassen den Server nie; nichts davon
   wird geloggt. HTTP über `httpx.AsyncClient` mit `transport`-Injektionsnaht
   für Tests (gleiches Muster wie `AdRpcClient`).
2. **Verknüpfung** über eine neue, nullable, unique Spalte `devices.ninja_device_id`
   (die numerische Ninja-ID als dauerhafter Anker).
3. **Matching:** Hostname zuerst (`Device.name` ↔ `systemName`/`dnsName`,
   Domain-Suffix entfernt, case-insensitiv), dann Seriennummer. Ein Treffer auf
   **mehrere** Ninja-Geräte gilt als **ambig** → kein Auto-Link, manuell zuweisen.
4. **Read-only bleibt read-only**, Script-Start ist eine schreibende Operation →
   **Audit-Event Pflicht**, RBAC am Endpoint (`require_smi`), `school_id`-Scope.
5. Ausgeführt werden **Bibliotheks-Scripts** aus dem NinjaOne-Katalog, kein
   Ad-hoc-Code-Upload (NinjaOne-Sicherheitsmodell).

## Phasen

- **Phase A (umgesetzt):** `ninja/client.py` (OAuth-Token-Cache, `list_devices`,
  `get_device`, `run_script`) + `ninja/match.py` (Hostname→Serial), voll
  unit-getestet mit `httpx.MockTransport` — keine echte Instanz nötig.
- **Phase B (offen):** `devices.ninja_device_id` + Migration; `app_settings`
  NinjaOne-Credentials (Modell/Service/Schema/Settings-UI); `NinjaConnectorService`
  (link/unlink/auto-match/status/run-script mit Audit); Router-Endpoints im
  `devices`-Modul; Integrationstests (Postgres-gated, Connector gemockt).
- **Phase C (offen):** Frontend — Ninja-Status + Aktion „Script ausführen" auf
  der Geräte-Detailseite; Admin-Settings-Felder für die Credentials.

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
