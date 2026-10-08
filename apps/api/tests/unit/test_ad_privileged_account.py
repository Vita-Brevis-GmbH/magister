"""``is_privileged_account``: the agent on the DC refuses changes to such accounts.

``adminCount=1`` (AdminSDHolder) and ``isCriticalSystemObject`` mark accounts
the platform must never touch. The check fails closed: an LDAP error raises
instead of answering "not privileged".
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from magister_api.ad.client import AdClient
from magister_api.ad.errors import AdUnavailableError

DN = "CN=Admin,OU=IT,DC=schule,DC=local"


def _client(result: dict[str, Any], entries: list[dict[str, Any]]) -> AdClient:
    client = AdClient(SimpleNamespace(ad_use_mock=False))  # type: ignore[arg-type]

    class _Conn:
        def unbind(self) -> None:
            return None

    client._acquire_connection = lambda: (_Conn(), False)  # type: ignore[assignment,method-assign]
    client._single_search = (  # type: ignore[assignment,method-assign]
        lambda _conn, **_kw: (result, entries)
    )
    return client


@pytest.mark.parametrize(
    "attrs",
    [{"adminCount": [1]}, {"adminCount": "1"}, {"isCriticalSystemObject": ["TRUE"]}],
)
def test_privileged_accounts_are_recognised(attrs: dict[str, Any]) -> None:
    client = _client({"result": 0}, [{"dn": DN, "attributes": attrs}])
    assert client._sync_is_privileged_account(DN) is True


@pytest.mark.parametrize("attrs", [{}, {"adminCount": [0]}, {"adminCount": []}])
def test_ordinary_accounts_are_not(attrs: dict[str, Any]) -> None:
    client = _client({"result": 0}, [{"dn": DN, "attributes": attrs}])
    assert client._sync_is_privileged_account(DN) is False


def test_a_failed_read_fails_closed() -> None:
    client = _client({"result": 50, "description": "insufficientAccessRights"}, [])
    with pytest.raises(AdUnavailableError):
        client._sync_is_privileged_account(DN)
