"""TLS config construction for the LDAPS pool (_make_tls).

Covers the two GUI-managed knobs: importing an inline CA certificate and the
"ignore certificate" verify toggle. ldap3's ``Tls`` validates the supplied CA
material eagerly, so the tests use a real self-signed certificate.
"""

from __future__ import annotations

import datetime as dt
import ssl
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from magister_api.ad.client import _make_tls
from magister_api.config import Settings


@pytest.fixture(scope="module")
def ca_pem() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Test Schulträger Root CA")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(dt.datetime(2020, 1, 1))
        .not_valid_after(dt.datetime(2040, 1, 1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM).decode()


def _settings(**kw: object) -> Settings:
    return Settings(**kw)  # type: ignore[arg-type]


class TestMakeTls:
    def test_default_requires_valid_cert(self) -> None:
        tls = _make_tls(_settings())
        assert tls.validate == ssl.CERT_REQUIRED

    def test_skip_verify_uses_cert_none(self) -> None:
        tls = _make_tls(_settings(ad_tls_verify=False))
        assert tls.validate == ssl.CERT_NONE
        # No CA material is attached when we are not validating.
        assert tls.ca_certs_file is None
        assert tls.ca_certs_data is None

    def test_inline_pem_is_passed_as_data(self, ca_pem: str) -> None:
        tls = _make_tls(_settings(ad_tls_ca_pem=ca_pem))
        assert tls.validate == ssl.CERT_REQUIRED
        assert tls.ca_certs_data == ca_pem.strip()
        assert tls.ca_certs_file is None

    def test_inline_pem_takes_precedence_over_file(self, ca_pem: str, tmp_path: Path) -> None:
        f = tmp_path / "ca.pem"
        f.write_text(ca_pem)
        tls = _make_tls(_settings(ad_tls_ca_pem=ca_pem, ad_ca_bundle_path=str(f)))
        assert tls.ca_certs_data == ca_pem.strip()
        assert tls.ca_certs_file is None

    def test_file_path_used_when_no_inline_pem(self, ca_pem: str, tmp_path: Path) -> None:
        f = tmp_path / "ca.pem"
        f.write_text(ca_pem)
        tls = _make_tls(_settings(ad_ca_bundle_path=str(f)))
        assert tls.ca_certs_file == str(f)
        assert tls.ca_certs_data is None

    def test_blank_inline_pem_falls_back_to_file(self, ca_pem: str, tmp_path: Path) -> None:
        f = tmp_path / "ca.pem"
        f.write_text(ca_pem)
        tls = _make_tls(_settings(ad_tls_ca_pem="   ", ad_ca_bundle_path=str(f)))
        assert tls.ca_certs_file == str(f)
        assert tls.ca_certs_data is None
