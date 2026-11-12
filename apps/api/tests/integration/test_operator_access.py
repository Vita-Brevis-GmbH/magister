"""Operator-Zugriff gegen eine echte Datenbank (ADR-0019).

Die Abnahme aus Phase 5 steht hier: **eine abgelaufene oder zweimal eingelöste
Assertion wird abgewiesen, und jeder Zugriff steht im Audit des Kunden.**

Dazu die zwei Eigenschaften, die sich nur über die ganze Anwendung prüfen
lassen: dass ein Operator **nichts** schreiben kann (die Methodenregel, an
jeder Route), und dass der Kunde den laufenden Zugriff sieht — als Balken und
in einer Liste.
"""

from __future__ import annotations

import base64
import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from magister_api.audit.service import AuditService
from magister_api.auth.operator_assertion import ASSERTION_PREFIX
from magister_api.config import Settings, get_settings
from magister_api.db import get_session
from magister_api.main import create_app
from magister_api.models.audit import AuditEvent
from magister_api.models.operator_access import OperatorAccess

pytestmark = pytest.mark.postgres

#: Der Slug, den die Einzel-Mandanten-Registry in den Tests vergibt.
TENANT = "default"
REASON = "Ticket 4711: Klassenlehrerin sieht die Klasse 4a nicht."


@pytest.fixture(scope="session")
def operator_key() -> ed25519.Ed25519PrivateKey:
    return ed25519.Ed25519PrivateKey.generate()


@pytest.fixture(scope="session")
def operator_settings(app_settings: Settings, operator_key: ed25519.Ed25519PrivateKey) -> Settings:
    pem = (
        operator_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("ascii")
    )
    return app_settings.model_copy(update={"operator_public_key": pem})


@pytest_asyncio.fixture
async def operator_app(engine: AsyncEngine, operator_settings: Settings) -> AsyncIterator[FastAPI]:
    """Eine Anwendung **mit** hinterlegtem öffentlichem Schlüssel.

    Eine eigene Fixture und nicht die gemeinsame `app`: ohne Schlüssel gibt es
    die Einlöseroute nicht (ADR-0019 D3), und genau das prüft
    `TestWithoutAKeyThereIsNoSurface` mit der gemeinsamen.
    """
    application = create_app(operator_settings)
    sm = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)

    async def _override_session() -> AsyncIterator[AsyncSession]:
        async with sm() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise
            else:
                await session.commit()

    application.dependency_overrides[get_settings] = lambda: operator_settings
    application.dependency_overrides[get_session] = _override_session
    yield application


@pytest_asyncio.fixture
async def as_customer(
    operator_app: FastAPI,
    operator_settings: Settings,
    db_session: AsyncSession,
    school_a: int,
) -> AsyncIterator[AsyncClient]:
    """Ein gewöhnlicher Benutzer des Kunden — gegen **diese** Anwendung.

    Nicht `as_schulleitung_a`: die Fixture hängt an der gemeinsamen
    `app`-Instanz ohne Schlüssel, und dort gibt es die Operator-Fläche nicht.
    Genau dieser Unterschied ist der Entscheid D3, und er hat den Test einmal
    zu Recht scheitern lassen.
    """
    from tests.integration._helpers import seed_user_with_session

    sid, csrf = await seed_user_with_session(
        session=db_session,
        settings=operator_settings,
        upn="sl-a@example.ch",
        ad_object_guid="00000000-0000-0000-0000-0000000000a1",
        school_id=school_a,
        kind="teacher",
        role="schulleitung",
        role_school_id=school_a,
    )
    await db_session.commit()
    transport = ASGITransport(app=operator_app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
        cookies={"magister_session": sid, "magister_csrf": csrf},
        headers={"X-CSRF-Token": csrf},
    ) as client:
        yield client


