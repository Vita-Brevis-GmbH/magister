"""Das Abgleich-Werkzeug: Befunde ohne Werte und ohne Parameterzeilen."""

from __future__ import annotations

import pytest

from magister_api.cli.abgleich import _check, _first_line
from magister_api.config import get_settings
from magister_api.tenancy.registry import Tenant


def test_only_the_first_line_of_an_error() -> None:
    # SQLAlchemy hängt gebundene Parameter in weiteren Zeilen an — die dürfen
    # nicht auf das Terminal.
    exc = RuntimeError("permission denied for table app_settings\n[parameters: ('geheim',)]")
    assert _first_line(exc) == "RuntimeError: permission denied for table app_settings"


async def test_a_tenant_from_the_environment_is_named_not_reconciled(
    capsys: pytest.CaptureFixture[str],
) -> None:
    tenant = Tenant(
        slug="alpha",
        name="Alpha",
        dsn="postgresql+asyncpg://x@localhost/x",
        schema_name="t_alpha",
        db_role=None,
        schema_version="x",
        console_id=None,
    )
    assert await _check(get_settings(), tenant, apply=True) is False
    assert "Kein Konsolen-Kunde" in capsys.readouterr().out
