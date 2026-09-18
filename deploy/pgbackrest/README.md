# Cluster-PITR mit pgBackRest

Ebene 1 der Sicherung aus [ADR-0016](../../docs/adr/0016-sicherung-wiederherstellung-export.md)
D1, umgesetzt nach **Entscheid E17 (Variante B, 2026-09-09)**: das Repository
liegt auf dem **Backup-Host**.

Ebene 2 — der logische Dump pro Kunde — bleibt daneben stehen und wird davon
nicht ersetzt. PITR kann keinen einzelnen Kunden zurückrollen, und ein Dump
kann keinen Cluster auf 14:37 bringen.

## Warum überhaupt

Ohne diese Ebene lautet die Zusage an einen Kunden: „jeder Stand der letzten
zehn Tage, in Nachtgranularität". Bei einem Datenbankschaden um 16:00 ist damit
ein Arbeitstag **aller** Kunden verloren. Genau diesen Fall deckt Ebene 2
ausdrücklich nicht ab.

## Der Aufbau

```
Anwendungsserver (app.magister.intern)          Backup-Host (backup.magister.intern)
┌──────────────────────────────────┐            ┌────────────────────────────────────┐
│ postgres                         │            │ pgbackrest server  :8432           │
│   archive_command ──────────────────WAL──────▶ │   Repository /var/lib/pgbackrest   │
│                                  │            │   verschlüsselt (aes-256-cbc)      │
│ pgbackrest server  :8433 ◀────────Sicherung────│ pgbackrest backup (cron, nachts)   │
└──────────────────────────────────┘            │ privater age-Schlüssel (Ebene 2)   │
                                                └────────────────────────────────────┘
```

Zwei Richtungen, und beide sind gewollt:

* **WAL geht hinüber** (der Anwendungsserver schiebt). Es muss laufend
  passieren, sonst ist die Kette lückenhaft.
* **Die Sicherung wird von dort angestossen** (der Backup-Host holt). Die Seite,
  die das Repository besitzt, entscheidet, wann gesichert und was verworfen
  wird. Das ist derselbe Gedanke wie bei den Kunden-Dumps, wo das Löschrecht
  auf dem Fileserver liegt und nicht auf dem Anwendungsserver (ADR-0016 D2).

### TLS und nicht SSH

pgBackRest kann beides. Wir nehmen TLS, und der Grund ist nicht Bequemlichkeit:

| | SSH | TLS |
|---|---|---|
| Was der Anwendungsserver auf dem Backup-Host darf | einen Befehl ausführen — eingeschränkt über ein `command=` in `authorized_keys`, also über eine Zeile, die stimmen muss | ausschliesslich das pgBackRest-Protokoll sprechen |
| Wenn die Einschränkung fehlerhaft ist | Shell-Zugang | nichts, das Protokoll kennt keine Shell |
| Welche Stanzas erreichbar sind | alle, die der Schlüssel erreicht | die in `tls-server-auth` genannten |

Die Annahme dahinter ist dieselbe wie beim Connector-Agenten (ADR-0014): **der
Anwendungsserver könnte kompromittiert sein.** Wer ihn übernimmt, soll nicht
in einem Schritt die Sicherungen mitbekommen.

Was TLS **nicht** verhindert: wer den Anwendungsserver übernimmt, kann weiter
WAL ins Repository schreiben und damit die Kette ab diesem Zeitpunkt entwerten.
Verwerfen kann er nichts — `expire` läuft auf dem Backup-Host und wird von dort
angestossen. Die älteren Basebackups und das WAL dazu bleiben also lesbar, und
genau dafür steht `repo1-retention-full=2`: die vorige Vollsicherung ist der
Stand, auf den man zurückgeht, wenn dem neueren nicht mehr zu trauen ist.

### Die Verschlüsselung des Repositories

`repo1-cipher-pass` steht **nur** in der Konfiguration des Backup-Hosts. Der
Anwendungsserver verschlüsselt nichts selbst; das tut der Remote-Prozess auf
der anderen Seite. Wer den Anwendungsserver übernimmt, bekommt damit keinen
Schlüssel für alte Sicherungen — dieselbe Trennung wie beim `age`-Schlüssel
für die Kunden-Dumps.

Die Passphrase gehört in denselben Verwahrungsablauf wie der private
age-Schlüssel (siehe [platform-ca.md](../../docs/runbooks/platform-ca.md) §3).
Sie zu verlieren heisst: alle Basebackups und alle WAL-Dateien verlieren.

## Die Dateien hier

| Datei | Wohin |
|---|---|
| `pgbackrest.conf.app.example` | Anwendungsserver → `/etc/pgbackrest.conf` (0600, `postgres`) |
| `pgbackrest.conf.backup.example` | Backup-Host → `/etc/pgbackrest.conf` (0600, `pgbackrest`) |
| `issue-channel-certs.sh` | läuft auf dem Backup-Host, erzeugt die Kanal-CA und beide Zertifikate |
| `pgbackrest-server.service` | beide Maschinen; `User=` unterscheidet sich |
| `Dockerfile.postgres` | Postgres 16 **mit** pgBackRest, für die containerisierte Installation |
| `../compose/docker-compose.pitr.yml` | Overlay, das die Archivierung einschaltet |
| `../../scripts/pitr-drill.sh` | die Übung: Wiederherstellung auf einen Zeitpunkt, auf dem Backup-Host |

