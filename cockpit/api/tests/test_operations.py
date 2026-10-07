"""Betrieb aus der Konsole (ADR-0024): Zustand, Versiegeln, Wartung, Plattform.

Die datenbankgestützten Tests brauchen ``COCKPIT_TEST_DATABASE_URL`` und werden
sonst übersprungen.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from cockpit_api.config import settings
from cockpit_api.services.backup_scheduler import parse_daily_at, slot_for

SLUG = "betriebtest"


def _dataplane_sealing() -> ModuleType:
    path = (
        Path(__file__).resolve().parents[3]
        / "apps"
        / "api"
        / "magister_api"
        / "tenancy"
        / "sealing.py"
    )
    spec = importlib.util.spec_from_file_location("dp_sealing_ops", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def tenant_id(cockpit_schema: str, cockpit_database_url: str) -> str:
    tid = str(uuid.uuid4())

    async def insert() -> None:
        engine = create_async_engine(cockpit_database_url, poolclass=NullPool)
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO tenants (id, slug, name, hostname, status, profile, "
                        "isolation_mode, dsn_ref, schema_name, db_role, created_at, updated_at) "
                        "VALUES (:id, :slug, 'Betriebstest', :host, 'active', 'company', "
                        "'schema', :ref, :schema, :role, now(), now())"
                    ),
                    {
                        "id": tid,
                        "slug": SLUG,
                        "host": f"{SLUG}.example.ch",
                        "ref": f"tenant_{SLUG}",
                        "schema": f"t_{SLUG}",
                        "role": f"r_{SLUG}",
                    },
                )
        finally:
            await engine.dispose()

    asyncio.run(insert())
    return tid


def _report(**extra: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "reconcile": {"ok": True, "at": datetime.now(UTC).isoformat(), "touched": False},
        "effective_profile": "school",
        "enabled_modules": ["platform", "classes"],
        "ad": {
            "configured": False,
            "missing": ["ad_users_search_base"],
            "backend": "connector",
            "last_success_at": None,
            "last_failure_at": None,
            "last_count": None,
            "last_mode": None,
        },
        "secrets_present": {"oidc_client_secret": False},
    }
    body.update(extra)
    return body


class TestStatus:
    def test_never_reported(self, console_client: TestClient, tenant_id: str) -> None:
        body = console_client.get(f"/api/tenants/{tenant_id}/status").json()
        assert body["report"] is None
        assert body["profile_matches"] is None

    def test_a_profile_mismatch_is_visible(
        self, console_client: TestClient, tenant_id: str
    ) -> None:
        # Der Fall vom Dev-Host: Konsole auf Firma, Installation auf Schule.
        resp = console_client.post(f"/api/tenants/{tenant_id}/status", json=_report())
        assert resp.status_code == 204, resp.text
        body = console_client.get(f"/api/tenants/{tenant_id}/status").json()
        assert body["console_profile"] == "company"
        assert body["report"]["effective_profile"] == "school"
        assert body["profile_matches"] is False

    def test_unknown_fields_are_refused(self, console_client: TestClient, tenant_id: str) -> None:
        resp = console_client.post(
            f"/api/tenants/{tenant_id}/status", json=_report(personendaten=["x"])
        )
        assert resp.status_code == 422


class TestSealedSecrets:
    def test_needs_a_reported_key(self, console_client: TestClient, tenant_id: str) -> None:
        resp = console_client.put(
            f"/api/tenants/{tenant_id}/sealed-secrets/oidc_client_secret", json={"value": "s"}
        )
        assert resp.status_code == 409

    def test_seal_reaches_the_desired_state_and_opens_on_the_data_plane(
        self, console_client: TestClient, tenant_id: str
    ) -> None:
        dp = _dataplane_sealing()
        key = "kundenschluessel-" + "z" * 32
        public = dp.public_key_b64(key)
        console_client.post(
            f"/api/tenants/{tenant_id}/status",
            json=_report(sealed_public_key=public, sealed_key_id=dp.key_id(public)),
        )
        resp = console_client.put(
            f"/api/tenants/{tenant_id}/sealed-secrets/oidc_client_secret",
            json={"value": "entra-secret-42"},
        )
        assert resp.status_code == 200, resp.text
        assert "entra-secret-42" not in resp.text
        listed = {s["name"]: s for s in resp.json()}
        assert listed["oidc_client_secret"]["sealed"] is True
        assert listed["oidc_client_secret"]["key_current"] is True

        desired = console_client.get(f"/api/tenants/{tenant_id}/desired-state").json()
        blob = desired["sealed_secrets"]["oidc_client_secret"]
        assert "entra-secret-42" not in json.dumps(desired)
        assert (
            dp.unseal(key, blob, tenant_ref=tenant_id, name="oidc_client_secret")
            == "entra-secret-42"
        )

    def test_unknown_secret_name(self, console_client: TestClient, tenant_id: str) -> None:
        resp = console_client.put(
            f"/api/tenants/{tenant_id}/sealed-secrets/ad_bind_password", json={"value": "x"}
        )
        assert resp.status_code == 422


class TestMaintenance:
    def test_confirmation_must_match(self, console_client: TestClient, tenant_id: str) -> None:
        resp = console_client.post(
            f"/api/tenants/{tenant_id}/maintenance",
            json={"action": "demo_purge", "reason": "vor der Übergabe", "confirm_slug": "falsch"},
        )
        assert resp.status_code == 422

    def test_request_travels_and_closes_with_the_report(
        self, console_client: TestClient, tenant_id: str
    ) -> None:
        url = f"/api/tenants/{tenant_id}/maintenance"
        body = {"action": "audit_reset", "reason": "Übergabe an die Schule", "confirm_slug": SLUG}
        created = console_client.post(url, json=body)
        assert created.status_code == 201, created.text
        request_id = created.json()["id"]
        assert console_client.post(url, json=body).status_code == 409  # schon offen

        desired = console_client.get(f"/api/tenants/{tenant_id}/desired-state").json()
        assert [m["id"] for m in desired["maintenance"]] == [request_id]

        console_client.post(
            f"/api/tenants/{tenant_id}/status",
            json=_report(maintenance=[{"id": request_id, "ok": True, "result": {"deleted": 12}}]),
        )
        listed = console_client.get(url).json()
        assert listed[0]["state"] == "done"
        assert listed[0]["result"] == {"deleted": 12}
        desired = console_client.get(f"/api/tenants/{tenant_id}/desired-state").json()
        assert desired["maintenance"] == []

    def test_cancel(self, console_client: TestClient, tenant_id: str) -> None:
        url = f"/api/tenants/{tenant_id}/maintenance"
        created = console_client.post(
            url, json={"action": "demo_purge", "reason": "doch nicht nötig", "confirm_slug": SLUG}
        ).json()
        resp = console_client.post(f"{url}/{created['id']}/cancel")
        assert resp.json()["state"] == "cancelled"


class TestDesiredStateCorrectsExistingPortals:
    def test_module_overrides_are_always_stated(
        self, console_client: TestClient, tenant_id: str
    ) -> None:
        """Bestehende Portale werden korrigiert: ein leeres `{}` räumt alte Schalter ab."""
        desired = console_client.get(f"/api/tenants/{tenant_id}/desired-state").json()
        assert desired["settings"]["module_overrides"] == {}
        assert desired["settings"]["instance_profile"] == "company"


class TestPlatformOps:
    def test_not_configured(
        self, console_client: TestClient, cockpit_schema: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "ops_dir", "")
        assert console_client.get("/api/platform/ops").json()["configured"] is False
        assert console_client.post("/api/platform/ops/restart").status_code == 503

    def test_request_is_dropped_for_the_host_agent(
        self,
        console_client: TestClient,
        cockpit_schema: str,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setattr(settings, "ops_dir", str(tmp_path))
        resp = console_client.post("/api/platform/ops/update")
        assert resp.status_code == 202, resp.text
        files = list((tmp_path / "requests").glob("*.json"))
        assert len(files) == 1
        payload = json.loads(files[0].read_text())
        assert payload["action"] == "update"
        assert payload["requested_by"] == "bootstrap-token"
        assert console_client.get("/api/platform/ops").json()["pending"] == 1

    def test_only_two_actions(
        self,
        console_client: TestClient,
        cockpit_schema: str,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setattr(settings, "ops_dir", str(tmp_path))
        assert console_client.post("/api/platform/ops/rm-rf").status_code == 422


class TestAttach:
    def test_request_carries_only_the_slug(
        self,
        console_client: TestClient,
        tenant_id: str,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setattr(settings, "ops_dir", str(tmp_path))
        resp = console_client.post(f"/api/tenants/{tenant_id}/attach")
        assert resp.status_code == 202, resp.text
        assert resp.json()["slug"] == SLUG
        (request,) = list((tmp_path / "requests").glob("*.json"))
        payload = json.loads(request.read_text())
        assert payload["action"] == "attach"
        assert payload["slug"] == SLUG
        # Kein DSN, kein Schlüssel, kein Passwort: die Konsole hat keines.
        assert set(payload) == {"id", "action", "slug", "requested_by", "requested_at"}

    def test_not_while_provisioning(
        self,
        console_client: TestClient,
        tenant_id: str,
        cockpit_database_url: str,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        async def set_provisioning() -> None:
            engine = create_async_engine(cockpit_database_url, poolclass=NullPool)
            try:
                async with engine.begin() as conn:
                    await conn.execute(
                        text("UPDATE tenants SET status = 'provisioning' WHERE id = :id"),
                        {"id": tenant_id},
                    )
            finally:
                await engine.dispose()

        asyncio.run(set_provisioning())
        monkeypatch.setattr(settings, "ops_dir", str(tmp_path))
        assert console_client.post(f"/api/tenants/{tenant_id}/attach").status_code == 409

    def test_not_configured(
        self, console_client: TestClient, tenant_id: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "ops_dir", "")
        assert console_client.post(f"/api/tenants/{tenant_id}/attach").status_code == 503


class TestBackupWorker:
    def test_queue_records_the_heartbeat(
        self, console_client: TestClient, cockpit_schema: str
    ) -> None:
        assert console_client.get("/api/backups/worker").json()["last_seen_at"] is None
        queue = console_client.get("/api/backups/worker-queue", params={"detail": "host=test"})
        assert queue.status_code == 200, queue.text
        assert queue.json() == {"verify": [], "restore": []}
        beat = console_client.get("/api/backups/worker").json()
        assert beat["last_seen_at"] is not None
        assert beat["detail"] == "host=test"


class TestDailySchedule:
    def test_parse(self) -> None:
        at = parse_daily_at("01:30")
        assert at is not None and (at.hour, at.minute) == (1, 30)
        assert parse_daily_at("") is None
        assert parse_daily_at("halb zwei") is None

    def test_slot_only_after_the_time(self) -> None:
        at = parse_daily_at("01:30")
        assert at is not None
        assert slot_for(datetime(2026, 10, 6, 1, 29, tzinfo=UTC), at) is None
        slot = slot_for(datetime(2026, 10, 6, 7, 0, tzinfo=UTC), at)
        assert slot == datetime(2026, 10, 6, 1, 30, tzinfo=UTC)
