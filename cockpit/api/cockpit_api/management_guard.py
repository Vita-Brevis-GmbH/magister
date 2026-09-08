"""Only reachable through the management listener (ADR-0015 D1).

The console can mint sessions into every customer, so it must not be reachable
from the internet. Three things carry that, in this order:

1. The listener is published only on the management address — a compose port
   mapping like ``10.0.0.5:4444:4444``, never ``0.0.0.0``. This is the actual
   boundary: what is not routed cannot be reached.
2. The listener requires a client certificate from the platform CA, so even a
   reachable port yields no TLS handshake without an operator certificate.
3. This module: the application refuses any request that did not arrive
   through that listener, so a reverse-proxy misconfiguration cannot expose the
   console by accident.

Layer 3 cannot verify layers 1 and 2 — inside its container the app binds
``0.0.0.0`` and sees no TLS. What it *can* do is insist on a marker that only
the management site block sets, and refuse to start when the configuration says
the listener is public. Both are checks on a declaration, and that is stated
plainly rather than dressed up as verification.

A request without the marker gets **404**, not 403: someone probing the public
origin should not learn that a console lives behind it.

Since ADR-0014 there is a **second** listener on the same application: the
connector channel on TCP 46200, which is deliberately public because the
agent calls in from the customer's network. It gets its own marker, and the
two are not interchangeable:

- management marker on ``/connector/*``  -> 404
- connector marker on ``/api/*``         -> 404

That is not paranoia about a stolen marker; it is what keeps the console's
property intact. Without the split, exempting the connector paths would mean
"reachable without any marker", and then a single mis-routed site block would
put the console's own paths one guess away.
"""

from __future__ import annotations

import logging
import secrets
from collections.abc import Awaitable, Callable

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)

#: Header the management site block sets and nothing else does. Named like an
#: ordinary proxy header on purpose — it carries no meaning without the value.
MARKER_HEADER = "x-magister-management"

#: Header the connector site block sets (TCP 46200, ADR-0014).
CONNECTOR_MARKER_HEADER = "x-magister-connector"

#: Paths that belong to the connector channel. Everything below this prefix
#: needs the connector marker and refuses the management one.
CONNECTOR_PREFIX = "/connector/"

#: Paths reachable without the marker. Only the container health probe, which
#: returns ``{"status": "ok"}`` and nothing else — same reasoning as Magister's
#: public ``/healthz``.
EXEMPT_PATHS: frozenset[str] = frozenset({"/api/health"})


class ManagementListenerRequiredError(RuntimeError):
    """Raised at startup when the guard is on but cannot possibly work."""


def check_configuration(
    *, required: bool, marker: str, published_address: str, connector_marker: str = ""
) -> None:
    """Refuse to start on a configuration that would silently expose the console.

    Two failure modes, both fatal:

    - the guard is required but no marker is configured — it would either be a
      no-op or lock every operator out, depending on which side is missing;
    - the published address is a wildcard, i.e. the operator is about to serve
      the console on every interface.

    The address is a *declaration*: the process cannot see the host's port
    mapping. This catches the common mistake (leaving the default in place),
    not a determined misconfiguration.
    """
    if required and not marker.strip():
        raise ManagementListenerRequiredError(
            "COCKPIT_REQUIRE_MANAGEMENT_LISTENER is on but "
            "COCKPIT_MANAGEMENT_MARKER is empty — the console would be "
            "unreachable for everyone. Set the same value here and in the "
            "management site block of the reverse proxy."
        )
    if required and connector_marker and marker.strip() == connector_marker.strip():
        # Gleiche Werte hebt die Trennung der beiden Listener auf: dann wäre
        # der Management-Marker auf dem Connector-Kanal gültig und umgekehrt.
        raise ManagementListenerRequiredError(
            "COCKPIT_MANAGEMENT_MARKER und COCKPIT_CONNECTOR_MARKER sind gleich. "
            "Damit gilt jeder Marker auf beiden Listenern und die Trennung "
            "zwischen Konsole (4444) und Connector (46200) existiert nicht mehr. "
            "Zwei verschiedene Werte setzen: openssl rand -hex 32."
        )
    host = published_address.strip().rsplit(":", 1)[0].strip("[]")
    if host in {"0.0.0.0", "::", "*", ""}:  # noqa: S104 — comparing against, not binding to
        raise ManagementListenerRequiredError(
            f"COCKPIT_PUBLISHED_ADDRESS={published_address!r} would serve the console "
            "on every interface. It must be the management address, e.g. "
            "10.0.0.5:4444 — see docs/runbooks/console-listener.md."
        )


def _matches(provided: str, marker: str) -> bool:
    """Constant-time marker comparison that survives any header bytes."""
    return secrets.compare_digest(
        provided.encode("latin-1", "replace"), marker.encode("latin-1", "replace")
    )


def make_management_guard(
    read_config: Callable[[], tuple[bool, str]],
    read_connector_marker: Callable[[], str] = lambda: "",
) -> Callable[[Request, Callable[[Request], Awaitable[Response]]], Awaitable[Response]]:
    """Build the middleware.

    ``read_config`` is called per request and returns ``(required, marker)``, so
    the guard follows a settings change without rebuilding the app — and so a
    test can flip it without re-importing the module. ``read_connector_marker``
    does the same for the connector channel.
    """

    async def guard(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        required, marker = read_config()
        path = request.url.path
        if not required or path in EXEMPT_PATHS:
            return await call_next(request)

        if path.startswith(CONNECTOR_PREFIX):
            # Der Connector-Kanal, nicht die Konsole: eigener Marker, und der
            # Management-Marker gilt hier ausdrücklich NICHT. Der Kanal ist
            # absichtlich öffentlich — geschützt wird er durch Client-Zertifikat
            # und API-Key, nicht durch die Bindung des Listeners.
            connector_marker = read_connector_marker()
            offered = request.headers.get(CONNECTOR_MARKER_HEADER)
            if offered is not None and connector_marker and _matches(offered, connector_marker):
                return await call_next(request)
            logger.warning(
                "Refused a request to %s: it did not arrive through the connector "
                "listener (marker %s missing or wrong).",
                path,
                CONNECTOR_MARKER_HEADER,
            )
            return JSONResponse(status_code=404, content={"detail": "not_found"})

        # Compared as bytes, not as str: Starlette decodes header values as
        # latin-1, so a raw high byte arrives as a non-ASCII character — and
        # ``compare_digest`` raises TypeError on those. That would turn a probe
        # with one odd byte into a 500 and tell the prober something is there.
        provided = request.headers.get(MARKER_HEADER)
        if provided is not None and marker and _matches(provided, marker):
            return await call_next(request)

        # WARNING, with the path: an operator debugging "why do I get 404"
        # needs to find the reason in the logs, since the response says nothing.
        logger.warning(
            "Refused a request to %s: it did not arrive through the management "
            "listener (marker %s missing or wrong). If this was a legitimate "
            "operator, the reverse proxy is not routing through the management "
            "site block.",
            path,
            MARKER_HEADER,
        )
        return JSONResponse(status_code=404, content={"detail": "not_found"})

    return guard


__all__ = [
    "CONNECTOR_MARKER_HEADER",
    "CONNECTOR_PREFIX",
    "EXEMPT_PATHS",
    "MARKER_HEADER",
    "ManagementListenerRequiredError",
    "check_configuration",
    "make_management_guard",
]
