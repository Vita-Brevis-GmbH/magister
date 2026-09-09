# Runbook · Plattform-CA

> Die private CA signiert die Client-Zertifikate der Connector-Agenten
> ([ADR-0014](../adr/0014-ad-connector-agent.md)) und der Konsolen-Operatoren
> ([ADR-0015](../adr/0015-authentisierungs-haertung.md) D1).
> Entscheid E9: **Offline-Root auf verschlüsselten USB-Sticks im Tresor**,
> Passphrase getrennt davon bei zwei Schlüsselverwahrern.
> Verwahrer: **Matthias Hadorn** und **Rolf Straubhaar**.
> Status: **Verfahren vollständig festgelegt (E9, E19, E20), Zeremonie noch
> nicht ausgeführt — sie kann terminiert werden.**

## 1 · Warum es dieses Verfahren braucht

Wer den Root-Schlüssel hat, kann sich ein Agent-Zertifikat für **jeden** Kunden
ausstellen und ein Operator-Zertifikat für die Konsole. Der Schlüssel ist damit
das wertvollste Geheimnis der Plattform — wertvoller als jedes einzelne
Kundenpasswort.

Gleichzeitig braucht man ihn selten: nur um ein Intermediate auszustellen oder
zu erneuern. Deshalb offline: er liegt nicht auf einem Server, sondern im
Schrank, und kommt nur für eine Zeremonie heraus.

## 2 · Aufbau

```
Root-CA (offline, 20 Jahre)
└── Intermediate "Connector" (5 Jahre, auf dem Plattform-Server)
│   └── Agent-Zertifikate (90 Tage, automatisch erneuert)
└── Intermediate "Operator" (5 Jahre, auf dem Plattform-Server)
    └── Operator-Zertifikate (1 Jahr, von Hand ausgestellt)
```

Zwei getrennte Intermediates, weil die zwei Zwecke verschiedene Lebenszyklen
und verschiedene Widerrufsgründe haben: ein verlorener Operator-Laptop soll
nicht die Agent-Flotte berühren.

Der Root selbst signiert nur diese zwei Intermediates. Für einen einzelnen
Kunden wird **kein** eigenes Intermediate ausgestellt — die Bindung an den
Kunden macht die Anwendung über den Fingerprint-Abgleich, nicht die
Zertifikatskette. (Das war im ersten Entwurf von ADR-0014 anders gedacht;
zwei Intermediates sind einfacher zu betreiben und ändern die Sicherheit
nicht, weil der Fingerprint-Abgleich ohnehin die scharfe Prüfung ist.)

## 3 · Einrichtung des Root (einmalig)

**Vorbereitung.** Ein Rechner ohne Netzverbindung (Notebook, Netzwerkkabel
gezogen, WLAN aus), ein Linux-Live-System vom USB-Stick, zwei neue USB-Sticks
plus einen **dritten, gewöhnlichen Transport-Stick** für das Protokoll.
Anwesend: **Matthias Hadorn** und **Rolf Straubhaar**, beide zeichnen das
Protokoll.

**Das Live-System und sein Hash (Entscheid E20).** Kein dediziertes Gerät,
sondern ein Live-System — aber eines, dessen Hash im Protokoll steht. Vor der
Zeremonie, auf einem Rechner mit Netz:

```bash
# 1. Image und die signierten Prüfsummen des Herstellers holen
#    (Debian: SHA256SUMS und SHA256SUMS.sign neben dem Image)
gpg --verify SHA256SUMS.sign SHA256SUMS
sha256sum -c SHA256SUMS --ignore-missing

# 2. Diesen Hash notieren — er geht in die Zeremonie mit
sha256sum debian-live-12.5-amd64-standard.iso
```

Die Reihenfolge ist der Punkt: erst die Signatur prüfen, dann den Hash nehmen.
Wer den Hash des heruntergeladenen Images ohne Signaturprüfung protokolliert,
protokolliert den Hash von etwas, das schon manipuliert sein konnte — sauber
nachvollziehbar und wertlos.

