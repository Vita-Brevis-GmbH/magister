"""Regression: provisioning must never orphan a freshly created AD account.

``_sync_create_user`` creates the account first, then applies best-effort
post-steps (the ``cannot_change_password`` DACL edit and the default-group
assignment). Those steps talk to real AD in ways the ldap3 mock never
exercises — in particular the security-descriptor parser was never run against
a real AD ``nTSecurityDescriptor``. If such a step raises an *unexpected*
exception type (not ``AdUnavailableError``/``LDAPException``), it must not
propagate: the AD object already exists, so failing the row would leave a
teacher in AD but never written to Magister — exactly the reported bulk-import
symptom. These tests pin the swallow-and-keep behaviour.
"""

from __future__ import annotations

from types import SimpleNamespace

from magister_api.ad.client import AdClient

_GUID = "abcdef01-2345-6789-abcd-ef0123456789"


def _client_with_fakes(dacl_exc: Exception | None, group_exc: Exception | None) -> AdClient:
    client = AdClient(SimpleNamespace(ad_use_mock=False))  # type: ignore[arg-type]

    class _FakeConn:
        def add(self, *_a: object, **_k: object) -> tuple[object, ...]:
            return (True, {"result": 0}, [], None)

        def modify(self, *_a: object, **_k: object) -> tuple[object, ...]:
            return (True, {"result": 0}, [], None)

    client._acquire_connection = lambda: (_FakeConn(), False)  # type: ignore[assignment,method-assign]
    client._read_object_guid = lambda _conn, _dn: _GUID  # type: ignore[assignment,method-assign]

    def _dacl(_dn: str, _value: bool) -> None:
        if dacl_exc is not None:
            raise dacl_exc

    def _groups(_dn: str, _groups: list[str]) -> list[str]:
        if group_exc is not None:
            raise group_exc
        return []

    client._sync_set_cannot_change_password = _dacl  # type: ignore[assignment,method-assign]
    client._sync_add_user_to_groups = _groups  # type: ignore[assignment,method-assign]
    return client


def _create(client: AdClient) -> str:
    return client._sync_create_user(
        "OU=Lehrpersonen,DC=schule,DC=local",
        "Erika Lehrer",
        "erika.lehrer",
        "erika.lehrer@schule.ch",
        "erika.lehrer@schule.ch",
        "Erika",
        "Lehrer",
        "Erika Lehrer",
        "S3cret-pw",
        True,  # force_change
        False,  # password_never_expires
        True,  # cannot_change_password → runs the DACL step
        ["CN=Lehrer,OU=Groups,DC=schule,DC=local"],  # group_dns → runs the group step
    )


def test_dacl_step_unexpected_error_does_not_orphan_account() -> None:
    # The SD parser trips on a real-AD descriptor with a ValueError (not an
    # LDAPException) — the account must still be returned, not the exception.
    client = _client_with_fakes(dacl_exc=ValueError("unexpected SD layout"), group_exc=None)
    assert _create(client) == _GUID


def test_group_step_unexpected_error_does_not_orphan_account() -> None:
    client = _client_with_fakes(dacl_exc=None, group_exc=RuntimeError("group bind hiccup"))
    assert _create(client) == _GUID
