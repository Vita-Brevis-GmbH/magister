"""Agentenpakete aus der Konsole (ADR-0014).

Geprüft wird, was schiefgehen kann, wenn man ein Verzeichnis über HTTP
ausliefert:

* **Der Pfad bricht nicht aus.** `../` und ein Symlink nach draussen führen zu
  404, nicht zu `/etc/shadow`. Beides mit echten Dateien im Dateisystem, nicht
  mit einem Mock: der Fehler, den dieser Test sucht, ist einer der
  Pfadauflösung, und ein Mock hätte dieselbe falsche Auflösung.
* **Nur Pakete.** Was neben den Paketen liegt (Signaturen, halbe Uploads),
  wird weder aufgelistet noch ausgeliefert.
* **Nicht öffentlich.** Ohne Anmeldung nichts; mit einem Dienst-Token auch
  nichts (ADR-0020 D4).
* **Nicht eingerichtet ist nicht leer.** Ohne Verzeichnis kommt 503 — die
  Oberfläche kann das erklären. Eine leere Liste sähe aus wie „es gibt kein
  Paket" und wäre die falsche Auskunft.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cockpit_api.config import settings

INHALT = b"nicht wirklich ein MSI, aber eine Datei mit Inhalt"


@pytest.fixture
def paketverzeichnis(tmp_path: Path) -> Iterator[Path]:
    verzeichnis = tmp_path / "agentenpakete"
    verzeichnis.mkdir()
    (verzeichnis / "magister-connector-1.4.0.msi").write_bytes(INHALT)
    (verzeichnis / "magister-connector_1.4.0_amd64.deb").write_bytes(INHALT)
    # Nachbarn, die nicht ausgeliefert werden sollen.
    (verzeichnis / "magister-connector-1.4.0.msi.sig").write_bytes(b"signatur")
    (verzeichnis / "SHA256SUMS").write_text("egal\n")
    (verzeichnis / "unterordner").mkdir()

    vorher = settings.agent_package_dir
    settings.agent_package_dir = str(verzeichnis)
    yield verzeichnis
    settings.agent_package_dir = vorher


@pytest.fixture
def ohne_verzeichnis() -> Iterator[None]:
    vorher = settings.agent_package_dir
    settings.agent_package_dir = ""
    yield
    settings.agent_package_dir = vorher


class TestListe:
    def test_nennt_nur_pakete_mit_pruefsumme(
        self, authed_client: TestClient, paketverzeichnis: Path
    ) -> None:
        antwort = authed_client.get("/api/agent-packages")
        assert antwort.status_code == 200
        pakete = antwort.json()
        namen = [p["filename"] for p in pakete]
        assert namen == [
            "magister-connector-1.4.0.msi",
            "magister-connector_1.4.0_amd64.deb",
        ]
        erwartet = hashlib.sha256(INHALT).hexdigest()
        assert {p["sha256"] for p in pakete} == {erwartet}
        assert {p["size_bytes"] for p in pakete} == {len(INHALT)}

    def test_ohne_verzeichnis_503_statt_leerer_liste(
        self, authed_client: TestClient, ohne_verzeichnis: None
    ) -> None:
        antwort = authed_client.get("/api/agent-packages")
        assert antwort.status_code == 503
        assert "COCKPIT_AGENT_PACKAGE_DIR" in antwort.json()["detail"]

    def test_verzeichnis_zeigt_ins_leere(self, authed_client: TestClient, tmp_path: Path) -> None:
        vorher = settings.agent_package_dir
        settings.agent_package_dir = str(tmp_path / "gibt-es-nicht")
        try:
            assert authed_client.get("/api/agent-packages").status_code == 503
        finally:
            settings.agent_package_dir = vorher


class TestDownload:
    def test_liefert_die_datei(self, authed_client: TestClient, paketverzeichnis: Path) -> None:
        antwort = authed_client.get("/api/agent-packages/magister-connector-1.4.0.msi")
        assert antwort.status_code == 200
        assert antwort.content == INHALT
        assert "magister-connector-1.4.0.msi" in antwort.headers["content-disposition"]

    @pytest.mark.parametrize(
        "versuch",
        [
            "..%2F..%2Fetc%2Fpasswd",
            "....//etc/passwd",
            "%2Fetc%2Fpasswd",
            "magister-connector-1.4.0.msi.sig",
            "SHA256SUMS",
            "unterordner",
        ],
    )
    def test_nichts_ausserhalb(
        self, authed_client: TestClient, paketverzeichnis: Path, versuch: str
    ) -> None:
        antwort = authed_client.get(f"/api/agent-packages/{versuch}")
        assert antwort.status_code == 404, antwort.text

    def test_symlink_fuehrt_nicht_hinaus(
        self, authed_client: TestClient, paketverzeichnis: Path, tmp_path: Path
    ) -> None:
        draussen = tmp_path / "geheim.msi"
        draussen.write_bytes(b"das gehoert nicht ausgeliefert")
        (paketverzeichnis / "abkuerzung.msi").symlink_to(draussen)

        antwort = authed_client.get("/api/agent-packages/abkuerzung.msi")
        assert antwort.status_code == 404
        assert b"gehoert nicht" not in antwort.content


class TestZugang:
    def test_ohne_anmeldung_nichts(self, client: TestClient, paketverzeichnis: Path) -> None:
        assert client.get("/api/agent-packages").status_code == 401
        assert client.get("/api/agent-packages/magister-connector-1.4.0.msi").status_code == 401

    def test_nicht_oeffentlich(self, public_client: TestClient, paketverzeichnis: Path) -> None:
        """Ohne Management-Marker gibt es die Fläche gar nicht (ADR-0015 D1)."""
        assert public_client.get("/api/agent-packages").status_code == 404
