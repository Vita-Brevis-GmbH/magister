# ADR-0027 · Rollen nur aus dem Cockpit

**Status:** Akzeptiert (2026-11-16)
**Kontext:** [ADR-0026](0026-rollen-aus-dem-cockpit.md) (Rollen aus dem Cockpit,
Herkunft `cockpit`), [ADR-0025](0025-anmeldung-ueber-keycloak.md) (Anmeldekonten,
`principal_guid`), [ADR-0017](0017-systemeinstellungen-und-rechte-in-der-konsole.md)
D1 (was dem Betreiber gehört, wird gehostet nicht gemountet),
[ADR-0015](0015-authentisierungs-haertung.md) D2 (lokales Notkonto),
[ADR-0019](0019-operator-zugriff.md) (Operator-Zugriff), Vertrag „Verwaltung nur
aus dem Cockpit" §3 (Cockpit, Automato, Magister)

Entscheid des Produktverantwortlichen (2026-11-16), wörtlich:

> „die Rollen und User (Sync vom Keycloak einrichten) sollen nur noch im Cockpit
> sein. Die Kunden sollen dies nicht machen können, da es zu gefährlich ist, dass
> wir neuen Benutzern bei einem Problem von aussen geben können. Also in den
> Tools raus und im Cockpit rein."

## Problem

