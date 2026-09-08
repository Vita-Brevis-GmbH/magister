# Runbook · Kunden-Onboarding

> Ein neuer Kunde auf der gehosteten Plattform, von der Bestellung bis zum
> ersten Passwort-Reset. Referenz: [ADR-0013](../adr/0013-mandantenfaehigkeit-control-plane.md),
> [ADR-0014](../adr/0014-ad-connector-agent.md), [ADR-0016](../adr/0016-sicherung-wiederherstellung-export.md).
> Status: **Verfahren entworfen, noch nicht ausgeführt.**

Dieselbe Abfolge gilt für eine Installation beim Kunden — dort ist es einfach
der eine Mandant (ADR-0013 D8). Es gibt keinen zweiten Ablauf.

## 0 · Der eine Satz, der Zeit spart

**Die Firewall-Freigabe muss bestätigt sein, bevor der Installationstermin
steht.** Ausgehend `TCP 46200` ist der einzige harte Blocker im ganzen Ablauf,
und es gibt keine Rückfallebene auf 443 (Entscheid E11). Wird das erst am
Termin entdeckt, fällt der Termin aus.

## 1 · Was der Kunde vorbereitet

Diese Liste geht als Dokument an die Kunden-IT, mit Rückmeldung vor dem Termin.

### 1.1 Netz

| Was | Wert |
|---|---|
| Richtung | ausgehend, vom Server mit dem Agenten |
| Ziel | `connect.magister.ch` |
| Port | `TCP 46200` |
| Protokoll | TLS 1.3 mit Client-Zertifikat |
| Eingehend | **nichts** — keine Portweiterleitung, kein NAT, kein VPN |
| Proxy | kein HTTP-Proxy auf diesem Weg (der Agent spricht TLS, nicht HTTP-CONNECT) |

Der Agent braucht ausserdem Sicht auf die eigenen Domänencontroller über
`LDAPS 636` — das ist internes Netz und meist schon gegeben.

### 1.2 Server für den Agenten

- Windows Server (2019 oder neuer) als Dienst, **oder** Linux mit systemd,
  **oder** ein Container-Host.
- Kein eigener Server nötig: ein bestehender Management- oder Applikationsserver
  genügt. Der Agent ist klein und hat keine eingehenden Ports.
- Domänenmitglied, wenn GSSAPI/Kerberos als Bind-Modus gewünscht ist
  (empfohlen — dann liegt kein Dienstkonto-Passwort herum).

### 1.3 AD-Dienstkonto mit delegierten Rechten

Kein Domänen-Admin. Auf den freigegebenen OUs delegieren
(`Active Directory-Benutzer und -Computer` → OU → Objektverwaltung zuweisen):

| Recht | GUID / Hinweis |
|---|---|
| Kennwort zurücksetzen | Erweitertes Recht `00299570-246d-11d0-a768-00aa006e0529` |
| Alle Eigenschaften lesen | auf Benutzerobjekte |
| Kontoeinschränkungen schreiben | für Aktivieren/Deaktivieren (`userAccountControl`) |
| Benutzerobjekte erstellen | nur wenn der Kunde Provisionierung per Import nutzt |
| Mitglied von schreiben | nur wenn Gruppenvorlagen genutzt werden |

Ausdrücklich **nicht** nötig: Domänen-Admin, Schema-Admin, Rechte auf der
Domänenwurzel, Rechte auf privilegierten Gruppen. Der Agent verweigert
Operationen auf `Domain Admins` und Verwandten ohnehin lokal
(ADR-0014 §7).

### 1.4 OU-Struktur

Welche OUs darf der Agent anfassen? Diese Liste kommt in die lokale Konfiguration
des Agenten und ist die Grenze, die auch eine kompromittierte Plattform nicht
überschreitet.

- OU der Schülerinnen und Schüler (bei mehreren Zyklen: je eine)
- OU der Lehrpersonen
- optional OU der Geräte (nur lesend, für die Gerätezuordnung)

### 1.5 LDAPS-Vertrauen

Entweder die Root-CA des Kunden als PEM (dann prüft der Agent gegen sie), oder
ein öffentlich vertrautes Zertifikat auf den DCs. Ungeprüftes LDAPS ist möglich,
aber dann ist der Kanal verschlüsselt und **nicht** authentisiert — nur als
Übergang, mit Vermerk.