Das Skript **verlangt** diesen Hash bei `root` und `intermediate` und prüft im
`preflight`, ob die Wurzel wirklich flüchtig ist (`overlay`, `tmpfs`,
`squashfs`). Ein installiertes System ist dort ein Befund, kein Hinweis.

[`scripts/platform-ca-ceremony.sh`](../../scripts/platform-ca-ceremony.sh)
führt die Zeremonie schrittweise durch, prüft die Voraussetzungen und schreibt
die Fingerprints ins Protokoll, statt sie abschreiben zu lassen:

```bash
./scripts/platform-ca-ceremony.sh preflight
./scripts/platform-ca-ceremony.sh root  --workdir /mnt/ceremony \
    --live-image debian-live-12.5-amd64-standard.iso \
    --live-sha256 <der oben geprüfte Hash>
./scripts/platform-ca-ceremony.sh stick --workdir /mnt/ceremony --device /dev/sdX   # zweimal
```

Die Passphrase berührt das Skript nie — `cryptsetup` fragt sie selbst, sie
landet in keiner Variable und in keiner Datei. Was das Skript im Einzelnen tut,
steht unten; wer es von Hand machen will, kann das:

```bash
# 1. Root-Schlüssel und -Zertifikat, ECDSA P-384, 20 Jahre
openssl ecparam -name secp384r1 -genkey -noout -out root.key
chmod 400 root.key
openssl req -new -x509 -sha384 -days 7300 -key root.key -out root.crt \
  -subj "/C=CH/O=Vita Brevis GmbH/CN=Vita Brevis Magister Root CA" \
  -addext "basicConstraints=critical,CA:TRUE,pathlen:1" \
  -addext "keyUsage=critical,keyCertSign,cRLSign"

# 2. Fingerprint ins Protokoll
openssl x509 -in root.crt -noout -fingerprint -sha256
```

**Sticks schreiben.** Beide Sticks identisch, LUKS-verschlüsselt — der
zweite ist die Kopie gegen Datenträgerdefekt, nicht eine zweite Berechtigung:

```bash
cryptsetup luksFormat /dev/sdX          # Passphrase: siehe unten
cryptsetup open /dev/sdX ca && mkfs.ext4 /dev/mapper/ca
mount /dev/mapper/ca /mnt/ca
cp root.key root.crt /mnt/ca/
sha256sum /mnt/ca/* > /mnt/ca/SHA256SUMS
umount /mnt/ca && cryptsetup close ca
```

Danach `root.key` auf dem Live-System **sicher** löschen — beziehungsweise das
Live-System einfach neu starten, es hält nichts persistent.

**Passphrase.** Nicht eine Person, nicht ein Passwortmanager auf einem Server:
die Passphrase wird auf Papier in **zwei versiegelten Umschlägen** hinterlegt,
je einer bei Matthias Hadorn und bei Rolf Straubhaar. Eine Person mit Stick
**und** Umschlag kann den Root benutzen — das ist gewollt, damit ein Ausfall
einer Person die Plattform nicht blockiert, und akzeptabel, weil eine Zeremonie
ohnehin protokolliert wird.

**Ablage (Entscheid E9).** Die Sticks liegen im **Tresor von Vita Brevis**.
Zwei identische Sticks, beide im selben Tresor.

Eine Trennung muss dabei halten, sonst ist der ganze Aufwand umsonst:
**die Umschläge gehören nicht in den Tresor.** Liegen Stick und Passphrase am
gleichen Ort, ist der Tresorzugang der einzige Faktor und die Zwei-Personen-Regel
existiert nur auf dem Papier. Die Umschläge bleiben persönlich bei den beiden
Verwahrern.

**Was ein einziger Standort kostet — und was nicht.** Ein verlorener Root ist
kein Ausfall. Bestehende Intermediates und alle davon ausgestellten Zertifikate
laufen weiter, bis das erste Intermediate erneuert werden muss — also bis zu
fünf Jahre. Wer den Root verliert, baut in dieser Zeit einen neuen auf: planbar,
ohne Unterbruch für Kunden. Der einzige Standort kostet Verfügbarkeit in einem
Fall, der ohnehin Jahre Vorlauf hat.

