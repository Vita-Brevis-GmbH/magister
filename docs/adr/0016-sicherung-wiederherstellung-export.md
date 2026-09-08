# ADR 0016: Sicherung, Wiederherstellung und Export pro Kunde

**Status:** Vorschlag · 2026-09-08
**Kontext:** [ADR-0013](0013-mandantenfaehigkeit-control-plane.md) — mit mehreren
Kunden auf einer Installation wird die Sicherung zur Kundenangelegenheit.

## Problem

Heute sichert eine `pg-backup`-Sidecar einmal täglich die **ganze** Datenbank
per `pg_dump` in ein lokales Volume: unverschlüsselt, ohne Kopie ausserhalb der
Box, ohne Prüfung, ob der Dump brauchbar ist, mit 14 Tagen Aufbewahrung. Für
eine Einzelinstallation ist das vertretbar. Gehostet trägt es nicht:

- Ein Kunde, der sich Daten zerschossen hat, braucht **seine** Daten zurück —
  nicht die ganze Datenbank auf den Stand von heute Nacht, was alle anderen
  Kunden mitzurückrollen würde.
- Aufbewahrungsfristen und Wiederherstellungszeiten sind Vertragssache und damit
  pro Kunde verschieden.
- Ein Dump mit Personendaten von Minderjährigen darf nicht unverschlüsselt auf
  einem Volume liegen, und er muss ausserhalb der Box existieren.
- Der Kunde hat ein Recht auf Herausgabe seiner Daten in einem brauchbaren
  Format (nDSG, DSGVO Art. 20) — beim Anbieterwechsel und auf Verlangen.
- Beim Offboarding muss belegbar gelöscht werden, auch aus den Sicherungen.
- Und: ein Backup, das nie wiederhergestellt wurde, ist kein Backup, sondern
  eine Datei.

Die Konsole zeigt bereits „letzte Sicherung" pro Kunde — dahinter muss etwas
stehen.

## Entscheidung

### D1 · Zwei Ebenen, weil sie zwei verschiedene Dinge können

**Ebene 1 — Cluster-PITR (Plattform).** Kontinuierliche WAL-Archivierung plus
periodisches Basebackup (pgBackRest oder WAL-G). Erlaubt
Point-in-Time-Recovery des ganzen Clusters auf einen Zeitpunkt, RPO im
Minutenbereich. Das ist das Werkzeug für „Datenbank beschädigt" und
„Rechenzentrum weg".

**Ebene 2 — logische Sicherung pro Kunde.** `pg_dump --schema=t_<slug>`
(beziehungsweise `--dbname` bei eigener Datenbank) — genau die Daten eines
Kunden, wiederherstellbar ohne die anderen anzufassen. Das ist das Werkzeug für
„der Kunde hat sich etwas zerschossen", für Export und für Offboarding.

Beides ist nötig und keines ersetzt das andere: PITR kann keinen einzelnen
Kunden zurückrollen, und ein logischer Dump kann keinen Cluster auf 14:37 Uhr
bringen.

### D2 · Verschlüsselt, mit einer Kopie ausserhalb der Box

Jeder Kunden-Dump wird beim Schreiben mit einem **öffentlichen**
Plattform-Backup-Schlüssel verschlüsselt (`age`). Der Sicherungsprozess braucht
damit nur den öffentlichen Teil; der private Schlüssel liegt getrennt und wird
nie auf dem Anwendungsserver gebraucht.

Zwei Schichten, weil `audit_events.payload` und `password_enc` im Dump als
pgcrypto-Chiffrat liegen und mit dem **Kundenschlüssel** verschlüsselt bleiben.
Ein gestohlenes Backup gibt ohne diesen Schlüssel keine Audit-Payloads her.

**Der Fallstrick dazu, ausgeschrieben:** ein Dump ohne den passenden
Kundenschlüssel ist teilweise unbrauchbar. Der Schlüssel muss also mitgesichert
werden — aber nicht im selben Bündel, sonst ist die zweite Schicht wieder weg.
Deshalb: Kundenschlüssel im getrennten Tresor mit eigener Sicherung, und jeder
Dump vermerkt nur die Schlüssel-Id (`audit_key_id` existiert seit Migration
`0011_audit_key_id`). Wer wiederherstellt, braucht beide Quellen — genau so ist
es gedacht.

**Ablage: ein lokaler Share, den das tägliche Unternehmens-Backup mitnimmt**
(Entscheid E13). Magister schreibt die verschlüsselten Dumps auf einen Share
(`/mnt/magister-backup/<kunde>/…`); die bestehende Backup-Infrastruktur von
Vita Brevis sichert diesen Share im Tageslauf weg. Kein Objektspeicher, kein
zweiter Anbieter.

Das ist betrieblich der einfachste Weg und nutzt eine Infrastruktur, die
ohnehin läuft und überwacht ist. Zwei Dinge muss man dabei ausdrücklich
mitdenken, sonst hat man ein Backup, das genau im Ernstfall nicht hilft:

