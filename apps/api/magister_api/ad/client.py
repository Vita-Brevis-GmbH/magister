"""Async-friendly LDAP client.

CLAUDE.md "Niemals"-Regel: no synchronous LDAP in the async request path.
Every public coroutine on this module wraps the underlying ``ldap3`` calls
in :func:`fastapi.concurrency.run_in_threadpool`.

The client supports two backends:
- Production: ldap3 ``ServerPool`` (FIRST strategy, ``exhaust=10``) over LDAPS 636.
- Tests: ldap3 ``MOCK_SYNC`` strategy with seedable entries (see :mod:`tests`).
"""

from __future__ import annotations

import struct
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from fastapi.concurrency import run_in_threadpool
from ldap3 import (
    ALL_ATTRIBUTES,
    BASE,
    FIRST,
    MOCK_SYNC,
    MODIFY_REPLACE,
    SAFE_SYNC,
    SIMPLE,
    SUBTREE,
    Connection,
    Server,
    ServerPool,
    Tls,
)
from ldap3.core.exceptions import LDAPException

from magister_api.ad.errors import AdUnavailableError, AdUserParseError
from magister_api.config import Settings

# AD `userAccountControl` bit 2 = ACCOUNTDISABLE (account disabled when bit set).
UAC_ACCOUNTDISABLE = 0x0002

DEFAULT_USER_ATTRIBUTES: tuple[str, ...] = (
    "objectGUID",
    "userPrincipalName",
    "givenName",
    "sn",
    "mail",
    "userAccountControl",
    "objectClass",
    "memberOf",
    "mS-DS-ConsistencyGuid",
    "distinguishedName",
)


@dataclass(frozen=True)
class AdUserRecord:
    """Parsed AD-user row, ready to upsert into ``ad_user_cache``."""

    ad_object_guid: str
    upn: str
    given_name: str | None
    surname: str | None
    mail: str | None
    enabled: bool
    kind: str
    ms_ds_consistency_guid: str | None
    distinguished_name: str

    def matches_school_via_ou(self, scope_short: str) -> bool:
        """Heuristic: ``scope_short`` appears as an OU component in the DN."""
        needle = f"OU={scope_short.upper()}"
        return needle in self.distinguished_name.upper()


def _decode_object_guid(raw: Any) -> str:
    """Convert an AD ``objectGUID`` blob to lowercase 8-4-4-4-12.

    Accepts either a canonical UUID string or the raw 16-byte LE blob.
    AD returns objectGUID as a 16-byte little-endian struct: 4-2-2 are
    little-endian, the last 8 bytes are big-endian (per DCE/MS-ADTS).

    ldap3 sometimes wraps raw binary attributes as latin-1 strings (one char
    per byte). We try canonical UUID parsing first; on failure, if the string
    is exactly 16 bytes we re-interpret it as the raw LE blob.
    """
    if isinstance(raw, uuid.UUID):
        return str(raw).lower()
    if isinstance(raw, str):
        try:
            return str(uuid.UUID(raw)).lower()
        except ValueError:
            pass
        # Fall back: ldap3 may pass the raw 16-byte blob as a latin-1 string.
        encoded = raw.encode("latin-1")
        if len(encoded) == 16:
            return _decode_object_guid(encoded)
        raise AdUserParseError(f"unparseable objectGUID string: {raw!r}")
    if isinstance(raw, (bytes, bytearray, memoryview)):
        b = bytes(raw)
        if len(b) != 16:
            raise AdUserParseError(f"objectGUID must be 16 bytes, got {len(b)}")
        d1, d2, d3 = struct.unpack("<IHH", b[:8])
        d4 = b[8:10]
        d5 = b[10:16]
        return f"{d1:08x}-{d2:04x}-{d3:04x}-{d4.hex()}-{d5.hex()}"
    raise AdUserParseError(f"unsupported objectGUID type: {type(raw).__name__}")


def _first_value(attr: Any) -> Any:
    if attr is None:
        return None
    if isinstance(attr, list):
        return attr[0] if attr else None
    return attr


def _kind_from_member_of(member_of: Iterable[str] | None) -> str:
    """Heuristic mapping. Refine via OU/group convention in #3.1.

    - Member of `*Teachers*` group → 'teacher'
    - Member of `*Admins*`        → 'admin'
    - else                          → 'student'
    """
    if not member_of:
        return "student"
    upper_members = [m.upper() for m in member_of]
    if any("ADMIN" in m for m in upper_members):
        return "admin"
    if any("TEACHER" in m or "LEHRER" in m for m in upper_members):
        return "teacher"
    return "student"


