# ADR 0005: Fachlehrer als eigene Tabelle (nicht als KL-Sub-Rolle)

**Status:** Akzeptiert · 2026-06-30
**Kontext:** Erweiterungen-Batch 2026-06 — neue Rolle „Fachlehrer"

## Problem

Schulträger brauchen eine Rolle **Fachlehrer** (Fachlehrperson): eine Lehrperson,
die in einer Klasse ein **Fach** unterrichtet, ohne Klassenlehrer:in (KL) zu sein.
Anforderungen:

- Ein Fachlehrer ist klassen-**und**-fachgebunden und kann in mehreren Klassen tätig sein.
- Ein Fachlehrer darf die Passwörter **seiner** Schüler:innen zurücksetzen
  (= Schüler:innen der Klassen, in denen er aktiv unterrichtet) — nicht mehr.
- Ein Fachlehrer soll **alle seine** Schüler:innen klassenübergreifend sehen.

Die naheliegende Option wäre, `fachlehrer` als vierte Sub-Rolle in
`class_teacher_roles` (neben `haupt`/`co`/`stellvertretung`) aufzunehmen.

## Entscheidung

Wir führen eine **eigene Tabelle `subject_teacher_roles`** ein (Migration `0014`),
strukturell analog zu `class_teacher_roles`, aber mit einer zusätzlichen Spalte
`subject` und **ohne** `role`-CheckConstraint.

Begründung gegen die KL-Sub-Rolle:

1. **KL-Autorität ist breiter.** `class_teacher_roles` speist die KL-Sicht
   (`is_active_kl_of`), die Stellvertretungs-Liste (`role = 'stellvertretung'`)
   und den Workload-Report (zählt `haupt`/`co`/`stellvertretung`). Ein vierter
   Rollenwert würde diese Abfragen verschmutzen oder müsste überall explizit
   ausgeschlossen werden — fehleranfällig.
2. **Trennung der Semantik.** „Fachlehrer" ist konzeptionell kein KL. Eine eigene
   Tabelle hält die Modelle (und ihre `__table_args__`) sauber getrennt.
3. **Fach gehört nicht in `class_teacher_roles`.** KL haben kein Fach; eine
   nullable `subject`-Spalte dort wäre ein Fremdkörper.

Die **Berechtigung** zum Schüler-PW-Reset wird in `auth.class_perm.require_student_writer`
erweitert: zusätzlich zu „aktiver KL einer Klasse des Schülers" gilt nun auch
„aktiver Fachlehrer einer Klasse des Schülers". Active-Window-Logik
(`valid_from <= now < COALESCE(valid_to, +infty)`) ist identisch zu KL.

## Konsequenzen

**Positiv:**

- KL-Sichten (Stellvertretungen, Workload) bleiben unberührt und brauchen keine Filter.
- Fachlehrer-Zuweisung/-Liste/-Widerruf laufen über einen eigenen, klar benannten
  Endpoint (`/classes/{id}/subject-teachers`) mit eigenem Audit-Action-Namen.
- `GET /me/students` vereint KL- und Fachlehrer-Klassen des Aufrufers für die
  „Meine Schüler"-Sicht.

**Negativ:**

- Etwas Code-Duplikation gegenüber `class_teachers` (Repo/Service/Schema spiegeln
  das Muster). Bewusst in Kauf genommen — die beiden Rollen divergieren fachlich
  und werden sich vermutlich weiter auseinanderentwickeln.
- Wer „alle Lehrpersonen einer Klasse" will, muss zwei Tabellen lesen.

## Alternativen verworfen

- **Vierte Sub-Rolle in `class_teacher_roles`**: verschmutzt KL-Autorität und
  Reports; `subject` würde dort zum Fremdkörper.
- **Generische `class_roles`-Tabelle mit `role_type` + optionalem `subject`**:
  größerer Umbau bestehender, getesteter KL-Pfade ohne kurzfristigen Nutzen.
