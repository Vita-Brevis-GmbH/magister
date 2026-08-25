# ADR 0008: Modulare Funktionen mit Profil-Preset (Company-Readiness)

**Status:** Vorgeschlagen · 2026-08-21
**Kontext:** M6 — Magister über die Schule hinaus (Company/Mischbetrieb)

## Problem

Magister ist heute tief „Schule"-geformt: `classes`, `class_teacher_roles`,
`subject_teacher_roles`, `class_memberships`, Schuljahresübergang (`promote`),
Zyklus/Jahrgangsstufe und Eltern-Briefe sind über Router, Services und Models
verteilt. Darunter liegt aber eine völlig domänenneutrale Basis: AD-Sync
(`ad_user_cache`), Passwort-Reset, Enable/Disable-Lifecycle, Devices, Audit,
Imports, Reports, OIDC, RBAC und der `school_id`-Scope-Filter.

Wir wollen Magister für **Firmen (Companies)** einsetzbar machen, ohne eine
zweite Codebasis zu betreiben. Die Anforderungen an Schulen und Firmen sind
fachlich verschieden, die Basis ist aber dieselbe.

Wichtige Präzisierungen aus der Produkt-Diskussion (Product Owner):

- **Kein harter „Schule oder Firma"-Schalter.** Der Betrieb ist gemischt: Eine
  Schule will z.B. `Klassen` **und** `Abteilungen` (für Schulsekretariat,
  Schulkommission), aber **keine** `Projektgruppen`. Umgekehrt bei Firmen. Wer
  was will, ist nicht vorhersehbar.
- **Funktionen einzeln schaltbar.** Jede fachliche Funktion soll sich über eine
  Admin-Seite als „Schieber" an-/ausschalten lassen — auch zur Wiederverwendung
  von „Company"-Ideen im Schulkontext.
- **Ein allgemeiner Schieber setzt die Grundeinstellung.** Wählt man „Schule",
  gehen die sinnvollen Start-Module automatisch an; weitere lassen sich
  dazunehmen. Analog für „Firma".

## Entscheidung

Wir führen eine **Feature-Modul-Architektur mit weichem Profil-Preset** ein.
Kern sind acht Entscheide:

### D1 — Drei Schichten statt zwei Produkte

- **Plattform (Basis, immer aktiv):** Identity/AD, OIDC, User-Cache,
  PW-Reset, Enable/Disable, Devices, Audit, RBAC-Engine, Scope-Engine,
  Import-Engine, Reporting-Engine, Settings, i18n, WebUI-Shell.
- **Feature-Module (der fachliche Oberbau, austauschbar/mischbar):** z.B.
  `classes`, `subject_teachers`, `substitutions`, `promotion`, `letters`
  (heute Schule) sowie neue Module wie `departments`, `manager_roles`,
  `onboarding` (Firma) — aber frei mischbar, nicht an eine „Edition" gebunden.
- **Profil (weiches Preset):** `school` / `company` / `neutral` — setzt nur
  Vokabular und ein empfohlenes Start-Set. Es **sperrt nichts**.

### D2 — Modul-Registry als einzige Kompositionsnaht

Heute koppeln nur zwei Stellen fachliche Funktionen fest ans System:
`main.py` (27× `include_router(...)`) und `Layout.tsx` (hartkodierte Nav).
Beide werden entkoppelt:

- **Backend:** Jedes Modul ist ein Package `magister_api/modules/<id>/` mit
  einem `ModuleManifest` (siehe unten). `create_app()` iteriert die
  **aktivierten** Module aus der Registry und mountet deren Router, statt sie
  hart zu listen.
- **Frontend:** Jedes Modul liegt unter `web/src/modules/<id>/` (Routes, Nav,
  Komponenten, Hooks, i18n-Namespace). `Layout` rendert die Nav aus einem
  neuen Endpoint `GET /me/modules`; der `beforeLoad`-Guard in `_app.tsx`
  (prefetcht heute schon `/auth/me`) sperrt Routen deaktivierter Module.

### D3 — Das Modul ist die atomare Einheit; Kategorien sind nur Anzeige

