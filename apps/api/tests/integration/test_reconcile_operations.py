"""Versiegelte Geheimnisse, Wartungsaufträge und Zustandsmeldung (ADR-0024).

Gegen eine echte Datenbank, weil die Zusagen dort liegen: ein Geheimnis wird
verschlüsselt geschrieben und nur einmal; ein Wartungsauftrag läuft genau
einmal und hinterlässt den Beleg im Audit; die Zustandsmeldung liest, was
wirklich gilt.
"""

from __future__ import annotations

import importlib.util
import sys
import uuid
from types import ModuleType
from typing import Any

import httpx
import pytest
from pydantic import BaseModel, SecretStr, ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.auth.oidc_check import REASON_MAX, check_oidc
from magister_api.config import Settings
from magister_api.models.audit import AuditEvent
from magister_api.repositories.local_admin import LocalAdminRepository
from magister_api.services.app_settings import AppSettingsService
from magister_api.services.local_admin import LocalAdminService, LoginOk
from magister_api.services.local_admin_mfa import LocalAdminMfaService, MfaStage
from magister_api.services.reconciler import MAINTENANCE_EVENT, Reconciler
from magister_api.tenancy.desired_state import DesiredMaintenance, DesiredState
from magister_api.tenancy.keys import keys_for
from magister_api.tenancy.registry import Tenant
from magister_api.tenancy.sealing import public_key_b64
from magister_api.tenancy.status_report import collect_status, reconcile_outcome
from tests.konsole import konsole_datei_oder_skip, konsole_modul

pytestmark = pytest.mark.postgres

