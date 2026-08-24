# ADR 0009: Mail-Aliase, editierbare Vorlagen und geführte Namensänderung

**Status:** Vorgeschlagen · 2026-08-24
**Kontext:** M6 — Zusatz-Features für Benutzerverwaltung (Product-Owner-Wunsch)

## Problem

Drei zusammenhängende Lücken in der Benutzerverwaltung:

1. **Nur eine Mailadresse pro Benutzer.** Heute kennt Magister genau ein
   `mail`-Attribut. Schulen/Firmen brauchen aber pro Person mehrere Adressen:
   eine Standard-Adresse (Primär) plus Zusatz-Adressen (Aliase), die in
   Exchange als weitere Empfangsadressen existieren sollen.
2. **Dokumente/Mails sind fest eincodiert.** Eltern-Briefe und Zugangsdaten-
   Handouts werden aus fixen Jinja2-Templates in `magister_api/letters/templates/`
   gerendert; Texte liegen als Konstanten im Code (`LETTER_STRINGS_DE`,
   `_STRINGS`). Ein Betreiber kann Inhalt/Layout nicht ohne Deployment anpassen.
3. **Keine Namensänderung als Vorgang.** Das Attribut-Formular kann einzelne
   Felder ändern, aber eine echte Namensänderung (z. B. nach Heirat) muss
   Nachname, Anzeigename, UPN, Mail und ggf. sAMAccountName **konsistent**
   umstellen — und die alte Adresse als Empfangsadresse erhalten, damit Mails
   nicht ins Leere laufen.

## Entscheidung

### D1 — Mail-Aliase über AD `proxyAddresses` (kein Graph)

Zusatz-Adressen werden als **`proxyAddresses`** ins on-prem-AD-Objekt
geschrieben; **Azure AD Connect** synchronisiert sie nach Exchange Online, das
die Aliase automatisch auf dem Postfach anlegt. Kein direkter Graph-/Exchange-
Online-API-Aufruf — das passt zum bestehenden ldap3-Stack, braucht keine neue
MSAL/Graph-Integration und keine zusätzliche Ausgangs-Netzwerkfreigabe.

- Primär bleibt `mail`. `proxyAddresses` wird bei jeder Änderung als komplette
  Menge geschrieben: `SMTP:<primär>` (Grossschreibung = Primär) plus je
  `smtp:<alias>` (Kleinschreibung = sekundär).
- Magister-Seite: eine neue mehrwertige Cache-Spalte `mail_aliases`
  (`list[str]`, analog zu `ad_groups`) hält **nur die sekundären** Adressen;
  die Primäradresse ist immer `mail`.
- Aliase durchlaufen dieselbe Domain-Allowlist wie `mail`/`upn`.
- AD-Sync liest `proxyAddresses` mit und spiegelt die sekundären Einträge in
  `mail_aliases`, damit extern gesetzte Aliase sichtbar werden.

### D2 — Editierbare Vorlagen in der DB, Fallback auf Built-in

Eine neue Tabelle `document_templates` hält betreiberspezifische Vorlagen
(`key`, `language`, `subject`, `body_html`, `is_active`, Audit-Felder). Der
Renderer bevorzugt eine aktive DB-Vorlage und fällt sonst auf das eingebaute
Jinja2-Template zurück — bestehendes Verhalten bleibt Default.

- Kein SMTP/Versand. Ausgabe weiterhin als PDF (WeasyPrint) bzw. Text; „Mail"
  meint hier den **Inhalt/die Vorlage**, nicht den Transport.
- Sicheres Rendern: Jinja2 **SandboxedEnvironment**, `StrictUndefined`,
  Autoescape; nur ein definierter, dokumentierter Platzhalter-Kontext je
  Template-Key ist verfügbar.
- Admin-only CRUD + Live-Vorschau mit Beispiel-Kontext.
- Scope: Vorlagen sind an `school_id` gebunden (Betreiber-/Schulträger-Ebene),
  mit `school_id IS NULL` als globalem Default — konsistent zur Scope-Engine.

### D3 — Namensänderung als geführter Vorgang

Ein neuer Service `UserRenameService` + Endpoint kapselt die Kaskade in **einem**
auditierten Vorgang (`user_renamed`):

1. Neuer Nachname (+ optional Vorname) → neuer `displayName`, `userPrincipalName`,
   `mail`, `sAMAccountName` nach konfigurierbarem Muster (Vorschlag, editierbar).
2. Die **bisherige** Primäradresse wird automatisch als `smtp:`-Alias in
   `proxyAddresses` behalten (nutzt D1).
3. Alle AD-Writes über die bestehende `modify_user_attributes`-Naht; ein
   Audit-Event mit `changed_keys`.

Zusätzlich wird das Attribut-Formular um **so viele AD-Attribute wie sinnvoll**
erweitert (Titel, Abteilung, Firma, Telefon, Mobil, Büro, Beschreibung,
Personalnummer …) — read/write über dieselbe `PATCH /users`-Naht.

## Konsequenzen

- **Niemals/Immer bleiben gültig:** Aliase/Namensänderung sind schreibende
  Operationen → Audit-Event Pflicht; Domain-Allowlist gilt weiter; LDAPS/
  sealed-signed; kein Attribut-Write ausserhalb der Repository-/AD-Naht.
- `proxyAddresses` als **vollständige Set-Ersetzung** zu schreiben ist bewusst
  gewählt (idempotent, kein Add/Remove-Drift); Magister ist Master der von ihm
  verwalteten Adress-Menge, respektiert aber extern gesetzte Einträge über den
  Sync-Readback.
- Template-Sandbox ist die Sicherheitsgrenze: Betreiber-editierbares HTML darf
  keinen Server-State erreichen; nur der deklarierte Kontext.
- Namensänderung ist zunächst **UPN/Mail/sAMAccountName-Vorschlag**; die
  Anmelde-Kontinuität (altes UPN als Alias) deckt D1 ab.

## Umsetzung (Slices, je einzeln lieferbar)

- **A — Mail-Aliase (proxyAddresses):** AD-Client-Write, `mail_aliases`-Spalte +
  Migration, Schema/Service/Sync-Readback, API + UI. *Grundlage für C.*
- **B — Editierbare Vorlagen:** `document_templates` + Migration, Sandbox-
  Renderer mit Fallback, Admin-CRUD + Vorschau, UI-Editor.
- **C — Namensänderung-Assistent:** erweiterte Attribute, `UserRenameService`
  mit Alias-Erhalt, API + UI-Wizard.
