"""Mailversand aus der Konsole: Plattform-Standard, eigene Anbindung, Aufräumen.

Das Plattform-Geheimnis ist mit dem Plattform-Schlüssel versiegelt (ein
Chiffrat für alle Kunden); das eines Kunden mit seinem eigenen. Schickt die
Konsole eine Anbindung ohne Geheimnis, wird ein noch gespeichertes entfernt.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import SecretStr, ValidationError
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


async def test_mail_test_order_sends_with_the_effective_connection(
    db_session: AsyncSession, app_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from magister_api.mail import MailConfig, MailError, MailMessage
    from magister_api.tenancy.desired_state import DesiredMaintenance

    sent: list[tuple[MailConfig, MailMessage]] = []

    async def fake_send(config: MailConfig, message: MailMessage) -> None:
        if message.to == "kaputt@vb.ch":
            raise MailError("graph: token 401 invalid_client: AADSTS7000215")
        sent.append((config, message))

    monkeypatch.setattr("magister_api.services.reconciler.send_mail", fake_send)
    settings = _settings(app_settings)
    console = _console_sealing()
    blob = console.seal(
        public_key_b64(PLATFORM_KEY), "vb-geheim", tenant_ref=PLATFORM_REF, name="mail_secret"
    )

    def order(order_id: str, to: str) -> DesiredState:
        return DesiredState(
            settings=GRAPH_STANDARD,
            platform_sealed_secrets={"mail_secret": blob},
            maintenance=(
                DesiredMaintenance(
                    id=order_id,
                    action="mail_test",
                    requested_by="ops@vitabrevis.ch",
                    reason=f"Testmail an {to}",
                    params={"to": to},
                ),
            ),
        )

    ok_id = "11111111-1111-1111-1111-111111111111"
    result = await _run(db_session, settings, order(ok_id, "ops@vb.ch"))
    # Dieselbe Runde: erst Anbindung und Geheimnis, dann der Versand damit.
    config, message = sent[0]
    assert (config.transport, config.secret, message.to) == ("graph", "vb-geheim", "ops@vb.ch")
    assert result.maintenance_results[0]["id"] == ok_id
    assert result.maintenance_results[0]["ok"] is True

    # Nur einmal: der zweite Lauf meldet das Ergebnis, sendet aber nicht nochmals.
    again = await _run(db_session, settings, order(ok_id, "ops@vb.ch"))
    assert len(sent) == 1
    assert again.maintenance_results[0]["ok"] is True

    bad_id = "22222222-2222-2222-2222-222222222222"
    failed = await _run(db_session, settings, order(bad_id, "kaputt@vb.ch"))
    outcome = failed.maintenance_results[0]
    assert outcome["ok"] is False
    assert outcome["result"]["error"].startswith("graph: token 401")
    assert "vb-geheim" not in repr(outcome)


async def test_a_failing_order_is_reported_and_does_not_sink_the_round(
    db_session: AsyncSession, app_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from magister_api.services.reconciler import Reconciler, safe_error
    from magister_api.tenancy.desired_state import DesiredMaintenance

    async def boom(self: Reconciler, request: DesiredMaintenance) -> dict[str, Any]:
        raise RuntimeError("kaputt")

    monkeypatch.setattr(Reconciler, "_mail_test", boom)
    desired = DesiredState(
        settings=GRAPH_STANDARD,
        maintenance=(
            DesiredMaintenance(
                id="44444444-4444-4444-4444-444444444444",
                action="mail_test",
                requested_by="ops",
                reason="Testmail an x@vb.ch",
                params={"to": "x@vb.ch"},
            ),
        ),
    )
    result = await _run(db_session, _settings(app_settings), desired)
    assert result.maintenance_results == [
        {
            "id": "44444444-4444-4444-4444-444444444444",
            "ok": False,
            "result": {"error": "RuntimeError: kaputt"},
        }
    ]
    # Die Einstellungen derselben Runde sind trotzdem geschrieben.
    eff = await AppSettingsService(db_session, app_settings).get_effective()
    assert eff.mail_transport == "graph"

    # Fehlertexte ohne Eingabewerte bzw. Parameter.
    from magister_api.schemas.app_settings import AppSettingsUpdate

    with pytest.raises(ValidationError) as caught:
        AppSettingsUpdate(mail_transport="sendmail")
    text = safe_error(caught.value)
    assert text.startswith("ValidationError: mail_transport:")
    assert "sendmail" not in text