TENANT_REF = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def _console_sealing() -> ModuleType:
    """Die Versiegel-Hälfte der Konsole, aus ihrer Datei geladen (kein Import über Pakete)."""
    path = konsole_datei_oder_skip("services", "sealing.py")
    spec = importlib.util.spec_from_file_location("console_sealing_it", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


async def _count(session: AsyncSession, action: str) -> int:
    stmt = select(func.count()).select_from(AuditEvent).where(AuditEvent.action == action)
    return (await session.execute(stmt)).scalar_one()


class TestProfileAndModules:
    async def test_the_console_profile_reaches_the_portal(
        self, db_session: AsyncSession, app_settings: Settings
    ) -> None:
        """Der Fall vom Dev-Host: Konsole auf Firma, Portal blieb auf Schule."""
        svc = AppSettingsService(db_session, app_settings)
        await svc.set_module_settings(
            instance_profile="school",
            module_overrides={"classes": True},
            actor_upn="vorher@kunde.ch",
            actor_object_guid=None,
            ip=None,
            request_id="t",
        )
        await db_session.commit()

        desired = DesiredState(settings={"instance_profile": "company", "module_overrides": {}})
        reconciler = Reconciler(db_session, app_settings)
        first = await reconciler.reconcile(desired, tenant_slug="alpha")
        await db_session.commit()
        assert set(first.changed_settings) == {"instance_profile", "module_overrides"}

        cfg = await svc.get_module_settings()
        assert cfg.instance_profile == "company"
        assert cfg.module_overrides == {}

        # Und nur einmal: der nächste Lauf findet nichts mehr zu tun.
        second = await reconciler.reconcile(desired, tenant_slug="alpha")
        await db_session.commit()
        assert second.changed_settings == {}
        assert not second.touched


class TestSealedSecrets:
    async def test_written_encrypted_once_and_not_again(
        self, db_session: AsyncSession, app_settings: Settings
    ) -> None:
        console = _console_sealing()
        public = public_key_b64(keys_for(db_session, app_settings).secrets_key)
        blob = console.seal(
            public, "entra-geheim", tenant_ref=TENANT_REF, name="oidc_client_secret"
        )
        desired = DesiredState(sealed_secrets={"oidc_client_secret": blob})
        svc = Reconciler(db_session, app_settings)

        first = await svc.reconcile(desired, tenant_slug="alpha", tenant_ref=TENANT_REF)
        await db_session.commit()
        assert first.changed_secrets == ["oidc_client_secret"]
        effective = await AppSettingsService(db_session, app_settings).get_effective()
        assert effective.oidc_client_secret == "entra-geheim"

        second = await svc.reconcile(desired, tenant_slug="alpha", tenant_ref=TENANT_REF)
        await db_session.commit()
        assert second.changed_secrets == []
        assert not second.touched

    async def test_a_secret_for_another_tenant_is_rejected(
        self, db_session: AsyncSession, app_settings: Settings
    ) -> None:
        console = _console_sealing()
        public = public_key_b64(keys_for(db_session, app_settings).secrets_key)
        blob = console.seal(public, "x", tenant_ref="someone-else", name="oidc_client_secret")
        result = await Reconciler(db_session, app_settings).reconcile(
            DesiredState(sealed_secrets={"oidc_client_secret": blob}),
            tenant_slug="alpha",
            tenant_ref=TENANT_REF,
        )
        assert "oidc_client_secret" in result.rejected_secrets
        assert result.changed_secrets == []


class TestMaintenance:
    async def test_runs_exactly_once(
        self, db_session: AsyncSession, app_settings: Settings
    ) -> None:
        request = DesiredMaintenance(
            id=str(uuid.uuid4()),
            action="demo_purge",
            requested_by="ops@vitabrevis.ch",
            reason="Demo vor Übergabe entfernen",
        )
        desired = DesiredState(maintenance=(request,))
        svc = Reconciler(db_session, app_settings)

        first = await svc.reconcile(desired, tenant_slug="alpha")
        await db_session.commit()
        assert first.maintenance_executed
        assert first.maintenance_results[0]["ok"] is True
        assert await _count(db_session, MAINTENANCE_EVENT) >= 1

        before = await _count(db_session, "demo_data_purged")
        second = await svc.reconcile(desired, tenant_slug="alpha")
        await db_session.commit()
        assert not second.maintenance_executed
        assert second.maintenance_results[0]["id"] == request.id
        assert second.maintenance_results[0]["ok"] is True
        assert await _count(db_session, "demo_data_purged") == before

    async def test_audit_reset_keeps_the_proof(
        self, db_session: AsyncSession, app_settings: Settings
    ) -> None:
        request = DesiredMaintenance(
            id=str(uuid.uuid4()),
            action="audit_reset",
            requested_by="ops@vitabrevis.ch",
            reason="Protokoll vor Übergabe leeren",
        )
        result = await Reconciler(db_session, app_settings).reconcile(
            DesiredState(maintenance=(request,)), tenant_slug="alpha"
        )
        await db_session.commit()
        assert result.maintenance_executed
        proof = (
            await db_session.execute(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action == MAINTENANCE_EVENT)
                .where(AuditEvent.target_id == request.id)
            )
        ).scalar_one()
        assert proof == 1

    async def test_unknown_action_is_reported_not_run(
        self, db_session: AsyncSession, app_settings: Settings
    ) -> None:
        request = DesiredMaintenance(
            id=str(uuid.uuid4()), action="drop_everything", requested_by="x", reason="y"
        )
        result = await Reconciler(db_session, app_settings).reconcile(
            DesiredState(maintenance=(request,)), tenant_slug="alpha"
        )
        assert result.maintenance_results == [
            {"id": request.id, "ok": False, "result": {"error": "unknown_action"}}
        ]
        assert not result.maintenance_executed


