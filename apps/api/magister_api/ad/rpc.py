"""Wire format for the internal AD-RPC boundary (ADR-0011).

The AD-owning container exposes :mod:`magister_api.routers.ad_rpc`; every other
container reaches AD only through :class:`magister_api.ad.rpc_client.AdRpcClient`.
Both sides share these (de)serializers and constants so the transport stays in
lockstep. Nothing here logs credentials — passwords ride inside request bodies,
never in log lines, and the shared secret only ever appears in a header.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime
from typing import Any

from magister_api.ad.client import AdUserRecord

# Internal-only mount path. NOT under any module's Caddy-routed prefix (``/ad``),
# so it is unreachable from outside the docker network; sibling containers call
# it directly (``http://magister-api-ad:8000<PATH>/<method>``).
RPC_PATH = "/internal/ad-rpc"

# Name of the header carrying the shared secret (not the secret itself).
SECRET_HEADER = "x-ad-rpc-secret"  # noqa: S105 — header name, not a credential

# The exact AdClient surface reachable over RPC. The recurring sync/search
# methods are deliberately absent — they run only in the AD container.
ALLOWED_METHODS: frozenset[str] = frozenset(
    {
        "find_user_dn",
        "fetch_user_groups",
        "probe_service_connection",
        "probe_service_connection_detailed",
        "probe_bind_as_user",
        "authenticate",
        "modify_password",
        "modify_user_attributes",
        "rename_user",
        "set_proxy_addresses",
        "set_account_enabled",
        "set_password_never_expires",
        "set_cannot_change_password",
        "delete_user_object",
        "add_user_to_groups",
        "remove_user_from_groups",
        "create_user",
    }
)


def ad_user_record_to_jsonable(rec: AdUserRecord) -> dict[str, Any]:
    """Flatten an :class:`AdUserRecord` to JSON-safe primitives."""
    data = dataclasses.asdict(rec)
    data["when_changed"] = rec.when_changed.isoformat() if rec.when_changed else None
    data["groups"] = list(rec.groups)
    data["mail_aliases"] = list(rec.mail_aliases)
    return data


def ad_user_record_from_jsonable(data: dict[str, Any]) -> AdUserRecord:
    """Rebuild an :class:`AdUserRecord` from :func:`ad_user_record_to_jsonable`."""
    fields = dict(data)
    when = fields.get("when_changed")
    fields["when_changed"] = datetime.fromisoformat(when) if when else None
    fields["groups"] = tuple(fields.get("groups") or ())
    fields["mail_aliases"] = tuple(fields.get("mail_aliases") or ())
    return AdUserRecord(**fields)
