# ADR-0021 · Betrieb im Grossen: Wellen, Grenzen und Befunde

**Status:** angenommen, 2026-09-11
**Kontext:** [ADR-0013](0013-mandantenfaehigkeit-control-plane.md) D1 (Schema je
Kunde, eigene Rolle), D4 (die Datenebene zieht, die Konsole schiebt nicht), D7
(Versions-Schranke), [ADR-0014](0014-ad-connector-agent.md) (Connector-Agenten),
[ADR-0016](0016-sicherung-wiederherstellung-export.md) D5 (Wiederherstellung in
ein eigenes Schema), D8 (Kundenschlüssel), [ADR-0017](0017-systemeinstellungen-und-rechte-in-der-konsole.md)
D3 (Abgleich als Schleife), Phase 6 in `docs/features/multitenancy.md`

## Problem

Alles bisher Gebaute funktioniert mit **einem** Kunden auf einer Installation
und würde mit zwei auch noch funktionieren. Fünf Dinge funktionieren **nicht**,
sobald es mehr werden — und zwei davon sind heute schon falsch, nur fällt es
bei einem Kunden nicht auf:

1. **Die Migrations-Welle läuft, aber niemand erfährt davon — und ihr Dump
   liegt im Klartext.** `magister-cli tenants migrate` gibt es seit Phase 1:
   Dump je Kunde, Kanarienvogel zuerst, Halt mit `--canary-only`, Migration
   unter der Rolle des Mandanten. Der Ablauf ist also da. Was fehlt, ist alles
   drumherum: die Konsole erfährt den neuen Stand nicht, im Protokoll des
   Kunden steht nicht, dass sein Schema angefasst wurde — und `dump_tenant()`
   schreibt ein nacktes `pg_dump --file=…` auf die Platte. Das verstösst gegen
   eine harte Regel („niemals einen Kunden-Dump unverschlüsselt schreiben oder
   ablegen“), und zwar in Code, der im Onboarding-Runbook steht.
2. **Die Schranke glaubt der Konsole, nicht dem Schema.** Was sie vergleicht,
   ist `tenants.schema_version` aus der Konsolen-Datenbank — und dort steht
   `COCKPIT_EXPECTED_SCHEMA_VERSION`, also der Wert, den die Konsole
   *erwartet* hat, nicht der, den Alembic *erreicht* hat. Stimmen die beiden
   nicht überein, ist die Schranke stumm: entweder hält sie einen gesunden
   Kunden zurück oder — schlimmer — sie lässt einen Kunden durch, dessen
   Schema hinterherhängt.
3. **Der periodische AD-Sync läuft am falschen Schema.** Er nimmt
   `get_sessionmaker()`, also die Prozess-Engine auf `MAGISTER_DATABASE_URL`,
   und nicht die Engine des Mandanten. Bei einem Kunden ist das dasselbe; bei
   zwei synchronisiert er einen und lässt den anderen liegen. Der Hinweis
   steht seit Phase 1 im Docstring von `db.py` — „der Fan-out kommt mit der
   Konsole in Phase 2" — und ist dort liegen geblieben.
4. **Ein Kunde kann die Installation für alle langsam machen.** Es gibt keine
   Obergrenze: kein `statement_timeout`, keine Verbindungsgrenze, keine Decke
   für gleichzeitige Anfragen. Ein Import mit einer entgleisten Abfrage hält
   Verbindungen, und die anderen Kunden warten.
5. **Die Agenten-Flotte wird angesehen, nicht überwacht.** Die Konsole zeigt
   Version, Zertifikatsablauf und `last_seen_at` — aber nur, wenn jemand
   hinsieht. Ein Agent, der seit drei Tagen still ist, und ein Zertifikat, das
   in fünf Tagen abläuft, sehen in der Liste gleich aus wie alles andere.

Was **nicht** das Problem ist: die Trennung. Sie hängt an der Anmelderolle und
an Postgres, nicht an Anwendungslogik (ADR-0013 D1), und daran ändert diese
Phase nichts.

## Entscheidung

### D1 · Die Welle bleibt auf dem Anwendungsserver — sie kann nirgends sonst laufen

Der erste Entwurf dieses ADR liess die **Konsole** die Welle fahren, wie sie
schon die Bereitstellung fährt. Das ist nicht machbar, und der Grund ist eine
Zusage, die weiter wiegt als die Bequemlichkeit: **die Konsole hat keine
Mandanten-DSNs** (ADR-0013 D2). Sie hält einen `dsn_ref`, den die Datenebene
aus ihrem eigenen Geheimnisspeicher auflöst. Bei der Bereitstellung kennt sie
das Rollenpasswort für einen Moment, weil sie es gerade selbst erzeugt hat —
danach nie wieder.

