# ADR-0025 · Anmeldung über den Keycloak-Realm des Kunden

**Status:** Akzeptiert (2026-11-13)
**Kontext:** [ADR-0013](0013-mandantenfaehigkeit-control-plane.md) D5 (Anmeldeweg
des Kunden: OIDC gegen Entra), [ADR-0015](0015-authentisierungs-haertung.md)
(„Was bleibt: OIDC gegen Entra und das lokale Notkonto"),
[ADR-0017](0017-systemeinstellungen-und-rechte-in-der-konsole.md) (Politik aus der
Konsole), [ADR-0024](0024-betrieb-aus-der-konsole.md) D3 (versiegelte
Geheimnisse), Cockpit ADR 0007 („Magister meldet über den Realm des Kunden an,
eingerichtet vom Cockpit")

Entscheid des Produktverantwortlichen, wörtlich:

> „Alle User sollen über Keycloak, man kann im Keycloak Lokale, Entra oder LDAP
> machen, aber die User sind immer dort, dies muss umgebaut sein. Nur das Login
> ändern. Entra wurde in Magister noch nie eingesetzt und nicht getestet. AD und
> Entra Sync für das Login nicht mehr im Magister. Grundsetup und
> Rollenverteilung soll im Cockpit geschehen, durch den IT Anbieter. Wir haben
> im Realm einen lokalen Admin user automato-admin, dieser User ist auch im
> Magister der lokale Admin und hat alle Rechte dort. Die User kommen dann
> später und werden den Rollen zugewiesen."

Und vorher: Keycloak verwaltet die Benutzer (Anmeldung), Magister nur die
Autorisierung — wie bei Automato.

## Problem

Die Anmeldung hing an zwei Dingen, die es beim Kunden so nicht gibt:

1. **Entra als Anbieter.** Der Client hiess `EntraOidcClient`, die Texte der
   Anmeldeseite nannten Entra, das Protokoll suchte AADSTS-Codes. Eingesetzt
   wurde Entra in Magister nie.
2. **Der AD-Abgleich als Voraussetzung.** Ein Benutzer kam nur hinein, wenn der
   Abgleich ihn schon in `ad_user_cache` geschrieben hatte (Treffer über `oid`
   gegen `mS-DS-ConsistencyGuid` oder über den UPN). Sonst `user_not_synced`;
   ein Bootstrap-Admin ohne `oid` bekam `oidc_no_oid_for_bootstrap`. Ein
   Benutzer, der nur in Keycloak steht — etwa `automato-admin`, der lokale Admin
   jedes Realms — kam nie hinein.

Seit Automato 1.12.0 liegt Magister unter `<kunde>-um.<domain>` hinter dem
Anmelde-Tor; Tor, Automato und NetBox melden schon über den Realm des Kunden an.
Magister war die Ausnahme.

## Entscheidung

### D1 · Endbenutzer melden sich nur per OIDC am Keycloak-Realm des Kunden an

Der Realm ist der einzige Anbieter. Ob dahinter lokale Benutzer, Entra (als
Identity Provider) oder LDAP/AD (als User Federation) stehen, entscheidet der
Realm und ist für Magister unsichtbar. Die Konfiguration kommt wie bisher aus
der Konsole (`oidc_issuer` = `<keycloak>/realms/<realm>`, `oidc_client_id`,
`oidc_redirect_uri`, `oidc_scopes`, `bootstrap_admins`; das Client-Secret
versiegelt als `oidc_client_secret`). **Kein neuer Vertrag mit der Konsole.**

Der Client ist reines OIDC (`StandardOidcClient`): Discovery, Authorization
Code mit PKCE, Signatur gegen die JWKS, `iss`/`aud`/`nonce`. Nichts
Anbieterspezifisches; das Protokoll nennt beim abgewiesenen Code-Tausch nur
HTTP-Status und die Fehlerart nach RFC 6749.

Das lokale Notkonto (Passwort + TOTP, ADR-0015 D2) bleibt unverändert.

### D2 · Identität = `iss` + `sub`, Anzeige = `preferred_username`

Neue Tabelle `login_accounts` je Mandantenschema: `issuer`, `subject` (beide
leer bis zur ersten Anmeldung), `username` (klein, eindeutig), `display_name`,
`email`, `principal_guid`, `enabled`, `created_at`, `last_login_at`.

Zuordnung beim Rückweg vom Realm, in dieser Reihenfolge:

1. Treffer über `issuer` + `subject` → dieses Konto (ein in Keycloak
   umbenannter Benutzer behält sein Konto; der neue Name wird übernommen, wenn
   er frei ist).
2. Sonst ein Konto mit diesem `username` ohne gebundenes `subject` (vorab
   angelegt) → `subject` wird gebunden.
3. `username` vorhanden, aber an ein **anderes** `subject` gebunden →
   abgewiesen (`account_bound_to_other_subject`), auditiert (`login_refused`),
   keine Übernahme.
4. Sonst ein neues Konto.

`principal_guid` ist der Schlüssel, an dem `role_assignments`, Klassen- und
Fachlehrer-Zuordnungen, Leitungen und die Sitzung hängen:

- gibt es in `ad_user_cache` eine Zeile mit `upn == username`
  (Gross-/Kleinschreibung egal), deren objectGUID — so behält eine Lehrperson
  ihre Klassen und Rollen;
- sonst `uuid5(e5df4e2c-4a65-4cbf-ae9d-7ea9a4e53044, "magister-konto:" + username)`
  — stabil, so dass vor der ersten Anmeldung vergebene Rollen nach
  Benutzername passen.

Einmal gesetzt, ändert sich `principal_guid` nicht mehr. Hält schon ein anderes
Konto dieselbe GUID (dieselbe Person mit neuem Benutzernamen und neu
angelegtem Keycloak-Benutzer), wird abgewiesen (`account_principal_conflict`);
ein Mensch entscheidet, welches Konto gilt.

Kein `oid`-Zwang, kein `user_not_synced` mehr. Ist das Konto einer AD-Person
zugeordnet, die im AD deaktiviert ist, gibt es keine Sitzung (`user_disabled`,
wie bisher); ein in Magister gesperrtes Konto ebenso (`account_disabled`).

### D3 · Kein AD- oder Entra-Abgleich für die Anmeldung

Der AD-Abgleich über den Connector bleibt — er verwaltet Schüler:innen und
Lehrpersonen, setzt Passwörter, füllt Klassen. Nur die **Anmeldung** hängt
nicht mehr an ihm. Ein Bootstrap-Admin bekommt keine Zeile mehr in
`ad_user_cache`.

### D4 · Autorisierung bleibt in Magister

Rollen (`role_assignments`), Rechte-Matrix (ADR-0010/0017) und Standorte gelten
unverändert, jetzt an `principal_guid`. Ein neues Konto ohne Rolle, Klasse,
Fach oder Leitung meldet sich an und **sieht nichts**: die API weist ab wie
bisher, die Oberfläche zeigt statt Menüs einen Hinweis „Noch keine Rechte"
(`/auth/me` liefert `has_permissions`).

Der Rolleneditor (`/admin/users/{guid}/roles`) nimmt neben AD-Benutzern auch
Anmeldekonten ohne AD-Zeile. Neu ist `/admin/login-accounts` (nur Admin, auch
gehostet gemountet wie die Rollenzuweisung): Konten ansehen, **vorab anlegen**,
sperren (beendet ihre Sitzungen), Bindung lösen (für einen in Keycloak neu
angelegten Benutzer oder einen Realm-Wechsel), löschen (Rollen bleiben an der
GUID stehen). Jede dieser Handlungen ist auditiert.

### D5 · Grundsetup durch die Konsole: `bootstrap_admins` sind Benutzernamen

`bootstrap_admins` sind jetzt **Keycloak-Benutzernamen** (Vorgabe im Cockpit:
`automato-admin`; ein UPN ist auch ein Benutzername). Bei **jeder** Anmeldung
bekommt ein gelisteter Benutzer die Rolle `admin` (wie bisher wiederholend),
ohne `oid` und ohne Zeile in `ad_user_cache`. Ein gelistetes Konto lässt sich in
Magister weder sperren noch löschen.

Regel für einen Benutzernamen, auf beiden Seiten gleich zu prüfen: klein
(verglichen wird klein und ohne Rand), 1–255 Zeichen, druckbar, ohne
Leerraum (`schemas.common.validate_login_name`). `AppSettingsUpdate` prüft
`bootstrap_admins` damit, schreibt die Liste aber nicht um — sonst schriebe der
Abgleich aus der Konsole bei jedem Lauf neu. Das Cockpit muss dieselbe Regel
(oder eine engere) anwenden, sonst scheitert der Abgleich der Einstellungen.

### D6 · Abmelden beim Realm

Nach dem Löschen der lokalen Sitzung nennt `POST /auth/logout` bei einer
Keycloak-Sitzung `redirect`: den `end_session_endpoint` aus der Discovery mit
`client_id` und `post_logout_redirect_uri=https://<host>/login`. `<host>` kommt
aus `oidc_redirect_uri` (Konsole), nicht aus dem `Host`-Kopf der Anfrage.
**Kein `id_token_hint`**: Magister speichert nach der Anmeldung kein Token.
Keycloak fragt deshalb einmal nach, ob abgemeldet werden soll. Ohne Eintrag in
der Discovery (oder ohne Netz zum Realm) bleibt es beim lokalen Abmelden. Die
Oberfläche folgt `redirect`, sonst `/login`. Notkonto- und Operator-Sitzungen
bekommen kein `redirect`.

## Konsequenzen

**Positiv**

- Ein Anmeldeweg für alle Werkzeuge des Kunden; MFA, Sperren, Passwortregeln
  und Anbindung an Entra/LDAP liegen im Realm.
- `automato-admin` kommt ohne AD-Zeile in eine frische Installation.
- Die Anmeldung fällt nicht mehr aus, weil ein Abgleich noch nicht lief.

**Negativ / Risiken**

- **Wiederverwendung von Benutzernamen.** Vergibt Keycloak einen Namen neu,
  weist Magister den neuen Benutzer ab (D2 Punkt 3) — richtig, aber ein
  Handgriff für die Administration („Bindung lösen"). Gefährlicher ist die
  Wiederverwendung **vor** der ersten Anmeldung: ein vorab angelegtes Konto
  bindet, wer sich zuerst mit diesem Namen anmeldet; ebenso hängen Rollen, die
  an einer synthetischen GUID stehen, nach dem Löschen eines Kontos am Namen.
  Wer eine Person entfernt, entzieht ihr zuerst die Rollen.
- **Vertrauen in die Benutzernamen des Realms.** Die Zuordnung zur AD-Person
  läuft über `upn == username`. Wer im Realm Benutzer anlegen oder umbenennen
  darf, kann damit die Rechte einer Lehrperson erhalten. Das Recht, Benutzer im
  Realm zu verwalten, ist damit so viel wert wie die Admin-Rolle in Magister.
- **Realm-Wechsel.** Ein neuer Issuer bindet keinen bestehenden Benutzer mehr
  (D2 Punkt 3); vorher alle Bindungen lösen oder die Konten neu anlegen.
- **Spätere AD-Zeile.** Meldet sich jemand an, bevor der Abgleich ihn kennt,
  bekommt das Konto die synthetische GUID und behält sie; Klassen aus dem AD
  hängen dann nicht daran. Abhilfe: Konto löschen, neu anmelden.
- **Rollen aus dem Cockpit** („Rollenverteilung im Cockpit"): seit
  [ADR-0026](0026-rollen-aus-dem-cockpit.md) liefert das Cockpit je Kunde eine
  Liste Keycloak-Benutzer → Rolle im Soll-Zustand (`role_assignments`); Magister
  legt fehlende Konten vorab an und berechnet die GUID selbst. Von Hand bleibt
  die Vergabe in Magister möglich.

## Nachtrag 2026-11-14: Anmeldung ohne zweite Maske (SSO)

Fund aus dem Test (Anwender: „Bekomme für das Login weiterhin das Anmelde Fenster von Magister …
also noch kein SSO mit dem Keycloak“): Hinter dem Anmelde-Tor von Automato hat der Benutzer schon
eine Keycloak-Sitzung, Magister zeigte trotzdem seine Anmeldeseite mit dem Knopf „Anmelden“.

- Ist der Realm eingerichtet (`oidc_enabled`), leitet `/login` gleich zu `/api/auth/login` weiter;
  mit bestehender Keycloak-Sitzung kommt der Benutzer ohne Rückfrage hinein.
- Nicht nach einem abgewiesenen Rückweg (`/login?error=…`): sonst entstünde eine Schleife, die
  Seite zeigt den Grund und den Knopf.
- Der lokale Notzugang bleibt unter `/login?lokal=1` (Formular direkt, keine Weiterleitung).
- Nach dem Abmelden führt der Weg über die Abmeldeseite von Keycloak zurück auf `/login` und von
  dort zur Anmeldemaske von Keycloak – die Sitzung ist dann beendet, es meldet nicht still wieder an.

## Abgelöst

- ADR-0013 D5 (letzter Absatz) und ADR-0015 D3 („Was bleibt: OIDC gegen Entra")
  — der reguläre Weg ist jetzt OIDC gegen den Keycloak-Realm des Kunden.
- ARCHITECTURE §3.1/§7 (Zuordnung über `oid`/UPN, Bootstrap per UPN).
