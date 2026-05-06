"""AD-specific error types."""

from __future__ import annotations


class AdUnavailableError(RuntimeError):
    """All DCs in the ServerPool are exhausted or unreachable.

    The router translates this to ``503 ad_unavailable`` and the frontend
    surfaces the i18n banner "AD nicht erreichbar — Daten sind X Minuten alt".
    """


class AdUserParseError(ValueError):
    """An LDAP entry could not be parsed into an :class:`AdUserRecord`."""