Eine Welle aus der Konsole müsste also für jeden Kunden das Rollenpasswort
**drehen**, um es zu kennen. Damit wäre die DSN, die die Datenebene
hinterlegt hat, ungültig: zwanzig Kunden migriert und zwanzig Installationen
ohne Datenbankzugang. Der Ausweg „als Verwaltungsrolle migrieren“ ist keiner —
dann gehören die neuen Tabellen dem Administrator und die Mandantenrolle
bekommt beim ersten Query `permission denied for table`; genau das steht als
nachgemessene Lehre im Kopf von `cli/tenants.py`.

Also bleibt die Welle da, wo die Anmeldedaten liegen: im CLI der Datenebene,
das sie schon fährt. Kanarienvogel zuerst, Halt mit `--canary-only`, Abbruch
beim ersten Fehler (für den Kanarienvogel zwingend, `--keep-going` gilt für
ihn ausdrücklich nicht).

Ein Halt und keine Haltezeit — das bleibt, und eine Frist wäre falsch: sie
läuft um drei Uhr morgens ab, und dann rollt eine kaputte Migration auf alle.
Der Zweck eines Kanarienvogels ist, dass jemand hinsieht; eine Automatik, die
ohne Hinsehen weitermacht, ist keiner. Der Halt ist hier der Mensch, der den
Befehl ein zweites Mal ohne das Flag aufruft.

**Der Vor-Migrations-Dump wird verschlüsselt oder es gibt keinen.** Heute
schreibt er ein nacktes `pg_dump --file=…`; künftig geht er durch `age` an den
Backup-Empfänger, wie jede andere Sicherung (ADR-0016 D2), und er wird in der
Konsole als `pre_migration` verzeichnet — die Art gibt es dort samt eigener
Frist (D6) und hat bisher nie jemand geschrieben. Ohne `age` und ohne
Empfänger scheitert der Schritt, statt einen Klartext-Dump zu hinterlassen.

### D2 · Das kundensichtbare Rollout-Ereignis schreibt die Datenebene, nicht die Konsole

Die harte Regel verlangt „ein kundensichtbares Audit-Ereignis bei jedem
Rollout in ein Kundenschema“. Die Konsole **kann** es nicht schreiben:
`audit_events.payload` ist mit dem Kundenschlüssel verschlüsselt, und der liegt
ausdrücklich nicht in der Konsole (ADR-0016 D8). Sie könnte es nur, wenn sie
den Schlüssel hätte — und dann wäre die Zusage aus D8 nicht mehr wahr.

Mit D1 ist das ohnehin die Stelle, an der die Migration läuft: das CLI hat den
Kundenschlüssel (es baut dieselbe Sitzung wie der Anfragepfad) und schreibt
das Ereignis `schema_migrated` in das Schema, das es gerade migriert hat — mit
Vorher- und Nachher-Revision und der Angabe, wohin der Dump ging.

Und weil das CLI schon dort ist, **meldet** es auch: eine Nachricht an die
Konsole mit dem **lokalen Alembic-Kopf**, gelesen aus `alembic_version` im
Kundenschema. Damit ist Problem 2 dasselbe Problem wie dieses — die Konsole
erfährt, was wirklich im Schema steht, statt zu notieren, was sie erwartet
hat. Weicht es ab, steht es in der Konsole als Abweichung, und die
Versions-Schranke hat endlich eine Grundlage, die aus dem Schema kommt.

Dieser Rückkanal ist neu und bleibt der einzige: **eine** Route, dieselbe
Anmeldung wie beim Abruf (Token plus Management-Marker), sie trägt
Revision und Zeitpunkt und **keine** Personendaten, und sie ist idempotent —
dieselbe Meldung zweimal ändert nichts. Sie ist auch der Punkt, an dem der
Restposten „Schema-Version zurückmelden“ erledigt ist.

Scheitert die Meldung, ist die Migration trotzdem gelaufen: eine Warnung, kein
Abbruch. Sonst sähe eine geglückte Migration mit unerreichbarer Konsole wie
eine gescheiterte aus — dieselbe Regel wie bei der Backup-Meldung.

