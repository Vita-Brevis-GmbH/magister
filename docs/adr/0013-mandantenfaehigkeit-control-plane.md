# ADR 0013: Mandantenfähigkeit — Control Plane plus Schema-Trennung pro Kunde

**Status:** Vorschlag · 2026-09-08
**Kontext:** Mehrere Kunden (Schulträger und Firmen) auf einer gehosteten
Magister-Installation, mit einer eigenen Global-Admin-Oberfläche.
**Ersetzt:** SPEC §2 Non-Goal „Mehrere Schulträger pro Instanz"

## Problem

Magister ist heute strikt einmandantig: `app_settings` ist eine Singleton-Zeile
(`CHECK id = 1`), der Datenscope endet bei `school_id`, `role_assignments.role='admin'`
ist die kundeninterne Super-Rolle, und ein Deployment gehört genau einem
Schulträger. Das Cockpit (ADR-0003) verwaltet zwar mehrere *Instanzen*, kennt
aber bewusst keine Kundendaten und keine Kundenkonfiguration.

Der Product Owner will:

1. Eine **Global-Admin-Oberfläche**, in der alle Kunden erfasst und die
   Systemeinstellungen *pro Kunde* gepflegt werden.
2. **Rechte** (Rollen-/Capability-Matrix) ausschliesslich dort — nicht mehr beim Kunden.
3. **Systemeinstellungen** nur noch für Global Admins sichtbar.
4. **Vorlagen** global pflegen und auf Kunden anwenden.
5. Kunden melden sich unter einem **eigenen Web-Pfad** an.
6. **Kundentrennung vollständig auf Datenbankebene**, damit kein Kunde einen
   anderen beeinflussen kann.
7. Nur **Global Operatoren und Admins** sehen alle Kunden und wählen nach dem
   Login, welchen Kunden sie bedienen.

## Entscheidung

### D1 · Trennung: Schema pro Kunde plus eigene Datenbankrolle

Jeder Kunde erhält ein eigenes Postgres-Schema (`t_<slug>`) **und eine eigene
Datenbankrolle** (`r_<slug>`), der `USAGE` auf alle anderen Kundenschemas
entzogen ist. Pro Transaktion setzt die Anwendung `SET LOCAL ROLE` und
`SET LOCAL search_path`; beides endet mit der Transaktion, ein
Verbindungs-Pool kann also nichts weitertragen. Vor dem ersten Query prüft eine
Zusicherung, dass `current_user` zum Kunden der Anfrage passt.

Damit ist die Trennung **von Postgres erzwungen, nicht von der Anwendung**: ein
vergessener Filter liefert keine fremden Zeilen, sondern einen Fehler.

Die Mandanten-Registry speichert pro Kunde **DSN + Schema**. Dadurch sind
„eigenes Schema", „eigene Datenbank" und „eigener Cluster" derselbe Code-Pfad
und unterscheiden sich nur im Registry-Eintrag — ein grosser oder besonders
regulierter Kunde wird umgezogen, nicht umgebaut.

### D2 · Control Plane als eigene Anwendung (das Cockpit wächst dazu)

