# Protokolle der CA-Zeremonien

Hier liegen die Protokolle jeder Zeremonie der Plattform-CA — Entscheid **E19**
(2026-09-09): auf dem Stick **und** hier.

Der Grund für den zweiten Ort ist ein Fall, nicht eine Vorschrift: wer in zwei
Jahren fragt, welcher Schlüssel dieses Intermediate ausgestellt hat und wer
dabei war, müsste sonst in den Tresor. Bei einem Audit oder einem Vorfall ist
das genau der Moment, in dem man das nicht will. Und gehen beide Sticks
verloren, wäre mit dem Schlüssel auch der Nachweis weg, dass es die Zeremonie
je gegeben hat.

## Was hier hineingehört

Datum, Anwesende, Zweck, Subject, Gültigkeitsdauer, Seriennummer,
Fingerprint, der Hash des Live-Systems (Entscheid E20) und die
Unterschriftenzeilen. Das ist nicht geheim, sondern beweisend.

## Was hier niemals hineingehört

Der Root-Schlüssel, ein Intermediate-Schlüssel, die LUKS-Passphrase, ein
`age`-Identity — überhaupt kein privater Schlüssel und kein Passwort.

Das Wort *Passphrase* darf vorkommen: „Passphrase in zwei versiegelten
Umschlägen bei den Verwahrern" ist genau die Aussage, die hierher gehört. Ein
Passphrase-**Wert** nicht.

## Wie eine Datei hierher kommt

Nicht mit `cp`. Der Weg geht über das Zeremonie-Skript, weil es vorher prüft:

```bash
# Auf einem Rechner MIT Netz und Repository-Klon — nicht auf dem Offline-Rechner.
# Die Datei kommt über einen gewöhnlichen Transport-Stick; der CA-Stick bleibt,
# wo er ist, und hängt nie an einem Rechner mit Netz.
./scripts/platform-ca-ceremony.sh protokoll --file /mnt/transport/PROTOKOLL.md
```

Das Skript lehnt ab, wenn die Datei aussieht wie ein Geheimnis (PEM-Marker
eines privaten Schlüssels, `AGE-SECRET-KEY-1`, ein Passphrase-Wert), legt sie
sonst als `protokoll-<datum>.md` ab und nennt deren SHA-256. Diese Prüfung
ersetzt das Durchlesen nicht — es sind zwanzig Zeilen.

## Gültig ist das Papier

Das unterschriebene Papierprotokoll bleibt das gültige Dokument. Was hier
liegt, ist die durchsuchbare Kopie.

Referenz: [`docs/runbooks/platform-ca.md`](../runbooks/platform-ca.md),
[ADR-0014](../adr/0014-ad-connector-agent.md),
[ADR-0015](../adr/0015-authentisierungs-haertung.md) D1.
