"""Zustandsmeldung an ein Cockpit, das älter ist als Magister (ADR-0025 Nachtrag 2026-11-16).

Das Cockpit prüft die Meldung streng (``extra=forbid``): ein Cockpit ohne das
Feld ``oidc`` weist die ganze Meldung mit 422 ab. Magister sendet sie dann
einmal ohne ``oidc`` — so kommt es nicht darauf an, wer zuerst aktualisiert
wird.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

import httpx
import pytest

from magister_api.tenancy.console_report import ReportRejectedError
from magister_api.tenancy.status_report import post_status, reconcile_outcome

CONSOLE = "https://cockpit.example.ch/api/tenants/registry"
OIDC = {
    "configured": True,
    "ok": False,
    "reason": "discovery_http_404 (auth.example.ch)",
    "checked_at": "2026-11-16T08:00:00+00:00",
}


def _report() -> dict[str, Any]:
    return {"reconcile": reconcile_outcome(ok=True), "oidc": dict(OIDC)}


class _Cockpit:
    """Nimmt Meldungen an wie das Cockpit; ``knows_oidc=False`` wie eines vor dem Feld."""

    def __init__(self, *, knows_oidc: bool, always: int | None = None) -> None:
        self.knows_oidc = knows_oidc
        self.always = always
        self.bodies: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body: dict[str, Any] = json.loads(request.content)
        self.bodies.append(body)
        if self.always is not None:
            return httpx.Response(self.always, json={"detail": "nein"})
        if "oidc" in body and not self.knows_oidc:
            return httpx.Response(
                422,
                json={
                    "detail": [
                        {
                            "type": "extra_forbidden",
                            "loc": ["body", "oidc"],
                            "msg": "Extra inputs are not permitted",
                            "input": body["oidc"],
                        }
                    ]
                },
            )
        return httpx.Response(204)


async def _post(cockpit: _Cockpit, tenant: str, report: dict[str, Any] | None = None) -> None:
    await post_status(
        CONSOLE,
        tenant,
        report if report is not None else _report(),
        token="nur-test-token",
        transport=httpx.MockTransport(cockpit),
    )


class TestOrderOfUpdates:
    async def test_a_new_cockpit_gets_the_field_in_one_request(self) -> None:
        cockpit = _Cockpit(knows_oidc=True)
        await _post(cockpit, str(uuid.uuid4()))
        assert len(cockpit.bodies) == 1
        assert cockpit.bodies[0]["oidc"] == OIDC

    async def test_an_older_cockpit_gets_the_report_without_it(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        cockpit = _Cockpit(knows_oidc=False)
        tenant = str(uuid.uuid4())
        with caplog.at_level(logging.DEBUG, logger="magister_api.tenancy.status_report"):
            await _post(cockpit, tenant)
            await _post(cockpit, tenant)

        assert [("oidc" in b) for b in cockpit.bodies] == [True, False, True, False]
        assert set(cockpit.bodies[1]) == {"reconcile"}
        notes = [r for r in caplog.records if "ohne oidc" in r.getMessage()]
        # Einmal als Warnung, danach leiser — die Meldung läuft alle paar Minuten.
        assert [r.levelno for r in notes] == [logging.WARNING, logging.DEBUG]
        assert "body.oidc: extra_forbidden" in notes[0].getMessage()
        # Der eingereichte Wert (`input` in der Antwort) kommt nicht ins Protokoll.
        assert "auth.example.ch" not in caplog.text

    async def test_after_the_cockpit_update_the_field_goes_through_again(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        tenant = str(uuid.uuid4())
        await _post(_Cockpit(knows_oidc=False), tenant)
        updated = _Cockpit(knows_oidc=True)
        await _post(updated, tenant)
        assert [("oidc" in b) for b in updated.bodies] == [True]

        # Ein späteres Zurücksetzen des Cockpits steht wieder als Warnung im Protokoll.
        caplog.clear()
        with caplog.at_level(logging.DEBUG, logger="magister_api.tenancy.status_report"):
            await _post(_Cockpit(knows_oidc=False), tenant)
        notes = [r for r in caplog.records if "ohne oidc" in r.getMessage()]
        assert [r.levelno for r in notes] == [logging.WARNING]

    async def test_a_422_for_another_reason_is_still_a_failure(self) -> None:
        cockpit = _Cockpit(knows_oidc=True, always=422)
        with pytest.raises(ReportRejectedError, match="HTTP 422"):
            await _post(cockpit, str(uuid.uuid4()))
        assert len(cockpit.bodies) == 2

    async def test_without_the_field_there_is_no_second_try(self) -> None:
        cockpit = _Cockpit(knows_oidc=True, always=422)
        report = {"reconcile": reconcile_outcome(ok=True)}
        with pytest.raises(ReportRejectedError, match="HTTP 422"):
            await _post(cockpit, str(uuid.uuid4()), report)
        assert len(cockpit.bodies) == 1

    async def test_other_errors_are_not_retried(self) -> None:
        cockpit = _Cockpit(knows_oidc=True, always=500)
        with pytest.raises(ReportRejectedError, match="HTTP 500"):
            await _post(cockpit, str(uuid.uuid4()))
        assert len(cockpit.bodies) == 1