ADR-0026 brachte die Rollen aus dem Cockpit, liess die Vergabe in Magister aber
offen: ein Admin des Kunden konnte weiter jeder Person jede Rolle geben, Konten
vorab anlegen, Bindungen lösen und Konten löschen (D5: „Entziehen bleibt möglich,
fragt aber nach"). Wer ein Admin-Konto des Kunden übernimmt, kann sich damit
einen zweiten Zugang schaffen — etwa einen neuen Keycloak-Benutzer mit
Admin-Rolle —, und das Cockpit erfährt nichts davon.

## Entscheidung

### D1 · Wann: solange das Cockpit die Rollen führt

Das Cockpit führt die Rollen eines Kunden, solange sein Soll-Zustand
`role_assignments` trägt und nicht `null` (ADR-0026 D1). Der Abgleich hält das
bei jedem Lauf im Kundenschema fest: `app_settings.roles_from_cockpit`
(Migration `0054_rollen_nur_cockpit`, Vorgabe `false`). Ändert sich der Merker,
schreibt der Abgleich das Audit-Ereignis `roles_source_changed`
(`{"from_cockpit": true|false}`); ein Probelauf (`dry_run`) setzt ihn nicht.

Ein Merker und nicht der Soll-Zustand selbst: der liegt nur im Speicher des
Abgleichs. Die API fragt die Datenbank, damit die Sperre in jedem Container und
nach jedem Neustart gilt. Fällt der Abgleich aus, bleibt der Merker, wie er war.

Sagt das Cockpit nichts mehr (`null`), fällt der Merker, und die Vergabe von
Hand geht wieder. Ohne Cockpit (Einzelinstallation, Kunde ohne Realm) ändert
sich nichts.

### D2 · Gesperrt: Rollen vergeben und entziehen, Konten anlegen, lösen, löschen

Bei gesetztem Merker lehnt die API mit **409** und `detail:
"roles_managed_by_cockpit"` ab (`auth/role_lock.require_roles_editable`):

| Endpunkt | Wozu |
|----------|------|
| `POST`, `PUT`, `DELETE /admin/users/{guid}/roles` | Rolle vergeben, Rollen setzen, entziehen |
| `POST /admin/login-accounts` | Konto vorab anlegen — bindet, wer sich zuerst mit dem Namen anmeldet |
| `POST /admin/login-accounts/{id}/unbind` | Bindung lösen — die nächste Anmeldung mit dem Namen übernimmt das Konto **samt Rollen** |
| `DELETE /admin/login-accounts/{id}` | Konto löschen — die Rollen bleiben an der GUID, ein neues Konto mit demselben Namen bekommt dieselbe (synthetische) GUID |

Die Sperre hängt an den Endpunkten, nicht an der Oberfläche. Reihenfolge: ohne
Anmeldung 401, ohne Admin-Recht 403 (die Sperre verrät niemandem ohne Recht, wer
die Rollen führt), dann 409 — auch vor der Prüfung des Inhalts (422).

**Bleibt:** Lesen (`GET /admin/roles`, `GET /admin/login-accounts`) sowie
**Sperren und Freigeben** eines Kontos (`PATCH /admin/login-accounts/{id}`).
Sperren nimmt nur weg und ist der schnelle Griff bei einem Vorfall; Freigeben
gibt einem bestehenden Konto zurück, was ihm das Cockpit gab — keiner neuen
Person. Neu ist `GET /admin/roles/source` → `{"from_cockpit", "editable",
"emergency_access"}` für die Oberfläche.

### D3 · Ausnahme: der Notzugang

Das lokale Administrationskonto (`auth_kind = "local"`, ADR-0015 D2) darf
weiter alles aus D2. Fällt der Abgleich aus oder steht im Cockpit etwas falsch,
muss jemand beim Kunden handeln können. Was der Notzugang vergibt, hat nicht die
Herkunft `cockpit` und erscheint deshalb im Cockpit als fremde Rolle (D5); jede
Handlung steht wie bisher im Audit. Operator-Sitzungen (ADR-0019) schreiben
ohnehin nicht.

### D4 · Weitere Wege zu Rechten — geprüft

| Weg | Entscheid | Grund |
|-----|-----------|-------|
| Konto bei der ersten Anmeldung (ADR-0025 D2) | bleibt | Ohne Rechte; Rechte gibt erst das Cockpit. |
| `bootstrap_admins` (erste Administratoren) | bleibt | Kommt aus der Konsole; die Systemeinstellungen sind gehostet nicht gemountet (ADR-0017 D1). Rollen aus dem Cockpit gibt es nur gehostet (der Abgleich läuft nur mit Konsole). |
| Rechte-Matrix, eigene Rollen (`/admin/rbac`) | schon gesperrt | Gehostet nicht gemountet (ADR-0017 D1). |
| Lokales Administrationskonto verwalten (`/admin/local-admin`) | bleibt | Der Notzugang selbst. Passwort ändern nur mit dem alten; anlegen und neu setzen gehostet nur als Wartungsauftrag aus dem Cockpit (`local_admin_setup`). |
| Zuständigkeiten: Klassen- und Fachlehrpersonen, Stellvertretungen, Leitungen und Mitglieder von Abteilungen | bleibt | Fachdaten des Kunden, keine Rollen: sie geben Rechte nur an den eigenen Klassen bzw. der eigenen Einheit, nie Verwaltung, Rollen oder Einstellungen. Das Cockpit kennt Klassen und Einheiten nicht (ADR-0026). Vergeben kann sie nur, wer schon eine Rolle hat — aus dem Cockpit oder als fremde Rolle sichtbar (D5). |
| Benutzer im AD anlegen (Lehrpersonen, Schüler:innen, Mitarbeitende) | bleibt | Die Fachaufgabe von Magister; ein neues AD-Konto bekommt keine Rolle. |
| Operator-Zugriff (ADR-0019) | bleibt | Stellt der Betreiber aus; nur lesend. |
| Einladungen | — | Gibt es in Magister nicht. |

### D5 · `rollen_fremd` in der Zustandsmeldung

Solange der Merker steht, trägt die Zustandsmeldung das optionale Feld

```json
"rollen_fremd": [
  {"username": "anna", "principal": "<guid>", "role": "smi", "granted_by": "admin@example.ch"}
]
```

- **Fremd** ist eine aktive Zuweisung, deren Herkunft nicht `cockpit` ist — von
  Hand, per SQL oder per Bootstrap. **Nicht** fremd: der Notzugang und die
  Admin-Rolle (ohne Einheit) eines Benutzers, der jetzt in `bootstrap_admins`
  steht (sie kommt bei seiner nächsten Anmeldung ohnehin wieder; die Liste steht
  im Cockpit). Ein ehemaliger erster Administrator ist fremd.
- **Je Person und Rolle ein Eintrag** über alle Einheiten: im Cockpit gilt eine
  Rolle für den ganzen Kunden. `granted_by` ist die Herkunft der ältesten Zeile
  (`"unbekannt"` ohne Herkunft).
- `username`: Benutzername des Anmeldekontos, sonst der UPN der AD-Zeile (klein,
  wenn er als Benutzername gilt), sonst `null`. **Keine weiteren
  Personendaten.**
- Höchstens **200** Einträge, sortiert nach Benutzername, Kennung und Rolle; mehr
  stehen als Warnung im Protokoll.
- Ohne Cockpit-Führung fehlt das Feld — dann vergibt der Kunde selbst, und jede
  Rolle wäre „fremd".

**Rückfall.** `rollen_fremd` steht in `status_report.OPTIONAL_FIELDS`. Weist ein
älteres Cockpit die Meldung mit 422 ab, geht sie einmal ohne die
**beanstandeten** optionalen Felder hinaus (aus `detail[].loc = ["body",
"<feld>"]`); nennt die Antwort keines, ohne alle. So bekommt ein Cockpit, das
`oidc` schon kennt und `rollen_fremd` noch nicht, `oidc` weiter. Bis dahin ging
bei einem 422 jedes optionale Feld verloren.

### D6 · `role_revocations` im Soll-Zustand

```json
"role_revocations": [{"principal": "<guid>", "role": "smi"}]
```

- Optional; fehlt es oder ist es `null`, wird nichts entzogen. Geprüft wird
  streng wie die Rollenliste (GUID, Rollenschlüssel `^[a-z][a-z0-9_-]{0,31}$`;
  zusätzliche Felder werden übergangen, doppelte zählen einmal). Eine falsche
  Form verwirft den Soll-Zustand, der letzte gute Stand bleibt.
- Wirkt nur, solange `role_assignments` nicht `null` ist (sonst Warnung im
  Protokoll, nichts entzogen).
- Entzogen wird **nur, was nach D5 fremd ist** — nach derselben Regel, ohne die
  Grenze von 200 —, und zwar an allen Einheiten der Person. Zuweisungen aus dem
  Cockpit, der Notzugang und die ersten Administratoren bleiben, auch wenn das
  Cockpit sie nennt.
- Jede Zeile: `role_revoked` mit `via: "cockpit_revocation"`, `role`,
  `school_id`, `username`, `granted_by`; ausführend ist der Abgleich.
- Ein Eintrag ohne fremde Rolle (schon entzogen, nie vorhanden, nicht fremd)
  wird übergangen (Debug-Protokoll). Das Cockpit sendet ihn, bis die Meldung die
  Rolle nicht mehr nennt; ein zweiter Lauf findet nichts und schreibt nichts.
- Läuft **vor** der Rollenliste: entzieht das Cockpit eine fremde Rolle, die es
  selbst auch nennt, vergibt die Rollenliste sie im selben Lauf neu mit Herkunft
  `cockpit` (ADR-0026 D7) — so übernimmt das Cockpit eine Rolle von Hand.
- `dry_run` meldet, was entzogen würde (`magister-cli abgleich`: `-N fremde`).

### D7 · Oberfläche

*Rollen & Berechtigungen* zeigt bei Cockpit-Führung den Hinweis „Rollen dieses
Kunden vergibt der Betreiber im Cockpit" und ist nur lesbar: kein Rolleneditor,
kein „Entziehen", bei den Anmeldekonten kein „Vorab anlegen", „Bindung lösen"
und „Löschen"; „Sperren"/„Freigeben" bleiben. Mit dem Notzugang bleibt alles
bearbeitbar, der Hinweis sagt, dass das Cockpit solche Rollen als fremd sieht.
Lehnt die API ab (409), steht der übersetzte Text da (de, en, fr, it).

## Konsequenzen

**Positiv**

- Wer ein Admin-Konto des Kunden übernimmt, kann damit niemandem Rollen geben
  und kein Konto auf eine neue Person umhängen.
- Altlasten von Hand werden im Cockpit sichtbar und lassen sich dort entziehen.

**Negativ / Risiken**

- **Bis zum ersten Abgleich nach dem Update** (höchstens ein Intervall, Vorgabe
  300 s) steht der Merker auf `false`.
- **Bindung lösen** für einen in Keycloak neu angelegten Benutzer
  (`account_bound_to_other_subject`, ADR-0025 D2 Punkt 3) geht nur noch mit dem
  Notzugang — bis das Cockpit dafür einen Auftrag hat.
- **Einheit löschen:** fremde Rollen an einer Einheit halten das Löschen weiter
  auf (ADR-0026 D6); sie entzieht das Cockpit (`role_revocations`) oder der
  Notzugang.
- **Zuständigkeiten bleiben beim Kunden** (D4): eine Leitung aus dem Cockpit
  kann Klassenlehrpersonen setzen, auch auf ein Konto, das nur in Keycloak
  steht. Rechte an Klassen, keine Verwaltung — aber ein Weg, den es zu kennen
  gilt.
- **Ältere Cockpits** kennen `rollen_fremd` nicht (Rückfall, D5) und senden
  keine `role_revocations`: fremde Rollen bleiben dann stehen, sichtbar nur in
  Magister.
- **Der Notzugang** bleibt ein Weg zu Rollen — gewollt; Audit und `rollen_fremd`
  zeigen jede Vergabe.

## Abgelöst

- ADR-0026 D5 („Entziehen bleibt möglich, fragt aber nach") für Kunden, deren
  Rollen das Cockpit führt; ohne Cockpit-Führung gilt D5 weiter.
- ADR-0025 D4 (Konten vorab anlegen, Bindung lösen, löschen in
  `/admin/login-accounts`) ebenso nur noch ohne Cockpit-Führung oder mit dem
  Notzugang.
