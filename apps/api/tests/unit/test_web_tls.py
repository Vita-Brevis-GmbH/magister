"""Webserver TLS import parsing + on-disk materialization."""

from __future__ import annotations

import datetime as dt
import os

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID

from magister_api.services import web_tls


def _make_cert() -> tuple[str, str, rsa.RSAPrivateKey, x509.Certificate]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "magister.example.ch")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(dt.datetime(2020, 1, 1))
        .not_valid_after(dt.datetime(2035, 1, 1))
        .sign(key, hashes.SHA256())
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode()
    key_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    return cert_pem, key_pem, key, cert


def test_normalize_pem_roundtrip() -> None:
    cert_pem, key_pem, _, _ = _make_cert()
    out_cert, out_key = web_tls.normalize_pem(cert_pem, key_pem)
    assert "BEGIN CERTIFICATE" in out_cert
    assert "BEGIN PRIVATE KEY" in out_key


def test_normalize_pem_rejects_mismatch() -> None:
    cert_pem, _, _, _ = _make_cert()
    _, other_key_pem, _, _ = _make_cert()
    with pytest.raises(web_tls.WebTlsError, match="key_cert_mismatch"):
        web_tls.normalize_pem(cert_pem, other_key_pem)


def test_normalize_pem_rejects_garbage() -> None:
    with pytest.raises(web_tls.WebTlsError):
        web_tls.normalize_pem("not a cert", "not a key")


def test_from_pfx_roundtrip() -> None:
    _, _, key, cert = _make_cert()
    pfx = pkcs12.serialize_key_and_certificates(
        name=b"magister",
        key=key,
        cert=cert,
        cas=None,
        encryption_algorithm=serialization.BestAvailableEncryption(b"s3cret"),
    )
    out_cert, out_key = web_tls.from_pfx(pfx, "s3cret")
    assert "BEGIN CERTIFICATE" in out_cert
    assert "BEGIN PRIVATE KEY" in out_key


def test_from_pfx_wrong_password() -> None:
    _, _, key, cert = _make_cert()
    pfx = pkcs12.serialize_key_and_certificates(
        name=b"magister",
        key=key,
        cert=cert,
        cas=None,
        encryption_algorithm=serialization.BestAvailableEncryption(b"right"),
    )
    with pytest.raises(web_tls.WebTlsError, match="invalid_pfx"):
        web_tls.from_pfx(pfx, "wrong")


def test_materialize_custom_writes_files_and_snippet(tmp_path: os.PathLike[str]) -> None:
    cert_pem, key_pem, _, _ = _make_cert()
    norm_cert, norm_key = web_tls.normalize_pem(cert_pem, key_pem)
    result = web_tls.materialize(str(tmp_path), norm_cert, norm_key)
    assert result == "custom"
    cert_file = os.path.join(str(tmp_path), web_tls.CERT_FILENAME)
    key_file = os.path.join(str(tmp_path), web_tls.KEY_FILENAME)
    snippet = os.path.join(str(tmp_path), web_tls.SNIPPET_FILENAME)
    assert os.path.exists(cert_file)
    assert os.path.exists(key_file)
    # Key file must be owner-only.
    assert (os.stat(key_file).st_mode & 0o777) == 0o600
    with open(snippet, encoding="utf-8") as fh:
        body = fh.read()
    assert body == f"tls {cert_file} {key_file}\n"


def test_materialize_selfsigned_removes_and_falls_back(tmp_path: os.PathLike[str]) -> None:
    cert_pem, key_pem, _, _ = _make_cert()
    norm_cert, norm_key = web_tls.normalize_pem(cert_pem, key_pem)
    # First install a custom cert, then clear it.
    web_tls.materialize(str(tmp_path), norm_cert, norm_key)
    result = web_tls.materialize(str(tmp_path), None, None)
    assert result == "selfsigned"
    assert not os.path.exists(os.path.join(str(tmp_path), web_tls.CERT_FILENAME))
    assert not os.path.exists(os.path.join(str(tmp_path), web_tls.KEY_FILENAME))
    with open(os.path.join(str(tmp_path), web_tls.SNIPPET_FILENAME), encoding="utf-8") as fh:
        assert fh.read() == "tls internal\n"
