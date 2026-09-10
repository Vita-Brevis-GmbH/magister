# ADR-0017 · Systemeinstellungen und Rechte gehören der Konsole

**Status:** angenommen, 2026-09-10
**Kontext:** [ADR-0013](0013-mandantenfaehigkeit-control-plane.md) (Steuerebene),
[ADR-0008](0008-modulare-funktionen.md) (Module),
[ADR-0010](0010-dynamische-rollen-rechte-matrix.md) (Rechte-Matrix),
Phase 3 in [multitenancy.md](../features/multitenancy.md)

## Problem

`/admin/app-settings` und `/admin/rbac` lassen einen **Kunden-Admin** die
Systemkonfiguration ändern: OIDC-Issuer, AD-Domänencontroller, Suchbasen,
Sync-Intervall, Modul-Freischaltung, Webserver-Zertifikat, und die
Rechte-Matrix, aus der sich alle Berechtigungen ableiten.

In einer Einzelinstallation ist das richtig: dort *ist* der Kunde der
Betreiber. In einer gehosteten Installation mit mehreren Schulträgern ist es
falsch, und zwar in drei Richtungen:

1. **Der Kunde kann sich selbst aussperren.** Ein falscher OIDC-Issuer, und
   niemand kommt mehr herein — der Betreiber muss an die Datenbank.
2. **Der Kunde kann sich Rechte geben, die der Betreiber vergibt.** Die
   Rechte-Matrix ist die Definition dessen, was eine Rolle darf. Wer sie
   ändern darf, ändert sein eigenes Recht.
3. **Der Kunde kann die Plattform berühren.** `admin_system` startet Prozesse
   neu, `admin_maintenance` schaltet den Wartungsmodus, `web_tls` schreibt das
   Zertifikat, das der Reverse Proxy liest. Auf einer Maschine mit mehreren
   Kunden ist das nicht seine Sache.

## Entscheidung

### D1 · „Von der Plattform verwaltet" ist eine Folge der Konfiguration, kein Schalter

Ist `MAGISTER_CONSOLE_REGISTRY_URL` gesetzt, holt die Datenebene ihre
Mandanten aus der Konsole — dann ist die Konsole der Betreiber, und die
System- und Rechte-Flächen der Kunden-API sind **nicht gemountet**. Ist der
Wert leer, ist es eine Einzelinstallation und alles bleibt wie heute.

Kein eigenes `MAGISTER_PLATFORM_MANAGED`. Dasselbe Muster wie bei
`ad_connector_enabled` (ADR-0014): „eingeschaltet, sobald eine Konsolen-URL
steht — kein eigener Schalter, sondern eine Folge der Konfiguration". Zwei
Schalter, die dasselbe bedeuten sollen, stehen irgendwann auf verschiedenen
Werten, und dann ist die Frage „welcher gilt?" eine Ausfallursache.

**Nicht gemountet, nicht 403.** Ein Endpunkt, der antwortet „das darfst du
nicht", ist noch da: er kann eine Lücke haben, er steht im OpenAPI-Schema, und
ein späterer Umbau kann die Prüfung verlieren. Was nicht gemountet ist, ist
ein 404 aus dem Router und kann nichts.

### D2 · Die Konsole besitzt die Politik. Die Geheimnisse bleiben beim Kunden

Das ist der Kern, und er widerspricht dem naheliegenden Entwurf.

Naheliegend wäre: alles nach oben, die Konsole hält die vollständige
Konfiguration jedes Kunden. Damit hielte sie auch das AD-Bind-Passwort, das
OIDC-Client-Secret, den privaten Webserver-Schlüssel — für **jeden** Kunden,
an **einem** Ort. Die Konsole ist aber genau der Ort, an dem wir bisher
konsequent keine Kundengeheimnisse haben: kein DSN (ADR-0013 D4, nur ein
Verweis), kein Kundenschlüssel (ADR-0016 D8), kein privater age-Schlüssel
(ADR-0016 D2). Wer die Konsole übernimmt, bekommt heute die Fähigkeit,
Sitzungen auszustellen — aber keine gespeicherten Geheimnisse. Das soll so
bleiben.

Also die Trennung:

| | Wo es lebt | Wer es setzt |
|---|---|---|
| **Politik** — Issuer, Client-Id, DC-Namen, Suchbasen, Intervalle, Modul-Freischaltung, Profil, Rechte-Matrix | Konsole; wird ins Kundenschema materialisiert | Betreiber in der Konsole |
| **Geheimnisse** — `oidc_client_secret`, `ad_bind_password`, `ninja_client_secret`, `web_tls_key` | ausschliesslich im Kundenschema, mit dem **Kundenschlüssel** verschlüsselt | Betreiber über `magister-cli` auf dem Anwendungsserver |

Der Preis ist ehrlich zu benennen: **das Einrichten eines Kunden ist damit
zweigeteilt.** Die Politik kommt aus der Konsole, die drei bis vier
Geheimnisse werden auf dem Anwendungsserver gesetzt. Ein Handgriff mehr pro
Kunde. Das ist billiger als ein Ort, an dem die Geheimnisse aller Kunden
liegen.

