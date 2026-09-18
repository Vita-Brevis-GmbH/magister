"""Operator-Assertions ausstellen (ADR-0019).

Geprüft wird vor allem, was **nicht** durchkommt: ein Zugriff ohne Grund, ein
Zugriff auf einen gesperrten Kunden, ein Schlüssel des falschen Typs. Und die
Form des Einlöseschein — sie ist eine Schnittstelle zur Datenebene, und ein
Test hier ist der einzige Ort, an dem eine Änderung daran auffällt, bevor sie
beim Kunden auffällt.
"""

from __future__ import annotations

import base64
import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, rsa
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from cockpit_api.config import settings
from cockpit_api.services.operator_access import (
    ASSERTION_PREFIX,
    ASSERTION_TTL,
    OperatorAccessError,
    load_signing_key,
    sign_assertion,
)

SLUG = "operatortest"


def _write_key(tmp_path: Path, key: Any, name: str = "operator.pem") -> str:
    path = tmp_path / name
    path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    return str(path)


def _decode(assertion: str) -> dict[str, Any]:
    prefix, body, _signature = assertion.split(".")
    assert prefix == ASSERTION_PREFIX
    padded = body + "=" * (-len(body) % 4)
    return json.loads(base64.urlsafe_b64decode(padded))


# --- Reine Logik: Format und Schlüssel ------------------------------------
class TestTheAssertionFormat:
    def test_it_carries_no_algorithm_field(self) -> None:
        """ADR-0019 D2, als Prüfung.

        Ein `alg` im signierten Dokument lädt dazu ein, dem Dokument zu
        glauben — `alg: none` und die Verwechslung von HMAC mit RSA sind zwei
        der bekanntesten Fehlerklassen im Web. Das Verfahren steht im Präfix
        und im Code.
        """
        key = ed25519.Ed25519PrivateKey.generate()
        payload = {"jti": str(uuid.uuid4()), "tenant": SLUG, "exp": 1}
        decoded = _decode(sign_assertion(payload, key))
        assert "alg" not in decoded
        assert "typ" not in decoded

    def test_the_signature_covers_exactly_the_transmitted_bytes(self) -> None:
        """Signiert wird die Bytefolge, die übertragen wird.

        Ohne `sort_keys` und feste Trennzeichen serialisiert eine andere
        Bibliothek dasselbe Dokument anders — und prüfte dann eine Signatur
        über etwas anderes als das, was ankam.
        """
        key = ed25519.Ed25519PrivateKey.generate()
        assertion = sign_assertion({"b": 2, "a": 1}, key)
        _, body, signature = assertion.split(".")
        raw_body = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
        raw_sig = base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4))
        assert raw_body == b'{"a":1,"b":2}'
        key.public_key().verify(raw_sig, raw_body)

    def test_it_has_no_padding(self) -> None:
        # Die Assertion reist in einem URL-Fragment; `=` müsste dort kodiert
        # werden, und eine Kodierung, die jemand vergisst, ist ein Fehler, der
        # nur manchmal auftritt.
        key = ed25519.Ed25519PrivateKey.generate()
        assert "=" not in sign_assertion({"jti": "x" * 30}, key)


class TestTheSigningKey:
    def test_a_missing_setting_says_what_to_do(self) -> None:
        with pytest.raises(OperatorAccessError) as exc:
            load_signing_key("")
        assert "COCKPIT_OPERATOR_SIGNING_KEY" in str(exc.value)

    def test_a_missing_file_is_named(self, tmp_path: Path) -> None:
        with pytest.raises(OperatorAccessError) as exc:
            load_signing_key(str(tmp_path / "gibtsnicht.pem"))
        assert "fehlt" in str(exc.value)

    def test_the_wrong_key_type_is_refused_here_and_not_at_the_tenant(self, tmp_path: Path) -> None:
        """Ein RSA-Schlüssel wäre nicht „auch gut".

        Die Datenebene prüft ausschliesslich Ed25519. Ohne diese Prüfung
        stellte die Konsole Assertions aus, die beim Kunden abgewiesen werden —
        und der Fehler stünde dort statt hier.
        """
        rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        with pytest.raises(OperatorAccessError) as exc:
            load_signing_key(_write_key(tmp_path, rsa_key))
        assert "Ed25519" in str(exc.value)

    def test_an_ed25519_key_loads(self, tmp_path: Path) -> None:
        path = _write_key(tmp_path, ed25519.Ed25519PrivateKey.generate())
        assert isinstance(load_signing_key(path), ed25519.Ed25519PrivateKey)


