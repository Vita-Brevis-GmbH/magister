# Runbook · Abnahme-Testplan Plattform (Mandanten, Module, Connector)

Stand 2026-10-05, Zweig `claude/multitenant-capability-planning-t6mygz`.
L-01, L-05 und L-11 sind seit dem ersten Stand dieses Plans behoben; ihre
Fälle sind jetzt gewöhnliche Fälle mit grünem Erwartungswert. Ziel: **alles einmal angefasst haben, bevor der erste
Fremdkunde produktiv geht** — und jeden Fehler so festhalten, dass er sich
nachstellen lässt.

Der Plan ergänzt die bestehenden Prüfungen, er ersetzt sie nicht:

| Ebene | Wo | Was sie abdeckt |
|---|---|---|
| CI | `.github/workflows/*` | Unit-, Router-, Vertrags- und Paket-Tests |
| Prüfer | `scripts/dev-pruefen.sh` (38 Prüfungen) | Trennung, Versions-Schranke, Lastgrenzen, Welle, Flotte, Sonden — **nur gegen die Prozess-Umgebung** (`dev-umgebung.sh`) |
| Dieser Plan | dev01 (Container-Aufbau) + Windows-Testserver + Test-AD | was eine Person, ein Browser, ein echter Agent oder ein echtes AD verlangt |

## 0 · Wie man ihn abarbeitet

- **Reihenfolge einhalten.** Stufe 1 vor Stufe 2 usw.; eine rote Stufe 1 macht
  alles danach wertlos.
- **Der negative Fall ist die Aussage.** Steht bei „Erwartet" eine Ablehnung,
  ist ein Erfolg ein Befund.
- **Ergebnis je Zeile:** ✅ bestanden · ❌ Befund · ⏭ übersprungen (mit Grund).
- **Befund festhalten** als GitHub-Issue mit Titel `[Abnahme <ID>] …` und vier
  Feldern: *Schritt*, *Erwartet*, *Gesehen* (Text, Screenshot, Log-Ausschnitt
  **ohne** Geheimnisse), *Kunde/Rolle/Sprache*.
- Fälle mit **⚠ erwartet rot** sind bekannte Lücken (§11). Sie werden trotzdem
  ausgeführt: bestätigt der Test die Lücke, ist das ✅ für den Plan und ein
  offenes Issue für den Code.

## 1 · Aufbau für den Test

| Was | Wert |
|---|---|
| Plattform-Host | dev01-000-vb, 172.25.12.10, `/opt/magister` |
| Domäne | `dev-mgmt.int.vitabrevis.ch` |
| Konsole | `https://konsole.dev-mgmt.int.vitabrevis.ch:4444` |
| Kunde A | Profil **Schule**, Slug z.B. `thun` |
| Kunde B | Profil **Firma**, Slug z.B. `bern` |
| Kunde C (nur §6) | Profil **neutral**, wird im Test angelegt und wieder gekündigt |
| Windows-Testserver | Mitglied der Test-Domäne, Ausgang TCP 46200 zur Plattform |
| Debian/Ubuntu-VM | für das `.deb` (§5.8) |
| Test-AD | eigene OU-Struktur je Kunde, ein Dienstkonto mit delegierten Rechten |
| Entra | Test-Tenant mit einer App-Registrierung je Kunde |
| Personen | 2 Operatoren (für Vier-Augen-Schritte), je Kunde: Admin, Schulleitung/Abteilungsleitung, Klassenlehrer, Fachlehrer, 3 Schüler |
| Browser | zwei getrennte Profile (oder ein privates Fenster), damit Sitzungen von A und B gleichzeitig offen sind |

Vor dem Start:

```bash
cd /opt/magister && git pull && ./scripts/plattform-aufbau.sh
./scripts/plattform-aufbau.sh status     # beide Stacks laufen, Stufe je Kunde
git log -1 --format=%h                   # im Protokoll notieren
```

## 2 · Stufe 1 — Automatisch

- [ ] **A-01** CI auf dem PR-Kopf: alle Checks grün (heute 12/12).
- [ ] **A-02** Lokal, Datenebene:
  `cd apps/api && uv sync && uv run ruff check && uv run ruff format --check && uv run pyright && uv run pytest`
  — Erwartet: grün; DB-gestützte Tests laufen **mit** Testcluster, nicht übersprungen.
- [ ] **A-03** Lokal, Konsole: dasselbe in `cockpit/api`.
- [ ] **A-04** Lokal, Agent: `cd agent && uv run pytest`.
- [ ] **A-05** Frontends: in `apps/web`
  `pnpm lint && pnpm format:check && pnpm typecheck && pnpm test && pnpm build`,
  in `cockpit/web` `pnpm lint && pnpm build` (mehr Skripte hat sie nicht).
