# Runbook · Plattform-CA

> Die private CA signiert die Client-Zertifikate der Connector-Agenten
> ([ADR-0014](../adr/0014-ad-connector-agent.md)) und der Konsolen-Operatoren
> ([ADR-0015](../adr/0015-authentisierungs-haertung.md) D1).
> Entscheid E9: **Offline-Root auf zwei verschlüsselten Datenträgern.**
> Status: **Verfahren entworfen, noch nicht ausgeführt.**

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
gezogen, WLAN aus), ein Linux-Live-System vom USB-Stick, zwei neue
USB-Datenträger. Zwei Personen anwesend, beide zeichnen das Protokoll.

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

**Datenträger schreiben.** Beide Datenträger identisch, LUKS-verschlüsselt:

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
je einer bei einem der beiden Schlüsselverwahrer. Eine Person mit Datenträger
**und** Umschlag kann den Root benutzen — das ist gewollt, damit ein Ausfall
einer Person die Plattform nicht blockiert, und akzeptabel, weil eine Zeremonie
ohnehin protokolliert wird.

**Ablage.** Die zwei Datenträger an **getrennten Standorten**, jeweils in einem
verschlossenen Behälter. Nicht beide im gleichen Gebäude, sonst schützt die
Zweitkopie nur gegen Datenträgerdefekt, nicht gegen Feuer.

## 4 · Ausstellen eines Intermediate (Zeremonie)

Nur bei Erstinbetriebnahme und alle 5 Jahre. Immer zu zweit, immer offline,
immer mit Protokoll.

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
Seriennummer, Fingerprint, welcher Datenträger benutzt wurde, wann er wieder
verschlossen wurde.

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
| **Ein Datenträger defekt oder verloren** | Kein Notfall, aber kein Aufschub: mit dem zweiten Datenträger einen neuen erzeugen (Abschnitt 3, nur der Datenträger-Teil), Protokoll ergänzen. Bei *Verlust* (nicht Defekt) den Root vorsorglich austauschen (Abschnitt 7) — man weiss nicht, wer den Datenträger hat. |
| **Beide Datenträger verloren oder unlesbar** | Der Root ist weg. Bestehende Zertifikate laufen weiter, bis das erste Intermediate erneuert werden muss (bis zu 5 Jahre). In dieser Zeit einen neuen Root aufsetzen und beide Intermediates neu ausstellen — planbar, kein Ausfall. |
| **Passphrase-Umschläge beide weg** | Wie „beide Datenträger verloren": der Root ist unbenutzbar. |
| **Ein Schlüsselverwahrer fällt dauerhaft aus** | Der andere hat Datenträger und Umschlag und kann handeln. Danach sofort einen neuen zweiten Verwahrer bestimmen und Datenträger plus Umschlag übergeben. |
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
| Jährlich | Beide Datenträger lesen (Bitrot), `SHA256SUMS` prüfen, Protokoll ergänzen. Gleichzeitig prüfen, ob die Verwahrer noch die richtigen Personen sind. |
| Jährlich | Verlustfall einmal trocken durchspielen: Datenträger holen, entschlüsseln, Fingerprint vergleichen, zurücklegen. Ein Verfahren, das nie geübt wurde, funktioniert im Ernstfall nicht. |
| 6 Monate vor Ablauf | Intermediate erneuern (Abschnitt 4). |
| Bei Personalwechsel | Verwahrer wechseln, Umschlag neu versiegeln. |

## 9 · Was noch festzulegen ist

Diese Angaben kann nur Vita Brevis liefern; ohne sie ist das Verfahren
unvollständig:

1. **Die zwei Schlüsselverwahrer** — namentlich. Vorschlag: Geschäftsführung
   plus technische Leitung, damit nicht beide Rollen dieselbe Person sind.
2. **Die zwei Standorte** für die Datenträger — konkret (Safe im Büro,
   Bankschliessfach, Privatadresse?). Bedingung: nicht dasselbe Gebäude.
3. **Wo das Protokoll liegt** — Papierordner mit den Datenträgern, oder ein
   getrennter Ordner. Es darf keine Passphrase enthalten.
4. **Ob ein dritter Datenträger** gewünscht ist. Drei Kopien erhöhen die
   Verfügbarkeit und die Angriffsfläche gleichermassen; bei zwei getrennten
   Standorten ist zwei aus meiner Sicht ausreichend.
5. **Ob der Offline-Rechner** ein dediziertes Gerät sein soll (bleibt im Safe)
   oder ein Live-System auf beliebiger Hardware. Live-System ist billiger und
   hinterlässt nichts; ein dediziertes Gerät ist bequemer.