Es gibt **keinen** Kategorie-Sammelschalter. Jedes Modul hat genau einen
eigenen Schieber. Kategorien (Organisation, Konten, Geräte, Kommunikation,
Auswertungen, Lifecycle …) sind ausschliesslich eine optische Gruppierung der
Admin-Liste. So bleibt „Klassen ja, Abteilungen ja, Projektgruppen nein" in
derselben Instanz möglich.

### D4 — Profil ist ein weiches Preset, kein Gate

- `instance_profile` (`school` / `company` / `neutral`) treibt **nur** das
  Top-Level-Vokabular (Term-Pack, siehe D7-Bezug unten) und ist die Quelle des
  empfohlenen Start-Sets.
- „Profil anwenden" ist eine **Aktion**, kein Dauerzustand: sie schreibt das
  Start-Set **additiv** in `module_settings`. Ein Profilwechsel wischt die
  Eigenwahl nicht weg — er bietet an, das neue Start-Set draufzulegen.
- Neu ausgelieferte Module starten `enabled=false` und erscheinen als „neu
  verfügbar", statt bei bestehenden Instanzen still anzugehen.

### D5 — Modularer Monolith, split-fähig (nicht Container-pro-Modul)

Ein `magister-api`- und ein `magister-web`-Container. Module sind
Code-Packages, „Modul starten" = Schieber kippen (Runtime, ohne Deploy).

Der Schieber (Runtime-Komposition) und der Container (Deployment/Distribution)
sind **zwei getrennte Achsen**. Im Mischbetrieb teilen alle Module denselben
User-Bestand, dieselben Scope-Rows, denselben Audit-Key und dieselbe Session —
im Monolith ein Funktionsaufruf, über Container-Grenzen ein verteiltes System
mit geteiltem Secret. Der Schieber zwingt daher **nicht** zu Containern.

Module werden aber mit **sauberen Grenzen** gebaut (siehe D8), sodass ein
einzelnes Modul später mechanisch in einen eigenen Container wandern kann —
wenn eines dieser Kriterien real wird: getrennte Auslieferung/Lizenzierung,
eigene Skalierung, eigener Release-Takt/Team, Fehler-Isolation. Der Weg ist der
`git subtree split`, den `cockpit/` (ADR-0003) bereits vorzeichnet.

### D6 — Parallele Domänen-Tabellen statt generischem Diskriminator-Modell

Die mittlere Hierarchie-Ebene (Schule→Klasse→Schüler bzw.
Firma→Abteilung→Mitarbeiter) wird **nicht** in ein generisches
`groups`-Modell mit `kind`-Diskriminator gepresst. Stattdessen behält das
`classes`-Modul seine Tabellen unverändert, und ein `departments`-Modul bekommt
eigene Tabellen. Grund: Im Mischbetrieb sind `classes` **und** `departments`
gleichzeitig aktiv (siehe D3-Beispiel) — ein Diskriminator-Modell würde hier
klemmen und den reifen, getesteten Klassen-Pfad (Promote, Zyklus, Fachlehrer)
gefährden. Konsistent mit ADR-0005 (Fachlehrer eigene Tabelle).

### D7 — RBAC von Rollennamen auf Capabilities

Router prüfen heute schul-gefärbte Rollennamen (`schulleitung`, `kl`, `smi`).
Darunter führen wir **Capabilities** ein (`reset_password`,
`manage_memberships`, `manage_units` …); jedes Profil mappt seine Rollennamen
darauf. Module prüfen Capabilities, nicht Rollennamen. Term-Packs relabeln die
Rollen im UI (`kl` → „Teamleiter", `schulleitung` → „HR/Standortleitung"). So
bleibt die RBAC-Engine domänenneutral und mischbetriebsfähig. Das ist ein
inkrementeller Umbau (bestehende `require_*`-Dependencies bleiben als dünne
Wrapper erhalten), kein Big Bang.

### D8 — Die „Niemals/Immer"-Regeln werden zu Modul-Verträgen

Statt die CLAUDE.md-Hard-Rules pro Modul manuell einzuhalten, deklariert das
Manifest sie, und ein CI-Check erzwingt sie:

- Modul deklariert seine `audit_actions` → CI prüft, dass jede Mutations-Route
  ein Event emittiert (Allowlist-Beitrag zentral registriert).
