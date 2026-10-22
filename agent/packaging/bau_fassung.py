"""Fassung eines Agenten-Baus festlegen: ``<major>.<minor>.<commits>``.

    python packaging/bau_fassung.py            # schreibt connector_agent/_build.py
    python packaging/bau_fassung.py --zeigen   # gibt nur die Fassung aus

Warum: jedes MSI hiess „0.2.0“. Windows hielt ein neues Paket damit für
dasselbe, und auf dem DC war nicht zu erkennen, ob die neue Fassung läuft.
Die dritte Stelle ist die Zahl der Commits auf dem gebauten Stand — sie
wächst mit jedem Commit, ist für CI und Handbau dieselbe und bleibt unter der
Grenze von Windows Installer (65535). Dafür braucht der Checkout die ganze
Geschichte (``fetch-depth: 0``).
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

AGENT = Path(__file__).resolve().parents[1]


def _git(*args: str) -> str:
    done = subprocess.run(  # noqa: S603 - fester Befehl
        ["git", *args],  # noqa: S607 - git aus dem Suchpfad, wie im ganzen Bau
        cwd=AGENT,
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


def fassung() -> tuple[str, str]:
    text = (AGENT / "connector_agent" / "cli.py").read_text(encoding="utf-8")
    match = re.search(r'^BASE_VERSION\s*=\s*"(\d+)\.(\d+)\.\d+"', text, re.MULTILINE)
    if match is None:
        raise SystemExit("BASE_VERSION in connector_agent/cli.py nicht gefunden.")
    commits = int(_git("rev-list", "--count", "HEAD"))
    if commits > 65535:
        raise SystemExit(f"{commits} Commits — über der Grenze von Windows Installer.")
    return f"{match.group(1)}.{match.group(2)}.{commits}", _git("rev-parse", "--short", "HEAD")


def main() -> int:
    version, commit = fassung()
    if "--zeigen" not in sys.argv:
        (AGENT / "connector_agent" / "_build.py").write_text(
            '"""Vom Bau geschrieben (packaging/bau_fassung.py) — nicht von Hand ändern."""\n\n'
            f'BUILD_VERSION = "{version}"\nBUILD_COMMIT = "{commit}"\n',
            encoding="utf-8",
        )
    sys.stdout.write(version + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
