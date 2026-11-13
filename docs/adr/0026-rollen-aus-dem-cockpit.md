# ADR-0026 · Rollen aus dem Cockpit

**Status:** Akzeptiert (2026-11-13)
**Kontext:** [ADR-0025](0025-anmeldung-ueber-keycloak.md) (Anmeldekonten,
`principal_guid`, vorab anlegen), [ADR-0017](0017-systemeinstellungen-und-rechte-in-der-konsole.md)
D3/D4 (Soll-Zustand, Abgleich schreibt nur die Differenz),
[ADR-0018](0018-globale-vorlagen.md) D6 (`null` = keine Aussage, Liste =
vollständig), [ADR-0010](0010-dynamische-rollen-rechte-matrix.md) (Rollen und
Einheiten), Cockpit ADR 0007 Nachtrag „Rollen aus dem Cockpit"

Entscheid des Produktverantwortlichen (2026-11-13), wörtlich:

> „Liste im Cockpit … Magister ist nicht nur für Schulen, es ist auch für
> Firmen … es sind einfach Kunden (auch keine Gruppengesellschaften)."

und bestätigt: „Im Cockpit je Kunde eine Liste Keycloak-Benutzer → Rolle, die
Rolle gilt immer für den ganzen Kunden; die Einheiten sieht das Cockpit nicht."

## Problem

ADR-0025 liess die „Rollenverteilung im Cockpit" offen: Rollen vergab
`automato-admin` bzw. ein Admin in Magister von Hand. Der IT-Anbieter führt die
Kunden aber im Cockpit, und dort steht schon, wer sich am Realm des Kunden
anmeldet.

## Entscheidung

### D1 · Vertrag: `role_assignments` im Soll-Zustand

`GET /tenants/{id}/desired-state` trägt das Feld `role_assignments`:

- fehlt es oder ist es `null`: **keine Aussage** — Magister lässt alle
  Zuweisungen, wie sie sind (das Cockpit führt die Anmeldung dieses Kunden nicht
  über den Realm, oder es ist älter);
- eine Liste `[{"username": "<keycloak-benutzer>", "role": "admin" | "schulleitung" | "smi"}]`
  ist **vollständig**, auch `[]`.

Geprüft wird streng (`tenancy/desired_state.py`): Benutzername nach
`validate_login_name` (dieselbe Regel prüft das Cockpit), Rolle in
`ROLE_ASSIGNMENT_ROLES`. Eine falsche Form verwirft den ganzen Soll-Zustand
(`DesiredStateUnavailableError`, der letzte gute Stand bleibt) — ein still
ausgelassener Eintrag nähme sonst Rollen weg. Zusätzliche Felder eines Eintrags
werden übergangen; doppelte Paare zählen einmal. Im Cockpit heissen die Rollen
„Administrator", „Leitung" und „IT-Verantwortliche".

### D2 · Die Rolle gilt für den ganzen Kunden

`services/cockpit_roles.py` macht aus der Liste die gewollten Zeilen in
`role_assignments`:

- `admin` → eine Zuweisung ohne Einheit (`school_id` NULL);
- `schulleitung`, `smi` → eine Zuweisung an **jeder** Einheit (`schools`; es
  gibt keine inaktiven). Kommt eine Einheit dazu, ergänzt der nächste Abgleich.
  Ohne Einheit gibt es noch keine Zuweisung, nur das Konto.

Person ist das Anmeldekonto zum Benutzernamen (ADR-0025 D2). Fehlt es, wird es
**vorab angelegt** (`LoginAccountService.precreate`; bindet bei der ersten
Anmeldung, `principal_guid` = objectGUID der AD-Zeile mit `upn == username`,
sonst die synthetische GUID). Hält schon ein anderes Konto diese GUID
(`account_principal_conflict`, etwa ein in Keycloak umbenannter Benutzer, der
sich seither nicht angemeldet hat), wird der Eintrag ausgelassen, im Ergebnis
(`skipped_assignments`), im Log und in der Zustandsmeldung an das Cockpit
gemeldet; der Rest läuft weiter. Welches Konto gilt, entscheidet ein Mensch.

### D3 · Herkunft `granted_by = "cockpit"`, nur sie wird zurückgenommen

- Fehlende gewollte Zuweisungen werden mit `granted_by = "cockpit"` angelegt.
  Besteht dieselbe Zuweisung (Person, Rolle, Einheit) schon aus anderer Quelle
  — von Hand oder per Bootstrap —, wird nichts angelegt und nichts übernommen.
- Aktive Zuweisungen mit Herkunft `cockpit`, die nicht mehr gewollt sind, werden
  **zurückgenommen** (`revoked_at`, wie in der Admin-Oberfläche).