1. **Die Unveränderlichkeit liegt nicht mehr bei Magister, sondern beim
   Tages-Backup.** Ein Angreifer mit Schreibzugriff auf den Share kann die
   Dumps löschen oder verschlüsseln. Was danach noch existiert, ist die Kopie,
   die das Unternehmens-Backup gezogen hat — dessen Aufbewahrung und
   Unveränderlichkeit bestimmen also ab jetzt die tatsächliche
   Wiederherstellungsgarantie, nicht Magister. Das ist vertretbar, muss aber
   bewusst so entschieden und dokumentiert sein.
2. **Schreiben ja, löschen nein.** Das Dienstkonto, mit dem Magister auf den
   Share schreibt, bekommt `Erstellen`/`Schreiben`, aber **kein** `Löschen`.
   Das Aufräumen alter Dumps läuft als getrennter Job mit einem eigenen Konto.
   Damit kann ein übernommener Anwendungsserver die Sicherungen nicht
   mitnehmen, auch ohne Object Lock.

Verschlüsselung bleibt trotzdem Pflicht — auf einem Share sind die Dumps für
mehr Personen und Systeme erreichbar als in der Datenbank.

### D3 · Aufbewahrung: zwei Fristen, zwei Zuständigkeiten

- **Auf dem Share:** 30 Tage täglich, dazu die `pre_migration`-Dumps für
  30 Tage. Magister räumt selbst auf (getrennter Job, siehe D2), damit der
  Share nicht unbegrenzt wächst. Pro Kunde in `tenant_backup_policy`
  überschreibbar und in der Konsole sichtbar.
- **Langfristig:** was darüber hinaus existiert, bestimmt die Aufbewahrung des
  Unternehmens-Backups. Diese Frist ist **nicht** von Magister gesteuert.

Daraus folgt eine Aufgabe, die vor der ersten Kundenzusage erledigt sein muss:
die Aufbewahrung des Tages-Backups muss bekannt und schriftlich sein, denn sie
ist die Zahl, die im Vertrag und in der Auftragsverarbeitungsvereinbarung
steht — sowohl als Wiederherstellungszusage als auch als Löschfrist.

Fristen sind hier keine Kostenfrage, sondern Datenschutz: Schülerdaten
unbegrenzt aufzubewahren ist ein Problem und kein Feature.

### D4 · Ein Backup gilt erst als Backup, wenn es eingespielt wurde

Wöchentlich wird pro Kunde automatisch der jüngste Dump in ein Wegwerf-Schema
(`v_<slug>_<datum>`) eingespielt und geprüft:

- alle erwarteten Tabellen vorhanden,
- Zeilenzahlen in plausibler Grössenordnung gegenüber dem Produktivschema,
- Alembic-Version entspricht der erwarteten,
- ein Audit-Payload lässt sich mit dem Kundenschlüssel entschlüsseln.

