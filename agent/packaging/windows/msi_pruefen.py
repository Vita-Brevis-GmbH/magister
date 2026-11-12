#!/usr/bin/env python3
"""Ein gebautes MSI von aussen prüfen — ohne Windows.

Der Anlass ist ein Paket, das die CI gebaut, `msiinfo` gelesen und Windows
mit „This installation package could not be opened" abgewiesen hat. Die
Übertragung war fehlerfrei (Hash auf dem Server = Hash auf dem Client), und
`msiexec /l*v` sagte nur `MainEngineThread is returning 1620` — kein Wort
dazu, woran es liegt.

Der Befund, nach dem Zerlegen des Containers: `wixl` schreibt in den
String-Pool die **Codepage 0** (= rein ASCII) und ignoriert dabei das
`Codepage`-Attribut der WiX-Quelle. Standen in einem Attributwert Umlaute,
landeten sie als Einzelbytes (`\\xe4`) in einer Datenbank, die ASCII
verspricht. Ein Leser, der es nicht so genau nimmt — `msiinfo` — liest das
anmutig; Windows Installer verweigert die Datei.

Das ist kein Fehler, den man beim Lesen der WiX-Quelle sieht: dort steht
korrektes UTF-8, und `Codepage="65001"` sah sogar nach einer Lösung aus. Also
wird das Ergebnis geprüft und nicht die Absicht.

    ./msi_pruefen.py magister-connector-x64.msi

Geprüft wird das, was Windows beim ÖFFNEN anschaut, bevor es überhaupt zum
Inhalt kommt: Containerformat, Wurzel-CLSID und die Widerspruchsfreiheit des
String-Pools.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

#: CLSID einer Installer-Datenbank. Ein Patch (.msp) hat eine andere; wer die
#: hier sieht, hat die falsche Datei gebaut.
MSI_CLSID = "000c1084-0000-0000-c000-000000000046"
MSP_CLSID = "000c1086-0000-0000-c000-000000000046"

#: Die Zeichen, mit denen MSI seine Stream-Namen kodiert.
ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz._"

FREI = 0xFFFFFFFF
ENDE = 0xFFFFFFFE


class Befund(Exception):
    """Etwas an der Datei stimmt nicht — mit Begründung."""


def _entmangeln(name: str) -> str:
    """Stream-Namen zurückübersetzen (MSI kodiert sie in einen eigenen Raum)."""
    aus: list[str] = []
    for i, ch in enumerate(name):
        c = ord(ch)
        if i == 0 and c == 0x4840:  # Markierung „Tabelle", kein Zeichen
            continue
        if 0x3800 <= c < 0x4800:
            v = c - 0x3800
            aus.append(ALPHABET[v & 0x3F])
            aus.append(ALPHABET[(v >> 6) & 0x3F])
        elif 0x4800 <= c < 0x4840:
            aus.append(ALPHABET[c - 0x4800])
        else:
            aus.append(ch)
    return "".join(aus)


class Container:
    """Der OLE-Verbunddatei-Anteil eines MSI, so weit wir ihn brauchen."""

    def __init__(self, pfad: Path) -> None:
        self.daten = pfad.read_bytes()
        kopf = self.daten[:512]
        if kopf[:8] != b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
            raise Befund(
                "Keine OLE-Signatur am Dateianfang. Das ist kein MSI — "
                "ein ZIP begänne mit 'PK'."
            )
        self.gr = 1 << struct.unpack_from("<H", kopf, 30)[0]
        dir_first = struct.unpack_from("<I", kopf, 48)[0]
        self.mini_cutoff, mini_first = struct.unpack_from("<II", kopf, 56)
        difat_first, n_difat = struct.unpack_from("<II", kopf, 68)

        fat_sektoren = [s for s in struct.unpack_from("<109I", kopf, 76) if s != FREI]
        naechster, rest = difat_first, n_difat
        while rest > 0 and naechster not in (ENDE, FREI):
            eintraege = struct.unpack_from("<%dI" % (self.gr // 4), self._sektor(naechster), 0)
            fat_sektoren += [s for s in eintraege[:-1] if s != FREI]
            naechster = eintraege[-1]
            rest -= 1
        self.fat: list[int] = []
        for s in fat_sektoren:
            self.fat += list(struct.unpack_from("<%dI" % (self.gr // 4), self._sektor(s), 0))

        self.eintraege: list[bytes] = []
        for s in self._kette(dir_first):
            blk = self._sektor(s)
            for k in range(self.gr // 128):
                self.eintraege.append(blk[k * 128 : (k + 1) * 128])

        wurzel = self.eintraege[0]
        self.mini = b"".join(
            self._sektor(s) for s in self._kette(struct.unpack_from("<I", wurzel, 116)[0])
        )
        self.minifat: list[int] = []
        for s in self._kette(mini_first):
            self.minifat += list(struct.unpack_from("<%dI" % (self.gr // 4), self._sektor(s), 0))

    def _sektor(self, i: int) -> bytes:
        ab = 512 + i * self.gr
        return self.daten[ab : ab + self.gr]

    def _kette(self, start: int) -> list[int]:
        aus, s = [], start
        while s not in (ENDE, FREI) and s < len(self.fat):
            aus.append(s)
            s = self.fat[s]
        return aus

    def wurzel_clsid(self) -> str:
        e = self.eintraege[0]
        d1, d2, d3 = struct.unpack_from("<IHH", e, 80)
        rest = e[88:96]
        return "%08x-%04x-%04x-%s-%s" % (d1, d2, d3, rest[:2].hex(), rest[2:].hex())

    def streams(self) -> dict[str, bytes]:
        aus: dict[str, bytes] = {}
        for e in self.eintraege[1:]:
            laenge = struct.unpack_from("<H", e, 64)[0]
            if laenge < 4 or e[66] != 2:  # 2 = Stream
                continue
            name = _entmangeln(e[: laenge - 2].decode("utf-16-le", "replace"))
            aus[name] = self._inhalt(e)
        return aus

    def _inhalt(self, e: bytes) -> bytes:
        start = struct.unpack_from("<I", e, 116)[0]
        groesse = struct.unpack_from("<I", e, 120)[0]
        if groesse < self.mini_cutoff:
            aus, s = b"", start
            while s not in (ENDE, FREI) and s < len(self.minifat):
                aus += self.mini[s * 64 : (s + 1) * 64]
                s = self.minifat[s]
            return aus[:groesse]
        return b"".join(self._sektor(s) for s in self._kette(start))[:groesse]


def pruefen(pfad: Path) -> list[str]:
    """Alle Prüfungen; gibt die Meldungen zurück oder wirft einen Befund."""
    c = Container(pfad)
    meldungen = [f"Container: OLE, Sektorgroesse {c.gr}, {pfad.stat().st_size} Bytes"]

    clsid = c.wurzel_clsid()
    if clsid == MSP_CLSID:
        raise Befund("Die Wurzel-CLSID ist die eines Patches (.msp), nicht die eines .msi.")
    if clsid != MSI_CLSID:
        raise Befund(
            f"Fremde Wurzel-CLSID {clsid}. Windows haelt die Datei dann fuer "
            "kein Installationspaket."
        )
    meldungen.append("Wurzel-CLSID: Installer-Datenbank")

    streams = c.streams()
    pool = streams.get("_StringPool")
    daten = streams.get("_StringData")
    if pool is None or daten is None:
        raise Befund("_StringPool oder _StringData fehlt — die Datenbank ist unvollstaendig.")

    codepage = struct.unpack_from("<H", pool, 0)[0]
    hoch = [b for b in daten if b > 127]
    meldungen.append(f"String-Pool: Codepage {codepage}, {len(daten)} Bytes Text")

    # Der eigentliche Grund für diese Datei.
    if codepage == 0 and hoch:
        stelle = next(i for i, b in enumerate(daten) if b > 127)
        umfeld = daten[max(0, stelle - 40) : stelle + 20].decode("latin-1", "replace")
        raise Befund(
            f"Der String-Pool meldet Codepage 0 (rein ASCII), enthaelt aber "
            f"{len(hoch)} Byte(s) ueber 127. Windows Installer weist so eine "
            f"Datenbank beim Oeffnen ab (Fehler 1620).\n"
            f"  Erste Stelle: …{umfeld}…\n"
            f"  Abhilfe: in magister-connector.wxs die Attributwerte (Name, "
            f"Description, Comments, Title) auf ASCII bringen. `wixl` "
            f"uebernimmt das Codepage-Attribut NICHT — die Quelle zu aendern "
            f"ist der einzige Weg."
        )
    if codepage == 65001:
        raise Befund(
            "Der String-Pool meldet Codepage 65001 (UTF-8). Windows Installer "
            "laesst fuer die Datenbank nur ANSI-Codepages zu."
        )
    meldungen.append(f"Text und Codepage passen zusammen ({len(hoch)} Byte(s) ueber 127)")
    return meldungen


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"Aufruf: {argv[0]} <paket.msi>", file=sys.stderr)
        return 2
    pfad = Path(argv[1])
    if not pfad.is_file():
        print(f"{pfad} gibt es nicht.", file=sys.stderr)
        return 2
    try:
        for zeile in pruefen(pfad):
            print(f"  {zeile}")
    except Befund as b:
        print(f"BEFUND: {b}", file=sys.stderr)
        return 1
    print("Pruefung: der Container ist so, wie Windows ihn erwartet.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
