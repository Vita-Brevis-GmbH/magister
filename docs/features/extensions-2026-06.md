# Magister · Erweiterungen 2026-06

Referenz für den Funktions-Batch auf Branch
`claude/magister-improvements-extensions-l16lcj` (parallel zum Produktiv-Rollout
entstanden). Gruppiert nach Bereich; je Feature: neue Endpoints, RBAC,
Audit-Actions, Migration und UI.

> Konventionen wie immer: jede Mutation erzeugt ein `audit_events`-Event, jede
> personenbezogene Query ist `school_id`-gefiltert (Ausnahmen mit
> `# scope-bypass:`-Kommentar), neue UI-Strings sind i18n-Keys in de/fr/it/en.

---

## Schulen-Dropdown bei Klassenerstellung

| | |
|---|---|
| **Endpoint** | `GET /schools` → `[{id, name, kuerzel, scope_short}]` |
| **RBAC** | `require_schulleitung` (Admin + Schulleitung) |
| **Scope** | Admin sieht alle Schulen; sonst nur `school_scope` (via `apply_scope` auf `School.id`) |
| **UI** | Klassenerstellung (Admin) wählt die Schule aus einem Dropdown statt einer numerischen ID; die Klassenliste zeigt den Schulnamen statt der ID. |

---

## Klassen-Detailfeld + Edit-Dialog

| | |
|---|---|
| **Migration** | `0012_class_details` — Spalte `classes.details TEXT NULL` |
| **Schema** | `ClassCreate`/`ClassUpdate`/`ClassOut` um `details` erweitert |
| **Endpoint** | `PATCH /classes/{id}` akzeptiert nun `name`/`kuerzel`/`details` |
| **Audit** | `class_renamed` — Payload enthält nur ein `details_changed`-Flag, **nie** den Freitext |
| **UI** | „Bearbeiten"-Dialog (vormals „Umbenennen") mit Name/Kürzel/Details; Detailseite zeigt Details. |
| **Bewusst NICHT** | Die Schule einer Klasse ist nicht editierbar (Scope-Grenze, siehe Analyse). |

---

## „Details anzeigen": Klasse → User-Detail

Pro Schülerzeile in der Klassendetailansicht ein Link auf `/users/$guid`. Nur
sichtbar für Admin/SMI — die User-Detailseite (`GET /users/{guid}`) ist
`require_user_writer` (Admin/SMI), Schulleitung würde dort 404 erhalten.

---

## User-Dashboard + Edit-Modus

| | |
|---|---|
| **Endpoint** | `GET /users/{guid}/dashboard` → `{classes: [{class_id, name, kuerzel, jahrgangsstufe, teachers: [{ad_object_guid, display_name, upn, role}]}]}` |
| **RBAC** | `require_user_writer` (Admin/SMI der Schule des Users) |
| **UI** | Die User-Detailseite ist standardmäßig **read-only** (Dashboard: Klassen + KL, Name/Mail/Adresse/Gerät). Ein „Bearbeiten"-Button schaltet das Formular frei; Speichern/Abbrechen kehrt zur Lese-Ansicht zurück. |

---

## Passwort-Reset in der Klassenansicht + Schüler-Klassenfilter

- Die Schülertabelle der Klassendetailansicht hat eine **„Passwort zurücksetzen"**-Aktion
  (nutzt `ResetPasswordModal`).
- `GET /users?class_id=…` matcht jetzt **Schüler** (aktive `class_memberships`)
  **und** Lehrer (aktive `class_teacher_roles`) — die Suche über eine Klasse
  findet damit auch Schüler:innen.

---

## Admin: AD-Verbindungstest (nur LDAP)