### 1.6 Entra ID

- Eigene App-Registrierung im Tenant des Kunden.
- Redirect-URI: `https://<kunde>.magister.ch/api/auth/callback`
- Client-ID und Client-Secret an Vita Brevis (über einen sicheren Kanal, nicht
  per Mail).
- Conditional Access mit MFA für die Gruppe der Magister-Nutzer — Magister
  erzwingt MFA nicht selbst, es verlässt sich auf diese Politik.
- Die UPN der ersten Kunden-Admins.

### 1.7 Stammdaten

Name, Kundennummer, gewünschte Subdomain, Profil (Schule oder Firma),
Sprachen, Standorte mit Adresse, Ansprechpartner IT.

## 2 · Was Vita Brevis macht

In dieser Reihenfolge; jeder Schritt ist auditiert.

1. **Kunde erfassen** in der Konsole: Name, Subdomain, Profil, Trennung
   (Standard: eigenes Schema), Vorlagen-Set, Rechte-Matrix, Module.
2. **DNS-Eintrag** `<kunde>.magister.ch` → Plattform. Das Wildcard-Zertifikat
   deckt ihn ab, es braucht kein eigenes.
3. **Bereitstellung** läuft als Auftrag: Schema, DB-Rolle mit `USAGE` nur auf
   dieses Schema, Alembic auf Kopf-Version, eigener Datenschlüssel, Materialisierung
   von Rechten und Vorlagen. Bricht ein Schritt ab, bleibt der Kunde auf
   `Bereitstellung` und ist nicht erreichbar — nie halb angelegt.
   Bis die Konsole das übernimmt (Phase 2), ist es der Block in §2.1.
4. **Systemeinstellungen** eintragen: OIDC (aus 1.6), AD (DCs, Bind-Modus,
   Such-Basis, LDAPS-Vertrauen aus 1.5), Sync-Intervall.
5. **Agent-Paket** beziehen und mit dem Einmal-Token (24 h) an die Kunden-IT
   übergeben. Das Paket enthält kein Geheimnis.
6. **Standorte anlegen** (oder den Kunden-Admin das tun lassen), OU-Zuordnung
   pro Standort setzen.
7. **Sicherung** prüfen: erster Dump auf dem Share, Aufbewahrung 10 Tage,
   Prüf-Wiederherstellung eingeplant.

### 2.1 Schema und Rolle von Hand (bis Phase 2)

```sql
-- Eine EIGENE ANMELDEROLLE, mit der sich die Anwendung für diesen Kunden
-- verbindet. Nicht eine gemeinsame Rolle, die per SET ROLE wechselt: Postgres
-- prüft SET ROLE gegen den Sitzungsbenutzer, eine gemeinsame Anmelderolle mit
-- Mitgliedschaft in allen Kundenrollen kann daher aus jedem Kunden in jeden
-- anderen wechseln (ADR-0013 D1, Korrektur).
CREATE ROLE r_<slug> LOGIN PASSWORD '<aus dem Passwort-Safe>';

CREATE SCHEMA t_<slug> AUTHORIZATION r_<slug>;
-- Ohne dieses REVOKE darf in Postgres jede Rolle über PUBLIC hineinsehen.
REVOKE ALL ON SCHEMA t_<slug> FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA t_<slug> TO r_<slug>;
```

Dann Registry-Zeile in `MAGISTER_TENANTS` ergänzen (Felder: `slug`, `name`,
`hostname`, `dsn` mit **dieser** Anmelderolle, `db_role`, `schema_name`) und
migrieren:

```bash
cd apps/api
uv run ../../scripts/magister-cli tenants migrate \
    --dump-dir /srv/backup/magister/pre-migration --only <slug>
```

Der Runner migriert mit der Anmelderolle des Kunden — dadurch gehören die
Tabellen ihm. Migriert man stattdessen als Superuser, bekommt die Kundenrolle
beim ersten Query `permission denied for table`.

Gegenprobe, bevor der Kunde freigegeben wird:

```sql
-- Erwartet: r_<slug>
SELECT DISTINCT tableowner FROM pg_tables WHERE schemaname = 't_<slug>';
-- Als r_<slug> verbunden, erwartet: permission denied
SELECT 1 FROM t_<andererkunde>.schools LIMIT 1;
```

