# ADR 0016: Sicherung, Wiederherstellung und Export pro Kunde

**Status:** Angenommen · 2026-09-08, Nachträge 2026-09-09
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
   Das Aufräumen alter Dumps läuft als **eigener Cron-Job mit eigenem Konto**,
   und zwar **nicht auf dem Anwendungsserver** — sonst liegen die Löschrechte
   genau auf der Maschine, die man vor einem Angreifer schützen will. Der Job
   gehört auf den Fileserver oder den Backup-Host.
   Damit kann ein übernommener Anwendungsserver die Sicherungen nicht
   mitnehmen, auch ohne Object Lock.

Verschlüsselung bleibt trotzdem Pflicht — auf einem Share sind die Dumps für
mehr Personen und Systeme erreichbar als in der Datenbank.

### D3 · Aufbewahrung: 10 Tage, eine Zahl für alles

Der Entscheid (E14): **10 Tage**, auf dem Share und im Tages-Backup gleich.
Ein Cron-Job auf dem Fileserver löscht Dumps, die älter als 10 Tage sind.

Diese eine Zahl ist damit gleichzeitig:

- die **Wiederherstellungszusage** an den Kunden („wir können auf jeden Stand
  der letzten 10 Tage zurück"),
- die **Löschfrist** beim Offboarding („10 Tage nach dem Crypto-Shredding ist
  auch der Rest weg"),
- der Wert in Vertrag und Auftragsverarbeitungsvereinbarung.

Kurze Fristen sind datenschutzrechtlich die richtige Richtung — Schülerdaten
unbegrenzt aufzubewahren ist ein Problem und kein Feature. Und beim Offboarding
ist eine 10-Tage-Zusage ein Verkaufsargument.

**Was 10 Tage nicht abdecken — bitte bewusst tragen:**

- Ein Fehler, der erst nach zwei Wochen auffällt (eine falsche
  Klassen-Promotion, ein verunglückter Import, ein gelöschter Standort), ist
  nicht mehr rückholbar. Bei Schulen ist genau das ein realistisches Muster:
  etwas fällt am Quartalsende auf, nicht am nächsten Tag.
- Verschlüsselungstrojaner sitzen typischerweise **Wochen** im Netz, bevor sie
  zuschlagen. Sind alle Sicherungen aus dieser Zeit, ist auch die letzte saubere
  Kopie weg.

Deshalb die Empfehlung, ohne die Entscheidung umzustossen: **zusätzlich eine
monatliche Kopie mit längerer Frist** (12 Monate) — das sind pro Kunde zwölf
Dateien und kaum Platz, deckt aber genau die beiden Fälle oben ab. Der
tägliche Zyklus bleibt bei 10 Tagen. Das Datenmodell (`tenant_backup_policy`)
hält die zwei Fristen ohnehin getrennt; sie einzuschalten ist ein Konfigwert,
kein Umbau. Offen als E15.

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
  **10 Tage** nach dem Crypto-Shredding ein (D3). Das ist eine Zusage, die man
  einem Kunden gut hinschreiben kann.
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
- Die Wiederherstellungsgarantie hängt jetzt am Unternehmens-Backup und ist auf
  **10 Tage** begrenzt. Alles, was später auffällt, ist verloren — siehe die
  Empfehlung zur monatlichen Kopie in D3.
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

## Nachträge aus der Umsetzung (2026-09-09)

Die Umsetzung von Phase 2b hat vier Entscheide berührt. Zwei davon sind
Abweichungen, zwei sind Voraussetzungen, die im ADR fehlten. Alle vier stehen
hier, weil ein ADR, der die Umsetzung nicht kennt, beim nächsten Mal in
dieselbe Falle führt.

### N1 · D2 und D4 widersprechen sich auf **einer** Maschine

D2 sagt, der private Backup-Schlüssel liege getrennt und werde auf dem
Anwendungsserver nie gebraucht. D4 verlangt eine wöchentliche
Prüf-Wiederherstellung — und die muss entschlüsseln. Beides gleichzeitig geht
nicht.

**Auflösung:** Wiederherstellen und Prüfen laufen **nicht** auf dem
Anwendungsserver, sondern auf dem Backup-Host, wo der Schlüssel liegt. Jede
Funktion in `cockpit_api/services/restore.py` nimmt den Pfad zur
Identitätsdatei als **Argument** und liest ihn nicht aus den Einstellungen:
eine Einstellung würde dazu verleiten, sie doch auf dem Anwendungsserver zu
konfigurieren, und damit wäre D2 aufgehoben.

Die Konsole **erfasst** deshalb Wiederherstellungen und **nimmt Ergebnisse
entgegen** (`POST /api/restore-jobs/{id}/report`,
`POST /api/backups/{id}/verify-result`). Sie führt keine aus. Ein Endpunkt,
der eine Wiederherstellung „auslöst", wäre bequemer und würde bedeuten, dass
ein übernommener Anwendungsserver alle alten Sicherungen lesen kann. Die
Umständlichkeit ist der Zweck.

Was die Konsole selbst kann, weil dafür nur der **öffentliche** Schlüssel
nötig ist: sichern. Und exportieren, weil darin kein Backup-Schlüssel vorkommt.

### N2 · Wiederhergestellt wird in eine eigene Datenbank, nicht in ein Nebenschema

D5 nennt ein Schema `r_<slug>_<zeitstempel>` neben dem Produktivschema. Der
Grund für die Abweichung ist handfest: ein `pg_dump --schema=t_slug` enthält
`CREATE SCHEMA t_slug` und durchgängig qualifizierte Namen. In dieselbe
Datenbank zurückspielen heisst also entweder auf das Produktivschema schreiben
(verboten) oder den Schemanamen im ausgegebenen SQL umschreiben — eine
Textersetzung auf SQL, die man nicht verantworten will.

In eine frische Datenbank spielt derselbe Dump unverändert ein, und das
Produktivschema wird nicht einmal geöffnet. Die Zusage „daneben, nie darüber"
wird damit stärker, nicht schwächer.

**Der Preis, ausgeschrieben:** D5 verspricht, das Umschalten sei „ein
Registry-Eintrag". Das ist es weiterhin — die Registry trägt DSN *und* Schema
(ADR-0013 D1), eine andere Datenbank ist dort dieselbe Art von Änderung wie
ein anderes Schema. Aber der DSN steht in der Konsole nur als **Verweis**
(ADR-0013 D2); aufgelöst wird er aus der Umgebung des Anwendungsservers
(`MAGISTER_TENANT_DSN_<REF>`). Umschalten ist deshalb eine
Konfigurationsänderung **auf dem Anwendungsserver** und kein Klick in der
Konsole. Die Konsole hält fest, *dass* und *wann* umgeschaltet wurde und
welches Schema verdrängt wurde; der Ablauf steht in
`docs/runbooks/sicherung-wiederherstellung.md`. Wer das Umschalten ohne
Umgebungsänderung will, findet dort auch den zweiten Weg (Produktivschema
umbenennen und den geprüften Stand darüber einspielen) mit seinen Kosten.

### N3 · D8 war ohne Kundenschlüssel je Mandant nicht erfüllbar

Das Abnahmekriterium „nach dem Vernichten des Kundenschlüssels ist kein
Audit-Payload mehr entschlüsselbar" war mit dem Stand vor der Umsetzung
**unwahr**, und zwar nicht knapp: der pgcrypto-Schlüssel kam aus *einer*
Umgebungsvariablen (`MAGISTER_AUDIT_KEY`) für die ganze Installation. Damit
gab es nur zwei Möglichkeiten, und beide sind unbrauchbar:

- Den Schlüssel vernichten und damit auch die Audit-Inhalte **aller** anderen
  Kunden unlesbar machen.
- Ihn behalten — dann ist die Löschzusage an den gekündigten Kunden unerfüllt,
  und ein gestohlener Dump gibt mit demselben Schlüssel die Inhalte aller
  Kunden her. Das hebt auch die zweite Verschlüsselungsschicht aus D2 auf.

**Jeder Mandant hat jetzt seinen eigenen Schlüssel**, aus der Umgebung
(`MAGISTER_TENANT_AUDIT_KEY_<REF>`) und nicht aus der Datenbank — aus der
Datenbank wäre er im Dump, und die zweite Schicht damit wieder weg. Fehlt er
bei mehr als einem Mandanten, antwortet die Datenebene für **diesen** Kunden
mit 503; ein stiller Rückfall auf den gemeinsamen Schlüssel wäre die Variante,
die niemandem auffällt. Bei genau einem Mandanten gilt der Rückfall weiter,
damit eine bestehende Installation nach dem Update ohne neue Konfiguration
läuft.

Die Konsole erzeugt den Schlüssel im Bereitstellungsschritt `data_key`, gibt
ihn **einmal** zurück und speichert ihn nicht — wie das Rollenpasswort und aus
demselben Grund, plus dem zweiten aus D2. Eingetragen wird er beim Ausrollen;
bis dahin antwortet der Mandant mit 503. Gespeichert wird nur die **Id**
(`tenants.audit_key_id`), und jede Sicherung vermerkt sie.

Beim Umbau fiel ein zweiter Fund an, der nicht zu diesem ADR gehört, aber
dieselbe Wurzel hat: der Cache der überlagerten Einstellungen war nur nach
`app_settings.version` geschlüsselt und liegt prozessweit. Zwei Kunden mit
derselben Version bekamen die Einstellungen des jeweils anderen — OIDC-Issuer,
AD-Domänencontroller, Bind-DN. Beide Installationen fangen bei Version 1 an,
die Kollision war also der Normalfall.

### N4 · Crypto-Shredding wird bestätigt, nicht geprüft

Die Konsole kann den Kundenschlüssel nicht vernichten: er liegt in der
Umgebung des Anwendungsservers. `tenant_offboarding.key_destroyed_at` ist
deshalb die **Bestätigung eines Menschen** über eine Handlung, die er selbst
ausgeführt hat — kein Nachweis. Das steht so im Modell, im Dienst und im
Endpunkt, weil ein Feld dieses Namens sonst wie eine Prüfung aussieht.

Was die Konsole dagegen nachprüft, ist das Löschen von Schema und Rolle: sie
führt das SQL aus und fragt danach `information_schema.schemata` und
`pg_roles` ab. Existiert eines von beiden noch, wird der Zustand **nicht** als
gelöscht vermerkt. Zwei verschiedene Grade von Gewissheit gehören nicht in
dasselbe Feld — deshalb sind `dropped_at` und `key_destroyed_at` getrennt.

Und `purged` ist keine Handlung, sondern ein Datum: `key_destroyed_at` plus
Aufbewahrungsfrist (E14: 10 Tage). Erst dann ist die Löschzusage erfüllt. Der
Endpunkt weigert sich, den Zustand vorher zu setzen — „vollständig gelöscht"
vor Fristablauf wäre eine unwahre Zusage an den Kunden.

### N5 · Kleinere Festlegungen, die in der Umsetzung entschieden wurden

- **CSV mit Semikolon und UTF-8-BOM** (`utf-8-sig`). Nicht Komma und nicht
  reines UTF-8: der Empfänger ist eine Gemeinde-IT mit Excel in einer
  deutschsprachigen Windows-Installation, und dort öffnet genau diese
  Kombination per Doppelklick richtig. Beides steht ausdrücklich im Manifest,
  damit ein Programm es nicht raten muss.
- **Die Export-Allowlist ist gegen das echte Schema getestet.** Eine
  handgeschriebene Spaltenliste verrottet gegen ein Schema, das sich mit jeder
  Migration ändert. Ein Test migriert deshalb ein echtes Kundenschema und
  verlangt, dass **jede** Tabelle entweder exportiert oder mit Begründung
  ausgeschlossen ist. Eine neue Migration bricht diesen Test, bis jemand
  entscheidet. Das ist die Absicht und kein Ärgernis.
- **Die README im Export ist nur auf Deutsch.** Für einen französisch- oder
  italienischsprachigen Kunden ist das eine offene Lücke; das Manifest selbst
  ist maschinenlesbar und sprachneutral.
- **Ein Export ist der einzige Ort mit Kundendaten im Klartext.** Deshalb ein
  eigenes Verzeichnis mit `0700` (ausdrücklich **nicht** der Backup-Share),
  Dateien mit `0600`, eine Frist (`COCKPIT_EXPORT_TTL_DAYS`, Vorgabe 7 Tage)
  und ein Audit-Eintrag bei jedem Download. Ein Export, der liegen bleibt, ist
  ein Datenleck mit Verfallsdatum „nie".