@pytest_asyncio.fixture
async def anon(operator_app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=operator_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _assertion(
    key: ed25519.Ed25519PrivateKey,
    *,
    now: datetime | None = None,
    **over: Any,
) -> str:
    moment = now or datetime.now(UTC)
    payload: dict[str, Any] = {
        "jti": str(uuid.uuid4()),
        "tenant": TENANT,
        "operator": "matthias.hadorn@vitabrevis.ch",
        "reason": REASON,
        "ticket": "4711",
        "iat": int(moment.timestamp()),
        "exp": int((moment + timedelta(seconds=60)).timestamp()),
    }
    payload.update(over)
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return f"{ASSERTION_PREFIX}.{_b64(body)}.{_b64(key.sign(body))}"


async def _redeem(client: AsyncClient, assertion: str) -> Any:
    return await client.post("/operator/redeem", json={"assertion": assertion})


async def _operator_client(
    operator_app: FastAPI, key: ed25519.Ed25519PrivateKey, **over: Any
) -> AsyncClient:
    """Ein Client mit einer eingelösten Operator-Sitzung.

    Der CSRF-Kopf wird ausdrücklich mitgesetzt. Ohne ihn schlägt jeder
    Schreibversuch an der CSRF-Prüfung fehl — und der Test hätte bewiesen,
    dass CSRF wirkt, nicht die Methodenregel. Der echte Fall ist ohnehin
    dieser: der Browser des Operators **hat** einen gültigen Token.
    """
    transport = ASGITransport(app=operator_app)
    client = AsyncClient(transport=transport, base_url="http://testserver")
    response = await _redeem(client, _assertion(key, **over))
    assert response.status_code == 200, response.text
    csrf = client.cookies.get("magister_csrf")
    assert csrf, "Die Einlösung muss ein CSRF-Cookie setzen."
    client.headers["X-CSRF-Token"] = csrf
    return client


async def _accesses(session: AsyncSession) -> list[OperatorAccess]:
    stmt = select(OperatorAccess).order_by(OperatorAccess.started_at)
    return list((await session.execute(stmt)).scalars().all())


async def _events(session: AsyncSession, action: str) -> int:
    stmt = select(func.count()).select_from(AuditEvent).where(AuditEvent.action == action)
    return (await session.execute(stmt)).scalar_one()


class TestRedeeming:
    async def test_a_valid_assertion_becomes_a_session(
        self, operator_app: FastAPI, operator_key: ed25519.Ed25519PrivateKey
    ) -> None:
        client = await _operator_client(operator_app, operator_key)
        me = await client.get("/auth/me")
        assert me.status_code == 200, me.text
        body = me.json()
        assert body["is_operator"] is True
        assert body["upn"] == "matthias.hadorn@vitabrevis.ch"
        # Kein AD-Objekt: ein Operator ist kein Benutzer des Kunden
        # (ADR-0019 D5).
        assert body["ad_object_guid"] == ""
        await client.aclose()

    async def test_the_access_is_recorded_with_its_reason(
        self,
        operator_app: FastAPI,
        operator_key: ed25519.Ed25519PrivateKey,
        db_session: AsyncSession,
    ) -> None:
        client = await _operator_client(operator_app, operator_key)
        await client.aclose()
        (row,) = await _accesses(db_session)
        assert row.operator_upn == "matthias.hadorn@vitabrevis.ch"
        assert row.reason == REASON
        assert row.ticket == "4711"
        # Nur der Anfang der Session-Id: der vollständige Wert ist das Cookie.
        assert len(row.session_ref) == 12

    async def test_it_is_in_the_customers_audit(
        self,
        operator_app: FastAPI,
        operator_key: ed25519.Ed25519PrivateKey,
        db_session: AsyncSession,
        app_settings: Settings,
    ) -> None:
        """Die Abnahme aus Phase 5: jeder Zugriff steht im Audit des Kunden."""
        client = await _operator_client(operator_app, operator_key)
        await client.aclose()
        stmt = select(AuditEvent.id).where(AuditEvent.action == "operator_access_started")
        event_id = (await db_session.execute(stmt)).scalars().one()
        record = await AuditService(db_session, app_settings).read(event_id)
        assert record is not None
        assert record.actor_upn == "matthias.hadorn@vitabrevis.ch"
        assert record.payload["reason"] == REASON
        assert record.payload["ticket"] == "4711"

    async def test_the_same_assertion_twice_is_refused(
        self,
        operator_app: FastAPI,
        operator_key: ed25519.Ed25519PrivateKey,
        anon: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        """Die zweite Abnahme aus Phase 5.

        Abgewiesen durch den Primärschlüssel und nicht durch eine Abfrage:
        zwei gleichzeitige Einlösungen wären sonst beide erfolgreich.
        """
        assertion = _assertion(operator_key)
        first = await _redeem(anon, assertion)
        assert first.status_code == 200
        second = await _redeem(anon, assertion)
        assert second.status_code == 403
        assert second.json()["detail"] == "operator_assertion_invalid"
        # Und **keine** zweite Sitzung: der Zugriffseintrag wird vor der
        # Sitzung geschrieben, damit die Reihenfolge das garantiert.
        assert len(await _accesses(db_session)) == 1

    async def test_an_expired_assertion_is_refused(
        self, operator_key: ed25519.Ed25519PrivateKey, anon: AsyncClient
    ) -> None:
        past = datetime.now(UTC) - timedelta(minutes=5)
        response = await _redeem(anon, _assertion(operator_key, now=past))
        assert response.status_code == 403

    async def test_an_assertion_for_another_tenant_is_refused(
        self, operator_key: ed25519.Ed25519PrivateKey, anon: AsyncClient
    ) -> None:
        response = await _redeem(anon, _assertion(operator_key, tenant="fremdestadt"))
        assert response.status_code == 403

    async def test_a_foreign_signature_is_refused(self, anon: AsyncClient) -> None:
        other = ed25519.Ed25519PrivateKey.generate()
        assert (await _redeem(anon, _assertion(other))).status_code == 403

    async def test_every_rejection_looks_the_same_from_outside(
        self, operator_key: ed25519.Ed25519PrivateKey, anon: AsyncClient
    ) -> None:
        """Abgelaufen, doppelt, falscher Kunde, falsche Signatur — ein Text.

        Eine Antwort, die „bereits verbraucht" von „falsche Signatur"
        unterscheidet, verrät, welcher Wert einmal gültig war.
        """
        used = _assertion(operator_key)
        await _redeem(anon, used)
        details = set()
        for bad in (
            used,
            _assertion(operator_key, now=datetime.now(UTC) - timedelta(minutes=5)),
            _assertion(operator_key, tenant="fremdestadt"),
            _assertion(ed25519.Ed25519PrivateKey.generate()),
        ):
            response = await _redeem(anon, bad)
            assert response.status_code == 403
            details.add(response.json()["detail"])
        assert details == {"operator_assertion_invalid"}


class TestReadOnly:
    """ADR-0019 D1 — eine Prüfung, für alle Routen."""

    async def test_reads_work(
        self,
        operator_app: FastAPI,
        operator_key: ed25519.Ed25519PrivateKey,
        school_a: int,
    ) -> None:
        client = await _operator_client(operator_app, operator_key)
        for path in ("/users", "/classes", "/audit/events", "/schools"):
            response = await client.get(path)
            assert response.status_code == 200, f"{path}: {response.text}"
        await client.aclose()

    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("POST", "/classes"),
            ("POST", "/schools"),
            ("POST", "/templates/preview"),
            ("PUT", "/templates"),
            ("DELETE", "/classes/1"),
            ("POST", "/ad/users"),
        ],
    )
    async def test_no_write_gets_through(
        self,
        operator_app: FastAPI,
        operator_key: ed25519.Ed25519PrivateKey,
        method: str,
        path: str,
    ) -> None:
        """Echte Schreibrouten, jede mit 403 und derselben Kennung.

        Ausdrücklich **echte**: der erste Entwurf listete erfundene Pfade und
        bekam 404 und 405 zurück — die Prüfung ist eine Abhängigkeit und läuft
        erst, wenn eine Route gefunden wurde. Ein Test gegen einen Tippfehler
        hätte bewiesen, dass Starlette 405 sagt. Dass **jede** schreibende
        Route erfasst ist, prüft `test_every_write_route_is_covered`.
        """
        client = await _operator_client(operator_app, operator_key)
        response = await client.request(method, path, json={})
        assert response.status_code == 403, f"{method} {path}: {response.text}"
        assert response.json()["detail"] == "operator_read_only"
        await client.aclose()

    async def test_the_password_list_stays_closed(
        self,
        operator_app: FastAPI,
        operator_key: ed25519.Ed25519PrivateKey,
        db_session: AsyncSession,
        school_a: int,
    ) -> None:
        """Die eine Leseroute, die ausdrücklich gesperrt ist.

        Der Kunde darf die Passwörter seiner Klasse drucken. Der Betreiber hat
        dort nichts zu suchen — und ein `GET` würde von der Methodenregel
        nicht erfasst.
        """
        from magister_api.models.school_class import SchoolClass

        cls = SchoolClass(school_id=school_a, name="4a", kuerzel="4a", jahrgangsstufe=4)
        db_session.add(cls)
        await db_session.commit()

        client = await _operator_client(operator_app, operator_key)
        response = await client.get(f"/classes/{cls.id}/password-list")
        assert response.status_code == 403
        assert response.json()["detail"] == "operator_no_passwords"
        await client.aclose()

    async def test_ending_the_own_access_is_allowed(
        self,
        operator_app: FastAPI,
        operator_key: ed25519.Ed25519PrivateKey,
        db_session: AsyncSession,
    ) -> None:
        """Die eine Ausnahme in die andere Richtung.

        Sie erweitert nichts — sie erlaubt, früher aufzuhören, und setzt beim
        Kunden sichtbar `ended_at`.
        """
        client = await _operator_client(operator_app, operator_key)
        response = await client.post("/auth/logout")
        assert response.status_code == 200, response.text
        await client.aclose()

        (row,) = await _accesses(db_session)
        assert row.ended_at is not None
        assert await _events(db_session, "operator_access_ended") == 1


