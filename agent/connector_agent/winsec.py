"""Rechteprüfung unter Windows: die ACL, nicht der POSIX-Modus (ADR-0014).

Der Agent weigert sich zu laufen, wenn sein Zustandsverzeichnis für andere
lesbar ist — dort liegen der private Schlüssel und der API-Key. Unter Linux ist
das eine Zeile: ``mode & 0o077``.

Unter Windows ist es das **nicht**, und der naheliegende Weg ist schlimmer als
keine Prüfung. ``os.stat()`` liefert dort erfundene Modus-Bits, abgeleitet
allein aus dem Read-Only-Attribut: Verzeichnisse melden ``0o777``, schreibbare
Dateien ``0o666``. Die POSIX-Prüfung schlägt damit **immer** fehl, egal wie gut
die Rechte sind — der Dienst startete nie. Und sie stumm zu überspringen hiesse,
die eine Zusage aufzugeben, um die es geht.

Geprüft wird deshalb, was unter Windows tatsächlich schützt: die
**DACL**. Über SDDL, nicht über eine Auswertung der ACE-Struktur, und nicht
über ``icacls``:

* ``icacls`` gibt **lokalisierte** Kontonamen aus (``BUILTIN\\Administratoren``
  auf einem deutschen Windows). Eine Prüfung, die Namen vergleicht, ist damit
  von der Anzeigesprache des Servers abhängig — beim Kunden gern eine andere
  als beim Entwickler.
* SDDL nennt die Treuhänder als **SID** oder als sprachunabhängige Kurzform
  (``SY``, ``BA``, ``WD``). Das ist überall dasselbe.

Erlaubt sind genau drei Treuhänder: ``SYSTEM`` (darunter läuft der Dienst),
``Administratoren`` (wer den Server verwaltet, kommt sowieso an alles) und
``Ersteller-Besitzer``. Jeder andere gewährende Eintrag ist ein Fund — auch
``Benutzer`` und ``Authentifizierte Benutzer``, denn auf einem Domänencontroller
oder Mitgliedsserver ist das jeder im Netz.

Die Zerlegung hier ist reine Textarbeit und damit auf jedem System prüfbar; nur
``read_sddl`` braucht Windows.
"""

from __future__ import annotations

import ctypes
import os
import re
import shutil
from pathlib import Path

#: Ein ACE in SDDL:
#: ``(ace_type;ace_flags;rights;object_guid;inherit_object_guid;sid[;attr])``
_ACE = re.compile(r"\(([^)]*)\)")

#: ACE-Typen, die Zugriff **gewähren**. Alles andere (Verweigern, Überwachen)
#: gibt niemandem etwas: ``D``/``OD``/``XD``/``ZD`` verweigern, ``AU``/``AL``
#: und Verwandte protokollieren nur.
_GRANTING_TYPES = frozenset({"A", "OA", "XA", "ZA"})

#: Treuhänder, die im Zustandsverzeichnis des Agenten etwas dürfen. Kurzformen
#: und die zugehörigen SIDs, weil beide Schreibweisen in SDDL vorkommen.
ALLOWED_TRUSTEES: frozenset[str] = frozenset(
    {
        "SY",  # NT AUTHORITY\SYSTEM — darunter läuft der Dienst
        "S-1-5-18",
        "BA",  # BUILTIN\Administratoren
        "S-1-5-32-544",
        "CO",  # ERSTELLER-BESITZER
        "S-1-3-0",
        "OW",  # BESITZERRECHTE
        "S-1-3-4",
    }
)

#: Konstanten aus der Windows-API. Als Modulkonstanten und nicht in der
#: Funktion, damit sie die Namensregel für lokale Variablen nicht brechen —
#: und weil sie ohnehin fest sind.
SE_FILE_OBJECT = 1
DACL_SECURITY_INFORMATION = 0x00000004
SDDL_REVISION_1 = 1

#: Klartext für die Treuhänder, die man in einem Fund am häufigsten sieht.
#: Ohne das steht in der Fehlermeldung ``WD``, und niemand weiss, was fehlt.
TRUSTEE_NAMES: dict[str, str] = {
    "WD": "Jeder (Everyone)",
    "S-1-1-0": "Jeder (Everyone)",
    "BU": "BUILTIN\\Benutzer",
    "S-1-5-32-545": "BUILTIN\\Benutzer",
    "AU": "Authentifizierte Benutzer",
    "S-1-5-11": "Authentifizierte Benutzer",
    "IU": "Interaktiv angemeldete Benutzer",
    "S-1-5-4": "Interaktiv angemeldete Benutzer",
    "AN": "Anonyme Anmeldung",
    "S-1-5-7": "Anonyme Anmeldung",
    "DU": "Domänen-Benutzer",
    "DG": "Domänen-Gäste",
    "GU": "Gäste",
    "PU": "Hauptbenutzer",
    "RC": "Eingeschränkter Code",
}