Für die **Vertraulichkeit** ist ein Standort eher besser als zwei: ein Ort,
dessen Zugang kontrolliert wird, statt zweier. Und die Vertraulichkeit ist hier
die Seite, die weh tut — wer Stick und Passphrase hat, stellt sich ein
Agent-Zertifikat für jeden Kunden und ein Operator-Zertifikat für die Konsole
aus. Deshalb bleibt es beim Tresor.

Die zweite Kopie im selben Tresor deckt den mit Abstand häufigsten Verlustfall
ab, den defekten Stick, und kostet zwanzig Franken. Gegen Feuer oder Einbruch im
Tresorraum hilft sie nicht: dieser Fall bleibt **bewusst offen** und ist nach
obiger Rechnung tragbar. Kommt später ein zweiter Standort dazu
(Bankschliessfach, zweiter Bürostandort), gehört ein Stick dorthin — das ist
eine Verbesserung, keine Voraussetzung für den Start.

## 4 · Ausstellen eines Intermediate (Zeremonie)

Nur bei Erstinbetriebnahme und alle 5 Jahre. Immer zu zweit, immer offline,
immer mit Protokoll.

```bash
# Mit dem Skript, auf dem Offline-Rechner mit entsperrtem Stick:
./scripts/platform-ca-ceremony.sh intermediate \
    --workdir /mnt/ca --csr connector-int.csr --purpose connector \
    --live-image debian-live-12.5-amd64-standard.iso \
    --live-sha256 <der geprüfte Hash>
```

Es prüft die Selbstsignatur der CSR, lässt den Subject bestätigen, setzt
`pathlen:0` (das Intermediate darf keine weiteren CAs ausstellen), verifiziert
die Kette gegen den Root und protokolliert Seriennummer und Fingerprint. Von
Hand:

```bash
# Auf dem Plattform-Server: Schlüssel und CSR erzeugen, Schlüssel bleibt dort
openssl ecparam -name secp384r1 -genkey -noout -out connector-int.key
openssl req -new -sha384 -key connector-int.key -out connector-int.csr \
  -subj "/C=CH/O=Vita Brevis GmbH/CN=Magister Connector Issuing CA"

# CSR auf einen USB-Stick, damit zum Offline-Rechner; dort:
openssl x509 -req -in connector-int.csr -CA root.crt -CAkey root.key \
  -CAcreateserial -sha384 -days 1826 -out connector-int.crt \
  -extfile <(printf 'basicConstraints=critical,CA:TRUE,pathlen:0\nkeyUsage=critical,keyCertSign,cRLSign\n')

# Nur das Zertifikat zurück auf den Server. Nie der Root-Schlüssel.
```

Der private Schlüssel des Intermediate entsteht auf dem Server und verlässt ihn
nie. Der Root-Schlüssel verlässt den Offline-Rechner nie.

**Protokoll** (Papier, beide Unterschriften): Datum, Anwesende, Zweck,
Seriennummer, Fingerprint, Live-System und dessen Hash, welcher Datenträger
benutzt wurde, wann er wieder verschlossen wurde.

## 4a · Das Protokoll ins Repository (Entscheid E19)

Das Protokoll lebt an **zwei** Orten: auf dem Stick und im Repository unter
[`docs/ca/`](../ca/). Der zweite Ort existiert für den Fall „wer hat dieses
Intermediate ausgestellt, und wer war dabei?" zwei Jahre später — ohne
Tresorgang, und auch dann noch, wenn beide Sticks verloren sind.

Noch auf dem Offline-Rechner, **vor** dem Neustart:

```bash
# Nur diese eine Datei, auf einen gewöhnlichen Transport-Stick.
cp /mnt/ceremony/PROTOKOLL.md /mnt/transport/
```

Danach, an einem Rechner **mit** Netz und Repository-Klon:

```bash
./scripts/platform-ca-ceremony.sh protokoll --file /mnt/transport/PROTOKOLL.md
git add docs/ca/protokoll-*.md && git commit -m 'docs(ca): Protokoll der Zeremonie vom ...'
```

Zwei Dinge daran sind nicht Bequemlichkeit:

* **Der CA-Stick hängt nie an einem Rechner mit Netz.** Deshalb der dritte,
  gewöhnliche Transport-Stick — und deshalb läuft `protokoll` nicht auf dem
  Offline-Rechner, der keinen Klon hat.
* **Das Skript prüft, bevor es kopiert.** Der Weg ins Repository ist der einzige
  Weg, auf dem etwas aus einer Zeremonie öffentlich werden kann; wer im Eifer
  das ganze Arbeitsverzeichnis kopiert, kopiert den Root-Schlüssel mit. Es
  lehnt PEM-Marker privater Schlüssel, `AGE-SECRET-KEY-1`, `MK digest:` und
  einen Passphrase-**Wert** ab. Das Wort *Passphrase* darf stehen —
  „Passphrase in zwei versiegelten Umschlägen" ist genau die Aussage, die
  hineingehört.

Gültig bleibt das unterschriebene Papier. Was im Repository liegt, ist die
durchsuchbare Kopie.

## 5 · Widerruf

Es gibt **keine CRL und kein OCSP**. Widerruf ist ein Datenbank-Flag, das die
Anwendung bei jeder Anfrage prüft (ADR-0014 §6). Das ist bewusst so: eine CRL,
die einmal am Tag aktualisiert wird, wäre langsamer und fehleranfälliger als
eine Zeile in der Registry.

- **Agent-Zertifikat:** in der Konsole widerrufen → nächste Anfrage 401.
- **Operator-Zertifikat:** in der Konsole widerrufen → nächster Handshake
  scheitert an der Anwendungsprüfung (Caddy prüft die Kette, die Anwendung den
  Fingerprint).

## 6 · Wenn etwas verloren geht

| Fall | Was zu tun ist |
|---|---|
| **Ein Stick defekt** | Kein Notfall, aber kein Aufschub: mit dem zweiten Stick eine neue Kopie erzeugen (Abschnitt 3, nur der Stick-Teil), Protokoll ergänzen. Der defekte Stick wird physisch zerstört, nicht weggeworfen. |
| **Ein Stick fehlt im Tresor** | Anders als ein Defekt: jemand hat ihn. Root vorsorglich austauschen (Abschnitt 7) und den Vorfall behandeln, auch wenn die Passphrase nicht mit im Tresor lag — Zeit arbeitet für den, der den Stick hat. |
| **Beide Sticks unlesbar, Tresor zerstört oder ausgeräumt** | Der Root ist weg. Bestehende Zertifikate laufen weiter, bis das erste Intermediate erneuert werden muss (bis zu 5 Jahre). In dieser Zeit einen neuen Root aufsetzen und beide Intermediates neu ausstellen — planbar, kein Ausfall für Kunden. Das ist der Fall, den der einzige Standort bewusst offen lässt (Abschnitt 3). |
| **Passphrase-Umschläge beide weg** | Wie „beide Sticks unlesbar": der Root ist unbenutzbar. Deshalb prüft die Jahreskontrolle beide Umschläge mit. |
| **Ein Schlüsselverwahrer fällt dauerhaft aus** | Der andere hat Tresorzugang und seinen Umschlag und kann handeln. Danach sofort einen neuen zweiten Verwahrer bestimmen, Umschlag neu versiegeln und übergeben. |
| **Intermediate-Schlüssel kompromittiert** (Server übernommen) | Der schwerwiegendste Fall. Alle davon ausgestellten Zertifikate in der Registry widerrufen, neues Intermediate ausstellen (Zeremonie), alle Agenten neu anmelden. Die Agenten kommen mit Einmal-Token wieder herein — der Ablauf existiert also schon, er ist nur mühsam. |
| **Root-Schlüssel kompromittiert** | Vollständiger Neuaufbau: neuer Root, neue Intermediates, alle Agenten und Operatoren neu. Deshalb liegt er offline. |