class TestLocalAdminSetup:
    """Lokales Admin-Konto aus der Konsole — für gehostete Kunden ohne Entra."""

    def _request(
        self, db_session: AsyncSession, app_settings: Settings, *, password: str, **extra: str
    ) -> DesiredMaintenance:
        console = _console_sealing()
        public = public_key_b64(keys_for(db_session, app_settings).secrets_key)
        sealed = console.seal(
            public,
            password,
            tenant_ref=extra.pop("tenant_ref", TENANT_REF),
            name="local_admin_password",
        )
        return DesiredMaintenance(
            id=str(uuid.uuid4()),
            action="local_admin_setup",
            requested_by="ops@vitabrevis.ch",
            reason="Zugang einrichten",
            params={"username": "vbadmin", "sealed_password": sealed, **extra},
        )

    async def test_creates_the_account_once_and_forces_totp(
        self, db_session: AsyncSession, app_settings: Settings
    ) -> None:
        request = self._request(db_session, app_settings, password="Sehr-geheim-2026!")
        desired = DesiredState(maintenance=(request,))
        svc = Reconciler(db_session, app_settings)

        first = await svc.reconcile(desired, tenant_slug="alpha", tenant_ref=TENANT_REF)
        await db_session.commit()
        assert first.maintenance_results[0]["ok"] is True
        assert first.maintenance_results[0]["result"]["created"] == 1
        # Kein Passwort, kein Siegel im Ergebnis für die Konsole.
        assert "Sehr-geheim" not in repr(first.maintenance_results)
        assert "sealed" not in repr(first.maintenance_results[0]["result"])

        login = await LocalAdminService(db_session).authenticate("vbadmin", "Sehr-geheim-2026!")
        assert isinstance(login, LoginOk)
        mfa = LocalAdminMfaService(db_session, app_settings)
        assert mfa.stage_for(login.admin) is MfaStage.ENROLL

        # Der Kunde ändert sein Passwort — der nächste Abgleich stellt es
        # NICHT zurück: der Auftrag ist erledigt.
        changed = await LocalAdminService(db_session).change_password(
            current_password="Sehr-geheim-2026!", new_password="Eigenes-Passwort-99"
        )
        assert changed
        await db_session.commit()
        await svc.reconcile(desired, tenant_slug="alpha", tenant_ref=TENANT_REF)
        await db_session.commit()
        again = await LocalAdminService(db_session).authenticate("vbadmin", "Eigenes-Passwort-99")
        assert isinstance(again, LoginOk)

    async def test_a_second_order_resets_password_and_second_factor(
        self, db_session: AsyncSession, app_settings: Settings
    ) -> None:
        svc = Reconciler(db_session, app_settings)
        first = self._request(db_session, app_settings, password="Erstes-Passwort-1!")
        await svc.reconcile(
            DesiredState(maintenance=(first,)), tenant_slug="alpha", tenant_ref=TENANT_REF
        )
        await db_session.commit()

        reset = self._request(
            db_session, app_settings, password="Neues-Passwort-22!", reset_mfa="1"
        )
        result = await svc.reconcile(
            DesiredState(maintenance=(reset,)), tenant_slug="alpha", tenant_ref=TENANT_REF
        )
        await db_session.commit()
        outcome = result.maintenance_results[0]["result"]
        assert outcome["created"] == 0
        assert outcome["mfa_reset"] == 1
        login = await LocalAdminService(db_session).authenticate("vbadmin", "Neues-Passwort-22!")
        assert isinstance(login, LoginOk)

    async def test_a_seal_for_another_tenant_fails_for_good(
        self, db_session: AsyncSession, app_settings: Settings
    ) -> None:
        request = self._request(
            db_session, app_settings, password="Fremdes-Passwort-3!", tenant_ref="jemand-anders"
        )
        svc = Reconciler(db_session, app_settings)
        result = await svc.reconcile(
            DesiredState(maintenance=(request,)), tenant_slug="alpha", tenant_ref=TENANT_REF
        )
        await db_session.commit()
        assert result.maintenance_results[0]["ok"] is False
        assert result.maintenance_results[0]["result"]["error"] == "unseal_failed"
        assert await LocalAdminRepository(db_session).get() is None


class TestStatusReport:
    async def test_reports_what_is_effective_and_no_secret(
        self, db_session: AsyncSession, app_settings: Settings
    ) -> None:
        tenant = Tenant(
            slug="alpha",
            name="Alpha",
            dsn=app_settings.database_url,
            schema_name="public",
            db_role=None,
            schema_version="x",
            console_id=TENANT_REF,
        )
        report = await collect_status(
            db_session, app_settings, tenant, reconcile=reconcile_outcome(ok=True)
        )
        assert report["reconcile"]["ok"] is True
        assert report["effective_profile"] in ("school", "company", "neutral")
        assert "platform" in report["enabled_modules"]
        assert set(report["ad"]) >= {"configured", "missing", "backend", "last_success_at"}
        assert report["sealed_public_key"]
        assert isinstance(report["secrets_present"]["oidc_client_secret"], bool)
        assert report["local_admin"] == {"exists": False}
        # Kein Geheimnis im Klartext, nur ob es gesetzt ist.
        assert "client-secret" not in repr(report)


