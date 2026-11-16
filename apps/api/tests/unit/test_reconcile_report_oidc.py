"""Die Selbstprüfung der Anmeldung reist mit der Zustandsmeldung (ADR-0025 Nachtrag 2026-11-16).

Verdrahtung in der Abgleichsschleife: geprüft wird mit den **wirksamen**
Einstellungen des Mandanten (Konsole über Umgebung), nach dem Schliessen der
Datenbanksitzung (die Prüfung geht ins Netz), und auch dann, wenn der
Soll-Zustand nicht zu holen war.
"""

from __future__ import annotations

from typing import Any

import pytest

from magister_api.config import Settings
from magister_api.services import reconcile_loop
from magister_api.tenancy.desired_state import DesiredStateUnavailableError
from magister_api.tenancy.registry import Tenant

TENANT = Tenant(
    slug="alpha",
    name="Alpha",
    dsn="postgresql+asyncpg://x/y",
    schema_name="t_alpha",
    db_role=None,
    schema_version="x",
    console_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
)
CHECKED = {
    "configured": True,
    "ok": False,
    "reason": "discovery_http_404 (auth.example.ch)",
    "checked_at": "2026-11-16T08:00:00+00:00",
}


class _Session:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def rollback(self) -> None:
        self.events.append("rollback")


class _Sessionmaker:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def __call__(self) -> _Sessionmaker:
        return self

    async def __aenter__(self) -> _Session:
        self.events.append("session_open")
        return _Session(self.events)

    async def __aexit__(self, *exc: object) -> None:
        self.events.append("session_closed")


class _Engines:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def sessionmaker_for(self, tenant: Tenant) -> _Sessionmaker:
        return _Sessionmaker(self.events)


async def test_the_report_carries_the_check_of_the_effective_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    base = Settings(console_registry_url="https://cockpit.example.ch/api/tenants/registry")
    effective = base.model_copy(
        update={"oidc_issuer": "https://auth.example.ch/realms/alpha", "oidc_client_id": "magister"}
    )
    checked_with: list[Settings] = []
    posted: list[dict[str, Any]] = []

    async def fetch(*args: Any, **kwargs: Any) -> Any:
        raise DesiredStateUnavailableError("Konsole nicht erreichbar")

    async def noop(*args: Any, **kwargs: Any) -> None:
        return None

    async def collect(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"reconcile": kwargs["reconcile"]}

    async def load(session: Any, settings: Settings) -> Settings:
        assert settings is base
        return effective

    async def check(settings: Settings) -> dict[str, Any]:
        events.append("check")
        checked_with.append(settings)
        return CHECKED

    async def post(console_url: str, console_id: str, report: dict[str, Any], **kw: Any) -> None:
        posted.append(report)

    monkeypatch.setattr(reconcile_loop, "fetch_desired_state", fetch)
    monkeypatch.setattr(reconcile_loop, "get_engines", lambda: _Engines(events))
    monkeypatch.setattr(reconcile_loop, "tenant_keys", lambda settings, tenant: None)
    monkeypatch.setattr(reconcile_loop, "attach_keys", lambda session, keys: None)
    monkeypatch.setattr(reconcile_loop, "apply_tenant_scope", noop)
    monkeypatch.setattr(reconcile_loop, "collect_status", collect)
    monkeypatch.setattr(reconcile_loop, "load_effective_settings", load)
    monkeypatch.setattr(reconcile_loop, "check_oidc", check)
    monkeypatch.setattr(reconcile_loop, "post_status", post)

    assert await reconcile_loop.reconcile_tenant(base, TENANT) is False

    (report,) = posted
    assert report["reconcile"]["ok"] is False
    assert report["oidc"] == CHECKED
    assert checked_with == [effective]
    # Die Prüfung geht ins Netz: erst nach dem Schliessen der Sitzung.
    assert events.index("check") > events.index("session_closed")
