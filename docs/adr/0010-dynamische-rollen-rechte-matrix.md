# ADR-0010 — Voll dynamische Rollen + Rechte-Matrix

- **Status:** Accepted
- **Date:** 2026-08-25
- **Context:** M6 Company-Readiness, Korrektur #3
- **Supersedes in part:** ADR-0008 §Capabilities (the static `ROLE_CAPABILITIES` map)

## Kontext

Bis M6 Phase 3 war die Autorisierung zweistufig (ADR-0008): Endpoints fordern
eine **Capability**, und eine **im Code fest verdrahtete** Tabelle
`ROLE_CAPABILITIES` entscheidet, welche Rolle welche Capability hält. Die Rollen
selbst (`admin`, `schulleitung`, `smi`, `kl`) sind Konstanten.

Für Firmen/Organisationen reicht das nicht: Betreiber wollen **eigene Rollen**
definieren und die **Rechte pro Rolle als Matrix** selbst pflegen, ohne Deploy.
Korrektur #3, gewählte Variante: *„Voll dynamische Rollen"*.

## Entscheidung

Die **Rolle→Capability-Zuordnung wird Daten** statt Code. Die **Capabilities
bleiben Code** — sie sind der stabile Vertrag, der an Endpoints verdrahtet ist;
eine Capability ohne zugehörigen Endpoint gibt es nicht. Betreiber schalten also
vorhandene Capabilities pro Rolle an/aus und legen eigene Rollen an — sie
erfinden keine neuen Capabilities.

### Datenmodell (Migration `0039_rbac_roles`)

- `roles` — eine Zeile je Rolle:
  `key` (slug, unique), `name`, `is_system` (bool), `is_admin` (bool,
  Super-Rolle), `is_derived` (bool, z. B. `kl` — nicht zuweisbar, keine
  Coarse-Caps), `created_at`, `updated_at`.
- `role_capabilities` — die editierbare Matrix: `(role_key, capability)`,
  Fremdschlüssel auf `roles.key` mit `ON DELETE CASCADE`.

Die Migration legt nur das Schema an. **Seed** der System-Rollen und der
Default-Matrix passiert idempotent beim App-Start (`RbacService
.seed_defaults_if_empty`), analog zu `local_admin`/`app_settings`. Quelle des
Seeds ist `default_role_capabilities()` in Code — nach dem Seed ist das Verhalten
**identisch** zur bisherigen `ROLE_CAPABILITIES`-Tabelle, daher bleiben alle
bestehenden Autorisierungstests unverändert grün.

### Laufzeit

- `RbacMatrix` (frozen) = `{role_key: frozenset[Capability]}` + `admin_roles`.
- `get_rbac_matrix(session)` — FastAPI-Dependency, lädt die Matrix pro Request
  (eine kleine indizierte Query; dieselbe Kostenklasse wie der bereits
  bestehende `make_module_guard`, der `app_settings` pro Request liest). Kein
  In-Process-Cache → keine Invalidierungs-Bugs; die Rechteänderung greift sofort.
- `has_capability(user, matrix, *required)` / `effective_capabilities(user,
  matrix)` sind **pure Funktionen** mit injizierter Matrix. `require_capability`
  reicht die Matrix per Dependency herein. Unbekannte Capabilities in der DB
  (z. B. nach Entfernen einer Capability aus dem Code) werden beim Laden
  ignoriert — die DB kann nie mehr Rechte gewähren als der Code kennt.

### Super-Rolle & abgeleitete Rolle

- `admin` bleibt die einzige Super-Rolle (`is_admin`, `school_id = NULL`,
  cross-school) und hält **implizit jede** Capability — ihre Matrix-Zeile ist
  nicht editierbar. `is_admin` am `AuthenticatedUser` wird weiterhin allein aus
  der `admin`-Zuweisung abgeleitet; eigene Rollen können nie Super-Rolle werden.
- `kl` bleibt abgeleitet (`is_derived`) aus `class_teacher_roles`, hält keine
  Coarse-Cap, ist nicht zuweisbar und nicht editierbar.

### Scope-Modell (unverändert generalisiert)

Bisher trug eine Zuweisung genau dann zum `school_scope` bei, wenn
`role ∈ {schulleitung, smi}`. Neu: **jede** Zuweisung mit `school_id != NULL`
trägt bei; `admin` (NULL) ist cross-school. Das ist für die bestehenden Rollen
verhaltensgleich (admin=NULL, schulleitung/smi immer mit `school_id`) und lässt
eigene Rollen sofort standort-scoped funktionieren, ohne eine zweite
Scope-Achse einzuführen. Eigene Rollen werden daher — wie schulleitung/smi — je
Standort zugewiesen (cross-standort = Zuweisung je Standort). Nur `admin` ist
NULL-scoped.

### Admin-API `/admin/rbac`

- `GET /admin/rbac` → `{capabilities: [...], roles: [{key,name,flags,capabilities}]}`
- `POST /admin/rbac/roles` — eigene Rolle anlegen `{key,name}`
- `PATCH /admin/rbac/roles/{key}` — umbenennen
- `PUT /admin/rbac/roles/{key}/capabilities` — Capability-Set der Rolle setzen
- `DELETE /admin/rbac/roles/{key}` — eigene (Nicht-System-)Rolle löschen

Guard überall `require_admin`. Invarianten serverseitig erzwungen: die
`admin`-Zeile ist nicht editier-/löschbar; System-Rollen sind nicht löschbar
(aber ihre Caps editierbar); abgeleitete Rollen (`kl`) sind nicht editierbar;
jede Mutation schreibt ein Audit-Event.

## Konsequenzen

- **+** Betreiber pflegen Rollen & Rechte als Matrix, ohne Deploy.
- **+** Endpoints bleiben unverändert (`require_capability(...)`); keine bare
  Rollennamen lecken in Feature-Module.
- **+** Kein Cache → deterministisch, sofort wirksam; Kostenklasse wie bestehende
  Per-Request-Reads.
- **−** Ein zusätzlicher kleiner Query pro geschütztem Request. Für eine
  Gemeinde/Instanz vernachlässigbar; falls je nötig, ist ein
  generationsbasierter Cache eine reine spätere Optimierung.
- **−** Die Capability-Liste bleibt Code-gebunden (bewusst): neue Rechte
  brauchen einen Endpoint und damit einen Deploy.
- **Frontend-Nav** gated weiter auf Rollennamen/`is_admin` (kosmetisch); die
  eigentliche Durchsetzung ist serverseitig über Capabilities. Eigene Rollen
  erscheinen in der Nav erst, wenn sie dort explizit berücksichtigt werden — die
  Autorisierung greift aber unabhängig davon.
