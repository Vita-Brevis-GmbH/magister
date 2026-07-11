"""Classification of ldap3 failures into safe, credential-free reason codes.

The connection-test endpoint returns these codes to the operator so the
frontend can explain *why* the LDAPS bind failed — without leaking anything the
"Niemals" rules forbid (no credentials, no bind-DN, no raw exception text).
"""

from __future__ import annotations

import ssl

from ldap3.core.exceptions import (
    LDAPBindError,
    LDAPCertificateError,
    LDAPException,
    LDAPInvalidCredentialsResult,
    LDAPSocketOpenError,
    LDAPSocketReceiveError,
)

from magister_api.ad.errors import (
    REASON_AUTH,
    REASON_GENERIC,
    REASON_TIMEOUT,
    REASON_TLS,
    REASON_UNREACHABLE,
    classify_ldap_error,
)


class TestClassifyLdapError:
    def test_socket_open_is_unreachable(self) -> None:
        assert classify_ldap_error(LDAPSocketOpenError("connection refused")) == REASON_UNREACHABLE

    def test_bind_error_is_auth(self) -> None:
        assert classify_ldap_error(LDAPBindError("invalidCredentials")) == REASON_AUTH

    def test_invalid_credentials_is_auth(self) -> None:
        assert classify_ldap_error(LDAPInvalidCredentialsResult()) == REASON_AUTH

    def test_receive_timeout_is_timeout(self) -> None:
        assert classify_ldap_error(LDAPSocketReceiveError("timed out")) == REASON_TIMEOUT

    def test_certificate_error_is_tls(self) -> None:
        assert classify_ldap_error(LDAPCertificateError("bad cert")) == REASON_TLS

    def test_socket_open_wrapping_ssl_error_is_tls(self) -> None:
        # ldap3 raises LDAPSocketOpenError when a DC certificate is rejected; the
        # underlying ssl.SSLError sits in the cause chain. TLS must win over the
        # plain "unreachable" bucket.
        inner = ssl.SSLError("certificate verify failed")
        exc = LDAPSocketOpenError("socket ssl wrapping error")
        exc.__cause__ = inner
        assert classify_ldap_error(exc) == REASON_TLS

    def test_unknown_falls_back_to_generic(self) -> None:
        assert classify_ldap_error(LDAPException("something odd")) == REASON_GENERIC