class TestTheSessionIsTimeBoxed:
    async def test_it_is_not_extended_by_activity(
        self,
        operator_app: FastAPI,
        operator_key: ed25519.Ed25519PrivateKey,
        db_session: AsyncSession,
    ) -> None:
        """Kein gleitendes Fenster.

        Für einen Benutzer ist die Verlängerung richtig; für einen
        Operator-Zugriff machte sie aus einer Stunde einen Arbeitstag, solange
        jemand das Fenster offen hat.
        """
        from magister_api.models.auth import Session as SessionRow

        client = await _operator_client(operator_app, operator_key)
        first = (await client.get("/auth/me")).json()["expires_at"]
        await client.get("/users")
        second = (await client.get("/auth/me")).json()["expires_at"]
        assert first == second
        await client.aclose()

        stmt = select(SessionRow.auth_kind).where(SessionRow.auth_kind == "operator")
        assert (await db_session.execute(stmt)).scalars().one() == "operator"


class TestVisibility:
    async def test_a_normal_user_sees_the_banner(
        self,
        operator_app: FastAPI,
        operator_key: ed25519.Ed25519PrivateKey,
        as_customer: AsyncClient,
    ) -> None:
        """Der Balken geht an jeden angemeldeten Benutzer (ADR-0019 D6).

        Eine Transparenz, die nur derjenige sieht, der den Zugriff ohnehin
        bewilligt hätte, ist keine.
        """
        before = (await as_customer.get("/auth/me")).json()
        assert before["operator_active"] is None

        client = await _operator_client(operator_app, operator_key)
        during = (await as_customer.get("/auth/me")).json()
        assert during["operator_active"]["operator"] == "matthias.hadorn@vitabrevis.ch"
        assert during["operator_active"]["reason"] == REASON
        assert during["is_operator"] is False

        await client.post("/auth/logout")
        after = (await as_customer.get("/auth/me")).json()
        assert after["operator_active"] is None
        await client.aclose()

    async def test_a_normal_user_can_read_the_list(
        self,
        operator_app: FastAPI,
        operator_key: ed25519.Ed25519PrivateKey,
        as_customer: AsyncClient,
    ) -> None:
        client = await _operator_client(operator_app, operator_key)
        await client.aclose()
        response = await as_customer.get("/operator/accesses")
        assert response.status_code == 200, response.text
        (row,) = response.json()
        assert row["reason"] == REASON
        assert row["ended_at"] is None

    async def test_the_list_does_not_leak_the_session(
        self,
        operator_app: FastAPI,
        operator_key: ed25519.Ed25519PrivateKey,
        as_customer: AsyncClient,
    ) -> None:
        client = await _operator_client(operator_app, operator_key)
        cookie = client.cookies.get("magister_session")
        await client.aclose()
        raw = (await as_customer.get("/operator/accesses")).text
        assert cookie
        assert cookie not in raw


class TestWithoutAKeyThereIsNoSurface:
    """ADR-0019 D3 — nicht 403, gar nicht da.

    Die gemeinsame `app`-Fixture hat keinen Schlüssel hinterlegt; sie ist damit
    die Einzelinstallation aus ADR-0016 D9.
    """

    async def test_redeem_is_not_mounted(self, client: AsyncClient) -> None:
        response = await client.post("/operator/redeem", json={"assertion": "x" * 40})
        assert response.status_code == 404

    async def test_the_list_is_not_mounted(self, as_schulleitung_a: AsyncClient) -> None:
        assert (await as_schulleitung_a.get("/operator/accesses")).status_code == 404
