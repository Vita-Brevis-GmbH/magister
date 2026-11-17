# ADR-0028 · Betrieb über den Host-Agenten des Cockpits

**Status:** Angenommen · 2026-11-16
**Bezug:** [ADR-0024](0024-betrieb-aus-der-konsole.md) D5 (Ops-Agent),
[ADR-0016](0016-sicherung-wiederherstellung-export.md) D2/D6/D9 (Sicherung,
Schlüsseltrennung), [ADR-0013](0013-mandantenfaehigkeit-control-plane.md) D7
(Schemastand je Schema), Cockpit ADR 0015 (Host-Agent v2), Vertrag `betrieb/v1`
(Einstiegspunkt je Produkt)

Entscheid des Anwenders (2026-11-16): „Bitte weiter bis P5" — Cockpit-Roadmap P3
„Aktualisieren": Update der Plattform aus dem Cockpit, mit Sicherung vorher und
Rückfall bei Fehler, ohne SSH vom Cockpit.

## Problem

Das Update aus der Konsole läuft heute über den Ops-Agenten (ADR-0024 D5):
`git pull --ff-only` in beiden Checkouts, dann `plattform-aufbau.sh update`.

* Es gibt nur „vorwärts auf dem Branch, auf dem der Checkout steht" — keine Wahl
  einer Version, kein Tag, kein Zurück.
* Gesichert wird nur, wenn Kundenschemas migriert werden, und auch dann nicht
  so, dass sich der Stand automatisch zurücklegen liesse.
* Nach dem Update prüft niemand, ob die Datenebene antwortet. Das Ergebnis ist
  das Ende eines Protokolls in `status.json`.

Das Cockpit (Version 2) aktualisiert alle Produkte über **einen** Host-Agenten
je Host mit einer festen Positivliste (`stand`, `sichern`, `aktualisieren`,
`zurueck`, `neustart`). Der Agent kennt keine Befehle der Produkte; er ruft je
Produkt einen Einstiegspunkt im Checkout auf. Was ein Update heisst, weiss nur
das Produkt.

## Entscheidung

### D1 · `scripts/betrieb.sh` ist der Einstiegspunkt von Magister

Nach dem Vertrag `betrieb/v1`: fünf Unterbefehle, als root im Checkout, ohne
Terminal, Umgebung nur `PATH`, `LANG`, `BETRIEB_AUFTRAG`. Auf stdout genau eine
Zeile JSON (Version, Commit, Health, `zurueck_moeglich`, `vorher`, letzte
Sicherung), Fortschritt und alle Ausgaben von `plattform-aufbau.sh` auf stderr.
Exit 0 ok · 1 gescheitert und selbst zurückgefallen · 2 gescheitert, von Hand
(die Meldung nennt den nächsten Schritt) · 3 abgelehnt, nichts geändert ·
4 belegt (`flock` auf `<checkout>/.betrieb.lock`).

Die Meldung ist fester Text mit Versionen und Schritten — nie Inhalte der
`.env`, nie Ausgaben fremder Programme. git läuft als root mit
`safe.directory`, wie im Ops-Agenten.

„Magister" ist hier die **Plattform auf diesem Host**: die Datenebene
(Compose-Projekt `magister`). Die Konsole ist ein eigenes Produkt
(vitabrevis-cockpit) mit eigenem Einstiegspunkt.

### D2 · Version heisst git

* Version = Tag, sonst `git describe --tags`, sonst der kurze Commit.
* `aktualisieren --ref <ref>`: Branch auf `origin` (der Branch wird wieder
  angehängt), sonst Tag, sonst Commit (beide losgelöst).
* Gleicher Commit wie laufend → Exit 0 „schon auf …", nichts geändert.
  Vorfahr des laufenden Stands → Exit 3 (zurück nur über `zurueck`). Lokale
  Commits auf dem Ziel-Branch oder lokale Änderungen an versionierten Dateien
  → Exit 3.
* Gebaut wird aus dem Checkout (`plattform-aufbau.sh update` ohne `--ziehen`),
  wie beim Ops-Agenten: ein Abbild `latest` aus GHCR hinge nicht an der Ref.

### D3 · Ablauf eines Updates

Sperre → lokale Änderungen? → `git fetch` → Ref auflösen und prüfen (D2) →
Schemastand merken → **Sicherung** → Zustand schreiben → umschalten →
`plattform-aufbau.sh update` → **Health bis 5 min** → sonst Rückfall (D5).

Gesichert wird erst, wenn die Ref geprüft ist: eine abgelehnte Ref oder
„schon auf" hinterlässt keine Sicherung. Health heisst: jeder Dienst der
Datenebene läuft, wo es eine Docker-Prüfung gibt, ist sie gesund, und die API
antwortet **jetzt** auf `/healthz` mit `ok`.

Der Zustand für `zurueck` (`plattform/betrieb/zustand`, root, 0600, keine
Geheimnisse) steht **vor** dem Umschalten. Bricht der Agent den Lauf am
Zeitlimit ab, geht `zurueck` trotzdem. Ein Versuch, der selbst zurückgefallen
ist, zählt nicht als „letztes erfolgreiches Update".

