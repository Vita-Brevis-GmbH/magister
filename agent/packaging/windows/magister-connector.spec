# PyInstaller-Bauplan für den Connector-Agenten (ADR-0014).
#
#     uv run --extra packaging pyinstaller packaging/windows/magister-connector.spec
#
# Läuft nur unter Windows: PyInstaller friert die Laufzeit ein, auf der es
# selbst läuft, und kann nicht für eine fremde Plattform bauen. Das Ergebnis
# in ``dist/magister-connector/`` ist das Payload für ``build-msi.sh``, das
# danach unter Linux mit wixl das MSI drumherum baut.
#
# **Zwei Programme, ein Verzeichnis.** ``magister-connector.exe`` ist die
# Kommandozeile (enroll, run, check), ``magister-connector-service.exe`` der
# Dienst-Einsprungpunkt. Sie teilen sich die Laufzeit und die Bibliotheken
# (ein ``COLLECT`` für beide) — sonst lägen Python und alle Abhängigkeiten
# zweimal im Paket, rund 40 MB für nichts.
#
# **onedir und nicht onefile.** Ein onefile-Exe entpackt sich bei jedem Start
# in ein temporäres Verzeichnis. Für einen Dienst, der Monate läuft, ist das
# unnötig; schlimmer ist, dass Virenscanner in Unternehmensnetzen genau dieses
# Verhalten anspringen, und dann startet der Dienst beim Kunden nicht mehr,
# ohne dass jemand versteht, warum.

import sys
from pathlib import Path

if sys.platform != "win32":  # pragma: no cover
    raise SystemExit(
        "Dieser Bauplan läuft nur unter Windows. Das MSI selbst baut "
        "packaging/windows/build-msi.sh unter Linux."
    )

AGENT_ROOT = Path(SPECPATH).resolve().parents[1]

# Was PyInstaller nicht von allein findet.
#
# ``magister_api.*``: die AD-Schicht wird erst zur Laufzeit importiert
# (``build_ad_client``), damit ein fehlendes Paket eine lesbare Meldung ergibt
# und keinen Importfehler beim Start. Genau deshalb sieht der statische Scan
# sie nicht.
#
# ``win32timezone``: pywin32 lädt es nachträglich über einen String-Import.
# Fehlt es, scheitert der Dienst beim ersten Zeitstempel — und zwar erst zur
# Laufzeit beim Kunden.
HIDDEN = [
    "magister_api.ad.client",
    "magister_api.ad.threadpool",
    "magister_api.config",
    "ldap3",
    "ldap3.core.exceptions",
    "pydantic_settings",
    "win32timezone",
    "servicemanager",
    "win32event",
    "win32service",
    "win32serviceutil",
]

# Was NICHT mit soll. Der Agent braucht keine Datenbank, keinen Webserver und
# keinen PDF-Satz — das hängt alles an magister_api, dessen AD-Schicht wir
# benutzen. Ohne diese Liste wächst das Paket um über hundert Megabyte an
# Dingen, die auf einem Kundenserver nichts zu suchen haben.
EXCLUDED = [
    "fastapi",
    "starlette",
    "uvicorn",
    "sqlalchemy",
    "asyncpg",
    "alembic",
    "weasyprint",
    "PIL",
    "tkinter",
    "matplotlib",
    "numpy",
    "pytest",
]

common = dict(
    pathex=[str(AGENT_ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=HIDDEN,
    hookspath=[],
    runtime_hooks=[],
    excludes=EXCLUDED,
    noarchive=False,
)

cli = Analysis([str(AGENT_ROOT / "connector_agent" / "cli.py")], **common)
service = Analysis([str(AGENT_ROOT / "connector_agent" / "winservice.py")], **common)

# MERGE teilt gemeinsame Abhängigkeiten zwischen den beiden Programmen auf,
# damit sie nur einmal im Verzeichnis liegen.
MERGE((cli, "cli", "magister-connector"), (service, "service", "magister-connector-service"))

cli_pyz = PYZ(cli.pure, cli.zipped_data)
service_pyz = PYZ(service.pure, service.zipped_data)

cli_exe = EXE(
    cli_pyz,
    cli.scripts,
    [],
    exclude_binaries=True,
    name="magister-connector",
    console=True,
    disable_windowed_traceback=False,
    # Kein UAC-Manifest: enroll und check brauchen Administratorrechte, aber
    # eine automatische Rechteanhebung würde in einer Skript-Umgebung einen
    # Dialog aufwerfen, auf den niemand klickt. Die Anleitung sagt
    # "Eingabeaufforderung als Administrator", und das Startmenü liefert eine.
    uac_admin=False,
)

service_exe = EXE(
    service_pyz,
    service.scripts,
    [],
    exclude_binaries=True,
    name="magister-connector-service",
    console=True,
    disable_windowed_traceback=False,
    uac_admin=False,
)

COLLECT(
    cli_exe,
    cli.binaries,
    cli.datas,
    service_exe,
    service.binaries,
    service.datas,
    strip=False,
    upx=False,  # UPX macht Virenscanner nervös und spart hier wenig.
    name="magister-connector",
)
