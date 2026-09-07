"""NinjaOne Public API v2 client — OAuth2 client-credentials + device calls.

Scope of the calls we make:
- read: ``GET /v2/devices`` (list, paginated), ``GET /v2/device/{id}`` (detail);
- run:  ``POST /v2/device/{id}/script/run`` (execute a library script/automation).

Auth is the *client-credentials* grant (the "API Services / machine-to-machine"
app type in NinjaOne). The **Management** scope is required to run scripts; the
**Monitoring** scope is enough for the read calls. Tokens are cached in memory
until shortly before they expire.

Regions: NinjaOne is multi-instance; the base host differs per region and the
token + API share that host. A Swiss tenant is normally on ``eu``.

⚠️ VERIFY-AGAINST-TENANT — the two write-ish shapes below could differ by API
version and MUST be confirmed against the customer's instance before go-live:
``_RUN_SCRIPT_PATH`` and ``_run_script_body``. Everything else (token endpoint,
device list/detail) is stable across current NinjaOne docs. They are isolated
here so a correction is a one-line change, never a scavenger hunt.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx

# region code -> API/token host. Both the OAuth token and the REST calls use it.
NINJA_REGIONS: dict[str, str] = {
    "us": "app.ninjarmm.com",
    "us2": "us2.ninjarmm.com",
    "eu": "eu.ninjarmm.com",
    "ca": "ca.ninjarmm.com",
    "oc": "oc.ninjarmm.com",
}

_TOKEN_PATH = "/ws/oauth/token"  # noqa: S105 — URL path, not a secret
_DEVICES_PATH = "/v2/devices"
_DEVICE_PATH = "/v2/device/{id}"
# ⚠️ VERIFY-AGAINST-TENANT (see module docstring).
_RUN_SCRIPT_PATH = "/v2/device/{id}/script/run"
_SCRIPTS_PATH = "/v2/automation/scripts"

# Refresh the token this many seconds before its stated expiry to avoid racing
# the boundary on a slow request.
_EXPIRY_SKEW_S = 60.0
_TIMEOUT = httpx.Timeout(30.0, connect=5.0)
_PAGE_SIZE = 1000
_MAX_PAGES = 100  # hard safety stop for the device pagination loop


class NinjaError(Exception):
    """Base class for every NinjaOne connector failure."""


class NinjaNotConfiguredError(NinjaError):
    """The connector was asked to act but no/incomplete credentials are set."""


class NinjaAuthError(NinjaError):
    """OAuth token request was rejected (bad client_id/secret or scope)."""


class NinjaApiError(NinjaError):
    """A REST call returned a non-2xx status."""

    def __init__(self, message: str, *, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class NinjaConfig:
    """Everything needed to reach one NinjaOne tenant.

    ``client_secret`` is plaintext here on purpose — it is decrypted from
    ``app_settings`` immediately before constructing the client and never
    stored or logged.
    """

    region: str
    client_id: str
    client_secret: str
    # Monitoring alone suffices for reads; Management is required to run scripts.
    scopes: tuple[str, ...] = ("monitoring", "management")

    def is_complete(self) -> bool:
        return bool(self.region and self.client_id and self.client_secret)


@dataclass
class _Token:
    value: str
    # monotonic deadline after which the token must be refreshed.
    expires_at: float


class NinjaClient:
    """Thin async client over the NinjaOne Public API.

    One reused connection pool; ``transport`` is the test injection seam (an
    ``httpx.MockTransport``). Not thread-safe by design — used within a single
    request/task like the AD RPC client.
    """

    def __init__(
        self,
        config: NinjaConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not config.is_complete():
            raise NinjaNotConfiguredError("ninja_not_configured")
        host = NINJA_REGIONS.get(config.region)
        if host is None:
            raise NinjaError(f"unknown_ninja_region:{config.region}")
        self._config = config
        self._base_url = f"https://{host}"
        self._http = httpx.AsyncClient(timeout=_TIMEOUT, transport=transport)
        self._token: _Token | None = None

    async def aclose(self) -> None:
        await self._http.aclose()

    # ---------- auth ----------

    async def _fetch_token(self) -> _Token:
        try:
            resp = await self._http.post(
                f"{self._base_url}{_TOKEN_PATH}",
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._config.client_id,
                    "client_secret": self._config.client_secret,
                    "scope": " ".join(self._config.scopes),
                },
                headers={"Accept": "application/json"},
            )
        except httpx.HTTPError as exc:
            raise NinjaError("ninja_unreachable") from exc
        if resp.status_code != 200:
            # Never echo the body — it can contain the client_id.
            raise NinjaAuthError(f"ninja_token_rejected:{resp.status_code}")
        body: dict[str, Any] = resp.json()
        access = body.get("access_token")
        if not isinstance(access, str) or not access:
            raise NinjaAuthError("ninja_token_missing")
        expires_in = float(body.get("expires_in", 3600))
        return _Token(value=access, expires_at=time.monotonic() + expires_in - _EXPIRY_SKEW_S)

    async def _auth_header(self, *, force_refresh: bool = False) -> dict[str, str]:
        if force_refresh or self._token is None or time.monotonic() >= self._token.expires_at:
            self._token = await self._fetch_token()
        return {"Authorization": f"Bearer {self._token.value}"}

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any | None = None,
    ) -> httpx.Response:
        headers = {"Accept": "application/json", **await self._auth_header()}
        url = f"{self._base_url}{path}"
        try:
            resp = await self._http.request(method, url, params=params, json=json, headers=headers)
            if resp.status_code == 401:
                # Token may have been revoked/expired early — refresh once.
                headers = {
                    "Accept": "application/json",
                    **await self._auth_header(force_refresh=True),
                }
                resp = await self._http.request(
                    method, url, params=params, json=json, headers=headers
                )
        except httpx.HTTPError as exc:
            raise NinjaError("ninja_unreachable") from exc
        if resp.status_code >= 400:
            raise NinjaApiError(f"ninja_api_error:{resp.status_code}", status_code=resp.status_code)
        return resp

    # ---------- devices (read) ----------

    async def list_devices(self) -> list[dict[str, Any]]:
        """Every device in the tenant, following NinjaOne cursor pagination.

        ``GET /v2/devices`` returns a JSON array and pages via ``after`` (the id
        of the last device seen) + ``pageSize``. We stop on a short/empty page
        or the safety cap.
        """
        out: list[dict[str, Any]] = []
        after: int | None = None
        for _ in range(_MAX_PAGES):
            params: dict[str, Any] = {"pageSize": _PAGE_SIZE}
            if after is not None:
                params["after"] = after
            page = self._as_list(await self._request("GET", _DEVICES_PATH, params=params))
            if not page:
                break
            out.extend(page)
            if len(page) < _PAGE_SIZE:
                break
            last_id = page[-1].get("id")
            if not isinstance(last_id, int):
                break
            after = last_id
        return out

    async def get_device(self, ninja_device_id: int) -> dict[str, Any]:
        resp = await self._request("GET", _DEVICE_PATH.format(id=ninja_device_id))
        body: Any = resp.json()
        if not isinstance(body, dict):
            raise NinjaApiError("ninja_bad_device_payload", status_code=resp.status_code)
        return body

    # ---------- scripts ----------

    async def list_scripts(self) -> list[dict[str, Any]]:
        """The tenant's automation/script library (id + name) for the picker.

        ⚠️ VERIFY-AGAINST-TENANT: ``_SCRIPTS_PATH`` may be ``/v2/scripting/...``
        depending on API version. Callers should treat a failure here as "no
        picker" and fall back to a manual script-id input, never as fatal.
        """
        return self._as_list(await self._request("GET", _SCRIPTS_PATH))

    async def run_script(
        self,
        ninja_device_id: int,
        *,
        script_id: int,
        parameters: str | None = None,
        run_as: str | None = None,
    ) -> dict[str, Any]:
        """Trigger a NinjaOne *library* script on one device (Management scope).

        Runs a script that already exists in the tenant's automation library —
        this is not arbitrary code upload, which is NinjaOne's security model.
        Returns whatever the API hands back (a job/queue acknowledgement).
        """
        resp = await self._request(
            "POST",
            _RUN_SCRIPT_PATH.format(id=ninja_device_id),
            json=self._run_script_body(script_id=script_id, parameters=parameters, run_as=run_as),
        )
        try:
            body: Any = resp.json()
        except ValueError:
            return {}
        return body if isinstance(body, dict) else {"result": body}

    @staticmethod
    def _run_script_body(
        *, script_id: int, parameters: str | None, run_as: str | None
    ) -> dict[str, Any]:
        # ⚠️ VERIFY-AGAINST-TENANT (see module docstring): field names may be
        # ``id``/``uid`` and ``runAs``/``credentialId`` depending on API version.
        body: dict[str, Any] = {"type": "SCRIPT", "id": script_id}
        if parameters:
            body["parameters"] = parameters
        if run_as:
            body["runAs"] = run_as
        return body

    # ---------- helpers ----------

    @staticmethod
    def _as_list(resp: httpx.Response) -> list[dict[str, Any]]:
        body: Any = resp.json()
        if isinstance(body, list):
            return [d for d in body if isinstance(d, dict)]
        # Some deployments wrap the array — accept {"results": [...]} defensively.
        if isinstance(body, dict) and isinstance(body.get("results"), list):
            return [d for d in body["results"] if isinstance(d, dict)]
        return []
