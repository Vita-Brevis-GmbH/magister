"""Anmeldung an der Konsole (ADR-0020).

Vier Dinge, die ohne Prüfung auseinanderlaufen:

1. **Die Identität hängt am Schlüsselpaar.** Ein anderes Zertifikat ist eine
   andere Person — auch mit demselben Namen darin (D1).
2. **Ein Code gilt einmal.** Auch innerhalb seiner dreissig Sekunden. Ohne den
   gespeicherten Zeitschritt wäre ein abgelesener Code eine halbe Minute lang
   brauchbar.
3. **Ohne bestätigten zweiten Faktor gibt es keine Sitzung.** Es darf keinen
   halb privilegierten Zustand geben.
4. **Die TOTP-Politik ist auf beiden Seiten dieselbe.** Die Datei ist eine
   Kopie; ein Test hält die Werte zusammen.
"""

from __future__ import annotations

import ast
import base64
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pyotp
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from cockpit_api import totp
from cockpit_api.config import settings
from cockpit_api.services.connector_ca import spki_fingerprint_from_certificate

CERT_HEADER = "X-Console-Client-Cert"


def _self_signed(common_name: str) -> tuple[str, str]:
    """Ein Zertifikat, wie der Browser es vorlegt — plus sein Fingerprint.

    Selbst signiert: die Kette prüft Caddy, nicht die Anwendung. Was hier
    zählt, ist der öffentliche Schlüssel.
    """
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    import datetime as dt

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(dt.datetime.now(dt.UTC) - dt.timedelta(minutes=5))
        .not_valid_after(dt.datetime.now(dt.UTC) + dt.timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    der_b64 = base64.b64encode(cert.public_bytes(serialization.Encoding.DER)).decode("ascii")
    pem = cert.public_bytes(serialization.Encoding.PEM).decode("ascii")
    return der_b64, spki_fingerprint_from_certificate(pem)


@pytest.fixture
def https_client(console_client: TestClient) -> TestClient:
    """Derselbe Client, aber über `https`.

    Der Sitzungs-Cookie ist `Secure` — der Listener ist ausschliesslich HTTPS
    (ADR-0015 D1), das ist keine Einstellung, sondern eine Tatsache. httpx legt
    einen solchen Cookie über `http` **nicht** ab, und ein Test mit
    Folgeanfrage sähe dann keine Sitzung.

    Genau das ist passiert: der Abmelde-Test war grün, ohne etwas zu prüfen —
    er bekam `totp_required`, weil der Cookie nie gespeichert wurde, nicht
    weil das Abmelden wirkte. Deshalb steht in ihm jetzt auch eine Gegenprobe.
    """
    console_client.base_url = "https://testserver"  # type: ignore[assignment]
    return console_client


@pytest.fixture
def secret_key() -> Iterator[str]:
    previous = settings.secret_key
    # Ein Testschlüssel ist kein hinterlegtes Passwort — und ohne einen lässt
    # sich die pgcrypto-Runde nicht prüfen.
    settings.secret_key = "konsolen-testschluessel"  # noqa: S105
    yield settings.secret_key
    settings.secret_key = previous


def _add_operator(url: str, *, upn: str, fingerprint: str) -> None:
    import asyncio

    async def insert() -> None:
        engine = create_async_engine(url, poolclass=NullPool)
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO console_operators (upn, name, spki_fingerprint) "
                        "VALUES (:upn, :name, :fp)"
                    ),
                    {"upn": upn, "name": upn.split("@")[0], "fp": fingerprint},
                )
        finally:
            await engine.dispose()

    asyncio.run(insert())


@pytest.fixture
def operator(cockpit_schema: str, cockpit_database_url: str) -> tuple[str, str]:
    """Ein eingetragener Operator ohne zweiten Faktor. Gibt (Header, Fingerprint)."""
    der_b64, fingerprint = _self_signed("matthias.hadorn")
    _add_operator(
        cockpit_database_url, upn="matthias.hadorn@vitabrevis.ch", fingerprint=fingerprint
    )
    return der_b64, fingerprint