Einzelheiten und der laufende Betrieb:
[mandanten-schema-umzug.md](mandanten-schema-umzug.md).

## 3 · Installation beim Kunden (gemeinsamer Termin, ~1 Stunde)

1. Agent installieren, Dienstkonto und OU-Grenzen konfigurieren.
2. Agent starten. Er erzeugt sein Schlüsselpaar **lokal**, löst das Einmal-Token
   ein und erhält Zertifikat plus API-Key.
3. **Fingerprint vergleichen:** die Konsole zeigt den SPKI-Fingerprint des neu
   ausgestellten Zertifikats, der Agent zeigt denselben lokal. Beide vorlesen.
   Stimmen sie nicht, abbrechen.
4. AD-Verbindungstest aus der Konsole (`Verbindung testen`).
5. Ersten AD-Sync auslösen, Benutzerzahl gegen die Erwartung prüfen.

## 4 · Abnahme

Der Kunde ist erst produktiv, wenn alle sechs Punkte grün sind:

- [ ] Anmeldung über Entra funktioniert für einen Kunden-Admin.
- [ ] AD-Sync liefert die erwartete Zahl an Benutzern.
- [ ] Ein Passwort-Reset an einem Testkonto geht durch — der Beweis, dass der
      ganze Weg Konsole → Warteschlange → Agent → LDAPS → AD trägt.
- [ ] Agent stoppen führt zu `503` mit dem Banner „AD nicht erreichbar", nicht
      zu einem Fehler. Agent wieder starten, Reset geht wieder.
- [ ] Erster Dump liegt auf dem Share und ist entschlüsselbar.
- [ ] Der Kunde hat die Liste „Zugriffe von Vita Brevis" gesehen und weiss, dass
      er den Agenten jederzeit stoppen kann.

Punkt 4 ist der wichtigste und wird am häufigsten übersprungen: er zeigt dem
Kunden, dass er die Kontrolle behält, und uns, dass der Ausfall sauber
behandelt wird.

## 5 · Was der Kunde schriftlich bekommt

- Was Vita Brevis sehen kann, was nicht, und wie ein Operator-Zugriff
  protokolliert wird.
- Wiederherstellung: **10 Tage** (Entscheid E14).
- Löschung beim Offboarding: Crypto-Shredding sofort, vollständig nach
  **10 Tagen**.
- Der Not-Aus: Agent stoppen beendet jeden Plattformzugriff auf das AD.
- Auftragsverarbeitungsvereinbarung mit genau diesen Zahlen.

## 6 · Offboarding

1. Kündigung → Status `offboarding` in der Konsole.
2. Export bereitstellen (CSV plus Manifest, zeitlich begrenzter Download).
3. Karenzzeit 30 Tage, damit der Kunde den Export prüfen kann.
4. Agent beim Kunden deinstallieren, Zertifikat und API-Key widerrufen.
5. Schema und DB-Rolle löschen, Datenschlüssel vernichten (Crypto-Shredding).
6. DNS-Eintrag entfernen.
7. Nach **10 Tagen** ist auch der Rest aus den Sicherungen ausgelaufen —
   Bestätigung an den Kunden.

## 7 · Was noch festzulegen ist

1. **Wer führt den Termin?** Ein Techniker allein oder zu zweit (einer redet mit
   der Kunden-IT, einer arbeitet)? Beim ersten Kunden würde ich zu zweit gehen.
2. **Über welchen Kanal** kommen Client-Secret und Einmal-Token? Nicht per Mail.
   Vorschlag: telefonische Durchsage des Tokens, Secret über ein
   passwortgeschütztes Ablagefach mit Ablauf.
3. **Wer ist der Ansprechpartner** bei Vita Brevis nach der Abnahme, und über
   welchen Weg meldet der Kunde eine Störung (Mail, Telefon, Ticketsystem)?
   Die Ticketnummer taucht im Operator-Zugriff auf — es braucht also ein
   System, das Nummern vergibt.
4. **Reaktionszeiten** — was wird zugesagt, wenn ein Agent ausfällt oder ein
   Passwort-Reset nicht geht? Gehört in denselben Vertrag wie die 10 Tage.
5. **Wer pflegt die Kunden-Dokumentation** aus Abschnitt 1 (das Dokument, das
   die Kunden-IT bekommt) — und in welcher Sprache neben Deutsch?
