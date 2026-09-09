# apt-Repository und Signaturen

Entscheid **E18, Schritt 1** (2026-09-09): GPG-Signatur und ein
`apt`-Repository. Damit ist **E10** frei — automatische Aktualisierung des
Agenten braucht eine Quelle, aus der ein Kunde ziehen kann, ohne dass ein
Mensch ein Paket kopiert.

Schritt 2 (Windows-Code-Signing-Zertifikat mit Hardware-Verwahrung) ist an ein
Ereignis gebunden und nicht an einen Zeitpunkt: **beim ersten Kunden mit
AppLocker oder ab der dritten Windows-Installation.** „Später" verfällt, ein
Ereignis nicht.

## Was apt tatsächlich prüft

Nicht das `.deb`. Die Kette hängt an genau einer Signatur:

```
InRelease / Release.gpg   ← signiert
  └── SHA-256 von Packages
        └── SHA-256 jedes .deb
```

Wer also glaubt, ein „signiertes .deb" sei der Schutz, sichert die falsche
Datei: `dpkg-sig`-Signaturen prüft apt von sich aus überhaupt nicht. Der
Schutz ist die signierte `Release`-Datei — und dass der Kunde den richtigen
öffentlichen Schlüssel unter `/etc/apt/keyrings/` liegen hat.

## Der Signierschlüssel

**Primärschlüssel offline, Signier-Unterschlüssel auf der Baumaschine.** Das
ist der Kern, und zwar aus einem konkreten Fall: wird die Baumaschine
übernommen, soll die Identität des Repositories nicht verloren sein. Mit einem
Unterschlüssel widerruft man diesen, stellt einen neuen aus — und **kein Kunde
muss seinen Keyring anfassen**, weil der Primärschlüssel derselbe bleibt. Läge
der Primärschlüssel selbst auf der Baumaschine, wäre der Wiederaufbau ein
Rundschreiben an alle Kunden.

Erzeugt wird er auf demselben Live-System wie die Plattform-CA (Entscheid E20)
und in derselben Sitzung protokolliert; der Primärschlüssel geht auf die
CA-Sticks in den Tresor.

`--pinentry-mode loopback` steht überall dabei und ist nicht Zierrat: ohne sie
ignoriert gpg 2.x die `--passphrase-file` und will trotzdem den Agenten fragen.
Auf einem Live-System ohne Terminal-Sitzung scheitert das mit
*„Inappropriate ioctl for device"* — geprüft, nicht vermutet.

```bash
# Auf dem Offline-Rechner, im tmpfs.
export GNUPGHOME=/mnt/ceremony/gnupg     # kurz halten: der gpg-agent-Socket
mkdir -p "$GNUPGHOME" && chmod 700 "$GNUPGHOME"   # hat eine Längengrenze

# 1. Primärschlüssel: NUR beglaubigen (certify), kein Signieren.
gpg --batch --pinentry-mode loopback --passphrase-file /mnt/ceremony/pass.txt \
    --quick-gen-key 'Vita Brevis Magister Packaging <packaging@vitabrevis.ch>' \
    ed25519 cert never

FPR=$(gpg --with-colons --fingerprint packaging@vitabrevis.ch \
      | awk -F: '$1=="fpr"{print $10; exit}')

# 2. Signier-Unterschlüssel, ein Jahr.
gpg --batch --pinentry-mode loopback --passphrase-file /mnt/ceremony/pass.txt \
    --quick-add-key "$FPR" ed25519 sign 1y

# 3. Widerrufszertifikat für den Fall, dass der Primärschlüssel verloren geht
#    — ohne es ist ein verlorener Primärschlüssel ein Repository, das man
#    nicht abkündigen kann.
gpg --output /mnt/ceremony/packaging-revoke.asc --gen-revoke "$FPR"

# 4. Was wohin geht:
#    - Primärschlüssel + Widerrufszertifikat  → CA-Sticks (Tresor)
#    - NUR der Unterschlüssel                 → Baumaschine
gpg --batch --pinentry-mode loopback --passphrase-file /mnt/ceremony/pass.txt \
    --export-secret-subkeys --armor "$FPR" > /mnt/transport/packaging-subkey.asc
gpg --export --armor "$FPR" > /mnt/transport/magister-archive-keyring.asc
```

Der Fingerprint gehört ins Zeremonie-Protokoll und damit nach `docs/ca/`
(Entscheid E19) — er ist die Angabe, an der ein Kunde erkennt, ob sein Keyring
der richtige ist.

Auf der Baumaschine dann `gpg --import packaging-subkey.asc` und
`gpg --import magister-archive-keyring.asc`. Dass der Primärschlüssel dort
**nicht** liegt, sieht man an der Raute:

```
sec#  ed25519 … [C]        ← die # heisst: geheimer Primärschlüssel fehlt
ssb   ed25519 … [S] [expires: …]
```

Was dort liegt, kann signieren und **nicht** einen weiteren Unterschlüssel
beglaubigen.

**Die Passphrase bleibt.** Sie wird bei jeder Freigabe von
Hand eingegeben — eine Freigabe ist ein Ereignis und kein Cron-Job, und
`build-repo.sh` lässt gpg deshalb fragen (kein `--batch` beim Signieren). Wer
sie in eine Datei neben den Schlüssel legt, hat einen Schlüssel ohne
Passphrase mit einem zusätzlichen Handgriff. Für CI mit Wegwerfschlüssel gibt
es `--passphrase-file`.

### Wenn der Unterschlüssel kompromittiert ist