## Was beim Aufbau tatsächlich schiefgegangen ist

Sechs Dinge, alle gemessen, alle in einem Probeaufbau gegen ein echtes
Postgres 16 mit pgBackRest 2.50 gefunden. Sie stehen hier, weil jedes einzelne
eine halbe Stunde Suchen an der falschen Stelle gekostet hat:

1. **Jeder Host braucht seine eigene `/etc/pgbackrest.conf`.** Der
   Remote-Prozess, den die eine Seite auf der anderen startet, liest
   `lock-path`, `log-path`, `spool-path` und `pg1-path` aus der
   Standard-Konfiguration **seines** Hosts — diese Werte kommen nicht über die
   Leitung. Anwendungsserver und Backup-Host können deshalb nicht dieselbe
   Maschine sein, auch nicht zum Ausprobieren.
2. **Der Hostname muss im Zertifikat stehen.** pgBackRest prüft
   `repo1-host`/`pg1-host` gegen CN und SAN und bricht sonst ab mit *„unable to
   find hostname '…' in certificate common name or subject alternative names"*.
   Eine IP-Adresse verlangt ein Zertifikat mit IP-SAN; `issue-channel-certs.sh`
   lehnt IPs deshalb ab.
3. **`lock-path` explizit setzen.** Die Vorgabe ist `/tmp/pgbackrest`. Streiten
   sich zwei Dienstkonten darum, lautet die Meldung *„unable to get info for
   path/file '/tmp/pgbackrest/<stanza>.stop': Permission denied"* — und zeigt
   auf eine Datei, die es nie gab.
4. **`restore` will ins Spool-Verzeichnis**, auch ohne asynchrone
   Archivierung. Auf dem Backup-Host muss `/var/spool/pgbackrest` dem Konto
   gehören, das die Übung fährt. Ein eigener `--spool-path` ist der
   naheliegende Ausweg und ein Holzweg: pgBackRest schreibt die Option ins
   `restore_command`, `archive-get` lehnt sie dort ab, die Wiederherstellung
   findet kein WAL und der Cluster stirbt mit *„invalid checkpoint record"* —
   drei Ecken von der Ursache entfernt. `--archive-async` lässt sich bei
   `restore` nicht mitgeben.
5. **Eine Wiederherstellung erbt die Pfade der Produktion.**
   `unix_socket_directories` zeigt auf `/var/run/postgresql`, wo das
   Übungskonto nicht schreiben darf, und der Cluster stirbt mit *„could not
   create lock file"*. Und die wiederhergestellte `pg_hba.conf` kennt das
   Übungskonto nicht.
6. **`pg_ctl -w` wartet nicht auf die Beförderung.** Der Cluster nimmt
   Verbindungen schon während der Wiederherstellung an; `pg_is_in_recovery()`
   direkt nach dem Start meldet deshalb zuverlässig „noch in Recovery", auch
   wenn alles richtig läuft. Die Übung wartet.

## Was geprüft ist und was nicht

**Geprüft**, in einem Aufbau mit getrennten Dienstkonten und gegenseitiger
Zertifikatsprüfung über TLS (pgBackRest 2.50, Postgres 16.13):

* `stanza-create`, `check`, `archive-push` und `backup` über den
  TLS-Remote-Pfad — die Sicherung wird vom Backup-Host angestossen und läuft.
* Eine echte Wiederherstellung auf einen Zeitpunkt: 500 Zeilen angelegt,
  Zeitpunkt notiert, zehn weitere Zeilen eingefügt, dann die Tabelle
  **gelöscht**. Nach `--type=time --target=<Zeitpunkt>` war die Tabelle wieder
  da, mit 500 Zeilen — die zehn nach dem Zielzeitpunkt eingefügten korrekt
  **nicht** dabei, und das Cluster-Protokoll nennt den Grund: *„recovery
  stopping before commit of transaction 745"*.
* `scripts/pitr-drill.sh` in beide Richtungen: bestanden bei einem erreichbaren
  Zeitpunkt, Rückgabewert ≠ 0 und klare Meldung bei einem unmöglichen.
* Beide Konfigurationsvorlagen werden von pgBackRest 2.50 gelesen und
  akzeptiert.

**Nicht geprüft**, und beim Aufbau deshalb Schritt für Schritt zu prüfen:

* Das Compose-Overlay lief noch nie gegen einen echten Docker-Daemon. Die
  YAML-Struktur stimmt, die Pfade und Rechte im Container (uid 999) sind
  hergeleitet und nicht gemessen.
* Der Betrieb über zwei echte Maschinen mit Firewall dazwischen.
* Wie lange ein Basebackup bei echter Datenmenge braucht und wie viel WAL pro
  Tag anfällt. Die Schätzung in `docs/entscheide-offen.md` (5–15 GB/Tag) ist
  eine Schätzung.

## Aufsetzen

Der Ablauf mit allen Befehlen steht im Runbook:
[sicherung-wiederherstellung.md](../../docs/runbooks/sicherung-wiederherstellung.md)
§1.4 und §2a.