`neustart` startet nur die Datenebene neu (`docker compose restart`, ohne
Neubau) und prüft Health — nicht die Konsole.

### D4 · Die Sicherung für den Rückfall hat Eigentümer und Rechte

Gesichert wird wie vor jeder Migration: `backup.sh` im Container `pg-backup`,
verschlüsselt mit dem **öffentlichen** age-Schlüssel, ins Volume `backups`
(ADR-0016 D9). Neu ist die Art `BACKUP_ART=rueckfall`
(`<db>-<zeit>-rueckfall.dump.age`): **mit** Eigentümern und Rechten.

Warum: jedes Kundenschema gehört seiner Rolle, und `REVOKE … FROM PUBLIC`
ist die Mandantentrennung. Eine Sicherung ohne Eigentümer (die tägliche, die
auf dem Backup-Host in eine fremde Datenbank geht) legt nach dem Einspielen
alles dem Administrator hin — kein Kunde käme mehr an seine Daten. Die
tägliche bleibt, wie sie ist.

Die Rückfall-Sicherungen unterliegen derselben Aufbewahrung wie alle Dumps im
Volume (`BACKUP_RETENTION_DAYS`, Vorgabe 14 Tage): `zurueck` mit Datenbank geht,
solange die Sicherung liegt. Läuft `pg-backup` noch mit dem alten `backup.sh`,
entsteht eine Sicherung ohne Rechte; sie wird erkannt und nie automatisch
eingespielt.

### D5 · Rückfall und seine Grenzen

Einspielen kann nur, wer den **privaten** Schlüssel hat. In Produktion liegt er
nicht auf dem Host (ADR-0016 D2, prod-installation.md §7), und daran ändert
dieser Entscheid nichts. Deshalb, beim Rückfall nach einem gescheiterten
Update wie bei `zurueck`:

| Lage | Was geschieht |
|---|---|
| privater Schlüssel in `plattform/certs/backup-age.key` (Test-Host) | Datenbank **und** Code zurück |
| kein Schlüssel, Schemastand unverändert | nur der Code zurück, Daten bleiben |
| kein Schlüssel, Schemastand geändert | nichts automatisch: Exit 2 (Update) bzw. 3 (`zurueck`), läuft auf dem neuen Stand |

* **Schemastand** = `alembic_version` aller Schemas (ADR-0013 D7), verglichen
  über eine Prüfsumme vor dem Update und jetzt. Unverändert heisst: der alte
  Code passt zur Datenbank. Unlesbar gilt als geändert.
* **Einspielen:** Probelauf zuerst (entschlüsseln und ganz lesen), dann
  `magister-api` anhalten, die laufende Datenbank **umbenennen**
  (`<db>_vor_rueckfall_<zeit>`, keine Verbindungen) und die Sicherung mit
  `pg_restore --create` aus dem Strom einspielen (`age -d | pg_restore`, nie
  Klartext auf der Platte). Scheitert das, kommt die bisherige Datenbank an
  ihren Platz zurück.
* **Erst die Datenbank, dann der Code:** scheitert das Einspielen, passen Code
  und Datenbank wenigstens noch zueinander.
* **Daten seit dem Update gehen verloren** — wie bei Automato. Sie liegen noch
  in der umbenannten Datenbank, bis jemand sie von Hand löscht.
* Kunden, die nach der Sicherung angelegt wurden, haben danach ihre Rolle,
  aber kein Schema.
* Der nächste Schritt im dritten Fall: den Schlüssel vorübergehend nach
  `plattform/certs/backup-age.key` legen, `zurueck` auslösen, Schlüssel
  wieder entfernen. Er steht so in der Meldung.
* `zurueck` geht **einmal**; danach `zurueck_moeglich: false`.

### D6 · Abgrenzung zum Ops-Agenten

Der Ops-Agent (ADR-0024 D5) bleibt für `attach`, `rotate-role` und die
Zustandserhebung für die Überwachung (`health.json`). Update und Neustart
kommen künftig über den Host-Agenten des Cockpits; `restart`/`update` des
Ops-Agenten bleiben, solange die Konsole sie anbietet und für Hosts ohne
Host-Agent.

Zwei Unterschiede sind gewollt: `betrieb.sh` holt nichts in den Checkout der
Konsole (sie aktualisiert ihr eigener Einstiegspunkt; `plattform-aufbau.sh
update` baut sie wie bisher mit auf), und `neustart` startet nur die
Datenebene neu.

### D7 · Was nie automatisch passiert

* Kein Daten-Rückfall ohne den privaten Schlüssel — und der Schlüssel wird
  nie auf den Host gelegt oder dort erzeugt.
* Keine Datenbank wird gelöscht, ausser der eben selbst halb eingespielten;
  die umbenannte bleibt liegen.
* Kein `git pull` oder `checkout` im Checkout der Konsole.
* Kein Update über lokale Änderungen, kein Downgrade über `aktualisieren`,
  kein zweites `zurueck`.
* Keine Abbilder aus GHCR.
* Keine Geheimnisse und keine Ausgaben fremder Programme in der Meldung.

## Konsequenzen

