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

from magister_api.ad.errors import AdUnavailableError, AdUserParseError
from magister_api.ad.remote_base import RemoteAdClient
from magister_api.ad.rpc import (
    RPC_PATH,
    SECRET_HEADER,
)
from magister_api.config import Settings

# AD writes chain several LDAP round-trips (create_user especially); keep the
# internal hop generous so a slow directory does not look like an RPC failure.
_TIMEOUT = httpx.Timeout(30.0, connect=5.0)

_ERROR_TYPES: dict[str, type[Exception]] = {
    "AdUnavailableError": AdUnavailableError,
    "AdUserParseError": AdUserParseError,
}


class AdRpcClient(RemoteAdClient):
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

    async def _call(self, method: str, payload: dict[str, Any]) -> Any:
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


__all__ = ["AdRpcClient"]
