"""AD-specific error types."""

from __future__ import annotations

from ldap3.core.exceptions import (
    LDAPBindError,
    LDAPCertificateError,
    LDAPException,
    LDAPInvalidCredentialsResult,
    LDAPSocketOpenError,
    LDAPSocketReceiveError,
    LDAPSSLConfigurationError,
    LDAPStartTLSError,
)


class AdUnavailableError(RuntimeError):
    """All DCs in the ServerPool are exhausted or unreachable.

    The router translates this to ``503 ad_unavailable`` and the frontend
    surfaces the i18n banner "AD nicht erreichbar — Daten sind X Minuten alt".
    """


class AdUserParseError(ValueError):
    """An LDAP entry could not be parsed into an :class:`AdUserRecord`."""


# Reason codes for a *sync* failure. The bind may succeed (the connection test
# is green) yet the sync still fail because it additionally searches a subtree —
# so "AD unreachable" is misleading. These distinguish the real cause. They
# double as i18n keys on the frontend (``admin.settings.sync_ad_reason.*``).
SYNC_REASON_SEARCH_BASE_MISSING = "ad_search_base_missing"
SYNC_REASON_SEARCH_BASE_NOT_FOUND = "ad_search_base_not_found"
SYNC_REASON_SEARCH_DENIED = "ad_search_denied"
SYNC_REASON_SEARCH_FAILED = "ad_search_failed"
SYNC_REASON_BIND_FAILED = "ad_bind_failed"
SYNC_REASON_CONFIG = "ad_config"
SYNC_REASON_UNAVAILABLE = "ad_unavailable"


def classify_sync_failure(exc: AdUnavailableError) -> str:
    """Map an :class:`AdUnavailableError` from the sync path to a reason code.

    The codes are safe to return and log: they carry no host, DN, or credential
    material (only the internal marker strings the AD client raises, plus the
    LDAP result *description* which is a protocol constant like ``noSuchObject``).
    Search failures may carry a ``:<description>`` suffix (e.g.
    ``ldap_search_failed:noSuchObject``) which we mine for a finer reason.
    """
    msg = str(exc)
    if "SEARCH_BASE" in msg:
        return SYNC_REASON_SEARCH_BASE_MISSING
    if msg == "ldap_bind_failed":
        return SYNC_REASON_BIND_FAILED
    if msg.startswith("ldap_search_failed") or msg.startswith("ldap_computer_search_failed"):
        low = msg.lower()
        if "nosuchobject" in low:
            return SYNC_REASON_SEARCH_BASE_NOT_FOUND
        if "insufficientaccess" in low or "insufficient access" in low:
            return SYNC_REASON_SEARCH_DENIED
        return SYNC_REASON_SEARCH_FAILED
    if "MAGISTER_AD_DCS" in msg or "BIND_DN" in msg or "BIND_PASSWORD" in msg:
        return SYNC_REASON_CONFIG
    return SYNC_REASON_UNAVAILABLE


# --- Failure classification ----------------------------------------------------------
#
# The connection test needs to tell the operator *why* a bind failed without
# leaking anything the "Niemals" rules forbid: no credentials, no bind-DN, no
# raw exception text (which may echo the bind string). We therefore collapse the
# ldap3 exception zoo into a small set of stable, translatable reason codes. The
# codes double as i18n keys on the frontend (``admin.settings.test_ad_reason.*``).

REASON_CONFIG = "ad_config"
REASON_UNREACHABLE = "ad_unreachable"
REASON_TLS = "ad_tls"
REASON_TIMEOUT = "ad_timeout"
REASON_AUTH = "ad_auth"
REASON_GENERIC = "ad_bind_failed"

_TLS_MARKERS = ("ssl", "certificate", "cert_", "tls", "handshake", "verify failed")


def _looks_like_tls(exc: BaseException) -> bool:
    """True if ``exc`` or any exception in its cause chain is TLS/cert-related.

    ldap3 wraps an ``ssl.SSLError`` from a rejected DC certificate inside a
    generic :class:`LDAPSocketOpenError`, so pattern-matching the message /
    cause chain is the only reliable signal. We match on category words, never
    echo the text itself.
    """
    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        if isinstance(cur, (LDAPCertificateError, LDAPStartTLSError, LDAPSSLConfigurationError)):
            return True
        haystack = str(cur).lower()
        if any(marker in haystack for marker in _TLS_MARKERS):
            return True
        # ldap3 stows the per-server socket errors in ``.args`` as a list.
        for arg in getattr(cur, "args", ()):  # pragma: no branch - trivial
            if any(marker in str(arg).lower() for marker in _TLS_MARKERS):
                return True
        cur = cur.__cause__ or cur.__context__
    return False


def classify_ldap_error(exc: LDAPException) -> str:
    """Map an ldap3 exception to a safe, credential-free reason code.

    The returned code is safe to send to the client and to log (it carries no
    host, DN, or credential material). Order matters: a TLS failure surfaces as
    an ``LDAPSocketOpenError`` too, so we test for TLS markers before the plain
    "unreachable" bucket.
    """
    if _looks_like_tls(exc):
        return REASON_TLS
    if isinstance(exc, (LDAPInvalidCredentialsResult, LDAPBindError)):
        return REASON_AUTH
    if isinstance(exc, LDAPSocketReceiveError):
        return REASON_TIMEOUT
    if isinstance(exc, LDAPSocketOpenError):
        return REASON_UNREACHABLE
    return REASON_GENERIC