- [ ] **A-06** Skripte: `bash scripts/tests/plattform-konfig.test.sh` — 27/27.
- [ ] **A-07** Prüfer gegen die Prozess-Umgebung (auf einer Entwicklermaschine):
  `./scripts/dev-umgebung.sh up && ./scripts/dev-pruefen.sh` — **38 bestanden, 0 gescheitert**.
- [ ] **A-08** Integrations-Test der Trennung:
  `uv run pytest tests/integration/test_tenant_isolation.py -v` gegen echtes Postgres 16.

## 3 · Stufe 2 — Mandantentrennung

Jeder Fall einmal **A → B** und einmal **B → A**.

- [ ] **M-01** Hostname-Auflösung: `curl -sk https://thun.dev-mgmt.int.vitabrevis.ch/api/me` und für `bern` — je 401 (nicht angemeldet), **nicht** 404.
  Unbekannter Name `https://gibtsnicht.dev-mgmt.int.vitabrevis.ch/api/me` → 404 ohne Hinweis auf die Kundenliste.
- [ ] **M-02** Postgres-Grenze (plattform-auf-einem-host.md §5, Punkt 2):
  `psql -U r_thun … -c 'select count(*) from t_bern.classes'` → *permission denied for schema t_bern*.
  Zusätzlich `select * from information_schema.tables where table_schema='t_bern'` als `r_thun` → **leer**.
- [ ] **M-03** `SET ROLE r_bern` als `r_thun` → abgelehnt.
- [ ] **M-04** Sitzungs-Übertrag: als Admin bei A anmelden, Session-Cookie kopieren,
  mit `curl -H "Cookie: …" https://bern…/api/me` → **401**.
- [ ] **M-05** Daten: in A eine Klasse „TEST-A" anlegen, in B eine Abteilung „TEST-B".
  Weder Name noch Id taucht beim jeweils anderen auf (Liste, Suche, Berichte, Export, Audit).
- [ ] **M-06** Fremde Id raten: GUID eines Benutzers aus A in der URL von B
  (`/users/<guid>`) → 404, nicht 403 (keine Bestätigung, dass es ihn gibt).
- [ ] **M-07** Audit-Schlüssel je Kunde: Audit-Liste in A und B lesbar;
  `MAGISTER_TENANT_AUDIT_KEY_<REF>` von A testweise entfernen, Stack neu starten →
  A meldet den fehlenden Schlüssel, **B läuft unverändert**. Schlüssel zurück.
- [ ] **M-08** Versions-Schranke: in der Konsolen-DB `schema_version` von A auf `0001_alt`
  → nach ≤ 1 min A = 503 `maintenance`, B = normal. Zurücksetzen.
- [ ] **M-09** Kunde sperren (Konsole) → A = 503, B unberührt; entsperren → A wieder da, Sitzungen gelten wieder oder verlangen neue Anmeldung (Verhalten notieren).
- [ ] **M-10** Lastgrenzen in der Konsole setzen (15000 ms, 20 Verbindungen),
  in `pg_roles` gegenlesen (`rolconnlimit`, `rolconfig`); eine absichtlich lange Abfrage als `r_thun` bricht nach 15 s ab.
- [ ] **M-11** Konsole ausgefallen (`docker compose … stop api` im Konsolen-Stack):
  beide Kunden arbeiten weiter (Anmeldung, Liste, Klasse anlegen). **Ausnahme**, dokumentiert: alles, was über den Connector geht (AD-Abgleich, PW-Reset), meldet `connector_console_unreachable` sauber statt zu hängen.
- [ ] **M-12** Rollenpasswort drehen (Konsole) → Kunde läuft nach dem Nachladen der Registry weiter; altes Passwort funktioniert nicht mehr.
- [ ] **M-13** Umzug auf andere Ablage (Konsole, nur gesperrt möglich): bei aktivem Kunden steht die Begründung statt des Formulars; nach dem Umzug Daten vollständig, Trennung (M-02) hält auch dort.
- [ ] **M-14** Migrationswelle: `magister-cli tenants migrate --canary thun --canary-only`
  → verschlüsselter Dump je Kunde (`age-encryption.org/v1`), Halt nach dem Kanarienvogel; Kundenprotokoll zeigt `schema_migrated`. Ohne `MAGISTER_BACKUP_AGE_RECIPIENT` → Abbruch **vor** jeder Änderung.

## 4 · Stufe 3 — Konsole

### 4.1 Anmeldung (ADR-0020/0023)

