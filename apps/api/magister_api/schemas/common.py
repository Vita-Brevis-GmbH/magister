"""Shared validators for system-boundary types (UPN, AD objectGUID).

Per CLAUDE.md "Immer"-Regel: validate UPN and objectGUID at the system boundary.
"""

from __future__ import annotations

import re
from typing import Annotated

from pydantic import AfterValidator

# UPN per RFC 5321/RFC 822 (simplified): user@domain, no whitespace, includes a dot in domain.
_UPN_RE = re.compile(r"^[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9.\-]{1,253}\.[A-Za-z]{2,63}$")
# Lower-case canonical 8-4-4-4-12 hex form.
_GUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def validate_upn(value: str) -> str:
    v = value.strip().lower()
    if not _UPN_RE.match(v):
        raise ValueError(f"invalid UPN: {value!r}")
    if len(v) > 320:
        raise ValueError("UPN exceeds 320 characters")
    return v


def validate_object_guid(value: str) -> str:
    v = value.strip().lower()
    # Strip braces if present, e.g. "{...}".
    if v.startswith("{") and v.endswith("}"):
        v = v[1:-1]
    if not _GUID_RE.match(v):
        raise ValueError(f"invalid AD objectGUID: {value!r}")
    return v


Upn = Annotated[str, AfterValidator(validate_upn)]
ObjectGuid = Annotated[str, AfterValidator(validate_object_guid)]