# --- Über die HTTP-Fläche, mit Datenbank ----------------------------------
@pytest.fixture
def tenant_row(cockpit_schema: str, cockpit_database_url: str) -> str:
    import asyncio

    tenant_id = str(uuid.uuid4())

    async def insert() -> None:
        engine = create_async_engine(cockpit_database_url, poolclass=NullPool)
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO tenants (id, slug, name, hostname, status, profile, "
                        "isolation_mode, dsn_ref, schema_name, db_role, created_at, "
                        "updated_at) VALUES (:id, :slug, 'Operatortest', "
                        "'operatortest.example.ch', 'active', 'school', 'schema', "
                        ":ref, :schema, :role, now(), now())"
                    ),
                    {
                        "id": tenant_id,
                        "slug": SLUG,
                        "ref": f"tenant_{SLUG}",
                        "schema": f"t_{SLUG}",
                        "role": f"r_{SLUG}",
                    },
                )
        finally:
            await engine.dispose()

    asyncio.run(insert())
    return tenant_id


@pytest.fixture
def signing_key(tmp_path: Path) -> Any:
    key = ed25519.Ed25519PrivateKey.generate()
    previous = settings.operator_signing_key
    settings.operator_signing_key = _write_key(tmp_path, key)
    yield key
    settings.operator_signing_key = previous


def _open(client: TestClient, tenant_id: str, **over: Any) -> Any:
    body: dict[str, Any] = {
        "reason": "Ticket 4711: Klassenlehrerin sieht die Klasse 4a nicht.",
    }
    body.update(over)
    return client.post(f"/api/tenants/{tenant_id}/operator-access", json=body)


