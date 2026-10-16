"""Passwort-Reset: die Antwort des AD entscheidet, nicht eine Probe-Anmeldung.

Für alle drei Wege (Schüler:innen, Lehrpersonen, Benutzer). Früher meldete
sich Magister vor dem Setzen mit dem *neuen* Passwort als der Benutzer an —
gegen ein echtes AD scheiterte das immer, und jedes eigene Passwort galt als
„entspricht nicht den Richtlinien“.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from magister_api.ad.errors import (
    PASSWORD_REJECTED,
    SYNC_REASON_CONNECTOR_OFFLINE,
    SYNC_REASON_CONNECTOR_SCOPE,
    AdUnavailableError,
    classify_sync_failure,
    is_password_rejected,
)
from magister_api.services.student_password_reset import (
    ManualPasswordPolicyError,
    StudentPasswordResetService,
)
from magister_api.services.teacher_password_reset import (
    TeacherManualPasswordPolicyError,
    TeacherPasswordResetService,
)
from magister_api.services.user_password_reset import (
    UserPasswordResetService,
    UserResetManualPasswordPolicyError,
)

GOOD = "Apfel-Stuhl-77!"


class _Audit:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def emit(self, **kwargs: Any) -> None:
        self.events.append(kwargs)


class _Ad:
    """Verhält sich wie ein echtes AD: eine Anmeldung mit dem neuen Passwort schlägt fehl."""

    def __init__(self, *, reject: bool = False, outage: bool = False) -> None:
        self.reject = reject
        self.outage = outage
        self.written: list[str] = []

    async def find_user_dn(self, ad_object_guid: str) -> str:
        return "CN=Muster,OU=Benutzer,DC=schule,DC=local"

    async def probe_bind_as_user(self, *, user_dn: str, password: str) -> bool:
        raise AssertionError("Vor dem Setzen darf nicht als Benutzer angemeldet werden.")

    async def modify_password(self, *, user_dn: str, new_password: str, force_change: bool) -> None:
        if self.outage:
            raise AdUnavailableError("ldap_modify_failed")
        if self.reject:
            raise AdUnavailableError(PASSWORD_REJECTED)
        self.written.append(new_password)


def _service(kind: str, ad: _Ad) -> tuple[Any, _Audit, type[Exception], str]:
    scope = SimpleNamespace(upn="admin@schule.ch", ad_object_guid=None)
    cls: Any
    error: type[Exception]
    if kind == "student":
        cls, error, arg = StudentPasswordResetService, ManualPasswordPolicyError, "student"
    elif kind == "teacher":
        cls, error, arg = TeacherPasswordResetService, TeacherManualPasswordPolicyError, "teacher"
    else:
        cls, error, arg = UserPasswordResetService, UserResetManualPasswordPolicyError, "target"
    svc = cls.__new__(cls)
    svc.session = None
    svc.settings = None
    svc.scope = scope
    svc.ad = ad
    audit = _Audit()
    svc.audit = audit
    return svc, audit, error, arg


def _person() -> Any:
    return SimpleNamespace(enabled=True, ad_object_guid="g-1", school_id=1, store_password=False)


KINDS = ["student", "teacher", "user"]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", KINDS)
async def test_a_good_manual_password_is_written_without_a_probe(kind: str) -> None:
    ad = _Ad()
    svc, audit, _error, arg = _service(kind, ad)
    await svc.reset(
        **{arg: _person()},
        mode="manual",
        manual_password=GOOD,
        force_change=False,
        ip=None,
        request_id="r",
    )
    assert ad.written == [GOOD]
    assert not any(str(e["action"]).endswith("_failed") for e in audit.events)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", KINDS)
async def test_an_ad_rejection_is_a_policy_answer(kind: str) -> None:
    svc, audit, error, arg = _service(kind, _Ad(reject=True))
    with pytest.raises(error, match="manual_password_rejected_by_ad"):
        await svc.reset(
            **{arg: _person()},
            mode="manual",
            manual_password=GOOD,
            force_change=False,
            ip=None,
            request_id="r",
        )
    (failed,) = [e for e in audit.events if str(e["action"]).endswith("_failed")]
    assert failed["payload"]["reason"] == "password_rejected_by_ad"
    # Kein Passwort im Audit, auch nicht im Fehlerfall.
    assert GOOD not in repr(audit.events)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", KINDS)
async def test_an_outage_stays_an_outage(kind: str) -> None:
    svc, audit, _error, arg = _service(kind, _Ad(outage=True))
    with pytest.raises(AdUnavailableError):
        await svc.reset(
            **{arg: _person()},
            mode="generate",
            manual_password=None,
            force_change=True,
            ip=None,
            request_id="r",
        )
    (failed,) = [e for e in audit.events if str(e["action"]).endswith("_failed")]
    assert failed["payload"]["reason"] == "ldap_unavailable"


def test_the_rejection_code_is_recognised_only_exactly() -> None:
    assert is_password_rejected(AdUnavailableError(PASSWORD_REJECTED))
    assert not is_password_rejected(AdUnavailableError("ldap_modify_failed"))
    assert not is_password_rejected(ValueError(PASSWORD_REJECTED))


@pytest.mark.parametrize(
    ("message", "reason"),
    [
        ("connector_refused_scope", SYNC_REASON_CONNECTOR_SCOPE),
        ("connector_agent_unavailable", SYNC_REASON_CONNECTOR_OFFLINE),
        ("connector_timeout", SYNC_REASON_CONNECTOR_OFFLINE),
        ("ldap_search_failed:noSuchObject", "ad_search_base_not_found"),
        ("ldap_search_failed:insufficientAccessRights", "ad_search_denied"),
        ("connector_job_failed", "ad_unavailable"),
    ],
)
def test_sync_failures_get_their_own_reason(message: str, reason: str) -> None:
    assert classify_sync_failure(AdUnavailableError(message)) == reason