Danach wird das Schema verworfen. Das Ergebnis steht pro Kunde in der Konsole
(„zuletzt geprüft"). Ohne diesen Schritt merkt man den kaputten Dump am Tag des
Ernstfalls.

### D5 · Wiederherstellung immer daneben, nie darüber

Ein Restore legt ein **neues** Schema an (`r_<slug>_<zeitstempel>`) und lässt
das Produktivschema unberührt. Erst nach Freigabe wird umgeschaltet: der
Registry-Eintrag zeigt auf das neue Schema, das alte bleibt einige Tage stehen.

Kein `DROP SCHEMA … CASCADE` auf ein Produktivschema — nie. Nebeneffekt: ein
**teilweiser** Restore wird damit möglich (eine Tabelle, eine Klasse, ein
Benutzer), weil man aus dem Nebenschema lesen kann, ohne umzuschalten. Das ist
in der Praxis der häufigere Fall.

Jeder Restore verlangt Grund oder Ticket und erzeugt ein für den Kunden
sichtbares Audit-Ereignis. Das Umschalten auf ein wiederhergestelltes Schema
verlangt zusätzlich eine zweite Person.

### D6 · Sicherung vor jeder Migration

Der Migrations-Fan-out aus ADR-0013 D7 zieht pro Kunde einen Dump, **bevor** er
die Migration anwendet. Das ist die Rückfahrkarte für eine misslungene
Migration und kostet fast nichts. Der Dump wird als Art `pre_migration`
vermerkt und unabhängig von der normalen Aufbewahrung 30 Tage gehalten.

### D7 · Export ist eine eigene Funktion, kein umbenanntes Backup

| | Sicherung | Export |
|---|---|---|
| Für wen | uns | den Kunden |
| Format | Datenbank-Dump | CSV pro Tabelle + JSON-Manifest, Vorlagen als Dateien |
| Inhalt | alles, inklusive Interna | nur Kundendaten, keine Plattform-Interna |
| Zweck | Wiederherstellung | Portabilität, Anbieterwechsel, Auskunft |

Der Export enthält eine Prüfsumme und ein Manifest, das jede Datei und ihre
Spalten beschreibt, damit die Daten ohne Magister lesbar sind. Bereitstellung
über einen zeitlich begrenzten Download in der Konsole, auditiert.

### D8 · Offboarding mit Fristen — und ehrlich zur Löschung

Ablauf: Kündigung → Status `offboarding` → Export bereitstellen → Karenzzeit
(Default 30 Tage, Vertragswert) → Schema und Datenbankrolle löschen,
Kundenschlüssel vernichten.

Was danach gilt, muss dem Kunden **so** zugesagt werden, wie es technisch ist:

- Das Vernichten des Kundenschlüssels macht die damit verschlüsselten Inhalte
  sofort und endgültig unlesbar (Audit-Payloads, gespeicherte Passwörter) —
  „Crypto-Shredding".
- Die übrigen Daten (Namen, Klassen, Zuordnungen) liegen in bereits
  geschriebenen Sicherungen — auf dem Share und in den Bändern oder Snapshots
  des Unternehmens-Backups. Aus einem abgeschlossenen Backup-Satz kann man
  einzelne Zeilen nicht herausschneiden. Vollständige Löschung tritt deshalb
  mit **Ablauf der Aufbewahrungsfrist des Tages-Backups** ein — dieselbe Zahl
  wie in D3.
- Diese Frist gehört in den Vertrag und in die Auftragsverarbeitungs­vereinbarung.
  Ein „wir löschen sofort alles" wäre eine Zusage, die die Technik nicht hält.

### D9 · On-prem bleibt einfach

Die bestehende `pg-backup`-Sidecar bleibt für Einzelinstallationen. Sie wird nur
erweitert um Verschlüsselung mit dem `age`-Public-Key des Betreibers, eine
wöchentliche Prüf-Wiederherstellung und `magister-cli backup verify`. Eine
Gemeinde mit einem Server bekommt keinen pgBackRest-Zwang.

### D10 · Datenmodell (Konsolen-Datenbank)

| Tabelle | Inhalt |
|---|---|
| `tenant_backups` | Kunde, Zeitpunkt, Art (`daily`/`pre_migration`/`manual`), Pfad auf dem Share, Grösse, Prüfsumme, Schlüssel-Id, Status, `verified_at` |
| `tenant_backup_policy` | Aufbewahrung, Zeitfenster, Ziel-Ablagen, Wiederherstellungsziel (RPO/RTO) pro Kunde |
| `restore_jobs` | Quelle, Ziel-Schema, Grund/Ticket, Freigaben, Status |
| `export_jobs` | Kunde, Umfang, Prüfsumme, Ablauf des Download-Links, Besteller |

## Konsequenzen

**Positiv**

- Ein Kunde kann zurückgeholt werden, ohne die anderen anzufassen.
- Sicherungen sind verschlüsselt, liegen ausserhalb der Box und unveränderlich.
- Der Restore-Weg ist geübt, weil er wöchentlich automatisch läuft.
- Migrationen haben eine Rückfahrkarte.
- Export und Löschung sind Funktionen mit Fristen, nicht Handarbeit — und die
  Zusagen an den Kunden entsprechen dem, was die Technik kann.
- On-prem bleibt eine Sidecar und ein Volume.

**Negativ**

- Deutlich mehr Bewegtteile: WAL-Archivierung, Prüfläufe, Schlüsselverwahrung
  an zwei Orten.
- Speicherbedarf pro Kunde auf dem Share und im Tages-Backup, der in die
  Preisgestaltung muss.
- Die Wiederherstellungsgarantie hängt jetzt am Unternehmens-Backup. Dessen
  Aufbewahrung, Unveränderlichkeit und Wiederherstellungszeit sind damit Teil
  der Zusage an die Kunden und müssen dokumentiert sein.
- Die Prüf-Wiederherstellung kostet jede Woche Rechenzeit und Platz.
- Die Löschzusage ist erklärungsbedürftig („mit Ablauf der Frist", nicht
  „sofort") — das muss im Vertrieb sauber kommuniziert werden.

## Alternativen verworfen

- **Nur Cluster-PITR.** Kann keinen einzelnen Kunden zurückrollen; jeder
  Restore wäre ein Eingriff bei allen.
- **Nur logische Dumps pro Kunde.** RPO von 24 Stunden und kein Weg zurück auf
  einen Zeitpunkt; bei einer beschädigten Datenbank zu wenig.
- **Postgres-Backup dem Hoster überlassen** (Managed-Service-Snapshots).
  Snapshots sind Cluster-weit — dasselbe Problem wie bei reinem PITR, plus
  Abhängigkeit vom Anbieter beim Restore-Werkzeug.
- **Unverschlüsselte Dumps wie heute, aber pro Kunde.** Personendaten von
  Minderjährigen auf einem Share, der mehr Systemen offensteht als die
  Datenbank; kommt nicht in Frage.
- **Objektspeicher mit Object Lock statt Share.** Technisch der stärkere
  Ransomware-Schutz, aber ein zweiter Anbieter und ein zweites
  Betriebsverfahren neben einer Backup-Infrastruktur, die es schon gibt. Mit
  den Schreibrechten aus D2 ist der Share nahe genug dran (Entscheid E13).
- **Sicherungen beim Offboarding selektiv bereinigen.** Aus unveränderlichem
  Speicher technisch nicht möglich. Crypto-Shredding plus Fristablauf ist der
  ehrliche Weg.