def _whoami(client: TestClient, cert: str | None = None) -> Any:
    headers = {CERT_HEADER: cert} if cert else {}
    return client.get("/api/auth/console/whoami", headers=headers)


def _totp(client: TestClient, cert: str, code: str) -> Any:
    return client.post("/api/auth/console/totp", json={"code": code}, headers={CERT_HEADER: cert})


class TestTheCertificateDecidesWho:
    def test_without_a_certificate_the_answer_says_nothing(
        self, console_client: TestClient, operator: tuple[str, str]
    ) -> None:
        """Dieselbe Antwort wie bei einem unbekannten Zertifikat.

        Sonst wäre die Antwort eine Auskunft darüber, welche Zertifikate
        eingetragen sind.
        """
        body = _whoami(console_client).json()
        assert body["stage"] == "unknown_certificate"
        assert body["upn"] is None

    def test_an_unknown_certificate_is_not_named(
        self, console_client: TestClient, cockpit_schema: str
    ) -> None:
        other, _fp = _self_signed("fremd")
        body = _whoami(console_client, other).json()
        assert body["stage"] == "unknown_certificate"
        assert body["upn"] is None

    def test_a_known_certificate_names_the_person(
        self, console_client: TestClient, operator: tuple[str, str]
    ) -> None:
        cert, _fp = operator
        body = _whoami(console_client, cert).json()
        assert body["stage"] == "enrolment_required"
        assert body["upn"] == "matthias.hadorn@vitabrevis.ch"

    def test_the_same_name_in_another_certificate_is_another_person(
        self, console_client: TestClient, operator: tuple[str, str]
    ) -> None:
        """Der Entscheid aus D1, als Prüfung.

        Ein zweites Zertifikat mit demselben `CN` hat ein anderes
        Schlüsselpaar — und ist damit unbekannt. Hinge die Identität am Namen,
        käme hier „bekannt" heraus.
        """
        same_name, _fp = _self_signed("matthias.hadorn")
        assert _whoami(console_client, same_name).json()["stage"] == "unknown_certificate"


