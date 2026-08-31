# ADR 0011: AD-Service als strikte Grenze + 10-Container-Split

**Status:** Angenommen · 2026-08-31
**Kontext:** Ein Container pro Funktion (Wartbarkeit); „AD Schreiben und Lesen
soll nur ein Modul erledigen, nicht alle."

## Problem

ADR-0008 hat Magister in Module zerlegt, die per `MAGISTER_CONTAINER_MODULES`
als eigene Container laufen können — aber die identitätsnahe Basis steckte bis
dahin in einem einzigen, 20 Router grossen `platform`-Modul. Damit berührte fast
jede Änderung dieselbe Datei, und Active-Directory-Zugriff (Lesen **und**
Schreiben) war über viele Module verstreut: `platform` (User/Passwörter),
`imports`, `classes` (Zyklus-Gruppen) und `departments` (Abteilungs-Gruppen)
riefen alle direkt `AdClient` auf (17 Aufrufstellen). Das widerspricht dem Ziel,
dass **genau ein** Modul mit AD spricht.

Der Product Owner will:

1. Eine feine Modulstruktur mit je eigenem Container: **API (Basis), AD-Service,
   User-Übersicht, Vorlagen, Settings, Geräte, Klassen, Abteilungen, Importe,
   Auswertungen** (10 Container).
2. **Strikte AD-Grenze:** nur der AD-Container hat AD-Zugang; jeder andere
   Container, der AD lesen/schreiben muss, ruft den AD-Container über eine
   interne API.

## Entscheidung

### 1. Feine Module (M1)

Das alte `platform`-Modul wird in vier immer-aktive Basismodule zerlegt —
`platform` (Auth/Session/Schulen/Audit/Privacy), `ad`, `users`, `settings` —
plus ein schaltbares `templates` (Vorlagen: Dokumentvorlagen + Serienbriefe).
Alle AD-nahen Endpunkte liegen unter dem disjunkten Prefix `/ad/*`, damit der
Reverse-Proxy sie eindeutig einem Container zuordnen kann; Dokumentvorlagen
ziehen von `/admin/document-templates` nach `/templates`. Reine Umverteilung,
kein Verhaltensbruch im Monolith.

### 2. Strikte AD-Grenze (M2)

Das `ad`-Modul exponiert eine **interne** HTTP-API (nur im Docker-Netz, vom
Caddy **nicht** nach aussen geroutet) für genau die AD-Operationen, die andere
Module brauchen: Bind/Authenticate (Login), `find_user`, `fetch_user_groups`,
`create_user`, `modify_password`, Attribut-/Rename-/Proxy-/Flag-Writes,
`delete_user_object`, `add_/remove_user_from_groups`.

- **Nur der AD-Container** erhält AD-Credentials (`MAGISTER_AD_*`) und
  Netzverbindung zu den Domänencontrollern. Er ist auch der einzige mit
  `MAGISTER_RUN_SCHEDULER=1` (die wiederkehrende Sync-Leseschleife).
- Jeder andere Container bekommt statt AD-Credentials nur die **AD-RPC-URL** und
  ein **gemeinsames Geheimnis** (`MAGISTER_AD_RPC_URL`, `MAGISTER_AD_RPC_SECRET`).
- `get_ad_client` liefert je nach Konfiguration entweder den echten `AdClient`
  (im AD-Container / Monolith) oder einen **RPC-Client** mit derselben
  Schnittstelle. Die 17 Aufrufstellen bleiben unverändert — sie sehen dieselbe
  `AdClient`-API.
- **Geschäftslogik + Audit bleiben im aufrufenden Container.** Die RPC macht nur
  die reine AD-I/O; Validierung, DB-Schreibvorgänge und das Audit-Event laufen
  weiterhin dort, wo der Request ankommt. LDAP-Fehler werden über HTTP
  serialisiert und im Client in dieselben Ausnahmetypen (`AdUnavailableError`
  etc.) zurückübersetzt, damit Fehlerbehandlung und i18n unverändert greifen.
- **Monolith bleibt möglich:** ist keine `MAGISTER_AD_RPC_URL` gesetzt, spricht
  jeder Prozess wie bisher direkt mit AD (ein Container, Default).

### 3. Topologie (M3)

`scripts/gen_split.py` erzeugt aus der Modul-Registry das Caddy-Routing + ein
Compose-Overlay: ein `magister-api-<modul>`-Service je Container, AD-Creds nur
auf `ad`, RPC-URL+Secret auf den Rest, Scheduler + Migrator genau einmal.
Gemeinsame Postgres-DB (kein Microservice-Datenschnitt) — der Split ist ein
**Deployment**-Split desselben Images, kein verteiltes Datenmodell.

## Konsequenzen

**Positiv**
- Eine Änderung an einer Funktion berührt genau ein Modul/Container.
- AD-Angriffsfläche minimiert: Credentials + DC-Netzweg leben in **einem**
  Container; alle anderen sind AD-credential-frei.
- Genau ein Scheduler, ein Migrator — kein doppelter Sync gegen AD.

**Negativ / Kosten**
- Zusätzlicher Netz-Hop für On-Demand-AD-Writes (interne RPC statt In-Process).
- Ein internes Auth-Geheimnis mehr im Betrieb (`MAGISTER_AD_RPC_SECRET`).
- Mehr laufende Container (RAM/Verbindungen) — vom PO als vernachlässigbar
  eingestuft; Ziel ist Wartbarkeit, nicht Server-Ressourcen.

**Sicherheit**
- Die AD-RPC ist niemals extern erreichbar (kein Caddy-Route), nur im internen
  Netz, und verlangt das gemeinsame Geheimnis. Kein AD-Bind-String, kein
  Passwort wird geloggt (bestehende Niemals-Regeln gelten weiter).