- [ ] **K-01** Ohne Client-Zertifikat, falls verlangt: Handshake scheitert; mit Passwort-Weg: Anmeldeseite erscheint.
- [ ] **K-02** Richtiges Passwort, falsches TOTP → abgelehnt; falsches Passwort und unbekannter UPN → **dieselbe** Meldung.
- [ ] **K-03** Fünf falsche Passwörter → 15 min gesperrt; der sechste Versuch mit richtigem Passwort scheitert ebenfalls.
- [ ] **K-04** Nach Passwort, ohne TOTP: Zwischenstand verfällt nach 10 min; kein API-Aufruf ausser TOTP möglich.
- [ ] **K-05** Erstanmeldung eines neuen Operators: TOTP-Einrichtung erzwungen; Wiederherstellungscodes einmal angezeigt.
- [ ] **K-06** `plattform-aufbau.sh operator --reset-mfa` → nächste Anmeldung verlangt neue Einrichtung; Operator abschalten → nächste Anfrage 401.
- [ ] **K-07** Abmelden, dann alte Sitzung per Cookie wiederverwenden → 401.

### 4.2 Kundenlebenszyklus

- [ ] **K-10** Kunde C anlegen (Profil neutral): Bereitstellungsauftrag läuft alle fünf Schritte; Abbruch simulieren (Postgres kurz stoppen) → „weiterführen" setzt am richtigen Schritt fort, ohne Doppel-Schema.
- [ ] **K-11** Slug-Prüfung: Grossbuchstaben, Umlaute, Bindestrich, Ziffer am Anfang → abgelehnt mit Feldname in der Meldung.
- [ ] **K-11a** Hostname `konsole.dev-mgmt.int.vitabrevis.ch`, `connect.…`, ein Name mit `_`, eine IP, ein Name ausserhalb der Plattform-Domäne (`kunde.example.com`) und einer zwei Ebenen darunter (`a.thun.dev-mgmt…`) → je 422 mit Begründung, nichts angelegt. Voraussetzung: `COCKPIT_TENANT_DOMAIN` steht in `cockpit/deploy/.env` (setzt `plattform-aufbau.sh` seit L-11 selbst).
- [ ] **K-12** Kunde C erscheint im Registry-Feed, Hostname antwortet nach ≤ 1 min.

### 4.3 Soll-Zustand: Einstellungen, Rechte, Vorlagen