class WindowsPermissionError(RuntimeError):
    """Die ACL gibt zu viel her — oder liess sich nicht lesen."""


def granting_trustees(sddl: str) -> list[str]:
    """Treuhänder aller **gewährenden** Einträge der DACL, in Reihenfolge.

    Nur der ``D:``-Teil wird gelesen. Ein SDDL-String trägt oft auch ``O:``
    (Besitzer), ``G:`` (Gruppe) und ``S:`` (Überwachung); die ``S:``-Einträge
    sehen wie ACEs aus, gewähren aber nichts, und sie mitzuzählen ergäbe
    Falschmeldungen.
    """
    dacl = _dacl_part(sddl)
    if dacl is None:
        return []
    found: list[str] = []
    for raw in _ACE.findall(dacl):
        fields = raw.split(";")
        if len(fields) < 6:
            continue
        ace_type = fields[0].strip().upper()
        if ace_type not in _GRANTING_TYPES:
            continue
        trustee = fields[5].strip().upper()
        if trustee:
            found.append(trustee)
    return found


def _dacl_part(sddl: str) -> str | None:
    """Den ``D:``-Abschnitt herausschneiden.

    Endet vor ``S:`` (Überwachung), falls einer folgt. Die Abschnitte stehen
    nicht in fester Reihenfolge, deshalb wird gesucht und nicht gezählt.
    """
    match = re.search(r"D:(?P<body>[^\s]*)", sddl)
    if match is None:
        return None
    body = match.group("body")
    # Ein folgender S:-Abschnitt hängt ohne Trennzeichen an. Er beginnt immer
    # mit "S:" und liegt damit hinter der letzten schliessenden Klammer der
    # DACL.
    cut = body.find("S:")
    return body if cut < 0 else body[:cut]


def offending_trustees(sddl: str) -> list[str]:
    """Gewährende Treuhänder, die nicht erlaubt sind — als Klartext."""
    problems: list[str] = []
    for trustee in granting_trustees(sddl):
        if trustee in ALLOWED_TRUSTEES:
            continue
        name = TRUSTEE_NAMES.get(trustee)
        problems.append(f"{name} [{trustee}]" if name else trustee)
    # Reihenfolge erhalten, Doppelte entfernen: eine ACL trägt denselben
    # Treuhänder gern zweimal (geerbt und direkt).
    seen: set[str] = set()
    unique: list[str] = []
    for item in problems:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def inherits_from_parent(sddl: str) -> bool:
    """Erbt das Objekt Rechte vom übergeordneten Verzeichnis?

    ``P`` im DACL-Kopf heisst „protected", also Vererbung abgeschaltet. Fehlt
    es, kann das übergeordnete Verzeichnis später Rechte hinzufügen, ohne dass
    hier etwas geändert wird — und dann stimmt die Prüfung heute und morgen
    nicht mehr. Das Installationsprogramm setzt deshalb ``P``.
    """
    dacl = _dacl_part(sddl)
    if dacl is None:
        return True
    head = dacl.split("(", 1)[0].upper()
    return "P" not in head


def read_sddl(path: Path) -> str:
    """DACL eines Pfades als SDDL lesen. Nur unter Windows.

    Über ``ctypes`` und nicht über ``pywin32``: der Agent soll unter Windows
    ohne zusätzliche Abhängigkeit auskommen, und diese zwei Aufrufe sind
    weniger Aufwand als ein Rad mehr im Paket.
    """
    if os.name != "nt":  # pragma: no cover - unter Linux nicht aufrufbar
        raise WindowsPermissionError("read_sddl läuft nur unter Windows.")

    # pragma: no cover ab hier — ohne Windows nicht ausführbar.
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)  # type: ignore[attr-defined]
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]

    sd = ctypes.c_void_p()
    rc = advapi32.GetNamedSecurityInfoW(
        ctypes.c_wchar_p(str(path)),
        ctypes.c_int(SE_FILE_OBJECT),
        ctypes.c_ulong(DACL_SECURITY_INFORMATION),
        None,
        None,
        None,
        None,
        ctypes.byref(sd),
    )
    if rc != 0:
        raise WindowsPermissionError(
            f"Die Rechte von {path} liessen sich nicht lesen (Fehler {rc}). "
            "Ohne diese Prüfung läuft der Agent nicht — dort liegt sein "
            "privater Schlüssel."
        )
    try:
        text = ctypes.c_wchar_p()
        length = ctypes.c_ulong(0)
        ok = advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW(
            sd,
            ctypes.c_ulong(SDDL_REVISION_1),
            ctypes.c_ulong(DACL_SECURITY_INFORMATION),
            ctypes.byref(text),
            ctypes.byref(length),
        )
        if not ok:
            raise WindowsPermissionError(
                f"Die Rechte von {path} liessen sich nicht in SDDL umwandeln "
                f"(Fehler {ctypes.get_last_error()})."
            )
        try:
            return text.value or ""
        finally:
            kernel32.LocalFree(text)
    finally:
        kernel32.LocalFree(sd)


