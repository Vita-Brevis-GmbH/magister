"""Audit-context middleware.

Attaches a per-request id and client-IP to ``request.state`` so service-layer
``audit.emit(...)`` calls can pick them up. The actual emission stays inside
the service that performs the mutation — that's the only place that knows
both the action semantics and the exact transactional boundary.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

REQUEST_ID_HEADER = "X-Request-ID"


class AuditContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex
        client_ip = (
            (request.client.host if request.client else None)
            or request.headers.get("x-forwarded-for", "").split(",")[0].strip()
            or None
        )
        request.state.request_id = request_id
        request.state.client_ip = client_ip
        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response
