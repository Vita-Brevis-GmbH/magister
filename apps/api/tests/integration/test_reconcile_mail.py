"""Mailversand aus der Konsole: Plattform-Standard, eigene Anbindung, Aufräumen.

Das Plattform-Geheimnis ist mit dem Plattform-Schlüssel versiegelt (ein
Chiffrat für alle Kunden); das eines Kunden mit seinem eigenen. Schickt die
Konsole eine Anbindung ohne Geheimnis, wird ein noch gespeichertes entfernt.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.config import Settings
from magister_api.services.app_settings import AppSettingsService
from magister_api.services.reconciler import Reconciler
from magister_api.tenancy.desired_state import DesiredState
from magister_api.tenancy.keys import keys_for
from magister_api.tenancy.sealing import PLATFORM_REF, public_key_b64

from .test_reconcile_operations import TENANT_REF, _console_sealing

pytestmark = pytest.mark.postgres

PLATFORM_KEY = "plattform-schluessel-fuer-tests-0123456789"

#: So schickt die Konsole eine Anbindung: vollständig, Leeres als "" bzw. 0.
GRAPH_STANDARD: dict[str, Any] = {
    "mail_transport": "graph",
    "mail_from": "noreply@vitabrevis.ch",
    "mail_from_name": "Magister",
    "smtp_host": "",
    "smtp_port": 0,
    "smtp_security": "starttls",
    "smtp_username": "",
    "graph_tenant_id": "vb-tenant",
    "graph_client_id": "vb-client",
}


def _settings(app_settings: Settings) -> Settings:
    return app_settings.model_copy(update={"platform_secrets_key": SecretStr(PLATFORM_KEY)})


async def _run(session: AsyncSession, settings: Settings, desired: DesiredState) -> Any:
    result = await Reconciler(session, settings).reconcile(
        desired, tenant_slug="alpha", tenant_ref=TENANT_REF
    )
    await session.commit()
    return result


async def test_platform_standard_then_own_connection_then_back(
    db_session: AsyncSession, app_settings: Settings
) -> None:
    settings = _settings(app_settings)
    console = _console_sealing()
    platform_blob = console.seal(
        public_key_b64(PLATFORM_KEY), "vb-geheim", tenant_ref=PLATFORM_REF, name="mail_secret"
    )
    standard = DesiredState(
        settings=GRAPH_STANDARD, platform_sealed_secrets={"mail_secret": platform_blob}
    )
    first = await _run(db_session, settings, standard)
    assert first.changed_secrets == ["mail_secret"]
    eff = await AppSettingsService(db_session, settings).get_effective()
    assert (eff.mail_transport, eff.graph_client_id, eff.mail_secret) == (
        "graph",
        "vb-client",
        "vb-geheim",
    )
    assert eff.smtp_host is None and eff.smtp_port is None

    # Zweiter Lauf: "" und 0 aus der Konsole sind dasselbe wie NULL — nichts zu tun.
    again = await _run(db_session, settings, standard)
    assert again.changed_settings == {}
    assert again.changed_secrets == []

    # Eigene SMTP-Anbindung mit eigenem Geheimnis (mit dem Kundenschlüssel versiegelt).
    tenant_public = public_key_b64(keys_for(db_session, settings).secrets_key)
    own_blob = console.seal(tenant_public, "eigen", tenant_ref=TENANT_REF, name="mail_secret")
    own = DesiredState(
        settings={
            **GRAPH_STANDARD,
            "mail_transport": "smtp",
            "mail_from": "it@schule.ch",
            "smtp_host": "mail.schule.ch",
            "smtp_username": "it@schule.ch",
            "graph_tenant_id": "",
            "graph_client_id": "",
        },
        sealed_secrets={"mail_secret": own_blob},
    )
    await _run(db_session, settings, own)
    eff = await AppSettingsService(db_session, settings).get_effective()
    assert (eff.mail_transport, eff.smtp_host, eff.mail_secret) == (
        "smtp",
        "mail.schule.ch",
        "eigen",
    )
    assert eff.graph_client_id is None  # nichts von der Plattform bleibt stehen

    # Anbindung ohne Geheimnis (z. B. Relay ohne Anmeldung): das alte fällt weg.
    relay = DesiredState(settings={**own.settings, "smtp_username": ""})
    result = await _run(db_session, settings, relay)
    assert "mail_secret" in result.changed_secrets
    eff = await AppSettingsService(db_session, settings).get_effective()
    assert eff.mail_secret is None


async def test_a_platform_seal_needs_the_platform_key(
    db_session: AsyncSession, app_settings: Settings
) -> None:
    console = _console_sealing()
    # Mit dem Kundenschlüssel versiegelt, aber als Plattform-Geheimnis geschickt.
    tenant_public = public_key_b64(keys_for(db_session, app_settings).secrets_key)
    wrong = console.seal(tenant_public, "x", tenant_ref=PLATFORM_REF, name="mail_secret")
    result = await _run(
        db_session,
        _settings(app_settings),
        DesiredState(settings=GRAPH_STANDARD, platform_sealed_secrets={"mail_secret": wrong}),
    )
    assert "mail_secret" in result.rejected_secrets
    eff = await AppSettingsService(db_session, app_settings).get_effective()
    assert eff.mail_secret is None
    # Kein Plattform-Geheimnis ausser dem Mail-Geheimnis.
    result = await _run(
        db_session,
        _settings(app_settings),
        DesiredState(platform_sealed_secrets={"oidc_client_secret": wrong}),
    )
    assert "oidc_client_secret" in result.rejected_secrets


async def test_the_status_report_carries_the_platform_key_only_when_set(
    db_session: AsyncSession, app_settings: Settings
) -> None:
    from magister_api.tenancy.registry import Tenant
    from magister_api.tenancy.status_report import collect_status, reconcile_outcome

    tenant = Tenant(
        slug="alpha",
        name="Alpha",
        dsn=app_settings.database_url,
        schema_name="public",
        db_role=None,
        schema_version="x",
        console_id=TENANT_REF,
    )
    plain = await collect_status(
        db_session, app_settings, tenant, reconcile=reconcile_outcome(ok=True)
    )
    assert "platform_sealed_public_key" not in plain
    assert plain["secrets_present"]["mail_secret"] is False
    keyed = await collect_status(
        db_session, _settings(app_settings), tenant, reconcile=reconcile_outcome(ok=True)
    )
    assert keyed["platform_sealed_public_key"] == public_key_b64(PLATFORM_KEY)
    assert PLATFORM_KEY not in repr(keyed)