Die Einstellungen eines Kunden haben seit ADR-0024 einen Reiter
(Kunde → „Einstellungen"); die Rechte-Matrix und die Plattform-Vorgaben noch
nicht (§11, L-02) — dafür die API (`PUT /api/platform/settings`,
`GET /api/tenants/{id}/desired-state`).

- [ ] **K-19** Zustand: Kunde → Übersicht → „Zustand der Installation" zeigt eine Meldung jünger als 5 Minuten, Abgleich „in Ordnung", Profil wie in der Konsole. Datenebene anhalten → nach 15 Minuten der Hinweis „seit … keine Meldung".
- [ ] **K-19a** Reiter „Einstellungen": Entra (Tenant-Id, Client-Id) speichern → Umleitungs-URI `https://<host>/api/auth/callback` wird angezeigt und mitgespeichert; nach dem Abgleich meldet sich ein Benutzer aus `bootstrap_admins` über Entra an.
- [ ] **K-19b** Client-Secret versiegeln → Antwort und Konsolen-DB enthalten den Klartext **nicht** (`select ciphertext from tenant_sealed_secrets`); Zustand wechselt auf „angekommen"; Anmeldung über Entra funktioniert. Ohne Meldung der Installation → 409.
- [ ] **K-19c** AD-Suchbasis im Reiter setzen → Zustand „AD eingerichtet: ja", AD-Sync im Kundenportal läuft durch. Ohne Suchbasis zeigt das Kundenportal gehostet „pflegt Vita Brevis" statt „oben eintragen".

- [ ] **K-20** Plattform-Vorgabe setzen (z.B. `ad_sync_interval_minutes`) → beide Kunden übernehmen sie; im Kundenprotokoll `settings_pushed` mit alt/neu.
- [ ] **K-21** Abweichung bei A setzen → nur A ändert sich; `desired-state` zeigt `settings_source: tenant`.
- [ ] **K-22** Unbekanntes Feld oder Feld mit Geheimnis-Namen (`ad_bind_password`) → Konsole lehnt ab, Feldname in der Meldung.
- [ ] **K-23** Zweiter Abgleich ohne Änderung schreibt **nichts** (kein neues Audit-Ereignis).
- [ ] **K-24** Rechte-Matrix global ändern → wirkt bei beiden; eigene Matrix bei B → ersetzt die globale bei B **ganz**.
- [ ] **K-25** Plattform-Capability (`platform.*`) in eine Kundenrolle schreiben → verworfen und protokolliert.
- [ ] **K-26** Globale Vorlage veröffentlichen, Zielgruppe „Firma" → nur B bekommt sie; A nicht. Neue Fassung → Hinweis „neue globale Fassung" beim Kunden-Admin, verschwindet erst nach Quittung.
- [ ] **K-27** Vorlage mit Jinja-Ausbruch (`{{ ''.__class__.__mro__ }}`) → nicht materialisiert, Grund in `rejected_templates`.

### 4.4 Operator-Zugriff (ADR-0019)

- [ ] **K-30** Einlöseschein ohne Grund oder < 10 Zeichen → keiner.
- [ ] **K-31** Schein nach 61 s einlösen → abgelehnt; zweimal einlösen → zweites Mal abgelehnt.
- [ ] **K-32** Eingelöst: Kundenprotokoll `operator_access_started` **mit Namen**; **jeder** angemeldete Benutzer des Kunden sieht den Hinweisbalken; Liste „Zugriffe von Vita Brevis" zeigt den Eintrag.
- [ ] **K-33** Operator-Sitzung ist lesend: jede schreibende Methode (Klasse anlegen, PW-Reset) → abgelehnt.
- [ ] **K-34** Schein von A bei B einlösen → abgelehnt. Sitzung endet nach 60 min.

### 4.5 Sicherung, Export, Kündigung

- [ ] **K-40** `pg_dump --version` im Konsolen-Container = 16.x (offener Punkt vom 2026-09-18):
  `$DC exec api sh -lc 'pg_dump --version; pg_restore --version; age --version'`.
- [ ] **K-41** Sicherung von A auslösen → Datei auf dem Share, beginnt mit `age-encryption.org/v1`; ohne Schlüssel nicht lesbar.
- [ ] **K-42** Prüf-Wiederherstellung auf dem Backup-Host (`cockpit_api.cli.verify_backup`) → Prüfabfragen grün, Audit-Payloads mit dem Kundenschlüssel entschlüsselbar.
- [ ] **K-43** Wiederherstellung in der Oberfläche erfassen (Knopf „Wiederherstellen" an der Sicherung) → Prüfer spielt sie ein (Zustand `restored`), Freigabe nur durch eine **zweite** Person, danach „Umschaltung vermerken".
- [ ] **K-47** Tägliche Sicherung: ohne Zutun steht nach `COCKPIT_BACKUP_DAILY_AT` (UTC) je aktivem Kunden genau eine neue Sicherung; ein Neustart der Konsole danach zieht keine zweite.
- [ ] **K-48** Prüfer (`sudo ./scripts/plattform-aufbau.sh backup-pruefer`): Plattform-Seite zeigt sein Lebenszeichen; geschriebene Sicherungen wechseln innerhalb von 5 Minuten auf `verified`. Im laufenden Konsolen-Container liegt **kein** privater Schlüssel (`docker compose exec api ls /run` ohne `backup-age.key`).
- [ ] **K-44** PITR-Übung `scripts/pitr-drill.sh` → Stand vor dem Zeitpunkt zurück, Zeilen danach korrekt nicht.
- [ ] **K-45** Export für A → CSV + Manifest, Prüfsumme stimmt, Download nach Ablauf → 404/410.
- [ ] **K-46** Kündigung von Kunde C: Reihenfolgeschranken (kein Löschen vor Export/Frist) werden durchgesetzt; danach Schema und Rolle weg, Hostname 404, Monatskopien mit `.offboarding` markiert.

### 4.6 Flotte, Rollouts, Überwachung

- [ ] **K-50** `python -m cockpit_api.cli.fleet_check` → Exit-Code passt zu den Befunden; Reiter „Flotte" zeigt dieselben.
- [ ] **K-51** `/healthz/stack` mit Token → JSON; ohne Token → 404.
- [ ] **K-52** PRTG-Sonde der Konsole mit Monitor-Zertifikat → `status`.

### 4.7 Plattform und Wartung (ADR-0024)

- [ ] **K-60** `sudo ./scripts/plattform-aufbau.sh ops-agent`, dann Plattform → „Neu starten": innerhalb von 20 s läuft der Auftrag, Protokoll erscheint, Zustand `success`, bestellt von <eigener UPN>. „Update einspielen" ebenso (git pull + Neubau).
- [ ] **K-61** Im Kundenportal gibt es gehostet keinen Menüpunkt „System"; `POST /api/admin/system/restart` → 404, `POST /api/admin/demo-data/purge` → 404.
- [ ] **K-62** Wartung bei Kunde C: „Aktivitäten zurücksetzen" mit Grund und Kürzel erfassen → nach dem nächsten Abgleich `done` mit Zählern; im Kundenprotokoll steht genau ein Eintrag mit `vita-brevis:<UPN>` und dem Grund. Falscher Kürzel → 422; zweiter offener Auftrag gleicher Art → 409.
- [ ] **K-63** AD-Connector → „Verbindung testen": mit laufendem Agenten „Anmeldung des Dienstkontos gelungen"; Agent gestoppt → Auftrag verfällt mit Hinweis auf Dienst/Port; falsches Bind-Passwort → „Dienstkonto abgewiesen".

## 5 · Stufe 4 — AD-Connector-Agent (echter Agent, echtes AD)

### 5.1 Windows-MSI

- [ ] **C-01** Paket in der Konsole (Kunde A → AD-Connector) herunterladen: neueste Fassung je Plattform oben, ältere aufklappbar.
- [ ] **C-02** `msiexec /i magister-connector-*.msi /l*v install.log` → kein Fehler 1620, Dienst installiert und läuft.
- [ ] **C-03** Deinstallieren und wieder installieren; Upgrade von älterer Fassung → Dienst bleibt angemeldet, keine doppelten Einträge.
- [ ] **C-04** ⚠ erwartet (L-04): SmartScreen-Warnung erscheint, weil das MSI unsigniert ist.

### 5.2 Anmeldung des Agenten

- [ ] **C-10** Einmal-Token aus der Konsole, `endpoint` = Name aus dem Zertifikat → Anmeldung gelingt; Token ein zweites Mal → abgelehnt; Token nach 24 h → abgelehnt.
- [ ] **C-11** `endpoint` als IP-Adresse → `enroll` scheitert mit „Das Zertifikat der Plattform gilt nicht für '<IP>' … an der Firewall liegt es nicht"; **kein** Hinweis auf TCP 46200.
- [ ] **C-12** Port 46200 blockiert → „Keine Antwort von …" bzw. „Verbindung … abgewiesen"; Name nicht auflösbar → „lässt sich nicht auflösen". Fremdes `ca_bundle` → Meldung nennt `ca_bundle`.
- [ ] **C-13** `magister-connector check` auf dem DC in einer **neuen** Eingabeaufforderung als Administrator → Zeilen *Endpunkt* (Warnung bei IP), *Rechte*, *Anmeldung*, *Zertifikat*, *Kanal* (echter TLS-Handshake), *Cockpit* (Konfiguration geholt), *OU-Freigabe* (aus dem Cockpit; eine Freigabe auf `OU=Domain Controllers` erscheint als „VERWORFEN"), *DC* und *AD* (LDAPS mit Kerberos-Anmeldung). Kein Passwort wird abgefragt oder angezeigt.
- [ ] **C-13a** Nach Deinstallation ist der Ordner wieder aus dem System-PATH entfernt.
- [ ] **C-14** Privater Schlüssel liegt nur auf dem Agenten (Dateirechte: nur SYSTEM/Administratoren); im Download-Paket kein Geheimnis ausser dem Einmal-Token.

### 5.3 Betrieb über den Agenten

- [ ] **C-20** AD-Abgleich (Einstellungen → Systemeinstellungen → „AD synchronisieren") → erwartete Benutzerzahl; zweiter Lauf inkrementell (nur Geänderte).
- [ ] **C-21** PW-Reset an Test-Schüler (generiert und manuell) → Anmeldung am Domänen-PC mit neuem Passwort, Zwangswechsel greift.
- [ ] **C-22** Benutzersuche, Aktivieren/Deaktivieren, Namensänderung (Kaskade UPN/Mail/sAMAccountName, alter Alias bleibt), Mail-Alias hinzufügen.
- [ ] **C-23** Schüler-Provisioning per CSV → Konten in der richtigen OU, Zugangsdaten-PDF.
- [ ] **C-24** **Agent stoppen** → PW-Reset zeigt „AD nicht erreichbar" (503 `ad_unavailable`), kein Hänger, kein 500; Agent starten → geht wieder. Ein verfallener Auftrag wird **nicht** nachträglich ausgeführt.
- [ ] **C-25** Agent in der Konsole widerrufen → nächste Anfrage des Agenten abgelehnt.
- [ ] **C-26** Client-Zertifikat von A auf dem Kanal von B → abgewiesen.
- [ ] **C-27** Methode ausserhalb der Allowlist einschleusen → plattformseitig verweigert.
- [ ] **C-28** Zertifikatserneuerung: Ablauf künstlich nahe setzen (Test-CA) → Agent erneuert selbst, ohne Unterbruch.
- [ ] **C-29** LDAPS: Agent spricht nur Port 636, signed+sealed; Mitschnitt auf dem Agenten-Server zeigt kein Klartext-LDAP.
- [ ] **C-30** Ein Kunde mit kaputtem AD (falsche Suchbasis) hält den Abgleich des anderen nicht auf.

### 5.4 Debian-Paket

- [ ] **C-40** `apt install ./magister-connector_*.deb` → Dienst, Rechte, Anmeldung wie C-10; `apt purge` entfernt Schlüssel und Konfiguration.
- [ ] **C-41** apt-Repository mit GPG-Signatur → `apt update` ohne Warnung; manipulierte `Release` → abgelehnt.

## 6 · Stufe 5 — Modularität (ADR-0008)

Module: Basis (immer an) `platform`, `ad`, `users`, `settings`; schaltbar
`templates`, `classes`, `imports`, `departments`, `reports`, `devices`.

| Modul | Schule | Firma | neutral |
|---|---|---|---|
| templates | an | an | aus |
| classes | an | aus | aus |
| imports | an | an | aus |
| departments | aus | an | aus |
| reports | an | an | aus |
| devices | an | an | aus |

- [ ] **D-01** Je Kunde A/B/C: Navigation zeigt genau die Module der Tabelle; `GET /api/me/modules` stimmt damit überein.
- [ ] **D-02** Abgeschaltetes Modul per API ansprechen (z.B. `GET /api/classes` bei B, `GET /api/departments` bei A) → **404 `module_disabled`**, nicht 403 und nicht 200.
- [ ] **D-03** Lesezeichen auf eine Seite eines abgeschalteten Moduls → saubere Meldung, keine weisse Seite.
- [ ] **D-04** Vokabular: in B heisst es „Abteilung/Mitarbeitende", in A „Klasse/Schüler:innen" — in **allen vier Sprachen**; kein „Schule"/„Klasse" im Firmenprofil (Seiten, Fehlermeldungen, Briefe, PDFs, E-Mail-Vorlagen).
- [ ] **D-05** Basis-Module lassen sich nicht abschalten (Schieber fehlt oder ist gesperrt; API lehnt ab).
- [ ] **D-06** Abhängigkeit: Modul abschalten, von dem ein anderes abhängt → abgelehnt mit Name der Abhängigkeit.
- [ ] **D-07** „Soft off": Modul mit Daten abschalten → Daten bleiben erhalten, nach Wiedereinschalten vollständig da.
- [ ] **D-08** Firmen-MVP bei B: Abteilung anlegen, Leitung zuweisen, Mitarbeitende zuordnen, Onboarding/Offboarding, CSV-Import `company_users`, Berichte.
- [ ] **D-09** Profilwechsel A Schule → Firma → Schule in der Konsole (Kunde → „Profil & Module"): Module und Vokabular folgen nach dem Abgleich, im Kundenprotokoll `settings_pushed`, keine Daten verloren. Einzelnen Modul-Schalter setzen und mit „Profil entscheiden lassen" wieder aufheben.
- [ ] **D-09a** Modul-Schalter für ein Basis-Modul oder ein unbekanntes Modul per API (`PUT /api/tenants/{id}/modules`) → 422.
- [ ] **D-10** Gehostet: Kunden-Admin von A öffnet „Module & Funktionen" → Hinweis „von Vita Brevis verwaltet", Profil-Auswahl und Schalter gesperrt; `PUT /api/admin/modules` → 405 (Route nicht gemountet). Einzelinstallation ohne Konsole: die Seite bleibt bedienbar.
- [ ] **D-11** Split-Betrieb (optional): `docker-compose.editions.yml --profile company` → Abteilungen laufen im eigenen Container, Rest unverändert; unbekannte Modul-Id in `MAGISTER_CONTAINER_MODULES` → Start abgewiesen.

## 7 · Stufe 6 — Fachliche Regression (Kunden-Oberfläche)

Je Rolle einmal durchklicken, **mit Rechte-Gegenprobe**: was die Rolle nicht
darf, ist nicht sichtbar **und** per API abgelehnt.

### 7.1 Schule (Kunde A)

- [ ] **F-01** Anmeldung über Entra (MFA via Conditional Access); Benutzer ohne Gruppe → kein Zugang mit verständlicher Meldung.
- [ ] **F-02** Admin: Schulen, Klassen-CRUD inkl. Soft-Delete, Klassen-Detail und Edit, Zuweisung Schüler/Lehrer mit `valid_from`/`valid_to`, KL-Subrollen (haupt/co/stellvertretung), Fachlehrer mit Fach.
- [ ] **F-03** Bulk: mehrere Schüler in eine Klasse (Teilerfolg mit Rückmeldung je Zeile), Schuljahres-Übergang 3a → 4a mit 3-Stufen-Dialog, Einzelschüler-Übergang.
- [ ] **F-04** Schulleitung: Dashboard-Kennzahlen, Off-Boarding-Queue, Stellvertretungen (Tabs, Widerruf), Benutzer aktivieren/deaktivieren.
- [ ] **F-05** Klassenlehrer: nur eigene Klassen; PW-Reset eigener Schüler; Reset eines fremden Schülers per API → 403/404.
- [ ] **F-06** Fachlehrer: „Meine Schüler", PW-Reset nur für eigene.
- [ ] **F-07** Lehrer: eigenes Passwort ändern (gegen AD).
- [ ] **F-08** CSV-Import: Stage → Diff → Apply; Datei > 10 MiB → 413; kaputtes CSV → Zeilenfehler, nichts angewandt.
- [ ] **F-09** Briefe/PDF (Anmeldung, Klassenwechsel, Passwort-Übergabe) in allen vier Sprachen; editierbare Vorlage mit Live-Vorschau.
- [ ] **F-10** Berichte; Betroffenenauskunft (`/privacy/subject-access/{guid}`) als JSON + CSV, erzeugt selbst ein Audit-Ereignis.
- [ ] **F-11** Audit-Liste: gefiltert, entschlüsselt; jede Mutation aus F-02…F-10 steht drin mit actor, action, target, ip, request_id.
- [ ] **F-12** Per-User-Einstellungen: Sprache/Region/Formate wirken app-weit.
- [ ] **F-13** Geräte (NinjaOne), falls konfiguriert: Liste je Schule gefiltert.

### 7.2 Firma (Kunde B)

- [ ] **F-20** Wie 7.1 für die Firmen-Module (D-08), dazu PW-Reset, Lifecycle, Namensänderung, Mail-Aliase.
- [ ] **F-21** Keine Schul-Seiten, -Texte oder -Briefe erreichbar.

### 7.3 Kunden-Anmeldeseite

- [ ] **F-30** Anmeldeseite in jedem Zustand: lädt / Fähigkeiten nicht abrufbar / kein Anmeldeweg konfiguriert — jeweils eine verständliche Meldung statt nur „Anmeldung / Melde dich…".
- [ ] **F-31** Gehostet: kein lokaler Notzugang, kein direkter AD-Login (`/auth/login/ad` → 404).

## 8 · Stufe 7 — Sicherheit und Querschnitt

- [ ] **S-01** Logs nach einem kompletten Durchlauf auf Geheimnisse durchsuchen:
  ```bash
  $DC logs --no-color > /tmp/konsole.log; docker compose --project-directory deploy/compose logs --no-color > /tmp/daten.log
  grep -EiH 'password=|passwd|bind_password|secret|bearer |authorization:|eyJ[a-zA-Z0-9_-]{10,}|BEGIN (RSA |EC )?PRIVATE' /tmp/*.log
  ```
  Erwartet: **keine** Treffer mit Werten (Feldnamen ohne Wert sind in Ordnung). Agenten-Log auf dem Windows-Server ebenso.
- [ ] **S-02** Jede schreibende Handlung aus Stufe 3–6 hat ein Audit-Ereignis (Stichprobe: 20 Handlungen, 20 Ereignisse).
- [ ] **S-03** Sicherheits-Header auf Kunden- und Konsolen-Origin (CSP, `X-Frame-Options`, `Referrer-Policy`; HSTS nur mit echtem Zertifikat, L-01 aus dem Härtungs-Audit); Cookies `Secure`, `HttpOnly`, `SameSite`.
- [ ] **S-04** Fehlermeldungen in der gewählten Sprache: `Accept-Language: fr` bzw. Benutzerprofil FR/IT/EN → API-Fehler und UI-Texte in dieser Sprache. ⚠ Übersetzungsqualität FR/IT nicht durch Muttersprachler geprüft (L-06); rund 30 Texte stehen noch auf Deutsch.
- [ ] **S-05** Rollen-Matrix-Gegenprobe automatisiert: jeder Endpoint mit jeder Rolle (Fitness-Test in CI) + 5 Stichproben von Hand.
- [ ] **S-06** Rate-Limit an Anmelde- und Reset-Endpunkten des Kunden → 429 nach der Schwelle. Die Konsole begrenzt über die Sperre (K-03), nicht über 429.
- [ ] **S-07** Konsole nur auf interner Adresse/Port 4444 erreichbar; von aussen kein Listener.

## 9 · Stufe 8 — Betrieb

- [ ] **B-01** Update-Weg: `git pull && ./scripts/plattform-aufbau.sh` auf einem laufenden System → keine Unterbrechung länger als der Neustart, Konsole danach erreichbar (Fehler, der zweimal passiert ist).
- [ ] **B-02** Neustart des ganzen Hosts → alles kommt von selbst wieder, Agenten verbinden sich neu.
- [ ] **B-03** Postgres-Neustart während Last → Anfragen scheitern kurz, Pools erholen sich ohne Neustart der API.
- [ ] **B-04** Plattenplatz: WAL-Archiv und Dumps nach einer Woche messen (Reserve 32 GB, E17).
- [ ] **B-05** Runbooks folgen können: eine zweite Person legt mit [kunde-anlegen-konsole.md](kunde-anlegen-konsole.md) und [kunden-onboarding.md](kunden-onboarding.md) einen Kunden an, ohne nachzufragen. Jede Rückfrage ist ein Doku-Befund.

## 10 · Abschluss

Der Stand ist **abnahmefähig für den ersten Fremdkunden**, wenn:

1. Stufe 1–3 vollständig ✅,
2. Stufe 4 (Connector) vollständig ✅ ausser den ⚠-Fällen,
3. Stufe 5–8 ohne ❌ der Schwere „Datenleck", „Trennung", „Geheimnis im Log" oder „Mutation ohne Audit",
4. jede ⚠-Lücke aus §11 entweder behoben oder schriftlich als bewusst akzeptiert vermerkt ist (mit Datum und Namen),
5. die organisatorischen Punkte aus §11 (CA-Zeremonie, Pentest) terminiert sind.

Ergebnis mit Datum, Commit (`git log -1`) und Name in den PR oder ein
Abnahme-Issue schreiben.

## 11 · Bekannte Lücken (Stand 2026-10-06)

| ID | Lücke | Wirkung | Fall |
|---|---|---|---|
| ~~L-01~~ | **Behoben 2026-10-05.** Profil und Module haben gehostet einen Autor: die Konsole (Reiter „Profil & Module"). Beim Kunden ist die Seite nur lesbar, der Schreibweg nicht gemountet. | — | D-09, D-10 |
| L-02 | Konsole hat keine Oberfläche für die Rechte-Matrix und die Plattform-Vorgaben (Einstellungen je Kunde, Profil und Module schon, ADR-0024). | nur per API bedienbar | §4.3 |
| L-03 | Die vier Reset-Eingriffe (ADR-0015 D2) gibt es nur im CLI. | Betrieb braucht Shell | — |
| L-04 | MSI unsigniert (E18 Schritt 2, beim ersten AppLocker-Kunden oder der dritten Windows-Installation). | SmartScreen-Warnung, AppLocker blockiert | C-04 |
| ~~L-05~~ | **Behoben 2026-10-05.** Verbindungsfehler nach Ursache benannt; `check` prüft Kanal und AD-Bind und warnt bei IP-Endpunkt; Installationsordner im System-PATH; INSTALL.txt, README und Beispielkonfiguration verlangen den Zertifikatsnamen. | — | C-11–C-13a |
| L-06 | FR/IT/EN nicht von Muttersprachlern geprüft, einzelne Texte noch deutsch. | nicht produktiv für Romandie/Tessin | S-04 |
| L-07 | Umschalter „auch bei Kunde X berechtigt" (E16, multitenancy.md §9.3) nicht gebaut. | Person mit zwei Kunden meldet sich zweimal an | — |
| L-08 | `dev-pruefen.sh` läuft nur gegen die Prozess-Umgebung, nicht gegen den Container-Aufbau auf dev01. | Stufe 2 auf dev01 von Hand | A-07 |
| ~~L-09~~ | **Behoben 2026-10-06 (ADR-0024 D6).** Tägliche Sicherung in der Konsole, Prüfer als Timer. | — | K-47, K-48 |
| L-10 | Organisatorisch offen: CA-Zeremonie (bis dahin nur Test-CA → kein echter Agent beim Fremdkunden), externer Pentest, Wildcard-Zertifikat. | blockiert ersten gehosteten Fremdkunden | §10 Punkt 5 |
| ~~L-11~~ | **Behoben 2026-10-05.** Hostname wird beim Anlegen auf Form, Plattform-Domäne (eine Ebene) und reservierte Namen geprüft. | — | K-11a |
