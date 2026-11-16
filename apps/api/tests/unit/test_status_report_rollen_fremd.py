"""Zustandsmeldung mit ``rollen_fremd`` an ein älteres Cockpit (ADR-0027).

Wie bei ``oidc`` (ADR-0025 Nachtrag): ein Cockpit, das das Feld nicht kennt,
weist die ganze Meldung mit 422 ab, und Magister sendet sie einmal ohne. Neu:
weggelassen wird nur, was die Antwort beanstandet — ein Cockpit, das ``oidc``
schon kennt, bekommt es weiter.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import httpx
import pytest

from magister_api.tenancy.console_report import ReportRejectedError
from magister_api.tenancy.status_report import OPTIONAL_FIELDS, post_status, reconcile_outcome

CONSOLE = "https://cockpit.example.ch/api/tenants/registry"
OIDC = {"configured": False, "ok": None, "reason": None, "checked_at": None}
FREMD = [
    {
        "username": "anna",
        "principal": "8a1f0a52-5c1d-5d7e-9a7f-000000000001",
        "role": "smi",
        "granted_by": "admin@example.ch",
    }
]


def _report() -> dict[str, Any]:
    return {"reconcile": reconcile_outcome(ok=True), "oidc": dict(OIDC), "rollen_fremd": FREMD}


class _Cockpit:
    """Weist jedes Feld aus ``unknown`` ab, wie FastAPI mit ``extra=forbid``."""

    def __init__(self, *unknown: str, detail: bool = True) -> None:
        self.unknown = unknown
        self.detail = detail
        self.bodies: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body: dict[str, Any] = json.loads(request.content)
        self.bodies.append(body)
        extra = [k for k in self.unknown if k in body]
        if not extra:
            return httpx.Response(204)
        if not self.detail:
            return httpx.Response(422, json={"detail": "ungültig"})
        return httpx.Response(
            422,
            json={
                "detail": [
                    {"type": "extra_forbidden", "loc": ["body", k], "input": body[k]} for k in extra
                ]
            },
        )


async def _post(cockpit: _Cockpit) -> None:
    await post_status(
        CONSOLE,
        str(uuid.uuid4()),
        _report(),
        token="nur-test-token",
        transport=httpx.MockTransport(cockpit),
    )


def test_the_field_is_optional() -> None:
    assert "rollen_fremd" in OPTIONAL_FIELDS


async def test_a_current_cockpit_gets_everything_in_one_request() -> None:
    cockpit = _Cockpit()
    await _post(cockpit)
    assert len(cockpit.bodies) == 1
    assert cockpit.bodies[0]["rollen_fremd"] == FREMD


async def test_a_cockpit_without_rollen_fremd_keeps_oidc() -> None:
    cockpit = _Cockpit("rollen_fremd")
    await _post(cockpit)
    assert [sorted(b) for b in cockpit.bodies] == [
        ["oidc", "reconcile", "rollen_fremd"],
        ["oidc", "reconcile"],
    ]


async def test_a_cockpit_without_both_gets_neither() -> None:
    cockpit = _Cockpit("oidc", "rollen_fremd")
    await _post(cockpit)
    assert sorted(cockpit.bodies[1]) == ["reconcile"]


async def test_without_a_named_field_all_optional_fields_go() -> None:
    cockpit = _Cockpit("rollen_fremd", detail=False)
    await _post(cockpit)
    assert sorted(cockpit.bodies[1]) == ["reconcile"]


async def test_a_second_422_is_still_a_failure() -> None:
    def always(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"detail": [{"loc": ["body", "rollen_fremd"]}]})

    with pytest.raises(ReportRejectedError, match="HTTP 422"):
        await post_status(
            CONSOLE,
            str(uuid.uuid4()),
            _report(),
            token="nur-test-token",
            transport=httpx.MockTransport(always),
        )