* Das Cockpit sieht je Host Version, Health, ob `zurueck` geht und die letzte
  Sicherung — und löst Update, Zurück und Neustart aus, ohne SSH.
* Nach einem Rückfall mit Datenbank liegt `<db>_vor_rueckfall_<zeit>` im
  Cluster und belegt Platz, bis sie nach Prüfung von Hand gelöscht wird
  (Runbook plattform-auf-einem-host.md §5f).
* In Produktion ist der automatische Rückfall eines Updates **mit** Migration
  ein Handgriff (Schlüssel bringen, `zurueck`). Ohne Migration geht er ohne.
* git läuft als root im Checkout des Betriebsbenutzers — wie beim Ops-Agenten
  gehören neu geschriebene Dateien danach root.

## Alternativen verworfen

* **Den privaten Schlüssel auf dem Host lassen**, damit der Rückfall immer
  geht. Hebt ADR-0016 D2 auf: wer den Host übernimmt, liest alle alten
  Sicherungen. Ein eigener „Rückfall-Schlüssel" auf dem Host wäre dasselbe
  unter anderem Namen.
* **Die tägliche Sicherung einspielen.** Ohne Eigentümer und Rechte (D4).
* **Eine Kopie der Datenbank im Cluster vor jedem Update** (`CREATE DATABASE …
  TEMPLATE`). Braucht eine Datenbank ohne Verbindungen schon vor dem Update
  (Ausfall bei jedem Update, auch dem erfolgreichen), verdoppelt den Platz und
  wäre eine zweite, unverschlüsselte Art Sicherung neben der verschlüsselten.
  Das Umbenennen beim Rückfall nutzt dieselbe Idee nur im Fehlerfall.
* **`zurueck` ohne Datenbank**, immer. Nach einem Update mit Migration passt
  der alte Code nicht zur Datenbank; Alembic kennt die neuere Revision nicht.

## Nachtrag 2026-11-17 · Repo privat: Stand aus dem git-Bundle des Cockpits

Die Repos (Magister, Automato, Cockpit) werden privat; **nur das Cockpit** hat
einen GitHub-Zugang (Cockpit ADR 0019, Vertrag „Alles privat“). Hosts sprechen
nie mit GitHub. Für jeden Auftrag mit Code löst das Cockpit die Ref auf, holt
den Stand als git-Bundle und gibt im signierten Auftrag Commit und SHA-256 mit;
der Host-Agent lädt das Bundle über den Host-Kanal und prüft es.

* **`aktualisieren --ref <ref> --bundle <datei> --commit <40 hex>`**
  (Erweiterung von `betrieb/v1`, rückwärts verträglich): `--bundle` und
  `--commit` nur zusammen, jede Angabe einmal. Dann wird origin **nie**
  kontaktiert: `git bundle verify` → `git fetch <bundle> <commit>` → der Commit
  muss ein Kopf des Bundles sein bzw. von einem Kopf erreichbar. Bundle fehlt,
  defekt, passt nicht zum Checkout (Voraussetzungen) oder ohne den Commit →
  Exit 3, nichts geändert (noch keine Sicherung). Ohne `--bundle` wie bisher
  von origin; scheitert `git fetch`, nennt die Meldung den Weg über das Bundle.
* **Branch oder losgelöst:** Commit (Hex-Präfix) und Tag (im Bundle oder
  lokal) → losgelöst; ein Branch, den das Bundle (`refs/heads/<ref>`) bzw. der
  Checkout kennt → `git checkout -B <ref> <commit>` **ohne Upstream** (ein
  früherer wird entfernt); unbekannt → losgelöst. Lokale Commits auf dem
  Ziel-Branch → Exit 3 wie bisher.
* **Tags des Bundles** kommen mit (bestehende werden nie überschrieben): die
  Version ist `git describe --tags` (D2), ohne sie stünde nach einem Update auf
  einen Tag nur „älterer Tag + Abstand“ da.
* **Images:** Magister baut weiterhin aus dem Checkout (D2, D7: keine Abbilder aus
  GHCR). Gibt der Agent trotzdem einen Pull-Zugang als `DOCKER_CONFIG` mit,
  erbt docker ihn; `betrieb.sh` setzt und nennt die Variable nie.
* `stand`, `sichern`, `zurueck` und `neustart` brauchen kein origin (getestet
  ohne Remote).

Verworfen: ein Archiv statt Bundle (Commit, `git describe` und `zurueck` per
Checkout gingen verloren); ein Lese-Zugang je Host (widerspricht „nur das
Cockpit hat einen GitHub-Zugang“).

Folge: Reihenfolge für den Betrieb — erst jeden Host auf diesen Stand bringen
und den Host-Agenten neu einrichten, dann das Repo privat stellen. Danach
geht ein `git pull` von Hand (und der Ops-Agent der Konsole mit `git pull
--ff-only`, ADR-0024 D5) nur mit eigenem Lese-Zugang des Hosts. Die
Magister-Plattform als Vorlage im Cockpit (`plattform-aufbau.sh` aus einer
Konfigurationsdatei) kommt in dieser Runde nicht: das Cockpit führt genau eine
Datenebene.