#: ``icacls``-Argumente, die aus einem Verzeichnis eines machen, in dem nur
#: SYSTEM und die Administratoren etwas dürfen.
#:
#: Mit **SIDs** (``*S-1-…``) und nicht mit Namen: ``icacls`` nimmt
#: lokalisierte Kontonamen, und ``BUILTIN\Administrators`` gibt es auf einem
#: deutschen Windows nicht. Eine SID ist überall dieselbe.
#:
#: ``/inheritance:r`` entfernt die geerbten Einträge — sonst behält
#: ``%ProgramData%`` sein Leserecht für „Benutzer", und auf einem
#: Mitgliedsserver ist das jeder angemeldete Domänenbenutzer. ``(OI)(CI)``
#: vererbt an Dateien und Unterverzeichnisse, damit der private Schlüssel
#: dieselben Rechte bekommt, ohne dass ihn jemand einzeln behandeln muss.
HARDEN_ARGS = (
    "/inheritance:r",
    "/grant:r",
    "*S-1-5-18:(OI)(CI)F",
    "/grant:r",
    "*S-1-5-32-544:(OI)(CI)F",
)


def harden_directory(path: Path) -> None:
    """Zustandsverzeichnis abdichten. Nur unter Windows.

    Gemacht wird das vom **Agenten** und nicht vom Installationsprogramm, und
    das ist Absicht: dann gilt es für jede Installationsart gleich — MSI,
    Handinstallation, ausgepacktes Archiv. Ein Sicherheitsmerkmal, das nur die
    MSI setzt, fehlt genau bei der Installation, die jemand „schnell zum
    Testen" gemacht hat und die dann drei Jahre läuft.

    Über ``icacls`` und nicht über ``SetNamedSecurityInfo``: das Setzen ist ein
    Vorgang beim Einrichten, nicht in der heissen Schleife, und ``icacls`` mit
    SIDs ist deutlich weniger Code als eine ACL von Hand zu bauen. Die
    **Prüfung** dagegen läuft bei jedem Start und geht über die API — dort
    wäre ein Unterprozess je Start Verschwendung, und die Ausgabe von
    ``icacls`` ist lokalisiert und damit nicht auswertbar.
    """
    if os.name != "nt":  # pragma: no cover - unter Linux nicht aufrufbar
        raise WindowsPermissionError("harden_directory läuft nur unter Windows.")

    # pragma: no cover ab hier — ohne Windows nicht ausführbar.
    import subprocess

    icacls = shutil.which("icacls")
    if icacls is None:
        raise WindowsPermissionError(
            "icacls ist nicht auffindbar. Ohne es lassen sich die Rechte des "
            "Zustandsverzeichnisses nicht setzen, und der Agent legt seinen "
            "privaten Schlüssel nicht in ein offenes Verzeichnis."
        )
    completed = subprocess.run(  # noqa: S603 — feste Argumente, kein Shell
        [icacls, str(path), *HARDEN_ARGS],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip().splitlines()
        raise WindowsPermissionError(
            f"Die Rechte von {path} liessen sich nicht setzen: "
            f"{detail[-1] if detail else 'ohne Meldung'}\n"
            'Von Hand: icacls "' + str(path) + '" ' + " ".join(HARDEN_ARGS)
        )


def assert_windows_permissions(path: Path, *, what: str) -> None:
    """Abbrechen, wenn die ACL von *path* jemandem zu viel gibt."""
    sddl = read_sddl(path)
    problems = offending_trustees(sddl)
    if problems:
        raise WindowsPermissionError(
            f"{what} {path} ist für {', '.join(problems)} zugänglich. "
            "Dort liegt der private Schlüssel des Agenten. Zu setzen mit:\n"
            f'  icacls "{path}" /inheritance:r '
            "/grant:r *S-1-5-18:(OI)(CI)F /grant:r *S-1-5-32-544:(OI)(CI)F"
        )
    if inherits_from_parent(sddl):
        raise WindowsPermissionError(
            f"{what} {path} erbt Rechte vom übergeordneten Verzeichnis. Damit "
            "kann dort jederzeit jemand Zugriff hinzufügen, ohne dass hier "
            "etwas geändert wird. Vererbung abschalten:\n"
            f'  icacls "{path}" /inheritance:r '
            "/grant:r *S-1-5-18:(OI)(CI)F /grant:r *S-1-5-32-544:(OI)(CI)F"
        )


__all__ = [
    "ALLOWED_TRUSTEES",
    "HARDEN_ARGS",
    "TRUSTEE_NAMES",
    "WindowsPermissionError",
    "assert_windows_permissions",
    "granting_trustees",
    "harden_directory",
    "inherits_from_parent",
    "offending_trustees",
    "read_sddl",
]