- Modul deklariert sein Scope-Modell → CI prüft `school_id`-Filter bzw. den
  expliziten `# scope-bypass:`-Marker je Query.
- Modul deklariert `required_capability` je Route → CI prüft die RBAC-Dependency.
- Modul bringt seinen i18n-Namespace → CI prüft „keine Hardstrings, alle vier
  Sprachen de/fr/it/en vorhanden".

## Modell im Detail

### Zwei-Ebenen-Schaltung (Admin-Seite „Module & Funktionen")

```
PROFIL (allgemeiner Schieber):  Schule · Firma · Neutral
  → setzt Vokabular (Schule/Standort, Klasse/Team …)
  → wendet EINMALIG ein empfohlenes Start-Set an (additiv, sperrt nichts)
        ⇣ seedet Defaults
EINZEL-SCHIEBER pro Modul (die Wahrheit, frei mischbar):
  Klassen           [on]   ← aus Profil „Schule"
  Abteilungen/Teams [on]   ← selbst dazugenommen (Sekretariat, Kommission)
  Projektgruppen    [off]  ← bewusst aus
  On-/Offboarding   [off]
  …
```

### Datenablage

- **`instance_profile`** (`school`/`company`/`neutral`): Label-/Preset-Quelle,
  kein Gate. Liegt in `app_settings` (Singleton-Row, versioniert).
- **`module_settings[<id>]`**: `enabled` (bool) + modul-eigenes JSONB-Config.
  Die tatsächliche Wahrheit, was an ist. Versioniert wie `app_settings`, damit
  der bestehende `effective_settings`-Overlay die Änderung live und ohne
  Neustart zieht (version-gestempelter Cache, wie beim OIDC/AD-Client-Cache).
- **Guardrails:** `platform` ist nicht abschaltbar. Ein Modul mit Daten geht
  nur „soft off" (Daten bleiben erhalten, Wiedereinschalten stellt alles her).
  Der Schieber ist **abhängigkeitsbewusst** (siehe `depends_on`): Wird eine
  Basis ausgeschaltet, werden ihre Aufbauten mit ausgegraut/deaktiviert.

### ModuleManifest (Backend, Skizze)

```python
ModuleManifest(
    id="school",
    depends_on=["platform"],
    profiles_default={"school"},      # Teil welchen Profil-Start-Sets
    routers=[classes_router, class_teachers_router, subject_teachers_router, ...],
    audit_actions=["class_teacher_assigned", "student_provisioned", ...],
    nav=[NavItem(key="nav.classes", to="/classes", capability="view_groups")],
    settings_schema=SchoolSettings,   # Zyklus-Grenzen etc. leben hier, nicht global
)
```

`create_app()`:

```python
for module in registry.enabled(profile=eff.instance_profile, overrides=eff.module_settings):
    for router in module.routers:
        app.include_router(router)
```

## Company-Readiness konkret

1. **Scope-Vokabular verallgemeinern — ohne Rename.** Die `schools`-Tabelle
   bleibt physisch die oberste Scope-Einheit; der `school_id`-Filter und die
   CI-Invariante bleiben **unangetastet**. Im Firmen-Vokabular ist eine
   „school"-Row eben ein Standort/eine Firma. Nur das Label wechselt (Term-Pack
   je `instance_profile`). Ein sauberer Rename `school_id` → `org_unit_id`
   bleibt optionale, spätere Kosmetik und ist bewusst **nicht** Teil dieses ADRs.
2. **School-Domäne ins `school`-Modul extrahieren** — reines Verschieben hinter
   die Registry, Verhalten unverändert, alles bleibt standardmässig aktiv.
3. **`company`-Modul bauen** (`departments`, `manager_roles`, `memberships`,
   `onboarding`/`offboarding`) — nutzt PW-Reset, Lifecycle, Devices, Imports,
   Audit, Reports der Plattform.
4. **Term-Packs** als i18n-Overlay je Profil (Schule/Standort, Klasse/Team,
   KL/Teamleiter …). Modul-eigenes Vokabular gehört dem Modul: eine Schule
   sieht oben „Schule", das dazugeschaltete Abteilungen-Modul heisst trotzdem
   „Abteilung".