Die Absicherung dazu ist kein Vorsatz, sondern eine Prüfung: der
Einstellungs-Dienst der Konsole führt eine **Allowlist** der erlaubten
Schlüssel und lehnt jeden Namen ab, der wie ein Geheimnis aussieht
(`*_secret`, `*_password`, `*_key`, `*_enc`, `*_pem`). Ein Feld, das später
dazukommt und ein Geheimnis trägt, fällt beim ersten Schreiben auf und nicht
beim ersten Vorfall.

### D3 · Der Reconciler zieht, die Konsole schiebt nicht

Die Datenebene holt den Soll-Zustand ab — wie schon die Registry
(ADR-0013 D4). Nicht die Konsole schreibt in das Kundenschema.

Drei Eigenschaften folgen daraus, alle gewollt:

* **Die Konsole braucht keinen Datenbankzugang zum Kunden.** Sie hat keinen,
  und das bleibt so.
* **Ein Ausfall der Konsole ist kein Ausfall des Betriebs.** Ist sie nicht
  erreichbar oder antwortet sie unbrauchbar, bleibt der letzte gute Stand in
  Kraft. Ein leeres Ergebnis ersetzt nichts — sonst setzte ein Fehler in der
  Konsole alle Kunden zurück.
* **Die Reihenfolge ist beobachtbar.** Was materialisiert wurde, steht im
  Audit des Kunden; was gewünscht ist, in der Konsole. Weichen sie ab, ist
  das eine Frage, die man stellen kann.

### D4 · Jede Materialisierung ist ein kundensichtbares Audit-Ereignis — aber nur bei echter Änderung

Ändert der Betreiber die Konfiguration eines Kunden, gehört das in **dessen**
Audit-Protokoll. Der Kunde muss nachlesen können, dass jemand von aussen sein
Sync-Intervall verändert hat, und wann.

Aber nur, wenn sich wirklich etwas geändert hat. Ein Reconciler, der alle fünf
Minuten läuft und jedes Mal ein Ereignis schreibt, füllt das Protokoll mit
Rauschen und macht die echten Einträge unfindbar — das ist keine
Nachvollziehbarkeit, das ist ihr Gegenteil. Der Vergleich läuft feldweise, das
Ereignis nennt **alte und neue Werte** der geänderten Felder.

### D5 · Plattform-Capabilities kann keine Kundenrolle halten

Was nur der Betreiber darf, bekommt eigene Capabilities
(`platform.settings.manage`, `platform.rbac.manage`, `platform.tenant.manage`,
`platform.maintenance`). Sie stehen in derselben Aufzählung wie die anderen,
damit es *eine* Liste gibt — aber der RBAC-Dienst weist ihre Zuweisung an eine
Kundenrolle ab.

Die Prüfung liegt im Dienst und nicht in der Oberfläche: sie muss auch für den
Reconciler gelten, für das CLI und für eine von Hand geschriebene Zeile. Eine
Regel, die nur das Formular kennt, ist keine Regel.

## Was on-prem passiert: nichts

Eine Einzelinstallation ohne Konsole behält `/admin/app-settings`,
`/admin/rbac` und die zugehörigen Oberflächen unverändert. Das ist keine
Nachlässigkeit, sondern dieselbe Linie wie in ADR-0016 D9 („eine Gemeinde mit
einem Server bekommt keinen pgBackRest-Zwang"): die Härtung gilt dort, wo
mehrere Kunden auf einer Maschine liegen.

Damit hat die Fläche zwei Betriebsarten, und das ist eine Last. Sie wird von
einem Contract-Test getragen, der beide prüft: in der gehosteten Betriebsart
darf keine System- oder Rechte-Route existieren, in der Einzelinstallation
müssen sie da sein. Ohne diesen Test wäre die Zweiteilung eine Behauptung.

## Verworfene Alternativen

**Alles in die Konsole, Geheimnisse eingeschlossen.** Einfacher zu erklären
und ein einziger Ort zum Einrichten. Macht die Konsole zum Tresor aller
Kundengeheimnisse und wirft damit die Trennung weg, für die ADR-0013 und
ADR-0016 an jeder Stelle Aufwand betrieben haben.

**Endpunkte bleiben, mit einer Rechte-Prüfung davor.** Weniger Umbau. Aber
eine Prüfung kann verloren gehen, und die Fläche bleibt im OpenAPI-Schema
sichtbar — inklusive der Felder, die es beim Kunden nicht mehr gibt.

**Die Konsole schreibt direkt ins Kundenschema.** Kein Reconciler, sofortige
Wirkung. Verlangt, dass die Konsole Datenbankzugang zu jedem Kunden hat —
genau das, was sie nicht haben soll.

**Ein Schalter `MAGISTER_PLATFORM_MANAGED`.** Ausdrücklich statt abgeleitet.
Zwei Werte, die dasselbe bedeuten, laufen auseinander; die Frage „welcher
gilt" ist dann eine Ausfallursache und kein Detail.
