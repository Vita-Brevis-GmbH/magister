"""AD client that reaches Active Directory through the AD container's RPC.

A drop-in for :class:`AdClient` used by every container that is NOT the
AD owner (ADR-0011): it holds no directory credentials, only the RPC base URL +
shared secret, and forwards each supported call over internal HTTP. Because it
subclasses ``AdClient`` the ~22 ``Depends(get_ad_client)`` call-sites keep their
``AdClient`` annotation unchanged; only the reachable methods are overridden.
The recurring sync/search methods are intentionally NOT overridden — they never
run in a non-AD container, and inheriting them means a stray call fails loudly
rather than silently hitting an unconfigured directory.
"""

from __future__ import annotations

from typing import Any

import httpx

from magister_api.ad.client import AdClient, AdUserRecord
from magister_api.ad.errors import AdUnavailableError, AdUserParseError
from magister_api.ad.rpc import (
    RPC_PATH,
    SECRET_HEADER,
    ad_user_record_from_jsonable,
)
from magister_api.config import Settings

# AD writes chain several LDAP round-trips (create_user especially); keep the
# internal hop generous so a slow directory does not look like an RPC failure.
_TIMEOUT = httpx.Timeout(30.0, connect=5.0)

_ERROR_TYPES: dict[str, type[Exception]] = {
    "AdUnavailableError": AdUnavailableError,
    "AdUserParseError": AdUserParseError,
}


class AdRpcClient(AdClient):
    def __init__(
        self,
        settings: Settings,
        *,
        base_url: str,
        secret: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(settings)
        self._base_url = base_url.rstrip("/")
        self._secret = secret
        # One reused connection pool; `transport` is an injection seam for tests.
        self._http = httpx.AsyncClient(timeout=_TIMEOUT, transport=transport)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _rpc(self, method: str, payload: dict[str, Any]) -> Any:
        url = f"{self._base_url}{RPC_PATH}/{method}"
        try:
            resp = await self._http.post(url, json=payload, headers={SECRET_HEADER: self._secret})
        except httpx.HTTPError as exc:
            # Network/timeout to the AD container is an AD outage from the caller's
            # point of view — same class the direct client raises.
            raise AdUnavailableError("ad_rpc_unreachable") from exc
        if resp.status_code == 200:
            return resp.json().get("result")
        # Structured error from the server → re-raise the original exception type.
        detail = "ad_rpc_failed"
        err_type = "AdUnavailableError"
        try:
            body = resp.json()
            detail = str(body.get("detail") or detail)
            err_type = str(body.get("error_type") or err_type)
        except (ValueError, httpx.HTTPError):
            pass
        raise _ERROR_TYPES.get(err_type, AdUnavailableError)(detail)

    # --- reads ---------------------------------------------------------------

    async def find_user_dn(self, ad_object_guid: str) -> str | None:
        return await self._rpc("find_user_dn", {"ad_object_guid": ad_object_guid})

    async def fetch_user_groups(self, ad_object_guid: str) -> list[str] | None:
        return await self._rpc("fetch_user_groups", {"ad_object_guid": ad_object_guid})

    async def probe_service_connection(self) -> bool:
        return bool(await self._rpc("probe_service_connection", {}))

    async def probe_service_connection_detailed(self) -> tuple[bool, str]:
        ok, reason = await self._rpc("probe_service_connection_detailed", {})
        return bool(ok), str(reason)

    async def probe_bind_as_user(self, *, user_dn: str, password: str) -> bool:
        return bool(
            await self._rpc("probe_bind_as_user", {"user_dn": user_dn, "password": password})
        )

    async def authenticate(self, *, login: str, password: str) -> AdUserRecord | None:
        result = await self._rpc("authenticate", {"login": login, "password": password})
        return ad_user_record_from_jsonable(result) if result else None

    # --- writes --------------------------------------------------------------

    async def modify_password(self, *, user_dn: str, new_password: str, force_change: bool) -> None:
        await self._rpc(
            "modify_password",
            {"user_dn": user_dn, "new_password": new_password, "force_change": force_change},
        )

    async def modify_user_attributes(
        self, *, user_dn: str, attributes: dict[str, str | None]
    ) -> None:
        await self._rpc("modify_user_attributes", {"user_dn": user_dn, "attributes": attributes})

    async def rename_user(self, *, user_dn: str, new_common_name: str) -> str:
        return await self._rpc(
            "rename_user", {"user_dn": user_dn, "new_common_name": new_common_name}
        )

    async def set_proxy_addresses(
        self, *, user_dn: str, primary: str | None, aliases: list[str]
    ) -> None:
        await self._rpc(
            "set_proxy_addresses",
            {"user_dn": user_dn, "primary": primary, "aliases": aliases},
        )

    async def set_account_enabled(self, *, user_dn: str, enabled: bool) -> tuple[bool, bool]:
        changed, now_enabled = await self._rpc(
            "set_account_enabled", {"user_dn": user_dn, "enabled": enabled}
        )
        return bool(changed), bool(now_enabled)

    async def set_password_never_expires(self, *, user_dn: str, value: bool) -> None:
        await self._rpc("set_password_never_expires", {"user_dn": user_dn, "value": value})

    async def set_cannot_change_password(self, *, user_dn: str, value: bool) -> None:
        await self._rpc("set_cannot_change_password", {"user_dn": user_dn, "value": value})

    async def delete_user_object(self, *, user_dn: str) -> None:
        await self._rpc("delete_user_object", {"user_dn": user_dn})

    async def add_user_to_groups(self, *, user_dn: str, group_dns: list[str]) -> list[str]:
        return await self._rpc("add_user_to_groups", {"user_dn": user_dn, "group_dns": group_dns})

    async def remove_user_from_groups(self, *, user_dn: str, group_dns: list[str]) -> list[str]:
        return await self._rpc(
            "remove_user_from_groups", {"user_dn": user_dn, "group_dns": group_dns}
        )

    async def create_user(
        self,
        *,
        ou_dn: str,
        common_name: str,
        sam_account_name: str,
        user_principal_name: str,
        mail: str | None,
        given_name: str,
        surname: str,
        display_name: str,
        password: str,
        force_change: bool,
        password_never_expires: bool = False,
        cannot_change_password: bool = False,
        group_dns: list[str] | None = None,
    ) -> str:
        return await self._rpc(
            "create_user",
            {
                "ou_dn": ou_dn,
                "common_name": common_name,
                "sam_account_name": sam_account_name,
                "user_principal_name": user_principal_name,
                "mail": mail,
                "given_name": given_name,
                "surname": surname,
                "display_name": display_name,
                "password": password,
                "force_change": force_change,
                "password_never_expires": password_never_expires,
                "cannot_change_password": cannot_change_password,
                "group_dns": list(group_dns or []),
            },
        )


__all__ = ["AdRpcClient"]