| | |
|---|---|
| **Endpoint** | `POST /admin/ad-test` → `{ok: bool, detail: "ad_ok" \| "ad_bind_failed"}` |
| **RBAC** | `require_admin` |
| **Mechanik** | Read-only Service-Account-Bind über LDAPS (`AdClient.probe_service_connection`, `run_in_threadpool`). **Keine** Credentials in Response oder Log. |
| **Audit** | `ad_connection_tested` — Payload nur `{ok}` |
| **UI** | „Verbindung testen"-Button auf der Admin-Settings-Seite. |
| **Entra ID** | Bewusst **nicht** umgesetzt: ein User+Passwort-Test bräuchte den ROPC-Flow, der MFA/Conditional Access umgeht (siehe Analyse). |

---

## Schulübergang: einzelne Schüler verschieben

`POST /classes/{id}/promote` akzeptiert optional `student_guids: [str]`
(weglassen = alle aktiven Schüler:innen, wie bisher). Der Promote-Wizard listet
im Bestätigungsschritt die Schüler:innen mit Checkboxen (per Default alle
ausgewählt) und sendet nur die gewählten.

---

## Per-User-Einstellungen (Sprache, Region, Formate)

| | |
|---|---|
| **Migration** | `0013_user_preferences` — Tabelle `user_preferences` (PK `ad_object_guid`), Defaults `de`/`CH`/`DD.MM.YYYY`/`24h` |
| **Endpoints** | `GET /me/preferences`, `PUT /me/preferences` |
| **RBAC** | `get_current_user` (jede:r authentifizierte User für die eigenen Einstellungen; nur Staff loggt sich ein) |
| **Audit** | `user_preferences_updated` |
| **UI** | Einstellungs-Card auf `/me`; Speichern wendet die Sprache sofort an, das Layout wendet die gespeicherte Sprache nach dem Login an. |
| **Hinweis** | Region/Datums-/Zeitformat werden gespeichert und sind wählbar; die globale Anwendung der Formate auf jede Datumsausgabe ist noch nicht überall verdrahtet (Folgearbeit). |

---

## Rolle Fachlehrer (Fachlehrperson)

Siehe [ADR 0005](../adr/0005-fachlehrer-separate-table.md) für die Modellierungs-Entscheidung.

| | |
|---|---|
| **Migration** | `0014_subject_teacher_roles` — Tabelle `subject_teacher_roles` (class_id, ad_object_guid, **subject**, valid_from/to), getrennt von `class_teacher_roles` |
| **Endpoints** | `GET/POST /classes/{id}/subject-teachers`, `DELETE /classes/{id}/subject-teachers/{role_id}` |
| **RBAC (Zuweisung)** | `require_schulleitung` (organisatorische Entscheidung, wie KL) |
| **Audit** | `subject_teacher_assigned`, `subject_teacher_revoked` |
| **PW-Reset-Berechtigung** | `require_student_writer` akzeptiert nun zusätzlich einen **aktiven Fachlehrer** einer Klasse, in der der/die Schüler:in aktiv ist → Fachlehrer dürfen die PW *ihrer* Schüler:innen zurücksetzen. |
| **„Meine Schüler"** | `GET /me/students` → Schüler:innen aller Klassen, in denen der/die Aufrufer:in aktive:r KL **oder** Fachlehrer ist; UI-Seite `/my-students` (Nav-Eintrag). |
| **UI** | Eigene „Fachlehrpersonen"-Sektion in der Klassendetailansicht (Zuweisen mit Fach, Liste, Beenden). |

---

## Test- & CI-Stützpunkte (in diesem Batch ergänzt)

- Coverage-Gate in `backend-ci.yml` (`--cov-fail-under=75`).
- Neue Integrationstests: `test_schools_router`, `test_users_listing`,
  `test_substitutions_router`, `test_user_dashboard`, `test_class_promote`,
  `test_ad_test_endpoint`, `test_me_preferences`, `test_rename_integrity`,
  `test_subject_teachers`.
- Pre-commit spiegelt jetzt auch die Frontend-CI-Checks (eslint/prettier/tsc)
  und verdrahtet den pre-push-Stage via `default_install_hook_types`.