```bash
# Auf dem Offline-Rechner, mit dem Primärschlüssel:
gpg --edit-key "$FPR"      # key 1 → revkey → save
gpg --quick-add-key "$FPR" ed25519 sign 1y
gpg --export --armor "$FPR" > magister-archive-keyring.asc   # neu ausliefern
```

Der Keyring beim Kunden bleibt gültig; er lernt den Widerruf mit dem nächsten
`magister-archive-keyring.asc`. Das ist der Grund für die Trennung.

## Repository bauen

```bash
agent/packaging/apt/build-repo.sh --out /srv/apt \
    --key 'Vita Brevis Magister Packaging' \
    agent/packaging/debian/magister-connector_0.1.0_amd64.deb
```

Das Ergebnis ist ein statisches Verzeichnis — HTTPS davor, kein
Anwendungsserver, keine Datenbank:

```
/srv/apt/
├── dists/stable/Release            ← signiert
├── dists/stable/Release.gpg
├── dists/stable/InRelease
├── dists/stable/main/binary-amd64/{Packages,Packages.gz,Release}
├── pool/main/m/magister-connector/*.deb
└── magister-archive-keyring.asc    ← der öffentliche Schlüssel
```

**`Valid-Until` läuft nach 30 Tagen ab.** Das ist Absicht: ohne Ablauf
akzeptiert apt eine beliebig alte, korrekt signierte `Release`-Datei — wer
einmal eine Version mit einer Lücke ausgeliefert hat, könnte sie damit
unbegrenzt weiter ausliefern. Der Preis: das Repository muss mindestens
monatlich neu signiert werden, auch wenn sich nichts geändert hat. Das gehört
in denselben Kalender wie die Jahreskontrolle der CA-Sticks.

### `apt-ftparchive` und nicht reprepro

Für eine Handvoll Pakete aus einer Quelle braucht es keine Datenbank, keinen
Zustand und kein zweites Werkzeug, das man alle zwei Jahre neu lernt.
`apt-ftparchive` gehört zu apt selbst: es ist auf jedem Debian und Ubuntu da
und veraltet nicht anders als apt. Kommen später mehrere Suites mit
Aufstiegspfad dazu (`testing` → `stable`), ist reprepro der richtige Schritt —
dann aber aus einem Bedarf.

## Beim Kunden

```bash
sudo install -d -m 755 /etc/apt/keyrings
curl -fsSL https://apt.magister.ch/magister-archive-keyring.asc \
  | sudo gpg --dearmor -o /etc/apt/keyrings/magister-archive-keyring.gpg

# Fingerprint gegen das Datenblatt prüfen — der Schritt, den man nicht
# überspringt: ohne ihn vertraut man dem Kanal, über den man den Schlüssel
# gerade geholt hat.
gpg --show-keys /etc/apt/keyrings/magister-archive-keyring.gpg

echo "deb [signed-by=/etc/apt/keyrings/magister-archive-keyring.gpg] \
https://apt.magister.ch/ stable main" \
  | sudo tee /etc/apt/sources.list.d/magister.list

sudo apt-get update
sudo apt-get install magister-connector
```

`signed-by` ist nicht optional. Ohne es gilt der Schlüssel für **alle**
Repositories in der Datei — auch für die von Debian, und umgekehrt würde ein
kompromittierter Spiegel eines Dritten von unserem Schlüssel gedeckt.
`apt-key add` tat genau das und ist deshalb abgeschafft.

## Was geprüft ist

Gegen `apt 2.8.3` mit dem echten `.deb` (39 MB, 6351 Einträge), in einem
eigenen apt-Wurzelverzeichnis:

| Fall | Ergebnis |
|---|---|
| richtig signiert, richtiger Keyring | `Candidate: 0.1.0`, Priorität 500 — gesehen und vertrauenswürdig |
| unsigniert | `E: The repository '…' is not signed.` |
| signiert, **falscher** Schlüssel im Keyring | `NO_PUBKEY …` und `is not signed` |
| `--key` fehlt und `--unsigned` nicht gesetzt | das Skript baut nichts |
| Signatur **nur mit dem Unterschlüssel** (Primärschlüssel nicht auf der Maschine) | apt nimmt es an; `gpg --verify` nennt den Unterschlüssel und darunter den Fingerprint des Primärschlüssels |
| `--batch` beim Signieren mit passphrasegeschütztem Schlüssel | *„signing failed: Inappropriate ioctl for device"* — deshalb signiert das Skript ohne `--batch` |

Beide Verneinungen laufen als Schritte in `.github/workflows/agent-ci.yml` mit.
Der Grund: ein Test, der nur den geglückten Fall prüft, wird auch grün, wenn
die Signatur bedeutungslos ist.

## Was noch fehlt

* **Der Ort.** `apt.magister.ch` existiert noch nicht. Es braucht nur
  statisches HTTPS-Hosting — der DNS-Eintrag und ein Caddy mit einem
  Wurzelverzeichnis genügen.
* **E10, die automatische Aktualisierung selbst.** Das Repository ist die
  Voraussetzung, nicht die Umsetzung. Offen ist die Frage, die E10 zu
  entscheiden hat: `unattended-upgrades` mit unserer Quelle in der Allowlist
  (der Kunde bekommt neue Fassungen ohne Termin, wir müssen jede Fassung
  entsprechend ernst nehmen) oder ein Hinweis in der Konsole, dass eine neue
  Fassung bereitliegt.
* **Windows.** Schritt 2 von E18, siehe oben.