def parse_ad_entry(entry_attrs: dict[str, Any], dn: str) -> AdUserRecord:
    """Parse one ldap3 search result into an :class:`AdUserRecord`."""
    upn = _first_value(entry_attrs.get("userPrincipalName"))
    if not upn:
        raise AdUserParseError(f"entry {dn!r} has no userPrincipalName")
    object_guid_raw = _first_value(entry_attrs.get("objectGUID"))
    if object_guid_raw is None:
        raise AdUserParseError(f"entry {dn!r} has no objectGUID")
    uac_raw = _first_value(entry_attrs.get("userAccountControl")) or 0
    try:
        uac = int(uac_raw)
    except (TypeError, ValueError):
        uac = 0
    member_of = entry_attrs.get("memberOf") or []
    if isinstance(member_of, str):
        member_of = [member_of]
    consistency_guid_raw = _first_value(entry_attrs.get("mS-DS-ConsistencyGuid"))
    consistency_guid: str | None
    if isinstance(consistency_guid_raw, (bytes, bytearray, memoryview)):
        try:
            consistency_guid = _decode_object_guid(consistency_guid_raw)
        except AdUserParseError:
            consistency_guid = None
    elif isinstance(consistency_guid_raw, str) and consistency_guid_raw:
        consistency_guid = consistency_guid_raw.lower()
    else:
        consistency_guid = None
    return AdUserRecord(
        ad_object_guid=_decode_object_guid(object_guid_raw),
        upn=str(upn).strip().lower(),
        given_name=_first_value(entry_attrs.get("givenName")),
        surname=_first_value(entry_attrs.get("sn")),
        mail=_first_value(entry_attrs.get("mail")),
        enabled=bool(uac & UAC_ACCOUNTDISABLE) is False,
        kind=_kind_from_member_of(member_of),
        ms_ds_consistency_guid=consistency_guid,
        distinguished_name=dn,
    )


# --- Pool / Connection construction --------------------------------------------------


def _make_pool(settings: Settings) -> ServerPool:
    if not settings.ad_dcs:
        raise AdUnavailableError("MAGISTER_AD_DCS is empty")
    tls = Tls(validate=2)  # ssl.CERT_REQUIRED — strict cert validation by default
    servers: list[Server] = [
        Server(host, port=636, use_ssl=True, get_info="NO_INFO", tls=tls)
        for host in settings.ad_dcs
    ]
    return ServerPool(servers, FIRST, active=True, exhaust=True)


def _open_connection(settings: Settings, *, mock: bool) -> Connection:
    """Return a (synchronous) ldap3 Connection. Caller closes via ``unbind()``."""
    if mock:
        # In mock mode we hand out a Connection that tests pre-populate via
        # ``connection.strategy.add_entry``. ldap3 requires a registered user
        # for bind() to succeed; register the svc user as a regular entry first.
        server = Server("ldap-mock.test", get_info="NO_INFO")
        conn = Connection(
            server,
            user="cn=svc,dc=test",
            password="svcpw",  # noqa: S106 — mock harness, no real cred
            client_strategy=MOCK_SYNC,
        )
        conn.strategy.add_entry(
            "cn=svc,dc=test",
            {"objectClass": ["user"], "userPassword": "svcpw"},
        )
        conn.bind()
        return conn
    pool = _make_pool(settings)
    if not settings.ad_bind_dn or not settings.ad_bind_password:
        raise AdUnavailableError("MAGISTER_AD_BIND_DN / _BIND_PASSWORD must be set")
    return Connection(
        pool,
        user=settings.ad_bind_dn,
        password=settings.ad_bind_password.get_secret_value(),
        authentication=SIMPLE,
        client_strategy=SAFE_SYNC,
        auto_bind=True,
        receive_timeout=10,
    )


# --- Async-friendly client -----------------------------------------------------------