## 7 · Root austauschen (planbar)

Neuen Root erzeugen, **beide** Intermediates zusätzlich vom neuen Root
signieren, das neue Root-Zertifikat über den Connector-Kanal an die Agenten
verteilen (sie pinnen dann beide), erst danach das alte Root-Zertifikat aus dem
Bundle entfernen. Überlappung mindestens 30 Tage, damit kein Agent unterwegs
den Anschluss verliert.

## 8 · Wiederkehrende Aufgaben

| Wann | Was |
|---|---|
| Jährlich | Beide Sticks lesen (Bitrot), `SHA256SUMS` prüfen, Protokoll ergänzen — und das ergänzte Protokoll wieder nach `docs/ca/` exportieren (`protokoll --file ...`), sonst driftet die Kopie im Repository von der auf dem Stick weg. Gleichzeitig prüfen, ob Matthias Hadorn und Rolf Straubhaar noch die richtigen Verwahrer sind und ob **beide Umschläge** noch vorhanden und versiegelt sind. |
| Jährlich | Verlustfall einmal trocken durchspielen: Stick holen, mit dem Umschlag entschlüsseln, `platform-ca-ceremony.sh verify --workdir /mnt/ca` laufen lassen, zurücklegen. Ein Verfahren, das nie geübt wurde, funktioniert im Ernstfall nicht. Diese Übung ist gleichzeitig die einzige regelmässige Prüfung, dass die Passphrase noch stimmt. |
| 6 Monate vor Ablauf | Intermediate erneuern (Abschnitt 4). |
| Bei Personalwechsel | Verwahrer wechseln, Umschlag neu versiegeln. |

## 9 · Festgelegt und noch offen

**Festgelegt (2026-09-08, Entscheid E9):**

| Punkt | Entscheid |
|---|---|
| Schlüsselverwahrer | **Matthias Hadorn** und **Rolf Straubhaar** |
| Ablage der Sticks | **Tresor von Vita Brevis**, zwei identische Sticks |
| Ablage der Passphrase | zwei versiegelte Umschläge, **persönlich bei den Verwahrern**, nicht im Tresor |
| Dritter Datenträger | **nein** — zwei Kopien am kontrollierten Ort, dafür die Jahreskontrolle |
| Zweiter Standort | **vorerst nicht**; die Begründung und der offen gelassene Fall stehen in Abschnitt 3 |

**Festgelegt (2026-09-09, Entscheide E19 und E20):**

| Punkt | Entscheid |
|---|---|
| Wo das Protokoll liegt | **auf dem Stick und im Repository** unter `docs/ca/` (E19, Variante B). Das unterschriebene Papier bleibt das gültige Dokument; die Kopie im Repository ist die, die ohne Tresorgang lesbar ist und einen Verlust beider Sticks überlebt. Der Weg dorthin läuft über `platform-ca-ceremony.sh protokoll`, das vorher auf Geheimnisse prüft. |
| Offline-Rechner | **Live-System auf bestehender Hardware** (E20, Variante A), kein dediziertes Gerät. Der Hash des Images steht im Protokoll und ist bei `root` und `intermediate` Pflicht. Ein Gerät für 250–400 CHF, das drei Jahre im Schrank liegt und dann mit ungepatchtem System aufwacht, ist teurer als der Gewinn. |

**Damit ist nichts mehr offen, was die Zeremonie blockiert.** Sie braucht:
das geprüfte Live-Image samt Hash, drei USB-Sticks (zwei neue für die CA, einer
für den Transport des Protokolls), zwei Umschläge, beide Verwahrer und
ungefähr zwei Stunden.

Kommt später eine Zertifizierung, die ein dediziertes Gerät verlangt, ist der
Wechsel eine Beschaffung und kein Umbau — das Verfahren bleibt dasselbe.
