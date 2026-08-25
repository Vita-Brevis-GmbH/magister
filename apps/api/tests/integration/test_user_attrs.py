"""End-to-end ``PATCH /users/{guid}`` — AD-MODIFY + DB-mirror + audit."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from magister_api.ad.client import AdClient
from magister_api.audit.service import AuditService
from magister_api.config import Settings
from magister_api.models.app_settings import AppSettings
from magister_api.models.audit import AuditEvent
from magister_api.models.auth import AdUserCache
from magister_api.routers.admin_sync import get_ad_client

if TYPE_CHECKING:
    from fastapi import FastAPI
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.postgres

TEACHER_GUID = "00000000-0000-0000-0000-000000000a01"
STUDENT_GUID = "00000000-0000-0000-0000-000000000a02"
OTHER_SCHOOL_TEACHER_GUID = "00000000-0000-0000-0000-000000000b01"


def _le(g: str) -> bytes:
    return uuid.UUID(g).bytes_le


@pytest_asyncio.fixture
async def mock_ad(app_settings: Settings):
    settings = app_settings.model_copy(
        update={"ad_use_mock": True, "ad_users_search_base": "DC=schule,DC=local"}
    )
    client = AdClient(settings)
    conn = client.mock_connection()
    for guid, dn in [
        (TEACHER_GUID, "CN=Anna,OU=Teachers,DC=schule,DC=local"),
        (STUDENT_GUID, "CN=Max,OU=Students,DC=schule,DC=local"),
        (OTHER_SCHOOL_TEACHER_GUID, "CN=B,OU=Teachers,DC=schule,DC=local"),
    ]:
        conn.strategy.add_entry(
            dn,
            {
                "objectClass": ["user"],
                "objectGUID": _le(guid),
                "userPrincipalName": f"{guid[:6]}@schule.example.ch",
                "userAccountControl": 0x200,
            },
        )
    yield client
    await client.aclose()


async def _seed_user(
    db_session: AsyncSession,
    *,
    school_id: int,
    guid: str,
    kind: str = "teacher",
    upn: str = "old@schule.example.ch",
    cannot_change_password: bool = False,
    store_password: bool = False,
) -> None:
    db_session.add(
        AdUserCache(
            ad_object_guid=guid,
            school_id=school_id,
            upn=upn,
            display_name="Old Name",
            sam_account_name="old.sam",
            kind=kind,
            enabled=True,
            cannot_change_password=cannot_change_password,
            store_password=store_password,
        )
    )
    await db_session.flush()
    await db_session.commit()


async def _enable_vault(db_session: AsyncSession) -> None:
    await db_session.execute(
        update(AppSettings).where(AppSettings.id == 1).values(password_store_enabled=True)
    )
    await db_session.commit()


async def _set_mail_domains(db_session: AsyncSession, domains: list[str]) -> None:
    """Mirror the admin GUI setting the mail-domains allowlist."""
    from sqlalchemy import update

    await db_session.execute(
        update(AppSettings).where(AppSettings.id == 1).values(mail_domains=domains)
    )
    await db_session.commit()


class TestCredentialPdf:
    @pytest.mark.asyncio
    async def test_cannot_change_user_pdf_resets_password(
        self,
        app: FastAPI,
        as_smi_a: AsyncClient,
        db_session: AsyncSession,
        school_a: int,
        engine: AsyncEngine,
        mock_ad: AdClient,
    ) -> None:
        await _seed_user(
            db_session,
            school_id=school_a,
            guid=STUDENT_GUID,
            kind="student",
            cannot_change_password=True,
        )
        app.dependency_overrides[get_ad_client] = lambda: mock_ad
        try:
            r = await as_smi_a.post(
                f"/users/{STUDENT_GUID}/credential-pdf",
                json={"custom_heading": "Hinweis", "custom_body": "Bitte aufbewahren."},
            )
            assert r.status_code == 200, r.text
            assert r.headers["content-type"] == "application/pdf"
            assert r.content[:4] == b"%PDF"
        finally:
            app.dependency_overrides.pop(get_ad_client, None)

        # Audited as a reset (cannot-change → password was regenerated).
        sm = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        async with sm() as s:
            rows = (
                (
                    await s.execute(
                        select(AuditEvent.action).where(
                            AuditEvent.action == "credential_pdf_generated"
                        )
                    )
                )
                .scalars()
                .all()
            )
        assert rows == ["credential_pdf_generated"]

    @pytest.mark.asyncio
    async def test_vault_user_pdf_stores_then_reuses_password(
        self,
        app: FastAPI,
        as_smi_a: AsyncClient,
        db_session: AsyncSession,
        school_a: int,
        mock_ad: AdClient,
    ) -> None:
        # store_password + global vault on: first PDF sets & stores a password,
        # the second reuses the stored one without touching AD again.
        await _enable_vault(db_session)
        await _seed_user(
            db_session,
            school_id=school_a,
            guid=STUDENT_GUID,
            kind="student",
            store_password=True,
        )
        app.dependency_overrides[get_ad_client] = lambda: mock_ad
        try:
            r1 = await as_smi_a.post(f"/users/{STUDENT_GUID}/credential-pdf", json={})
            assert r1.status_code == 200, r1.text
        finally:
            app.dependency_overrides.pop(get_ad_client, None)

        # A password is now stored (encrypted).
        row = await db_session.get(AdUserCache, STUDENT_GUID)
        assert row is not None
        await db_session.refresh(row)
        assert row.password_enc is not None
        stored_before = row.password_enc

        app.dependency_overrides[get_ad_client] = lambda: mock_ad
        try:
            r2 = await as_smi_a.post(f"/users/{STUDENT_GUID}/credential-pdf", json={})
            assert r2.status_code == 200, r2.text
        finally:
            app.dependency_overrides.pop(get_ad_client, None)

        # Reused — the stored ciphertext is unchanged.
        await db_session.refresh(row)
        assert row.password_enc == stored_before

    @pytest.mark.asyncio
    async def test_can_change_user_pdf_is_masked_no_reset(
        self,
        app: FastAPI,
        as_smi_a: AsyncClient,
        db_session: AsyncSession,
        school_a: int,
        mock_ad: AdClient,
    ) -> None:
        # A user who may change their own password: no reset, masked PDF.
        await _seed_user(db_session, school_id=school_a, guid=TEACHER_GUID, kind="teacher")
        app.dependency_overrides[get_ad_client] = lambda: mock_ad
        try:
            r = await as_smi_a.post(f"/users/{TEACHER_GUID}/credential-pdf", json={})
            assert r.status_code == 200, r.text
            assert r.content[:4] == b"%PDF"
        finally:
            app.dependency_overrides.pop(get_ad_client, None)


class TestHappyPath:
    @pytest.mark.asyncio
    async def test_smi_can_set_display_name_and_address(
        self,
        app: FastAPI,
        as_smi_a: AsyncClient,
        db_session: AsyncSession,
        school_a: int,
        mock_ad: AdClient,
    ) -> None:
        await _seed_user(db_session, school_id=school_a, guid=TEACHER_GUID)
        app.dependency_overrides[get_ad_client] = lambda: mock_ad
        try:
            r = await as_smi_a.patch(
                f"/users/{TEACHER_GUID}",
                json={
                    "display_name": "Anna Beispiel",
                    "street_address": "Schulweg 12",
                    "locality": "Musterhausen",
                    "postal_code": "3000",
                    "country": "Schweiz",
                    "temp_device_name": "Loaner-04",
                },
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["display_name"] == "Anna Beispiel"
            assert body["street_address"] == "Schulweg 12"
            assert body["temp_device_name"] == "Loaner-04"
        finally:
            app.dependency_overrides.pop(get_ad_client, None)

    @pytest.mark.asyncio
    async def test_smi_can_set_org_attributes(
        self,
        app: FastAPI,
        as_smi_a: AsyncClient,
        db_session: AsyncSession,
        school_a: int,
        mock_ad: AdClient,
    ) -> None:
        await _seed_user(db_session, school_id=school_a, guid=TEACHER_GUID)
        app.dependency_overrides[get_ad_client] = lambda: mock_ad
        try:
            r = await as_smi_a.patch(
                f"/users/{TEACHER_GUID}",
                json={
                    "title": "Lehrperson",
                    "department": "Primarstufe",
                    "company": "Schule Musterhausen",
                    "telephone_number": "+41 31 000 00 00",
                    "mobile": "+41 79 000 00 00",
                    "office": "B12",
                    "description": "Klassenlehrperson 4a",
                    "employee_id": "P-1234",
                },
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["title"] == "Lehrperson"
            assert body["department"] == "Primarstufe"
            assert body["telephone_number"] == "+41 31 000 00 00"
            assert body["employee_id"] == "P-1234"
        finally:
            app.dependency_overrides.pop(get_ad_client, None)

        row = await db_session.get(AdUserCache, TEACHER_GUID)
        assert row is not None
        await db_session.refresh(row)
        assert row.company == "Schule Musterhausen"
        assert row.office == "B12"

    @pytest.mark.asyncio
    async def test_smi_can_set_ad_policy_flags(
        self,
        app: FastAPI,
        as_smi_a: AsyncClient,
        db_session: AsyncSession,
        school_a: int,
        mock_ad: AdClient,
    ) -> None:
        # password_never_expires flips the UAC bit in (mock) AD;
        # cannot_change_password is a DACL no-op under the mock but is still
        # mirrored into the cache. Both round-trip through the response.
        await _seed_user(db_session, school_id=school_a, guid=TEACHER_GUID)
        app.dependency_overrides[get_ad_client] = lambda: mock_ad
        try:
            r = await as_smi_a.patch(
                f"/users/{TEACHER_GUID}",
                json={"password_never_expires": True, "cannot_change_password": True},
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["password_never_expires"] is True
            assert body["cannot_change_password"] is True

            row = await db_session.get(AdUserCache, TEACHER_GUID)
            assert row is not None
            await db_session.refresh(row)
            assert row.password_never_expires is True
            assert row.cannot_change_password is True

            # The mock AD entry now carries the DONT_EXPIRE_PASSWD bit (0x10000).
            conn = mock_ad.mock_connection()
            conn.search(
                "CN=Anna,OU=Teachers,DC=schule,DC=local",
                "(objectClass=user)",
                attributes=["userAccountControl"],
            )
            uac = int(conn.entries[0].userAccountControl.value)
            assert uac & 0x10000
        finally:
            app.dependency_overrides.pop(get_ad_client, None)

    @pytest.mark.asyncio
    async def test_admin_can_change_upn(
        self,
        app: FastAPI,
        as_admin: AsyncClient,
        db_session: AsyncSession,
        school_a: int,
        mock_ad: AdClient,
    ) -> None:
        await _seed_user(db_session, school_id=school_a, guid=TEACHER_GUID)
        await _set_mail_domains(db_session, ["schule.example.ch", "lehrer.example.ch"])
        app.dependency_overrides[get_ad_client] = lambda: mock_ad
        try:
            r = await as_admin.patch(
                f"/users/{TEACHER_GUID}",
                json={
                    "upn": "anna.lehrer@lehrer.example.ch",
                    "sam_account_name": "anna.l",
                },
            )
            assert r.status_code == 200, r.text
            assert r.json()["upn"] == "anna.lehrer@lehrer.example.ch"
            assert r.json()["sam_account_name"] == "anna.l"
        finally:
            app.dependency_overrides.pop(get_ad_client, None)

    @pytest.mark.asyncio
    async def test_audit_records_changed_keys_only(
        self,
        app: FastAPI,
        as_smi_a: AsyncClient,
        app_settings: Settings,
        db_session: AsyncSession,
        school_a: int,
        engine: AsyncEngine,
        mock_ad: AdClient,
    ) -> None:
        await _seed_user(db_session, school_id=school_a, guid=TEACHER_GUID)
        app.dependency_overrides[get_ad_client] = lambda: mock_ad
        try:
            r = await as_smi_a.patch(
                f"/users/{TEACHER_GUID}",
                json={"display_name": "New Name", "locality": "Bern"},
            )
            assert r.status_code == 200
        finally:
            app.dependency_overrides.pop(get_ad_client, None)

        sm = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        async with sm() as s:
            row = (
                (
                    await s.execute(
                        select(AuditEvent)
                        .where(AuditEvent.action == "user_attribute_changed")
                        .order_by(AuditEvent.id.desc())
                    )
                )
                .scalars()
                .first()
            )
            assert row is not None
            event = await AuditService(s, app_settings).read(row.id)
        assert event is not None
        assert set(event.payload["changed_keys"]) == {"display_name", "locality"}
        # Belt-and-braces: the actual new values must NOT leak into the payload.
        assert "New Name" not in repr(event.payload)
        assert "Bern" not in repr(event.payload)


class TestRbac:
    @pytest.mark.asyncio
    async def test_smi_cannot_change_upn(
        self,
        app: FastAPI,
        as_smi_a: AsyncClient,
        db_session: AsyncSession,
        school_a: int,
        mock_ad: AdClient,
    ) -> None:
        await _seed_user(db_session, school_id=school_a, guid=TEACHER_GUID)
        await _set_mail_domains(db_session, ["schule.example.ch"])
        app.dependency_overrides[get_ad_client] = lambda: mock_ad
        try:
            r = await as_smi_a.patch(
                f"/users/{TEACHER_GUID}",
                json={"upn": "x@schule.example.ch"},
            )
            assert r.status_code == 403
            assert r.json()["detail"].startswith("admin_only_field:")
        finally:
            app.dependency_overrides.pop(get_ad_client, None)

    @pytest.mark.asyncio
    async def test_smi_cannot_change_sam(
        self,
        app: FastAPI,
        as_smi_a: AsyncClient,
        db_session: AsyncSession,
        school_a: int,
        mock_ad: AdClient,
    ) -> None:
        await _seed_user(db_session, school_id=school_a, guid=TEACHER_GUID)
        app.dependency_overrides[get_ad_client] = lambda: mock_ad
        try:
            r = await as_smi_a.patch(
                f"/users/{TEACHER_GUID}",
                json={"sam_account_name": "new.sam"},
            )
            assert r.status_code == 403
        finally:
            app.dependency_overrides.pop(get_ad_client, None)

    @pytest.mark.asyncio
    async def test_schulleitung_blocked(
        self,
        app: FastAPI,
        as_schulleitung_a: AsyncClient,
        db_session: AsyncSession,
        school_a: int,
        mock_ad: AdClient,
    ) -> None:
        """Schulleitung is not in the user-writer tier."""
        await _seed_user(db_session, school_id=school_a, guid=TEACHER_GUID)
        app.dependency_overrides[get_ad_client] = lambda: mock_ad
        try:
            r = await as_schulleitung_a.patch(
                f"/users/{TEACHER_GUID}",
                json={"display_name": "X"},
            )
            assert r.status_code == 404
            assert r.json()["detail"] == "user_not_found"
        finally:
            app.dependency_overrides.pop(get_ad_client, None)

    @pytest.mark.asyncio
    async def test_smi_cross_school_blocked(
        self,
        app: FastAPI,
        as_smi_a: AsyncClient,
        db_session: AsyncSession,
        school_b: int,
        mock_ad: AdClient,
    ) -> None:
        await _seed_user(db_session, school_id=school_b, guid=OTHER_SCHOOL_TEACHER_GUID)
        app.dependency_overrides[get_ad_client] = lambda: mock_ad
        try:
            r = await as_smi_a.patch(
                f"/users/{OTHER_SCHOOL_TEACHER_GUID}",
                json={"display_name": "X"},
            )
            assert r.status_code == 404
        finally:
            app.dependency_overrides.pop(get_ad_client, None)


class TestDomainAllowlist:
    @pytest.mark.asyncio
    async def test_upn_domain_not_in_allowlist_rejected(
        self,
        app: FastAPI,
        as_admin: AsyncClient,
        db_session: AsyncSession,
        school_a: int,
        mock_ad: AdClient,
    ) -> None:
        await _seed_user(db_session, school_id=school_a, guid=TEACHER_GUID)
        await _set_mail_domains(db_session, ["schule.example.ch"])
        app.dependency_overrides[get_ad_client] = lambda: mock_ad
        try:
            r = await as_admin.patch(
                f"/users/{TEACHER_GUID}",
                json={"upn": "x@evil.example.ch"},
            )
            assert r.status_code == 422
            assert r.json()["detail"].startswith("domain_not_allowed:upn:evil.example.ch")
        finally:
            app.dependency_overrides.pop(get_ad_client, None)

    @pytest.mark.asyncio
    async def test_upn_change_blocked_when_allowlist_empty(
        self,
        app: FastAPI,
        as_admin: AsyncClient,
        db_session: AsyncSession,
        school_a: int,
        mock_ad: AdClient,
    ) -> None:
        await _seed_user(db_session, school_id=school_a, guid=TEACHER_GUID)
        # mail_domains stays empty (default).
        app.dependency_overrides[get_ad_client] = lambda: mock_ad
        try:
            r = await as_admin.patch(
                f"/users/{TEACHER_GUID}",
                json={"upn": "x@schule.example.ch"},
            )
            assert r.status_code == 422
            assert r.json()["detail"].startswith("mail_domains_not_configured:")
        finally:
            app.dependency_overrides.pop(get_ad_client, None)


class TestConflicts:
    @pytest.mark.asyncio
    async def test_upn_collision_returns_409(
        self,
        app: FastAPI,
        as_admin: AsyncClient,
        db_session: AsyncSession,
        school_a: int,
        mock_ad: AdClient,
    ) -> None:
        await _seed_user(db_session, school_id=school_a, guid=TEACHER_GUID)
        await _seed_user(
            db_session,
            school_id=school_a,
            guid=STUDENT_GUID,
            kind="student",
            upn="taken@schule.example.ch",
        )
        await _set_mail_domains(db_session, ["schule.example.ch"])
        app.dependency_overrides[get_ad_client] = lambda: mock_ad
        try:
            r = await as_admin.patch(
                f"/users/{TEACHER_GUID}",
                json={"upn": "taken@schule.example.ch"},
            )
            assert r.status_code == 409
            assert r.json()["detail"].startswith("upn_conflict:")
        finally:
            app.dependency_overrides.pop(get_ad_client, None)


class TestNoOp:
    @pytest.mark.asyncio
    async def test_empty_payload_is_noop_200(
        self,
        app: FastAPI,
        as_smi_a: AsyncClient,
        db_session: AsyncSession,
        school_a: int,
        mock_ad: AdClient,
    ) -> None:
        await _seed_user(db_session, school_id=school_a, guid=TEACHER_GUID)
        app.dependency_overrides[get_ad_client] = lambda: mock_ad
        try:
            r = await as_smi_a.patch(f"/users/{TEACHER_GUID}", json={})
            assert r.status_code == 200
        finally:
            app.dependency_overrides.pop(get_ad_client, None)

    @pytest.mark.asyncio
    async def test_value_unchanged_is_noop(
        self,
        app: FastAPI,
        as_smi_a: AsyncClient,
        db_session: AsyncSession,
        school_a: int,
        engine: AsyncEngine,
        mock_ad: AdClient,
    ) -> None:
        """Sending the current value is dropped before AD-MODIFY runs."""
        await _seed_user(db_session, school_id=school_a, guid=TEACHER_GUID)
        # Manually set display_name so the request "changes" it back to the same.
        from sqlalchemy import update as sql_update

        async with async_sessionmaker(engine, expire_on_commit=False, autoflush=False)() as s:
            await s.execute(
                sql_update(AdUserCache)
                .where(AdUserCache.ad_object_guid == TEACHER_GUID)
                .values(display_name="Already Set")
            )
            await s.commit()

        app.dependency_overrides[get_ad_client] = lambda: mock_ad
        try:
            r = await as_smi_a.patch(
                f"/users/{TEACHER_GUID}",
                json={"display_name": "Already Set"},
            )
            assert r.status_code == 200
        finally:
            app.dependency_overrides.pop(get_ad_client, None)

        # No user_attribute_changed audit event for the no-op.
        async with async_sessionmaker(engine, expire_on_commit=False, autoflush=False)() as s:
            count = (
                (
                    await s.execute(
                        select(AuditEvent).where(AuditEvent.action == "user_attribute_changed")
                    )
                )
                .scalars()
                .all()
            )
        assert len(count) == 0


def _proxy_addresses(mock_ad: AdClient, dn: str) -> set[str]:
    conn = mock_ad.mock_connection()
    conn.search(dn, "(objectClass=user)", attributes=["proxyAddresses"])
    raw = conn.entries[0].proxyAddresses.values if conn.entries else []
    return set(raw)


_ANNA_DN = "CN=Anna,OU=Teachers,DC=schule,DC=local"


class TestMailAliases:
    @pytest.mark.asyncio
    async def test_set_primary_and_aliases_writes_proxy_addresses(
        self,
        app: FastAPI,
        as_smi_a: AsyncClient,
        db_session: AsyncSession,
        school_a: int,
        mock_ad: AdClient,
    ) -> None:
        await _seed_user(db_session, school_id=school_a, guid=TEACHER_GUID)
        await _set_mail_domains(db_session, ["schule.example.ch"])
        app.dependency_overrides[get_ad_client] = lambda: mock_ad
        try:
            r = await as_smi_a.patch(
                f"/users/{TEACHER_GUID}",
                json={
                    "mail": "anna@schule.example.ch",
                    "mail_aliases": [
                        "anna.beispiel@schule.example.ch",
                        "a.b@schule.example.ch",
                    ],
                },
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["mail"] == "anna@schule.example.ch"
            assert body["mail_aliases"] == [
                "anna.beispiel@schule.example.ch",
                "a.b@schule.example.ch",
            ]
        finally:
            app.dependency_overrides.pop(get_ad_client, None)

        row = await db_session.get(AdUserCache, TEACHER_GUID)
        assert row is not None
        await db_session.refresh(row)
        assert row.mail_aliases == [
            "anna.beispiel@schule.example.ch",
            "a.b@schule.example.ch",
        ]
        # proxyAddresses: uppercase SMTP: primary + lowercase smtp: aliases.
        assert _proxy_addresses(mock_ad, _ANNA_DN) == {
            "SMTP:anna@schule.example.ch",
            "smtp:anna.beispiel@schule.example.ch",
            "smtp:a.b@schule.example.ch",
        }

    @pytest.mark.asyncio
    async def test_alias_domain_not_in_allowlist_rejected(
        self,
        app: FastAPI,
        as_smi_a: AsyncClient,
        db_session: AsyncSession,
        school_a: int,
        mock_ad: AdClient,
    ) -> None:
        await _seed_user(db_session, school_id=school_a, guid=TEACHER_GUID)
        await _set_mail_domains(db_session, ["schule.example.ch"])
        app.dependency_overrides[get_ad_client] = lambda: mock_ad
        try:
            r = await as_smi_a.patch(
                f"/users/{TEACHER_GUID}",
                json={"mail_aliases": ["x@evil.example.ch"]},
            )
            assert r.status_code == 422
            assert r.json()["detail"].startswith("domain_not_allowed:mail_aliases:evil.example.ch")
        finally:
            app.dependency_overrides.pop(get_ad_client, None)

    @pytest.mark.asyncio
    async def test_alias_equal_to_primary_is_deduped(
        self,
        app: FastAPI,
        as_smi_a: AsyncClient,
        db_session: AsyncSession,
        school_a: int,
        mock_ad: AdClient,
    ) -> None:
        await _seed_user(db_session, school_id=school_a, guid=TEACHER_GUID)
        await _set_mail_domains(db_session, ["schule.example.ch"])
        app.dependency_overrides[get_ad_client] = lambda: mock_ad
        try:
            r = await as_smi_a.patch(
                f"/users/{TEACHER_GUID}",
                json={
                    "mail": "anna@schule.example.ch",
                    "mail_aliases": ["anna@schule.example.ch", "b@schule.example.ch"],
                },
            )
            assert r.status_code == 200, r.text
            # The alias identical to the primary is dropped.
            assert r.json()["mail_aliases"] == ["b@schule.example.ch"]
        finally:
            app.dependency_overrides.pop(get_ad_client, None)
        assert _proxy_addresses(mock_ad, _ANNA_DN) == {
            "SMTP:anna@schule.example.ch",
            "smtp:b@schule.example.ch",
        }

    @pytest.mark.asyncio
    async def test_clear_aliases_empties_proxy_addresses(
        self,
        app: FastAPI,
        as_smi_a: AsyncClient,
        db_session: AsyncSession,
        school_a: int,
        mock_ad: AdClient,
    ) -> None:
        await _seed_user(db_session, school_id=school_a, guid=TEACHER_GUID)
        await _set_mail_domains(db_session, ["schule.example.ch"])
        app.dependency_overrides[get_ad_client] = lambda: mock_ad
        try:
            await as_smi_a.patch(
                f"/users/{TEACHER_GUID}",
                json={
                    "mail": "anna@schule.example.ch",
                    "mail_aliases": ["alias@schule.example.ch"],
                },
            )
            # Now clear only the aliases (empty list).
            r = await as_smi_a.patch(
                f"/users/{TEACHER_GUID}",
                json={"mail_aliases": []},
            )
            assert r.status_code == 200, r.text
            assert r.json()["mail_aliases"] == []
        finally:
            app.dependency_overrides.pop(get_ad_client, None)

        row = await db_session.get(AdUserCache, TEACHER_GUID)
        assert row is not None
        await db_session.refresh(row)
        assert row.mail_aliases == []
        # Only the primary remains.
        assert _proxy_addresses(mock_ad, _ANNA_DN) == {"SMTP:anna@schule.example.ch"}


class TestRename:
    @pytest.mark.asyncio
    async def test_preview_suggests_cascaded_values(
        self,
        app: FastAPI,
        as_admin: AsyncClient,
        db_session: AsyncSession,
        school_a: int,
        mock_ad: AdClient,
    ) -> None:
        await _seed_user(db_session, school_id=school_a, guid=TEACHER_GUID)
        # give the seeded row a given/surname + mail to cascade from
        from sqlalchemy import update as sql_update

        await db_session.execute(
            sql_update(AdUserCache)
            .where(AdUserCache.ad_object_guid == TEACHER_GUID)
            .values(given_name="Anna", surname="Meier", mail="anna.meier@schule.example.ch")
        )
        await db_session.commit()
        app.dependency_overrides[get_ad_client] = lambda: mock_ad
        try:
            r = await as_admin.post(
                f"/users/{TEACHER_GUID}/rename/preview",
                json={"new_surname": "Müller"},
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["display_name"] == "Anna Müller"
            assert body["mail"] == "anna.mueller@schule.example.ch"
            assert body["old_mail_kept_as_alias"] == "anna.meier@schule.example.ch"
        finally:
            app.dependency_overrides.pop(get_ad_client, None)

    @pytest.mark.asyncio
    async def test_apply_cascades_and_keeps_old_address_as_alias(
        self,
        app: FastAPI,
        as_admin: AsyncClient,
        app_settings: Settings,
        db_session: AsyncSession,
        school_a: int,
        engine: AsyncEngine,
        mock_ad: AdClient,
    ) -> None:
        await _seed_user(db_session, school_id=school_a, guid=TEACHER_GUID)
        await _set_mail_domains(db_session, ["schule.example.ch"])
        from sqlalchemy import update as sql_update

        await db_session.execute(
            sql_update(AdUserCache)
            .where(AdUserCache.ad_object_guid == TEACHER_GUID)
            .values(given_name="Anna", surname="Meier", mail="anna.meier@schule.example.ch")
        )
        await db_session.commit()

        app.dependency_overrides[get_ad_client] = lambda: mock_ad
        try:
            r = await as_admin.post(
                f"/users/{TEACHER_GUID}/rename",
                json={
                    "given_name": "Anna",
                    "surname": "Müller",
                    "display_name": "Anna Müller",
                    "upn": "anna.mueller@schule.example.ch",
                    "mail": "anna.mueller@schule.example.ch",
                    "sam_account_name": "anna.mueller",
                    "keep_old_mail_as_alias": True,
                },
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["surname"] == "Müller"
            assert body["mail"] == "anna.mueller@schule.example.ch"
            assert body["upn"] == "anna.mueller@schule.example.ch"
            # the old primary is preserved as an alias
            assert "anna.meier@schule.example.ch" in body["mail_aliases"]
        finally:
            app.dependency_overrides.pop(get_ad_client, None)

        # proxyAddresses: new primary + old address as smtp alias.
        assert _proxy_addresses(mock_ad, _ANNA_DN) == {
            "SMTP:anna.mueller@schule.example.ch",
            "smtp:anna.meier@schule.example.ch",
        }

        # Audited as a single user_renamed event.
        sm = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        async with sm() as s:
            row = (
                (
                    await s.execute(
                        select(AuditEvent)
                        .where(AuditEvent.action == "user_renamed")
                        .order_by(AuditEvent.id.desc())
                    )
                )
                .scalars()
                .first()
            )
            assert row is not None
            event = await AuditService(s, app_settings).read(row.id)
        assert event is not None
        assert "surname" in event.payload["changed_keys"]

    @pytest.mark.asyncio
    async def test_smi_cannot_rename_upn(
        self,
        app: FastAPI,
        as_smi_a: AsyncClient,
        db_session: AsyncSession,
        school_a: int,
        mock_ad: AdClient,
    ) -> None:
        # A rename that changes the UPN is admin-only; SMI is refused (the same
        # per-field RBAC as PATCH, since rename reuses the attribute service).
        await _seed_user(db_session, school_id=school_a, guid=TEACHER_GUID)
        await _set_mail_domains(db_session, ["schule.example.ch"])
        app.dependency_overrides[get_ad_client] = lambda: mock_ad
        try:
            r = await as_smi_a.post(
                f"/users/{TEACHER_GUID}/rename",
                json={"surname": "Müller", "upn": "anna.mueller@schule.example.ch"},
            )
            assert r.status_code == 403
            assert r.json()["detail"].startswith("admin_only_field:")
        finally:
            app.dependency_overrides.pop(get_ad_client, None)


# Keep imports happy.
_ = ASGITransport
