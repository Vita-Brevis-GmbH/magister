"""Unit tests for the LDAP entry parser + GUID decoder."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from magister_api.ad.client import (
    UAC_ACCOUNTDISABLE,
    AdClient,
    AdUserRecord,
    _decode_object_guid,
    _kind_from_member_of,
    parse_ad_entry,
)
from magister_api.ad.errors import AdUnavailableError, AdUserParseError
from magister_api.config import Settings


class _FakeSafeSyncConn:
    """Mimics a SAFE_SYNC ldap3 connection: ``search`` returns the 4-tuple
    ``(status, result, response, request)`` and does NOT put the entries on
    ``conn.response`` — the production shape that MOCK_SYNC hides."""

    def __init__(self, entries: list[dict[str, Any]], *, result_code: int = 0) -> None:
        self._entries = entries
        self._result = {
            "result": result_code,
            "description": "success" if result_code == 0 else "operationsError",
        }
        # SAFE_SYNC contract: the connection attribute is not the source of truth.
        self.response: list[dict[str, Any]] = []
        self.result: dict[str, Any] = {}

    def search(
        self, **_kwargs: Any
    ) -> tuple[bool, dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
        return (self._result["result"] == 0, self._result, self._entries, {})

    def unbind(self) -> None:  # pragma: no cover - trivial
        pass


class TestFindUserDnSafeSync:
    """find_user_dn must read results from the returned tuple (SAFE_SYNC),
    not from conn.response, and must surface real LDAP errors."""

    @pytest.mark.asyncio
    async def test_reads_dn_from_tuple_not_conn_response(self, monkeypatch: Any) -> None:
        guid = "12345678-90ab-cdef-1234-567890abcdef"
        dn = "CN=Anna,OU=Users,DC=schule,DC=local"
        entries = [{"type": "searchResEntry", "dn": dn, "attributes": {}}]
        client = AdClient(Settings(ad_users_search_base="DC=schule,DC=local"))
        monkeypatch.setattr(
            client, "_acquire_connection", lambda: (_FakeSafeSyncConn(entries), False)
        )

        assert await client.find_user_dn(guid) == dn

    @pytest.mark.asyncio
    async def test_ldap_error_raises_instead_of_silent_none(self, monkeypatch: Any) -> None:
        guid = "12345678-90ab-cdef-1234-567890abcdef"
        conn = _FakeSafeSyncConn([], result_code=1)  # operationsError
        client = AdClient(Settings(ad_users_search_base="DC=schule,DC=local"))
        monkeypatch.setattr(client, "_acquire_connection", lambda: (conn, False))

        with pytest.raises(AdUnavailableError):
            await client.find_user_dn(guid)

    @pytest.mark.asyncio
    async def test_genuinely_absent_returns_none(self, monkeypatch: Any) -> None:
        guid = "12345678-90ab-cdef-1234-567890abcdef"
        conn = _FakeSafeSyncConn([], result_code=0)  # success, zero entries
        client = AdClient(Settings(ad_users_search_base="DC=schule,DC=local"))
        monkeypatch.setattr(client, "_acquire_connection", lambda: (conn, False))

        assert await client.find_user_dn(guid) is None


class TestDecodeObjectGuid:
    def test_canonical_string_passthrough(self) -> None:
        v = "01020304-0506-0708-090a-0b0c0d0e0f10"
        assert _decode_object_guid(v) == v

    def test_uppercase_string_lowercased(self) -> None:
        v = "01020304-0506-0708-090A-0B0C0D0E0F10"
        assert _decode_object_guid(v) == v.lower()

    def test_uuid_object(self) -> None:
        u = uuid.UUID("12345678-90ab-cdef-1234-567890abcdef")
        assert _decode_object_guid(u) == str(u)

    def test_ad_le_blob(self) -> None:
        u = uuid.UUID("12345678-90ab-cdef-1234-567890abcdef")
        decoded = _decode_object_guid(u.bytes_le)
        assert decoded == str(u)

    def test_invalid_string_raises(self) -> None:
        with pytest.raises(AdUserParseError):
            _decode_object_guid("not-a-guid")

    def test_invalid_byte_length_raises(self) -> None:
        with pytest.raises(AdUserParseError):
            _decode_object_guid(b"\x00" * 5)

    def test_unsupported_type_raises(self) -> None:
        with pytest.raises(AdUserParseError):
            _decode_object_guid(12345)  # type: ignore[arg-type]


class TestKindFromMemberOf:
    def test_default_student(self) -> None:
        assert _kind_from_member_of(None) == "student"
        assert _kind_from_member_of([]) == "student"

    def test_teacher(self) -> None:
        assert _kind_from_member_of(["CN=Teachers,OU=Groups"]) == "teacher"
        assert _kind_from_member_of(["cn=Lehrer,OU=Groups"]) == "teacher"

    def test_admin_group_is_teacher_not_admin(self) -> None:
        # People who sign in are staff — the admin group must NOT make them a
        # "student"/"admin" *kind*; they are teachers (admin is an RBAC role).
        assert _kind_from_member_of(["CN=Admins,OU=Groups"]) == "teacher"
        assert _kind_from_member_of(["CN=Admins,OU=Groups", "CN=Teachers,OU=Groups"]) == "teacher"


class TestClassifyKindByOu:
    TEACHER_OU = "OU=Lehrer,OU=Schule,DC=schule,DC=local"
    STUDENT_OU = "OU=Schueler,OU=Schule,DC=schule,DC=local"

    def _c(self, dn: str, fallback: str = "student") -> str:
        from magister_api.ad.client import classify_kind_by_ou

        return classify_kind_by_ou(
            dn, fallback, teacher_ou=self.TEACHER_OU, student_ous=[self.STUDENT_OU, None]
        )

    def test_dn_under_teacher_ou(self) -> None:
        assert self._c(f"CN=Hans Muster,{self.TEACHER_OU}") == "teacher"

    def test_dn_under_teacher_ou_case_insensitive(self) -> None:
        assert self._c("cn=hans,ou=lehrer,ou=schule,dc=schule,dc=local") == "teacher"

    def test_dn_under_student_ou(self) -> None:
        assert self._c(f"CN=Kind,{self.STUDENT_OU}", fallback="teacher") == "student"

    def test_boundary_not_substring(self) -> None:
        # OU=NichtLehrer must not match teacher_ou "OU=Lehrer,...".
        dn = "CN=x,OU=NichtLehrer,OU=Schule,DC=schule,DC=local"
        assert self._c(dn, fallback="student") == "student"

    def test_no_match_keeps_fallback(self) -> None:
        dn = "CN=y,OU=Other,DC=schule,DC=local"
        assert self._c(dn, fallback="teacher") == "teacher"


class TestParseAdEntry:
    def _attrs(self, **overrides: Any) -> dict[str, Any]:
        guid_le = uuid.UUID("aabbccdd-eeff-0011-2233-445566778899").bytes_le
        base = {
            "objectGUID": guid_le,
            "userPrincipalName": "anna@example.ch",
            "givenName": "Anna",
            "sn": "Beispiel",
            "mail": "anna@example.ch",
            "userAccountControl": 0x200,
            "memberOf": [],
        }
        base.update(overrides)
        return base

    def test_happy_path(self) -> None:
        rec = parse_ad_entry(self._attrs(), "CN=Anna,OU=A,DC=schule,DC=local")
        assert isinstance(rec, AdUserRecord)
        assert rec.upn == "anna@example.ch"
        assert rec.given_name == "Anna"
        assert rec.surname == "Beispiel"
        assert rec.enabled is True
        assert rec.kind == "student"
        assert rec.distinguished_name == "CN=Anna,OU=A,DC=schule,DC=local"

    def test_extended_attributes(self) -> None:
        """displayName, sAMAccountName, address fields all flow through."""
        rec = parse_ad_entry(
            self._attrs(
                displayName="Anna Beispiel",
                sAMAccountName="anna.b",
                streetAddress="Schulweg 12",
                l="Musterhausen",
                postalCode="3000",
                co="Schweiz",
            ),
            "CN=Anna,OU=A,DC=schule,DC=local",
        )
        assert rec.display_name == "Anna Beispiel"
        assert rec.sam_account_name == "anna.b"
        assert rec.street_address == "Schulweg 12"
        assert rec.locality == "Musterhausen"
        assert rec.postal_code == "3000"
        assert rec.country == "Schweiz"
        # device_name stays None until Phase 4 plugs in the Computer-OU sync.
        assert rec.device_name is None

    def test_extended_attributes_default_none(self) -> None:
        """Missing optional attrs come back as None, not as empty strings."""
        rec = parse_ad_entry(self._attrs(), "CN=Anna")
        assert rec.display_name is None
        assert rec.sam_account_name is None
        assert rec.street_address is None
        assert rec.locality is None
        assert rec.postal_code is None
        assert rec.country is None

    def test_disabled_account(self) -> None:
        rec = parse_ad_entry(
            self._attrs(userAccountControl=0x200 | UAC_ACCOUNTDISABLE),
            "CN=X,DC=schule,DC=local",
        )
        assert rec.enabled is False

    def test_missing_upn_raises(self) -> None:
        with pytest.raises(AdUserParseError):
            parse_ad_entry(self._attrs(userPrincipalName=None), "CN=X")

    def test_missing_object_guid_raises(self) -> None:
        with pytest.raises(AdUserParseError):
            parse_ad_entry(self._attrs(objectGUID=None), "CN=X")

    def test_member_of_string_normalised(self) -> None:
        rec = parse_ad_entry(
            self._attrs(memberOf="CN=Teachers,OU=Groups"),
            "CN=X",
        )
        assert rec.kind == "teacher"

    def test_school_match_via_ou(self) -> None:
        rec = parse_ad_entry(
            self._attrs(),
            "CN=Anna,OU=Students,OU=ALPHA,DC=schule,DC=local",
        )
        assert rec.matches_school_via_ou("alpha") is True
        assert rec.matches_school_via_ou("beta") is False


class TestMakeTls:
    """The LDAPS TLS config must enforce CERT_REQUIRED + TLS 1.2 floor."""

    def _settings(self, **overrides: Any) -> Any:
        from magister_api.config import Settings

        defaults: dict[str, Any] = {
            "ad_dcs": ["dc1.example.local"],
            "audit_key": "x",
            "session_secret": "x",
            "csrf_secret": "x",
        }
        defaults.update(overrides)
        return Settings(**defaults)

    def test_cert_required_and_no_old_tls(self) -> None:
        import ssl

        from magister_api.ad.client import _make_tls

        tls = _make_tls(self._settings())
        assert tls.validate == ssl.CERT_REQUIRED
        # ssl_options is a list per ldap3; the combined int must have all
        # legacy-TLS OP_NO bits set so SSLv3 and TLS 1.0/1.1 are refused.
        # (ssl.OP_NO_SSLv2 is 0 on modern Python — SSLv2 is gone from OpenSSL.)
        assert tls.ssl_options is not None
        combined = 0
        for opt in tls.ssl_options:
            combined |= opt
        assert combined & ssl.OP_NO_SSLv3
        assert combined & ssl.OP_NO_TLSv1
        assert combined & ssl.OP_NO_TLSv1_1
        assert tls.version == ssl.PROTOCOL_TLS_CLIENT

    def test_ca_bundle_path_threaded_through(self, tmp_path: Any) -> None:
        from magister_api.ad.client import _make_tls

        # ldap3.Tls validates the path exists at construction; use a real file.
        ca = tmp_path / "ad-ca.pem"
        ca.write_text("-----BEGIN CERTIFICATE-----\nfake\n-----END CERTIFICATE-----\n")
        tls = _make_tls(self._settings(ad_ca_bundle_path=str(ca)))
        assert tls.ca_certs_file == str(ca)

    def test_ca_bundle_absent_uses_system_trust(self) -> None:
        from magister_api.ad.client import _make_tls

        tls = _make_tls(self._settings())
        assert tls.ca_certs_file is None
