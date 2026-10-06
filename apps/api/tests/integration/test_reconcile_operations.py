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
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.config import Settings
from magister_api.models.audit import AuditEvent
from magister_api.services.app_settings import AppSettingsService
from magister_api.services.reconciler import MAINTENANCE_EVENT, Reconciler
from magister_api.tenancy.desired_state import DesiredMaintenance, DesiredState
from magister_api.tenancy.keys import keys_for
from magister_api.tenancy.registry import Tenant
from magister_api.tenancy.sealing import public_key_b64
from magister_api.tenancy.status_report import collect_status, reconcile_outcome

pytestmark = pytest.mark.postgres

TENANT_REF = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def _console_sealing() -> ModuleType:
    """Die Versiegel-Hälfte der Konsole, aus ihrer Datei geladen (kein Import über Pakete)."""
    path = (
        Path(__file__).resolve().parents[4]
        / "cockpit"
        / "api"
        / "cockpit_api"
        / "services"
        / "sealing.py"
    )
    if not path.is_file():
        pytest.skip(f"Konsole nicht gefunden: {path}")
    spec = importlib.util.spec_from_file_location("console_sealing_it", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


async def _count(session: AsyncSession, action: str) -> int:
    stmt = select(func.count()).select_from(AuditEvent).where(AuditEvent.action == action)
    return (await session.execute(stmt)).scalar_one()


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
        # Kein Geheimnis im Klartext, nur ob es gesetzt ist.
        assert "client-secret" not in repr(report)