class TestEnrolmentAndLogin:
    def test_the_secret_is_shown_once_and_a_code_opens_a_session(
        self, console_client: TestClient, operator: tuple[str, str], secret_key: str
    ) -> None:
        cert, _fp = operator
        enrol = console_client.post("/api/auth/console/enrol", headers={CERT_HEADER: cert})
        assert enrol.status_code == 200, enrol.text
        body = enrol.json()
        assert len(body["recovery_codes"]) == totp.RECOVERY_CODE_COUNT
        assert body["qr_data_uri"].startswith("data:image/svg+xml")

        # Noch keine Sitzung: ohne bestätigten Code gibt es keine.
        assert _whoami(console_client, cert).json()["stage"] == "enrolment_required"

        code = pyotp.TOTP(body["secret"]).now()
        response = _totp(console_client, cert, code)
        assert response.status_code == 200, response.text
        assert response.json()["stage"] == "authenticated"
        assert response.cookies.get("cockpit_session")

    def test_a_wrong_code_opens_nothing(
        self, console_client: TestClient, operator: tuple[str, str], secret_key: str
    ) -> None:
        cert, _fp = operator
        console_client.post("/api/auth/console/enrol", headers={CERT_HEADER: cert})
        assert _totp(console_client, cert, "000000").status_code == 401

    def test_a_code_is_single_use(
        self, console_client: TestClient, operator: tuple[str, str], secret_key: str
    ) -> None:
        """Auch innerhalb seiner dreissig Sekunden.

        Ohne den gespeicherten Zeitschritt wäre ein abgelesener Code eine
        halbe Minute lang brauchbar — genau die Zeit, die ein Anruf braucht.
        """
        cert, _fp = operator
        secret = console_client.post("/api/auth/console/enrol", headers={CERT_HEADER: cert}).json()[
            "secret"
        ]
        code = pyotp.TOTP(secret).now()
        assert _totp(console_client, cert, code).status_code == 200
        console_client.cookies.clear()
        assert _totp(console_client, cert, code).status_code == 401

    def test_a_recovery_code_works_and_is_consumed(
        self, console_client: TestClient, operator: tuple[str, str], secret_key: str
    ) -> None:
        cert, _fp = operator
        body = console_client.post("/api/auth/console/enrol", headers={CERT_HEADER: cert}).json()
        # Erst mit einem echten Code bestätigen, sonst ist der Faktor nicht
        # eingerichtet — ein Wiederherstellungscode ist ein Ersatz, kein
        # Einrichtungsweg.
        assert _totp(console_client, cert, pyotp.TOTP(body["secret"]).now()).status_code == 200
        console_client.cookies.clear()
        recovery = body["recovery_codes"][0]
        assert _totp(console_client, cert, recovery).status_code == 200
        console_client.cookies.clear()
        assert _totp(console_client, cert, recovery).status_code == 401

    def test_enrolment_cannot_be_restarted_once_confirmed(
        self, console_client: TestClient, operator: tuple[str, str], secret_key: str
    ) -> None:
        """Ein bestätigter Faktor wird nicht überschrieben.

        Sonst könnte ein gestohlenes Zertifikat allein den zweiten Faktor
        austauschen — und damit den Faktor abschaffen, den es nicht hat.
        """
        cert, _fp = operator
        secret = console_client.post("/api/auth/console/enrol", headers={CERT_HEADER: cert}).json()[
            "secret"
        ]
        _totp(console_client, cert, pyotp.TOTP(secret).now())
        assert (
            console_client.post("/api/auth/console/enrol", headers={CERT_HEADER: cert}).status_code
            == 409
        )

    def test_five_wrong_codes_lock_the_account(
        self, console_client: TestClient, operator: tuple[str, str], secret_key: str
    ) -> None:
        cert, _fp = operator
        secret = console_client.post("/api/auth/console/enrol", headers={CERT_HEADER: cert}).json()[
            "secret"
        ]
        _totp(console_client, cert, pyotp.TOTP(secret).now())
        console_client.cookies.clear()
        for _ in range(5):
            _totp(console_client, cert, "000000")
        assert _whoami(console_client, cert).json()["stage"] == "locked"
        # Und ein richtiger Code hilft jetzt auch nicht.
        assert _totp(console_client, cert, pyotp.TOTP(secret).now()).status_code == 401

    def test_without_a_secret_key_the_answer_says_which_setting_is_missing(
        self, console_client: TestClient, operator: tuple[str, str]
    ) -> None:
        cert, _fp = operator
        previous = settings.secret_key
        settings.secret_key = ""
        try:
            response = console_client.post("/api/auth/console/enrol", headers={CERT_HEADER: cert})
        finally:
            settings.secret_key = previous
        assert response.status_code >= 400
        assert "COCKPIT_SECRET_KEY" in response.text


class TestTheSessionIsBoundToTheCertificate:
    def test_a_cookie_with_another_certificate_does_not_work(
        self, https_client: TestClient, operator: tuple[str, str], secret_key: str
    ) -> None:
        """Ein gestohlener Cookie allein nützt nichts.

        Der Grund, aus dem der Fingerprint an der Sitzung steht.
        """
        cert, _fp = operator
        secret = https_client.post("/api/auth/console/enrol", headers={CERT_HEADER: cert}).json()[
            "secret"
        ]
        _totp(https_client, cert, pyotp.TOTP(secret).now())
        assert _whoami(https_client, cert).json()["stage"] == "authenticated"

        other, _ = _self_signed("fremd")
        assert _whoami(https_client, other).json()["stage"] == "unknown_certificate"

    def test_logout_ends_it(
        self, https_client: TestClient, operator: tuple[str, str], secret_key: str
    ) -> None:
        cert, _fp = operator
        secret = https_client.post("/api/auth/console/enrol", headers={CERT_HEADER: cert}).json()[
            "secret"
        ]
        _totp(https_client, cert, pyotp.TOTP(secret).now())
        # Erst die Gegenprobe: die Sitzung steht wirklich.
        assert _whoami(https_client, cert).json()["stage"] == "authenticated"
        assert (
            https_client.post("/api/auth/console/logout", headers={CERT_HEADER: cert}).status_code
            == 204
        )
        assert _whoami(https_client, cert).json()["stage"] == "totp_required"