class AdClient:
    """Async wrapper that off-loads each ldap3 call to a worker thread.

    In mock mode the client lazily creates a single persistent ``Connection`` so
    test code can seed entries (entries live on the strategy, not the server).
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._mock_conn: Connection | None = None

    async def search_users(
        self,
        *,
        search_base: str | None = None,
        attributes: Sequence[str] = DEFAULT_USER_ATTRIBUTES,
    ) -> list[AdUserRecord]:
        """Return all users below ``search_base``. Defaults to the configured base."""
        base = search_base or self._settings.ad_users_search_base
        if not base:
            raise AdUnavailableError("MAGISTER_AD_USERS_SEARCH_BASE is not configured")
        return await run_in_threadpool(self._sync_search, base, list(attributes))

    def _acquire_connection(self) -> tuple[Connection, bool]:
        """Return ``(connection, owned)``. ``owned=True`` means caller must unbind."""
        if self._settings.ad_use_mock:
            if self._mock_conn is None:
                self._mock_conn = _open_connection(self._settings, mock=True)
            return self._mock_conn, False
        try:
            return _open_connection(self._settings, mock=False), True
        except LDAPException as exc:
            raise AdUnavailableError("ldap_bind_failed") from exc

    def _sync_search(self, base: str, attributes: list[str]) -> list[AdUserRecord]:
        conn, owned = self._acquire_connection()
        try:
            ok = conn.search(
                search_base=base,
                search_filter="(objectClass=user)",
                search_scope=SUBTREE,
                attributes=attributes,
            )
            # ldap3 SAFE_SYNC returns a (status, result, response, request) tuple;
            # MOCK_SYNC returns a bool. Normalise.
            if isinstance(ok, tuple):
                ok = ok[0]
            if not ok:
                raise AdUnavailableError("ldap_search_failed")
            entries: list[AdUserRecord] = []
            for entry in conn.response or []:
                if entry.get("type") != "searchResEntry":
                    continue
                try:
                    entries.append(parse_ad_entry(entry.get("attributes", {}), entry.get("dn", "")))
                except AdUserParseError:
                    # Skip malformed rows — they are visible in the audit log.
                    continue
            return entries
        finally:
            if owned:
                try:
                    conn.unbind()
                except LDAPException:
                    pass

    async def find_user_dn(self, ad_object_guid: str) -> str | None:
        """Return the LDAP DN for a user identified by ``objectGUID``."""
        return await run_in_threadpool(self._sync_find_user_dn, ad_object_guid)

    def _sync_find_user_dn(self, ad_object_guid: str) -> str | None:
        conn, owned = self._acquire_connection()
        try:
            # AD octet-string filter requires the GUID expressed as \xx\xx... bytes.
            try:
                guid_bytes = uuid.UUID(ad_object_guid).bytes_le
            except ValueError:
                return None
            search_filter = "(objectGUID=" + "".join(f"\\{b:02x}" for b in guid_bytes) + ")"
            base = self._settings.ad_users_search_base or ""
            ok = conn.search(
                search_base=base,
                search_filter=search_filter,
                search_scope=SUBTREE,
                attributes=["distinguishedName"],
            )
            if isinstance(ok, tuple):
                ok = ok[0]
            if not ok:
                return None
            for entry in conn.response or []:
                if entry.get("type") != "searchResEntry":
                    continue
                return entry.get("dn") or None
            return None
        finally:
            if owned:
                try:
                    conn.unbind()
                except LDAPException:
                    pass

    async def modify_password(self, *, user_dn: str, new_password: str, force_change: bool) -> None:
        """Reset ``unicodePwd`` and (optionally) set ``pwdLastSet=0`` for forced change."""
        await run_in_threadpool(self._sync_modify_password, user_dn, new_password, force_change)

    def _sync_modify_password(self, user_dn: str, new_password: str, force_change: bool) -> None:
        # AD requires unicodePwd as quoted UTF-16-LE bytes.
        encoded = f'"{new_password}"'.encode("utf-16-le")
        changes: dict[str, list[tuple[str, list[bytes | str]]]] = {
            "unicodePwd": [(MODIFY_REPLACE, [encoded])],
        }
        if force_change:
            changes["pwdLastSet"] = [(MODIFY_REPLACE, ["0"])]

        conn, owned = self._acquire_connection()
        try:
            ok = conn.modify(user_dn, changes)
            if isinstance(ok, tuple):
                ok = ok[0]
            if not ok:
                raise AdUnavailableError("ldap_modify_failed")
        except LDAPException as exc:
            raise AdUnavailableError("ldap_modify_failed") from exc
        finally:
            if owned:
                try:
                    conn.unbind()
                except LDAPException:
                    pass

    async def probe_bind_as_user(self, *, user_dn: str, password: str) -> bool:
        """Try a SIMPLE bind as ``user_dn`` to validate the password against AD policy."""
        return await run_in_threadpool(self._sync_probe_bind, user_dn, password)

    def _sync_probe_bind(self, user_dn: str, password: str) -> bool:
        if self._settings.ad_use_mock:
            # In mock mode we don't actually check passwords; the policy gate
            # is exercised by the unit tests on ``passes_default_complexity``.
            return True
        try:
            conn = Connection(
                _make_pool(self._settings),
                user=user_dn,
                password=password,
                authentication=SIMPLE,
                client_strategy=SAFE_SYNC,
                auto_bind=True,
                receive_timeout=10,
            )
        except LDAPException:
            return False
        try:
            return True
        finally:
            try:
                conn.unbind()
            except LDAPException:
                pass

    # --- Test helpers --------------------------------------------------------

    def mock_connection(self) -> Connection:
        """Return the persistent MOCK_SYNC connection so tests can seed entries."""
        if not self._settings.ad_use_mock:
            raise RuntimeError("AdClient.mock_connection requires MAGISTER_AD_USE_MOCK=true")
        if self._mock_conn is None:
            self._mock_conn = _open_connection(self._settings, mock=True)
        return self._mock_conn

    async def aclose(self) -> None:
        """Release the persistent mock connection (no-op in production)."""
        if self._mock_conn is not None:
            try:
                self._mock_conn.unbind()
            except LDAPException:
                pass
            self._mock_conn = None


# Re-exports for tests.
__all__ = [
    "ALL_ATTRIBUTES",
    "BASE",
    "DEFAULT_USER_ATTRIBUTES",
    "AdClient",
    "AdUserRecord",
    "parse_ad_entry",
]
