# ADR 0006 — Schüler-AD-Provisioning über den CSV-Import

**Status:** akzeptiert · **Datum:** 2026-07-03

## Kontext

Bisher liest Magister User per Sync *aus* AD (AD = Source of Truth für
Identitäten, objectGUID als Join-Key). Der CSV-Import verknüpft nur bereits
existierende User mit Klassen. Für die Schuljahres-Ersterfassung braucht die
Schulleitung aber einen Weg, **100+ neue Schüler-Accounts** schnell anzulegen —
inklusive generierter, schülerfreundlicher Passwörter und der Option „Passwort
beim nächsten Login ändern".

## Entscheidung

Ein neuer Import-Typ **`students`** legt beim *Apply* neue **AD-Accounts** an
(`AdClient.create_user`, ldap3 `add` über LDAPS mit dem bestehenden Service-Bind),
setzt das Passwort, aktiviert das Konto und — je nach Flag — `pwdLastSet=0`.
Anschliessend werden ein `ad_user_cache`-Eintrag (kind=student) und eine
`class_membership` erzeugt; der reguläre Sync gleicht später über die
objectGUID ab.

Konkrete Festlegungen:

- **Bind-User:** derselbe AD-Connect-Service-Account (keine neuen Credentials);
  er braucht Anlege- + Passwort-Rechte in den Ziel-OUs.
- **Ziel-OUs** sind in den App-Settings konfigurierbar: Schüler Zyklus 3,
  Schüler „alle anderen" (Zyklus 1/2) und Lehrer. Die Schüler-OU wird aus dem
  **Zyklus der Klasse** (abgeleitet aus `jahrgangsstufe`) gewählt. Fehlt die
  passende OU, wird die Zeile abgelehnt — **kein** Fallback in eine falsche OU.
- **UPN = Mail** (per Policy gleichgesetzt); `sAMAccountName` optional (Default =
  UPN-Lokalteil, ≤ 20 Zeichen); `displayName` separat (Default „Vorname Name").
- **Passwörter** sind lesbar (`Wort-Wort-Zahl` aus kuratierter Wortliste),
  erfüllen aber die AD-Default-Komplexität. Sie werden **einmalig** in der
  Apply-Antwort zurückgegeben (für die Handout-PDFs) und danach verworfen.
- **Niemals persistiert, niemals auditiert:** Die Audit-Payload-Allowlist würde
  einen `password`-Key ohnehin ablehnen; `student_provisioned` loggt nur
  `upn`, `class_name`, `force_change` und die objectGUID.
- **Partial-Success:** wie bei den anderen Importen läuft jede Zeile in einem
  eigenen Savepoint. Eine Credential wird erst nach erfolgreichem Commit in die
  Handout-Liste aufgenommen.

## Alternativen

- **Schul-IT legt Accounts an, Magister verknüpft nur** — verworfen: verliert
  die Passwort-Generierung und den „100 Schüler in einem Schritt"-Nutzen.
- **Provisioning als eigener Endpoint statt Import-Typ** — verworfen: der
  Stage→Diff→Apply-Flow (Vorschau, Fehler pro Zeile, Audit) ist genau das, was
  die Ersterfassung braucht, und ist schon vorhanden.

## Konsequenzen

- Magister schreibt jetzt **anlegend** in AD (nicht mehr nur Passwort/Attribute/
  Enable). Der Service-Account braucht entsprechend erweiterte Rechte in den
  Ziel-OUs; ohne diese schlägt das Anlegen zeilenweise fehl (sichtbar im
  Apply-Ergebnis, nicht als Gesamtabbruch).
- Ein AD-Account kann angelegt werden, während der anschliessende DB-Insert
  fehlschlägt (Netz/DB) → seltener Orphan-Account. Da AD Source of Truth ist,
  holt der Sync ihn nach; der Fall ist im Apply-Ergebnis als „failed" sichtbar.
- Die Passwort-Übergabe erfolgt als PDF (Handout pro Schüler + Klassentabelle),
  siehe Folge-Arbeit (Welle 3).
