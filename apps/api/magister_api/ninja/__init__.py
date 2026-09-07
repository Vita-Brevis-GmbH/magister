"""NinjaOne RMM connector (read device data + run library scripts).

This package is the ONLY place that talks to the NinjaOne Public API. The
credentials (client_id/secret) live encrypted in ``app_settings`` and never
leave the server or reach a log line; the HTTP layer mirrors the ``AdRpcClient``
pattern (one reused ``httpx.AsyncClient`` + a ``transport`` injection seam for
tests).
"""

from __future__ import annotations

from magister_api.ninja.client import (
    NINJA_REGIONS,
    NinjaApiError,
    NinjaAuthError,
    NinjaClient,
    NinjaConfig,
    NinjaError,
    NinjaNotConfiguredError,
)
from magister_api.ninja.match import MatchResult, match_device, ninja_hostnames, ninja_serial

__all__ = [
    "NINJA_REGIONS",
    "MatchResult",
    "NinjaApiError",
    "NinjaAuthError",
    "NinjaClient",
    "NinjaConfig",
    "NinjaError",
    "NinjaNotConfiguredError",
    "match_device",
    "ninja_hostnames",
    "ninja_serial",
]