### D3 · Lastgrenzen setzt Postgres durch, nicht die Anwendung

`statement_timeout`, `idle_in_transaction_session_timeout` und
`CONNECTION LIMIT` gehören an die **Mandantenrolle** (`ALTER ROLE`), gesetzt
bei der Bereitstellung und änderbar aus der Konsole.

Nicht als `SET LOCAL` je Transaktion: eine Rollen-Einstellung gilt auch für
den Codepfad, den jemand vergisst, für das CLI, für den Reconciler und für die
Wiederherstellung. Was an der Rolle hängt, kann die Anwendung nicht aus
Versehen weglassen.

Die Verbindungsgrenze ist die eigentliche Zusage: Verbindungen wachsen mit
Mandanten × Prozesse × Pool (siehe `tenancy/engines.py`), und ohne Grenze
nimmt der erste Kunde, der viele Verbindungen aufbaut, den anderen ihre weg —
bis `max_connections` erschöpft ist und **alle** ausfallen. Mit Grenze fällt
genau der eine aus, der sie reisst.

Dazu, in der Anwendung, **eine Decke für gleichzeitige Anfragen je Mandant**:
über der Decke gibt es 503 mit `Retry-After`. Bewusst eine
Nebenläufigkeits-Decke und **keine** Anfragen-pro-Minute-Grenze — was einen
geteilten Prozess lähmt, ist Belegung und nicht Häufigkeit, und ein Zähler pro
Minute bräuchte gemeinsamen Zustand über alle Prozesse (also Redis), während
eine Semaphore je Prozess ehrlich das begrenzt, was dieser Prozess tatsächlich
hat.

### D4 · Der AD-Sync bekommt denselben Fan-out wie der Abgleich

Eine Schleife über die Registry, je Mandant eine eigene Sitzung aus der Engine
dieses Mandanten, je Mandant ein eigenes `try`, und das Intervall aus den
**wirksamen Einstellungen dieses Kunden** — nicht aus einer globalen Zahl.

Die Startzeiten werden **versetzt**, und zwar deterministisch über die
Reihenfolge in der Registry (Kunde *i* von *n* startet bei *i·Intervall/n*).
Nicht zufällig: ein Zufallsversatz ist im Log nicht nachvollziehbar, und die
Frage „warum hat Kunde 7 um 04:13 synchronisiert“ soll eine Antwort haben.

Der Grund für den Versatz ist nicht die Datenbank, sondern der
**Domänencontroller des Kunden** — und ab mehreren Kunden auch der
Connector-Kanal: zehn gleichzeitige Vollsynchronisationen sind eine Last, die
sich ohne Not auf zehn Zeitpunkte verteilen lässt.

Dass ein Kunde stolpert, hält die anderen nicht auf. Genau wie beim Abgleich,
und mit derselben Begründung.

### D5 · Der Umzug auf eine eigene Datenbank ist ein Runbook, kein Knopf

Ein Kunde zieht um, indem er gesperrt, gesichert, im Zielcluster eingespielt,
in der Registry umgestellt und geprüft wird. Das ist der Weg aus ADR-0016 D5
plus eine geänderte Zeile.

In der Konsole entsteht dafür **ein** neues Können: `dsn_ref` ändern, mit
Begründung und im Protokoll. Kein Umzugs-Assistent. Ein Knopf „umziehen“
müsste zwei Cluster, ein Wartungsfenster, eine Prüfung und einen Rückweg in
sich tragen — und wäre der Knopf, der ein halb umgezogenes Schema hinterlässt.
Der Umzug ist selten und teuer; was er braucht, ist eine geübte Anleitung und
keine Automatik.

Die Registry trägt ohnehin nur einen **Verweis** (`dsn_ref`), den die
Datenebene aus ihrem eigenen Geheimnisspeicher auflöst. Der Umzug ist damit
auf der Konsolenseite wirklich eine Zeile — und auf der Datenebene ein neuer
Eintrag im Geheimnisspeicher, der dort hingehört und nicht hierher.

### D6 · Alarmieren ist die Aufgabe der Überwachung, nicht von Magister

Die Konsole berechnet **Befunde** über die Flotte: Zertifikat läuft in weniger
als 14 Tagen ab, Erneuerung ist gescheitert, Agent seit mehr als einer Stunde
still, Agent-Version älter als die ausgelieferte, Kunde ohne Agent. Sie zeigt
sie oben in der Oberfläche, und sie liefert sie über einen Endpunkt.

