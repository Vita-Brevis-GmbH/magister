# ADR 0007 — Optionaler GSSAPI/Kerberos-Service-Bind ans AD

**Status:** akzeptiert · **Datum:** 2026-07-03

## Kontext

Magister bindet den AD-Service-Account bisher per `SIMPLE`-Bind (Bind-DN +
Passwort) über LDAPS. Das Passwort liegt pgcrypto-verschlüsselt in der DB — aus
einem DB-Dump allein nicht lesbar, aber ein reversibles Secret (die App muss es
zur Laufzeit an AD schicken). Gewünscht ist, das Passwort **ganz** aus DB und
Files zu entfernen und von AD verwalten/rotieren zu lassen.

Der Docker-Host ist bereits **AD-integriert (SSSD, domain-joined)** — die
schwierigste Voraussetzung (Kerberos/KDC-Erreichbarkeit) ist erfüllt.

## Entscheidung

Ein **optionaler** Bind-Modus `gssapi` (SASL/GSSAPI, Kerberos) neben dem
bestehenden `simple`. `MAGISTER_AD_BIND_MODE=gssapi` schaltet **alle**
AD-Operationen (Sync, Passwort-Reset, Provisioning) auf Kerberos um; es wird
**kein Bind-Passwort** mehr gelesen. `simple` bleibt Default, damit bestehende
Instanzen unverändert laufen.

- **Credential-Träger:** ein **Keytab** eines regulären AD-Service-Kontos,
  erzeugt/rotiert mit **`msktutil`** auf dem joined Host (bewusst *nicht* gMSA
  — auf Linux/Containern deutlich einfacher, rotiert trotzdem).
- **Ticket:** ldap3/GSSAPI holt die Credentials aus dem Client-Keytab
  (`KRB5_CLIENT_KTNAME`); kein Passwort, kein `kinit`-Zwang im Normalfall.
- **Image:** krb5-Runtime + SASL-GSSAPI-Modul und das optionale `gssapi`-Extra
  sind im API-Image enthalten (Build braucht `libkrb5-dev`); ohne den
  Env-Schalter bleiben sie ungenutzt.
- **Der User-Passwort-Probe-Bind** (manueller Reset) bleibt `SIMPLE` — er
  authentifiziert bewusst *als der Zielnutzer* mit dessen Passwort.

Einrichtung: siehe [Runbook `ad-gssapi-bind.md`](../runbooks/ad-gssapi-bind.md).

## Konsequenzen

- Im `gssapi`-Modus existiert **kein** Bind-Passwort in DB, `.env` oder Logs —
  das Secret ist ein maschinen-gebundener **Keytab** (Modus 600), von AD
  rotierbar. Das ist der pragmatische 90-%-Gewinn gegenüber „Passwort in DB".
- **Kein** vollständig datenträgerloses Setup: der Keytab liegt als File auf dem
  Host. Ein gMSA-Runtime-Retrieval (Passwort nie persistiert) wäre die
  aufwändigere Variante und ist als spätere Option offen.
- Kerberos ist zeitkritisch (NTP) und KDC-abhängig — Fehlkonfiguration äussert
  sich als Bind-Fehler; der `/admin/ad-test`-Endpoint prüft auch den GSSAPI-Bind.
- Getestet werden kann der Modus nur gegen ein echtes AD (kein Mock); die
  Modus-Auswahl (`_service_bind_kwargs`) ist unit-getestet.