Die Global-Admin-Oberfläche ist **kein Magister-Modul**, sondern die
Weiterentwicklung des bestehenden `cockpit/` zur Control Plane („Magister
Console"): eigene Datenbank, eigene Anmeldung, eigene Origin. Sie hält
Mandanten-Registry, Kundenkonfiguration, globale Vorlagen, globale
Rechte-Matrix, Bereitstellungs-Aufträge und das Plattform-Audit — und
**keinerlei Personendaten der Kunden**. Damit bleibt ADR-0003 („Schulträger
sehen das Cockpit nie", keine Vermischung der RBAC-Modelle) gültig.

Die heutige Cockpit-Anmeldung (Bootstrap-Token + Basic-Auth hinter VPN) genügt
dafür **nicht** und wird auf OIDC gegen den Entra-Tenant von Vita Brevis mit
Hardware-Schlüssel und verwaltetem Gerät umgestellt: Die Konsole kann Sitzungen
in jeden Kunden ausstellen und ist damit das höchstwertige Ziel im System.

### D3 · Origins und Pfade

- Konsole: **eigene Origin** (`console.magister.ch`) auf einem **eigenen
  Listener** (TCP 4444), nur auf der Management-Adresse veröffentlicht und mit
  Client-Zertifikat — siehe [ADR-0015](0015-authentisierungs-haertung.md) D1.
  Der Kunden-vhost auf 443 routet nie zur Konsole.
- Kunden: `magister.ch/k/<slug>/…`, Session-Cookie mit `Path=/k/<slug>`;
  optional später eine eigene Domain pro Kunde.

Der Cookie-Pfad ist **Bequemlichkeit, keine Sicherheitsgrenze** (ein Operator
kann parallel in zwei Kunden angemeldet sein). Die Grenze ist serverseitig: die
Session-Zeile trägt `tenant_id`, eine Session von Kunde A auf dem Pfad von
Kunde B ist ein hartes 401.

Offen und zu entscheiden (siehe Plan, Entscheid E1): alle Kunden auf **einer**
Origin teilen sich Browser-Storage und XSS-Radius. Eine Subdomain pro Kunde
(`<slug>.magister.ch`) wäre die echte Trennung; der Pfad bleibt dann als Alias.

### D4 · Konsole ist Autorenstelle, Kundenschema hält die Kopie

Konfiguration (Systemeinstellungen, Rechte-Matrix, globale Vorlagen, Module)
wird in der Konsole **geschrieben** und von einem Reconciler als
schreibgeschützte Kopie in jedes Kundenschema **materialisiert**.

Kein Kunden-Request liest je die Konsolen-Datenbank. Das erhält die
Trennungs-Invariante im heissen Pfad, lässt jeden Kunden bei einem Ausfall der
Konsole weiterlaufen, und macht jeden Rollout im Kunden-Audit sichtbar
(`settings_pushed`, `templates_pushed`).

### D5 · Systemeinstellungen und Rechte verlassen die Kunden-API strukturell

`/admin/app-settings` und `/admin/rbac` werden **nicht** hinter eine neue
Capability gestellt, sondern aus der Kunden-API **entfernt** und in der Konsole
neu angesiedelt. Auch ein übernommener Kunden-Admin oder ein Fehler in der
Rechteprüfung kann sie dann nicht erreichen — es gibt keine Route.

Neue Plattform-Capabilities (`platform.tenant.manage`, `platform.settings.write`,
`platform.rights.write`, `platform.templates.publish`,
`platform.tenant.impersonate`) existieren ausschliesslich in der Konsole; keine
Kundenrolle kann sie halten.

Der Anmeldeweg des Kunden reduziert sich damit auf OIDC gegen Entra; der lokale
Notzugang entfällt gehostet ganz und der direkte AD-Login verschwindet aus dem
Code (ADR-0015 D2, D3).

### D6 · Operator-Zugriff ist befristet, begründet und für den Kunden sichtbar

Die Konsole stellt keine Kunden-Session direkt aus. Sie erzeugt eine signierte,
einmalig einlösbare Assertion (TTL 60 s), die die Kunden-API gegen eine
befristete Session (60 min) tauscht. Jeder Zugriff verlangt Grund oder
Ticketnummer und erscheint **im Audit des Kunden** sowie in einer für den Kunden
sichtbaren Liste „Zugriffe von Vita Brevis" — mit laufendem Hinweisbalken
während des Zugriffs.

### D7 · Migrationen als Fan-out mit Kanarienvogel und Versions-Schranke

Alembic läuft pro Schema (`version_table_schema`), gesteuert von einem Runner,
der die Registry abläuft: erst ein Kanarienvogel-Kunde, dann Wellen. Der Stand
pro Kunde steht in der Registry. Passt der Stand eines Kunden nicht zur
Kopf-Version des Codes, wird dieser Kunde mit **503 Wartung** bedient statt mit
möglicherweise falschen Queries. Migrationen sind pro Release **nur erweiternd**
(expand/contract über zwei Releases).

### D8 · Ein Codebase, zwei Betriebsarten

`MAGISTER_MULTITENANT=0` (Default) heisst: genau ein Mandant, aufgelöst ohne
Pfad-Präfix. Die bestehenden On-Prem-Installationen bleiben damit unverändert
gültig und unterstützt; die gehostete Mehrmandanten-Variante ist eine
**zusätzliche Betriebsart**, kein Ersatz.

### D9 · Geheimnisse pro Kunde

`MAGISTER_AUDIT_KEY` ist heute installationsweit. Künftig hat jeder Kunde einen
eigenen Datenschlüssel, verpackt in einem Plattform-Schlüssel (Envelope). Ein
kompromittierter Kundenschlüssel entschlüsselt nichts von anderen Kunden. Dasselbe
gilt für AD-Bind-Passwort und OIDC-Client-Secret.

### D10 · AD-Erreichbarkeit über einen ausgehenden On-Prem-Connector

Eine gehostete Installation erreicht die Domänencontroller im Kundennetz nicht.
Die AD-Grenze aus ADR-0011 löst das: ein Connector-Agent bleibt beim Kunden vor
Ort und baut die Verbindung **ausgehend** zur Plattform auf (heute ist AD-RPC
eingehend im Docker-Netz — das ist die eigentliche Änderung). Nur er hat
AD-Credentials und Netzzugang zu den DCs; LDAP verlässt das Kundennetz nie.

Absicherung, Anmeldeverfahren und Auslieferung des Agenten sind in
[ADR-0014](0014-ad-connector-agent.md) ausgeführt: zwei unabhängige Faktoren
(mTLS gegen eine private CA plus API-Key), Schlüsselerzeugung auf dem Agenten,
Bezug des Pakets beim Erfassen des Kunden.

## Konsequenzen

**Positiv**

- Trennung ist von Postgres erzwungen und damit prüfbar, nicht bloss
  konventionell.
- Die 43 bestehenden Migrationen und der komplette Repository-Layer bleiben
  unverändert: kein `tenant_id` in jeder Tabelle, kein Umschreiben jedes Queries.
- Systemeinstellungen und Rechte sind für Kunden nicht erreichbar, weil die
  Routen fehlen — die stärkste Form dieser Anforderung.
- Vorlagen und Rechte einmal pflegen, kontrolliert ausrollen, pro Kunde
  nachvollziehbar.
- „Eigene Datenbank" und „eigener Cluster" sind ein Registry-Eintrag, kein Umbau.
- Bestehende On-Prem-Kunden sind nicht betroffen (D8).

**Negativ**

- Die Konsole ist ein neues, hochwertiges Angriffsziel und braucht ein
  entsprechendes Härtungs- und Auditniveau.
- Verbindungen und Migrationen skalieren mit der Kundenzahl; pgbouncer,
  Pool-Obergrenzen pro Kunde und ein Wellen-Runner werden Pflicht.
- Konfiguration existiert an zwei Orten (Autorenstelle plus Kopie); der
  Reconciler muss idempotent und beobachtbar sein.
- Gehostet ist Vita Brevis Auftragsverarbeiter für Personendaten von
  Minderjährigen. Das verlangt Auftragsverarbeitungsverträge, dokumentierte
  Trennung, Datenhaltung in der Schweiz — und eine Revision der
  Zero-Phone-Home-Politik, die für eine selbst gehostete Plattform eine andere
  Bedeutung hat.
- Der ausgehende On-Prem-Connector (D10) ist neue Infrastruktur beim Kunden.

## Alternativen verworfen

- **Gemeinsame Tabellen mit `tenant_id` (plus Row Level Security).** Billigste
  Variante, aber die Trennung hängt an einem Prädikat in jedem Query. Verlangt
  eine Spalte und einen Index in fast jeder Tabelle, berührt jedes Repository und
  jede Migration — und erfüllt „vollständig auf Datenbankebene" nur unter der
  Annahme, dass jede RLS-Policy korrekt ist.
- **Konsole als Magister-Subapp** (`/admin/global`). Würde genau die
  RBAC-Vermischung einführen, die ADR-0003 vermeidet: die kundenübergreifende
  Super-Rolle liefe in derselben Anwendung und derselben Origin wie die
  Kundenoberfläche.
- **Weiter eine Instanz pro Kunde, nur zentral gesteuert.** Erfüllt die
  Anforderung „Kunden erfassen und Systemsettings zentral machen" nur indirekt,
  bleibt bei N Deployments, N Update-Fenstern, N Zertifikaten — und der Kunde
  behält technisch Zugriff auf seine Systemeinstellungen.
- **Eine Datenbank pro Kunde von Beginn an.** Härter, aber teurer in Betrieb und
  Migration, ohne dass die meisten Kunden es brauchen. Über D1 jederzeit
  nachträglich erreichbar.
