"""Internal AD-RPC server — the AD container's only inbound directory surface.

Mounted (from :func:`magister_api.main.create_app`) ONLY in an AD-capable
process — the monolith or the dedicated ``ad`` container, i.e. when
``MAGISTER_AD_RPC_URL`` is unset. Sibling containers reach it directly on the
docker network at ``<RPC_PATH>/<method>``; it is never behind the Caddy
``/api/*`` route, so it is not externally reachable. Access requires the shared
secret (``MAGISTER_AD_RPC_SECRET``); the recurring sync/search methods are not
dispatchable (they run in-process here, not over RPC).

Business logic + audit stay in the CALLING container: this endpoint performs
only the raw AD I/O and re-serialises the same result / exception the direct
``AdClient`` would have produced.
"""

from __future__ import annotations

import secrets
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.responses import JSONResponse

from magister_api.ad.client import AdClient, AdUserRecord
from magister_api.ad.errors import AdUnavailableError, AdUserParseError
from magister_api.ad.rpc import (
    ALLOWED_METHODS,
    RPC_PATH,
    SECRET_HEADER,
    ad_user_record_to_jsonable,
)
from magister_api.routers.admin_sync import get_ad_client

router = APIRouter(prefix=RPC_PATH, tags=["internal"])


def require_rpc_secret(request: Request) -> None:
    """Constant-time check of the shared secret. No secret configured → closed."""
    settings = request.app.state.settings
    configured = settings.ad_rpc_secret
    provided = request.headers.get(SECRET_HEADER)
    if (
        configured is None
        or not provided
        or not secrets.compare_digest(provided, configured.get_secret_value())
    ):
        raise HTTPException(status_code=403, detail="ad_rpc_forbidden")


def _serialize(result: Any) -> Any:
    if isinstance(result, AdUserRecord):
        return ad_user_record_to_jsonable(result)
    if isinstance(result, tuple):
        return list(result)
    return result


@router.post("/{method}")
async def dispatch(
    method: str,
    body: dict[str, Any],
    _secret: None = Depends(require_rpc_secret),
    ad: AdClient = Depends(get_ad_client),
) -> Any:
    if method not in ALLOWED_METHODS:
        raise HTTPException(status_code=404, detail="unknown_method")
    fn = getattr(ad, method)
    try:
        result = await fn(**body)
    except (AdUnavailableError, AdUserParseError) as exc:
        # Re-serialise so the RPC client can re-raise the same exception type.
        return JSONResponse(
            status_code=502,
            content={"error_type": type(exc).__name__, "detail": str(exc)},
        )
    except TypeError as exc:
        # Wrong/extra kwargs for the target method — a caller/version mismatch.
        raise HTTPException(status_code=422, detail="bad_rpc_args") from exc
    return {"result": _serialize(result)}


__all__ = ["router"]