class TestTheTotpPolicyMatchesTheDataPlane:
    """Die Datei ist eine Kopie (ADR-0020 D2) — die Werte müssen gleich sein.

    Gelesen wird die Datei der Datenebene, nicht importiert: die Konsole hängt
    nicht von `magister_api` ab, und das soll so bleiben.
    """

    def _data_plane_values(self) -> dict[str, Any] | None:
        path = (
            Path(__file__).resolve().parents[3]
            / "apps"
            / "api"
            / "magister_api"
            / "auth"
            / "totp.py"
        )
        if not path.exists():
            return None
        tree = ast.parse(path.read_text(encoding="utf-8"))
        found: dict[str, Any] = {}
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                name = getattr(target, "id", "")
                if name in {"DIGITS", "PERIOD", "DRIFT_STEPS", "RECOVERY_CODE_COUNT"}:
                    found[name] = ast.literal_eval(node.value)
                if name == "_RECOVERY_ALPHABET":
                    found[name] = ast.literal_eval(node.value)
        return found

    def test_same_values(self) -> None:
        theirs = self._data_plane_values()
        if not theirs:
            pytest.skip("Datenebene liegt in dieser Umgebung nicht daneben")
        assert theirs["DIGITS"] == totp.DIGITS
        assert theirs["PERIOD"] == totp.PERIOD
        assert theirs["DRIFT_STEPS"] == totp.DRIFT_STEPS
        assert theirs["RECOVERY_CODE_COUNT"] == totp.RECOVERY_CODE_COUNT
        assert theirs["_RECOVERY_ALPHABET"] == totp._RECOVERY_ALPHABET


class TestOnlyAPersonWritesToACustomerLog:
    """ADR-0020 D4 — ein Dienst-Token kommt an die drei Flächen nicht.

    Was einen Namen in das Protokoll eines Kunden schreibt, soll nicht von
    einem Token ausgehen, das in einem Container liegt und keinen Menschen
    kennt. Der Runner holt Update-Aufträge ab und braucht keine davon.
    """

    @pytest.fixture
    def service_token(self, console_client: TestClient, cockpit_schema: str) -> Iterator[str]:
        created = console_client.post(
            "/api/service-tokens",
            json={"description": "runner-test", "ttl_days": 1},
        )
        assert created.status_code in (200, 201), created.text
        token = created.json()["token"]
        yield token

    def _as_service(self, client: TestClient, token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def test_settings_refuse_a_service_token(
        self, console_client: TestClient, service_token: str
    ) -> None:
        response = console_client.put(
            "/api/platform/settings",
            json={"defaults": {"ad_sync_interval_minutes": 60}},
            headers=self._as_service(console_client, service_token),
        )
        assert response.status_code == 403
        assert "Person" in response.json()["detail"]

    def test_reading_still_works_for_a_service_token(
        self, console_client: TestClient, service_token: str
    ) -> None:
        """Die Gegenprobe: der Boden am Router lässt Dienste lesen.

        Die Datenebene holt den Soll-Zustand mit genau so einem Token ab. Wäre
        `require_person` am Router statt an den Schreibrouten, stünde sie
        draussen.
        """
        response = console_client.get(
            "/api/platform/settings",
            headers=self._as_service(console_client, service_token),
        )
        assert response.status_code == 200, response.text