- Von Hand oder per Bootstrap vergebene Zuweisungen fasst der Abgleich nie an.
- Ein Keycloak-Benutzer, der `cockpit` heisst, vergibt von Hand als
  `konto:cockpit` — sonst nähme der nächste Abgleich seine Vergaben zurück.

Jede Änderung ist auditiert: `role_granted`/`role_revoked` (Ziel
`principal_guid`, Payload `role`, `school_id`, `username`, `via: "cockpit"`),
ein vorab angelegtes Konto als `login_account_created`; Ausführender ist der
Abgleich (`platform-reconciler@vitabrevis.ch`). `dry_run` schreibt nichts und
meldet, was geschähe. Ein zweiter Lauf ändert nichts und schreibt kein Audit.
Zwei Container: gibt es etwas zu tun, sperrt ein Advisory-Lock je Mandant, und
unter der Sperre wird neu geplant.

### D4 · Wirkung beim nächsten Request

Rollen werden je Anfrage aus `role_assignments` gelesen (`get_optional_user`),
nicht in der Sitzung gehalten. Eine zurückgenommene Rolle fehlt ab der nächsten
Anfrage; laufende Sitzungen bleiben, sehen aber nur noch, was die übrigen
Rollen erlauben.

### D5 · In der Oberfläche erkennbar, entziehen mit Hinweis

`GET /admin/roles` liefert `from_cockpit`. Die Liste zeigt solche Zuweisungen
als „aus dem Cockpit", der Rolleneditor markiert sie und erklärt die Herkunft.
Entziehen bleibt möglich, fragt aber nach: der nächste Abgleich setzt die Rolle
wieder, solange die Person im Cockpit mit dieser Rolle steht. Gesperrt wäre
einfacher zu lesen, liesse aber Zuweisungen zurück, die niemand mehr entfernen
kann, sobald das Cockpit die Anmeldung nicht mehr führt (`null`).

### D6 · Einheit löschen

Zuweisungen aus dem Cockpit halten das Löschen einer Einheit nicht auf: sie
gehen mit der Einheit (die aktiven als `role_revoked`, `via: "school_deleted"`).
Sonst liesse sich keine Einheit mehr löschen, sobald das Cockpit eine Leitung
oder IT-Verantwortliche nennt. Zuweisungen von Hand halten das Löschen weiter
auf.

### D7 · Wieder vergeben

Die Eindeutigkeit (Person, Rolle, Einheit) in `role_assignments` gilt auch für
zurückgenommene Zeilen. Wieder vergeben (von Hand oder aus dem Cockpit) lässt
deshalb die zurückgenommene Zeile mit neuer Herkunft wieder aufleben, statt
eine zweite anzulegen — vorher scheiterte das mit `UniqueViolation`, in der
Admin-Oberfläche wie im Abgleich. Den Verlauf hält das Audit.

## Konsequenzen

**Positiv**

- Grundsetup und Rollenverteilung an einem Ort, durch den IT-Anbieter; eine
  Person lässt sich im Cockpit entfernen, und ihre Rechte in Magister gehen mit.
- Keine Einheiten im Cockpit: es bleibt „Kunden", für Schulen wie für Firmen.

**Negativ / Risiken**

- **Andere Quelle bleibt stehen.** Bestand eine Zuweisung schon von Hand oder
  per Bootstrap (etwa `automato-admin` vor dem ersten Abgleich angemeldet),
  übernimmt das Cockpit sie nicht. Nimmt es die Rolle später weg, bleibt sie und
  ist in Magister zu entziehen. Die Liste zeigt die Herkunft („Vergeben von").
- **Von Hand entzogen kommt wieder.** Wer eine Rolle aus dem Cockpit in Magister
  entzieht, sieht sie nach dem nächsten Abgleich wieder (Hinweis in der
  Oberfläche). Dauerhaft ändert man sie im Cockpit.
- **Ausgelassen heisst nicht geschützt.** Wird ein Eintrag wegen eines
  Konflikts ausgelassen, nimmt der Abgleich Zuweisungen aus dem Cockpit an der
  GUID des anderen Kontos zurück, wenn dieses nicht mehr gelistet ist — die
  sichere Richtung. Nach der nächsten Anmeldung (Konto folgt dem neuen Namen)
  setzt der nächste Abgleich sie wieder.
- **Gesperrte Konten** bekommen Rollen wie alle anderen; anmelden können sie
  sich nicht.
- **Keine Aussage behält alles.** Führt das Cockpit die Anmeldung nicht mehr
  (`null`), bleiben seine Zuweisungen stehen und sind in Magister von Hand zu
  entziehen.