Der Alarm selbst kommt aus einem **CLI mit Exit-Code**, das die bestehende
Überwachung aufruft. Kein SMTP in Magister, keine Webhooks, keine
Alarmierungs-Konfiguration.

Denn dieselbe Überlegung wie bei den Quell-IP-Regeln, die ausdrücklich nicht
in Magister nachgebaut werden: eine zweite Alarmierung neben der, die es im
Betrieb schon gibt, ist eine, die niemand pflegt — und die dann genau in der
Nacht schweigt, in der sie zählt. Ein Exit-Code ist die Schnittstelle, die
jedes Überwachungssystem versteht.

## Folgen

**Gut:**

- Der Vor-Migrations-Dump ist verschlüsselt. Die harte Regel gilt damit auch
  für den Weg, auf dem tatsächlich migriert wird, und nicht nur für den, den
  die Konsole geht.
- Die Versions-Schranke urteilt nach dem, was im Schema steht, statt nach dem,
  was die Konsole notiert hat.
- Der Kunde sieht in seinem Protokoll, dass und wann sein Schema angefasst
  wurde, geschrieben von der Stelle, die seinen Schlüssel hat.
- Ein Kunde, der die Last an sich reisst, fällt allein aus.
- Der AD-Sync erreicht endlich alle Kunden — und zwar versetzt.
- Ein stilles Zertifikat oder ein stehender Agent ist ein Befund mit
  Exit-Code, nicht eine Zeile, die niemand ansieht.

**Preis:**

- **Eine Welle braucht einen Menschen auf dem Anwendungsserver.** Der Halt
  nach dem Kanarienvogel ist Absicht, aber er heisst: ein Update auf zwanzig
  Kunden ist nicht unbeaufsichtigt, und es ist eine Sitzung auf der Maschine
  und kein Knopf in der Konsole. Bei zwanzig ist das richtig; bei zweihundert
  braucht es Wellen von Wellen, und das ist dann ein neuer Entscheid.
- **Der Rückkanal ist neu.** Bisher zog die Datenebene nur. Jetzt meldet sie
  zwei Dinge zurück (Kopf-Revision und Rollout-Quittung). Das ist eine
  Richtung mehr, die abgesichert sein muss — dieselbe Anmeldung, derselbe
  Marker, und sie trägt **keine** Personendaten.
- **Grenzen erzeugen Fehler, die vorher Wartezeit waren.** Ein
  `statement_timeout` macht aus einer langsamen Auswertung einen Abbruch. Das
  ist gewollt, aber es ist eine Verhaltensänderung, die im Betrieb auffällt —
  deshalb sind die Vorgaben eher gross gewählt und je Kunde änderbar.
- **Die Nebenläufigkeits-Decke gilt je Prozess.** Bei mehreren Containern ist
  die wirksame Grenze ein Vielfaches davon. Eine prozessübergreifende Grenze
  bräuchte gemeinsamen Zustand; das ist der Preis dafür, kein Redis zu
  brauchen, und er gehört benannt.
- **Der Umzug bleibt Handarbeit.** Bewusst (D5) — aber es heisst, dass der
  erste Umzug ein geübter Termin ist und kein Klick.

## Verworfen

**Migrationen im Startpfad der Datenebene** (`alembic upgrade head` beim
Hochfahren). Bequem, und bei mehreren Kunden auf einer Installation eine
Migration, die während des Betriebs alle Schemata anfasst — ohne Dump, ohne
Kanarienvogel, ohne Reihenfolge. Ausserdem gilt schon: kein Auto-Migrate in
Produktion.

**Die Welle aus der Konsole fahren.** Der erste Entwurf dieses ADR. Sie
bräuchte die Rollenpasswörter, die dort ausdrücklich nicht liegen — oder das
Drehen jedes einzelnen, was jede Datenebene aussperrt. Siehe D1.

**Haltezeit statt Halt.** Siehe D1.

**Die Konsole schreibt das Audit-Ereignis des Kunden.** Sie bräuchte den
Kundenschlüssel. Siehe D2.

**`SET LOCAL statement_timeout` im Anfragepfad.** Ein Schutz, der am Code
hängt, den jemand vergisst. Siehe D3.

**Anfragen pro Minute je Kunde.** Bräuchte gemeinsamen Zustand und misst die
falsche Grösse. Siehe D3.

**Ein Umzugs-Assistent in der Konsole.** Siehe D5.

**Alarm-Mails aus Magister.** Siehe D6.