## Konsequenzen

**Positiv:**

- Eine Codebasis, ein Deployment-Stack — Schule und Firma teilen sich die
  ganze Basis (Auth, Scope, Audit, AD) reibungslos.
- Freier Mischbetrieb pro Instanz; keine Schwarz-Weiss-Entscheidung.
- Neue Funktionen („auch für Schulen interessant") landen als weiteres Modul im
  selben Katalog, statt als Fork.
- Modularität und Sicherheit ziehen am selben Strang: Die Hard-Rules werden pro
  Modul strukturell geprüft (D8).
- Runtime-Schaltung ohne Neustart über den bereits vorhandenen
  `effective_settings`-Mechanismus.
- Split-fähig: ein Modul kann später ohne Rewrite zum eigenen Container werden.

**Negativ:**

- Die Registry-Naht (Phase 0) ist ein nicht-triviales Refactoring quer durch
  `main.py`, `Layout.tsx` und die Router-/Route-Struktur — Aufwand ohne
  sofortigen fachlichen Zugewinn (aber voll rückwärtskompatibel).
- Etwas Code-Duplikation zwischen `classes` und `departments` (bewusst, D6).
- Abhängigkeitsgraph + „soft off"-Semantik erhöhen die Komplexität der
  Admin-Seite.
- Der Capability-Umbau (D7) berührt viele Router (inkrementell, aber breit).

## Alternativen verworfen

- **Harter `EDITION=school|company`-Schalter:** widerspricht dem Mischbetrieb
  (Schule mit Abteilungen) und der Wiederverwendung von „Company"-Ideen in
  Schulen. Zugunsten des weichen Profil-Presets (D4) verworfen.
- **Ein Container pro Modul/Untermenü:** würde Session, CSRF, Audit-Key und den
  `school_id`-Scope-Filter über Netzwerk-Grenzen erzwingen und den Mischbetrieb
  erschweren statt erleichtern. Auf eine spätere Pro-Modul-Entscheidung
  verschoben (D5).
- **Kategorie-Sammelschalter:** würde die „Klassen ja / Projektgruppen nein"-
  Feinsteuerung verhindern. Kategorien bleiben reine Anzeige (D3).
- **Generisches `groups`-Modell mit `kind`-Diskriminator:** klemmt im
  Mischbetrieb und gefährdet den reifen Klassen-Pfad. Zugunsten paralleler
  Tabellen verworfen (D6).
- **Zweite Codebasis „Magister für Firmen":** doppelte Pflege von Auth, AD,
  Audit, Security-Härtung — genau das, was die Plattform-Schicht vermeidet.

## Umsetzung

Schrittweise über **M6** (siehe `ROADMAP.md`). Jede Phase ist einzeln
lieferbar und rückwärtskompatibel:

- **Phase 0 — Modul-Naht (kein Verhaltenswechsel):** Registry + Manifest,
  bestehende Router in `platform` + `school` einsortieren, Nav aus
  `GET /me/modules`. Prod läuft unverändert weiter.
- **Phase 1 — Schalter & Profil:** `instance_profile` + `module_settings` in
  `app_settings`, Admin-Seite „Module & Funktionen" mit Zwei-Ebenen-Schaltung,
  Term-Packs, `/me/modules`.
- **Phase 2 — Company-MVP:** `departments` + `manager_roles` + `memberships` +
  On-/Offboarding, Firmen-Term-Pack.
- **Phase 3 — Härten & optional splitten:** Capability-RBAC vollenden (D7),
  Modul-Vertrags-CI (D8); ein Modul bei Bedarf in einen eigenen Container
  promoten (D5).

## Offene Punkte (bewusst später)

- Rename `school_id` → `org_unit_id` (Kosmetik, nicht Teil dieses ADRs).
- Genauer Zuschnitt der Capability-Liste (wird in Phase 3 mit dem konkreten
  Company-Modul festgezurrt).
- Ob `departments` und `classes` mittelfristig eine gemeinsame
  Mitgliedschafts-Mechanik teilen (nach Erfahrungswerten aus Phase 2 neu
  bewerten).