def _cockpit_status_report() -> type[BaseModel]:
    """`StatusReport` des Cockpits, aus seiner Datei (`schemas/operations.py`)."""
    module = konsole_modul("schemas", "operations.py", name="console_operations_it")
    model: type[BaseModel] = module.StatusReport
    return model


def _tenant(app_settings: Settings) -> Tenant:
    return Tenant(
        slug="alpha",
        name="Alpha",
        dsn=app_settings.database_url,
        schema_name="public",
        db_role=None,
        schema_version="x",
        console_id=TENANT_REF,
    )


async def _oidc_variants() -> list[dict[str, Any]]:
    """Was die Selbstprüfung melden kann: nicht eingerichtet, in Ordnung, Fehler mit 300 Zeichen."""
    issuer = "https://auth.example.ch/realms/kunde-a"
    settings = Settings(
        oidc_issuer=issuer, oidc_client_id="magister", oidc_client_secret=SecretStr("x")
    )

    def provider(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/certs"):
            return httpx.Response(200, json={"keys": [{"kty": "RSA", "kid": "k"}]})
        named = issuer if request.url.host == "auth.example.ch" else "https://x/" + "y" * 400
        return httpx.Response(
            200,
            json={
                "issuer": named,
                "authorization_endpoint": f"{issuer}/auth",
                "token_endpoint": f"{issuer}/token",
                "jwks_uri": f"{issuer}/certs",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as http:
        ok = await check_oidc(settings, http=http)
        # Ein langer Rechnername: der Grund stösst an seine Grenze von 300 Zeichen.
        long_host = ".".join(c * 63 for c in "abc") + ".example.ch"
        wrong = await check_oidc(
            settings.model_copy(update={"oidc_issuer": f"https://{long_host}/realms/a"}),
            http=http,
        )
    assert ok["ok"] is True
    assert wrong["ok"] is False and len(wrong["reason"]) == REASON_MAX
    unconfigured = await check_oidc(settings.model_copy(update={"oidc_issuer": ""}))
    return [unconfigured, ok, wrong]


class TestStatusReportMatchesTheCockpit:
    """Gleichlauf mit dem Cockpit: die Meldung gegen sein echtes Pydantic-Modell.

    Das Cockpit prüft streng (`extra=forbid`): ein Feld, das es nicht kennt,
    weist die ganze Meldung ab. Bis 2026-11-16 verglich kein Test die Meldung
    mit dem Cockpit.
    """

    async def test_the_report_without_oidc_is_accepted(
        self, db_session: AsyncSession, app_settings: Settings
    ) -> None:
        """So geht die Meldung an ein Cockpit, das `oidc` noch nicht kennt (Rückfall bei 422)."""
        model = _cockpit_status_report()
        report = await collect_status(
            db_session, app_settings, _tenant(app_settings), reconcile=reconcile_outcome(ok=True)
        )
        assert "oidc" not in report
        model.model_validate(report)
        if "oidc" not in model.model_fields:
            # Die Voraussetzung für den Rückfall: dieses Cockpit weist `oidc` ab.
            with pytest.raises(ValidationError, match="oidc"):
                model.model_validate({**report, "oidc": (await _oidc_variants())[0]})

    async def test_the_report_with_oidc_is_accepted(
        self, db_session: AsyncSession, app_settings: Settings
    ) -> None:
        model = _cockpit_status_report()
        if "oidc" not in model.model_fields:
            pytest.skip("Das Cockpit kennt das Feld `oidc` der Zustandsmeldung noch nicht.")
        report = await collect_status(
            db_session, app_settings, _tenant(app_settings), reconcile=reconcile_outcome(ok=True)
        )
        for oidc in await _oidc_variants():
            parsed = model.model_validate({**report, "oidc": oidc})
            back = parsed.model_dump(mode="json")["oidc"]
            assert set(back) == {"configured", "ok", "reason", "checked_at"}
            assert (back["configured"], back["ok"], back["reason"]) == (
                oidc["configured"],
                oidc["ok"],
                oidc["reason"],
            )