class TestIssuing:
    def test_a_grant_comes_back_with_a_redeem_url(
        self, console_client: TestClient, tenant_row: str, signing_key: Any
    ) -> None:
        response = _open(console_client, tenant_row)
        assert response.status_code == 200, response.text
        body = response.json()
        # Die Assertion steht im **Fragment**: ein Fragment erreicht keinen
        # Server-Log und keinen Referer-Header.
        assert body["redeem_url"].startswith("https://operatortest.example.ch/operator/redeem#")
        assert body["assertion"] in body["redeem_url"]

    def test_the_payload_names_tenant_operator_and_reason(
        self, console_client: TestClient, tenant_row: str, signing_key: Any
    ) -> None:
        body = _open(console_client, tenant_row).json()
        payload = _decode(body["assertion"])
        assert payload["tenant"] == SLUG
        # Der Name kommt aus der **Sitzung** (ADR-0020 D3). Der Testclient
        # benutzt den Bootstrap-Token, und der heisst im Protokoll so.
        assert payload["operator"] == "bootstrap-token"
        assert "4711" in payload["reason"]
        assert payload["jti"] == body["jti"]

    def test_a_name_in_the_body_is_refused(
        self, console_client: TestClient, tenant_row: str, signing_key: Any
    ) -> None:
        """Der Kern von ADR-0020 D3, als Regressionsschutz.

        Vorher stand der Name des Operators im Anfragekörper — wer den Token
        hatte, schrieb jeden Namen in das Audit des Kunden, auch den des
        Kollegen.

        Und ausdrücklich **422** statt „wird ignoriert": ein alter Aufrufer
        soll nicht glauben, sein Name sei angekommen, während im Protokoll des
        Kunden ein anderer steht. Wer das Feld wieder einführt, bricht diesen
        Test.
        """
        response = console_client.post(
            f"/api/tenants/{tenant_row}/operator-access",
            json={
                "operator": "jemand.anderes@vitabrevis.ch",
                "reason": "Ticket 4711: Klassenlehrerin sieht die Klasse 4a nicht.",
            },
        )
        assert response.status_code == 422, response.text

    def test_it_is_signed_by_the_configured_key(
        self, console_client: TestClient, tenant_row: str, signing_key: Any
    ) -> None:
        assertion = _open(console_client, tenant_row).json()["assertion"]
        _, raw_body, raw_sig = assertion.split(".")
        signing_key.public_key().verify(
            base64.urlsafe_b64decode(raw_sig + "=" * (-len(raw_sig) % 4)),
            base64.urlsafe_b64decode(raw_body + "=" * (-len(raw_body) % 4)),
        )

    def test_it_expires_in_a_minute(
        self, console_client: TestClient, tenant_row: str, signing_key: Any
    ) -> None:
        payload = _decode(_open(console_client, tenant_row).json()["assertion"])
        assert payload["exp"] - payload["iat"] == int(ASSERTION_TTL.total_seconds())

    def test_a_short_reason_is_refused(
        self, console_client: TestClient, tenant_row: str, signing_key: Any
    ) -> None:
        # „test" ist die Eingabe, die ein Pflichtfeld ohne Mindestlänge bekommt.
        assert _open(console_client, tenant_row, reason="test").status_code == 422

    def test_a_suspended_tenant_gets_no_access(
        self,
        console_client: TestClient,
        tenant_row: str,
        signing_key: Any,
        cockpit_database_url: str,
    ) -> None:
        """Ein Schein, der nicht einlösbar ist, wird nicht ausgestellt.

        Sonst stünde die Fehlermeldung beim Kunden statt hier — und zwar bei
        einem Kunden, der gerade gesperrt ist.
        """
        import asyncio

        async def suspend() -> None:
            engine = create_async_engine(cockpit_database_url, poolclass=NullPool)
            try:
                async with engine.begin() as conn:
                    await conn.execute(
                        text("UPDATE tenants SET status = 'suspended' WHERE id = :id"),
                        {"id": tenant_row},
                    )
            finally:
                await engine.dispose()

        asyncio.run(suspend())
        response = _open(console_client, tenant_row)
        assert response.status_code == 422
        assert "suspended" in response.json()["detail"]

    def test_without_a_key_the_answer_says_which_setting_is_missing(
        self, console_client: TestClient, tenant_row: str
    ) -> None:
        previous = settings.operator_signing_key
        settings.operator_signing_key = ""
        try:
            response = _open(console_client, tenant_row)
        finally:
            settings.operator_signing_key = previous
        assert response.status_code == 422
        assert "COCKPIT_OPERATOR_SIGNING_KEY" in response.json()["detail"]

    def test_an_unknown_tenant_is_404(
        self, console_client: TestClient, cockpit_schema: str, signing_key: Any
    ) -> None:
        assert _open(console_client, str(uuid.uuid4())).status_code == 404

    def test_it_needs_a_token(self, client: TestClient, cockpit_schema: str) -> None:
        assert (
            client.post(f"/api/tenants/{uuid.uuid4()}/operator-access", json={}).status_code == 401
        )


class TestHistory:
    def test_what_was_issued_is_listed(
        self, console_client: TestClient, tenant_row: str, signing_key: Any
    ) -> None:
        _open(console_client, tenant_row)
        _open(console_client, tenant_row, ticket="4712")
        rows = console_client.get(f"/api/tenants/{tenant_row}/operator-access").json()
        assert len(rows) == 2
        assert {row["ticket"] for row in rows} == {None, "4712"}

    def test_the_assertion_itself_is_not_in_the_history(
        self, console_client: TestClient, tenant_row: str, signing_key: Any
    ) -> None:
        """Der Einlöseschein wird einmal ausgeliefert und nicht gespeichert.

        Eine Liste, die ihn mitführte, wäre eine Liste von Zugangsmitteln —
        auch wenn sie nach einer Minute wertlos sind.
        """
        _open(console_client, tenant_row)
        raw = console_client.get(f"/api/tenants/{tenant_row}/operator-access").text
        assert ASSERTION_PREFIX not in raw

    def test_a_fresh_tenant_has_an_empty_history(
        self, console_client: TestClient, tenant_row: str
    ) -> None:
        assert console_client.get(f"/api/tenants/{tenant_row}/operator-access").json() == []


def test_the_ttl_is_short_enough_to_matter() -> None:
    """Sechzig Sekunden, und der Test hält die Absicht fest.

    Der Einlöseschein ist unterwegs: in einer Zwischenablage, in einer
    Adresszeile, vielleicht in einem Chat. Wer diesen Wert auf eine Stunde
    setzt, hat aus einem Schein einen Zugang gemacht.
    """
    assert ASSERTION_TTL <= timedelta(minutes=2)
    assert datetime.now(UTC) + ASSERTION_TTL > datetime.now(UTC)
