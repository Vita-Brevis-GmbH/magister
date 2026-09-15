"""Anmeldung mit Benutzername, Passwort und TOTP (ADR-0023).

Fünf Aussagen, und die dritte ist die, um die es geht:

1. Das richtige Passwort führt **nicht** in die Konsole, sondern zum Code.
2. Fünf falsche Passwörter sperren — mit einem eigenen Zähler, nicht dem des
   zweiten Faktors.
3. **Der Zwischenstand berechtigt zu nichts.** Wer das Passwort gezeigt hat
   und den Code nicht, ist für jede geschützte Fläche niemand. Das ist genau
   der Zustand, in dem ein Angreifer mit gestohlenem Passwort steckt.
4. Nach dem Code wird aus dem Zwischenstand eine Sitzung — dieselbe Zeile,
   derselbe Cookie.
5. Unbekannter Benutzer, falsches Passwort und gesperrt sehen von aussen
   gleich aus.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any

import pyotp
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from cockpit_api import passwords
from cockpit_api.config import settings

UPN = "operatorin@vitabrevis.ch"
PASSWORT = "ein-hinreichend-langes-passwort"
#: Was jemand tippt, der es nicht weiss. Als Konstante, weil ruff eine
#: Zeichenkette am Parameter `password` sonst für ein echtes Geheimnis hält.
FALSCH = "falsch-aber-lang-genug"


@pytest.fixture
def https_client(console_client: TestClient) -> TestClient:
    """Wie ein Browser: über `https`, mit Marker-Kopf, **ohne** Token.

    Zwei Eigenheiten, und beide haben schon einmal einen Test grün gemacht,
    der nichts prüfte:

    * Der Sitzungs-Cookie ist `Secure`. Über `http` legt httpx ihn nicht ab,
      und die Folgeanfrage sähe keine Sitzung.
    * `console_client` schickt den Bootstrap-Token mit. Damit ist jede
      geschützte Fläche offen, ganz unabhängig von der Anmeldung — die
      Aussage „der Zwischenstand berechtigt zu nichts" wäre nicht prüfbar.
      Genau so ist dieser Test beim ersten Lauf durchgegangen.
    """
    console_client.base_url = "https://testserver"  # type: ignore[assignment]
    console_client.headers.pop("Authorization", None)
    return console_client


@pytest.fixture
def secret_key() -> Iterator[str]:
    previous = settings.secret_key
    settings.secret_key = "konsolen-testschluessel"  # noqa: S105
    yield settings.secret_key
    settings.secret_key = previous


def _sql(url: str, statement: str, **params: Any) -> None:
    async def run() -> None:
        engine = create_async_engine(url, poolclass=NullPool)
        try:
            async with engine.begin() as conn:
                await conn.execute(text(statement), params)
        finally:
            await engine.dispose()

    asyncio.run(run())


@pytest.fixture
def operator_mit_passwort(cockpit_schema: str, cockpit_database_url: str) -> str:
    """Ein Operator mit Passwort, ohne Zertifikat — der Normalfall ab ADR-0023."""
    _sql(
        cockpit_database_url,
        "INSERT INTO console_operators (upn, name, password_hash, password_set_at) "
        "VALUES (:upn, :name, :hash, now())",
        upn=UPN,
        name="Operatorin",
        hash=passwords.hash_password(PASSWORT),
    )
    return cockpit_database_url


def _login(client: TestClient, *, upn: str = UPN, password: str = PASSWORT) -> Any:
    return client.post("/api/auth/console/login", json={"upn": upn, "password": password})


class TestDerErsteFaktor:
    def test_das_richtige_passwort_fuehrt_zum_code_nicht_in_die_konsole(
        self, https_client: TestClient, operator_mit_passwort: str
    ) -> None:
        antwort = _login(https_client)
        assert antwort.status_code == 200, antwort.text
        # Kein zweiter Faktor eingerichtet -> Einrichtung, nicht Anmeldung.
        assert antwort.json()["stage"] == "enrolment_required"
        assert antwort.json()["upn"] == UPN

    def test_ein_falsches_passwort_ist_ein_401(
        self, https_client: TestClient, operator_mit_passwort: str
    ) -> None:
        assert _login(https_client, password=FALSCH).status_code == 401

    def test_ein_unbekannter_benutzer_sieht_genauso_aus(
        self, https_client: TestClient, cockpit_schema: str
    ) -> None:
        antwort = _login(https_client, upn="gibtsnicht@vitabrevis.ch")
        assert antwort.status_code == 401
        # Kein Hinweis darauf, ob es das Konto gibt.
        assert antwort.json()["detail"] == "invalid"

    def test_fuenf_fehlversuche_sperren(
        self, https_client: TestClient, operator_mit_passwort: str, cockpit_database_url: str
    ) -> None:
        for _ in range(5):
            assert _login(https_client, password=FALSCH).status_code == 401
        # Jetzt auch mit dem RICHTIGEN Passwort nicht mehr.
        assert _login(https_client).status_code == 401


class TestDerZwischenstand:
    def test_berechtigt_zu_nichts(
        self, https_client: TestClient, operator_mit_passwort: str
    ) -> None:
        """Die eigentliche Aussage: Passwort allein öffnet keine Fläche."""
        assert _login(https_client).status_code == 200
        # Der Cookie ist gesetzt — und trotzdem ist das keine Anmeldung.
        geschuetzt = https_client.get("/api/tenants")
        assert geschuetzt.status_code == 401, geschuetzt.text

    def test_whoami_zeigt_den_offenen_schritt(
        self, https_client: TestClient, operator_mit_passwort: str
    ) -> None:
        _login(https_client)
        body = https_client.get("/api/auth/console/whoami").json()
        assert body["stage"] == "enrolment_required"
        assert body["upn"] == UPN


class TestDerZweiteFaktorMachtDieSitzung:
    def test_einrichten_und_anmelden(
        self,
        https_client: TestClient,
        operator_mit_passwort: str,
        secret_key: str,
    ) -> None:
        assert _login(https_client).status_code == 200

        einrichtung = https_client.post("/api/auth/console/enrol")
        assert einrichtung.status_code == 200, einrichtung.text
        geheimnis = einrichtung.json()["secret"]

        code = pyotp.TOTP(geheimnis).now()
        angemeldet = https_client.post("/api/auth/console/totp", json={"code": code})
        assert angemeldet.status_code == 200, angemeldet.text
        assert angemeldet.json()["stage"] == "authenticated"
        assert angemeldet.json()["expires_at"] is not None

        # Und jetzt ist die geschützte Fläche offen.
        assert https_client.get("/api/tenants").status_code == 200

    def test_ein_falscher_code_laesst_den_zwischenstand_zwischenstand(
        self,
        https_client: TestClient,
        operator_mit_passwort: str,
        secret_key: str,
    ) -> None:
        _login(https_client)
        https_client.post("/api/auth/console/enrol")
        assert (
            https_client.post("/api/auth/console/totp", json={"code": "000000"}).status_code == 401
        )
        assert https_client.get("/api/tenants").status_code == 401


class TestEinrichtenIstWiederholbar:
    """Der Fehler, der einen Abend gekostet hat.

    Vorher erzeugte jeder Aufruf von `/enrol` ein neues Geheimnis. Wer die
    Seite neu lud oder ein zweites Telefon einrichten wollte, machte damit
    den bereits gescannten QR-Code ungültig — und bekam beim Code nur
    „stimmt nicht". Mit zwei Apps nebeneinander ist das praktisch
    unvermeidlich, und die Meldung nennt die Ursache nicht.
    """

    def test_zweimal_einrichten_zeigt_dasselbe_geheimnis(
        self, https_client: TestClient, operator_mit_passwort: str, secret_key: str
    ) -> None:
        _login(https_client)
        erste = https_client.post("/api/auth/console/enrol").json()
        zweite = https_client.post("/api/auth/console/enrol").json()
        assert zweite["secret"] == erste["secret"], (
            "Der zweite Aufruf darf den gescannten QR-Code nicht ungültig machen."
        )
        # Die Wiederherstellungscodes sind neu: die alten liegen nur als Hash
        # vor und liessen sich nicht ein zweites Mal anzeigen. Es gelten also
        # die zuletzt gezeigten.
        assert zweite["recovery_codes"] != erste["recovery_codes"]

    def test_der_code_zum_gezeigten_geheimnis_passt_nach_dem_zweiten_aufruf(
        self, https_client: TestClient, operator_mit_passwort: str, secret_key: str
    ) -> None:
        _login(https_client)
        https_client.post("/api/auth/console/enrol")
        zweite = https_client.post("/api/auth/console/enrol").json()
        code = pyotp.TOTP(zweite["secret"]).now()
        antwort = https_client.post("/api/auth/console/totp", json={"code": code})
        assert antwort.status_code == 200, antwort.text
        assert antwort.json()["stage"] == "authenticated"
