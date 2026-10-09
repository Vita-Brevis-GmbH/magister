"""TOTP policy around pyotp: drift window, single-use codes, code shapes."""

from __future__ import annotations

import time

import pyotp
import pytest

from magister_api.auth import totp


def _at(secret: str, step: int) -> str:
    return pyotp.TOTP(secret, digits=totp.DIGITS, interval=totp.PERIOD).at(step * totp.PERIOD)


class TestVerifyCode:
    def test_current_code_is_accepted_and_returns_its_step(self) -> None:
        secret = totp.new_secret()
        now = totp.current_step()
        assert totp.verify_code(secret, _at(secret, now), last_step=None) == now

    @pytest.mark.parametrize("offset", [-1, 0, 1])
    def test_one_step_of_drift_either_side(self, offset: int) -> None:
        secret = totp.new_secret()
        step = totp.current_step() + offset
        assert totp.verify_code(secret, _at(secret, step), last_step=None) == step

    @pytest.mark.parametrize("offset", [-2, 2, 10])
    def test_beyond_the_window_is_refused(self, offset: int) -> None:
        secret = totp.new_secret()
        step = totp.current_step() + offset
        assert totp.verify_code(secret, _at(secret, step), last_step=None) is None

    def test_a_step_is_single_use(self) -> None:
        """The property the login flow relies on: no replay inside the window."""
        secret = totp.new_secret()
        step = totp.current_step()
        code = _at(secret, step)
        assert totp.verify_code(secret, code, last_step=None) == step
        assert totp.verify_code(secret, code, last_step=step) is None

    def test_an_older_step_is_refused_after_a_newer_one(self) -> None:
        secret = totp.new_secret()
        now = totp.current_step()
        assert totp.verify_code(secret, _at(secret, now - 1), last_step=now) is None

    def test_spaces_are_tolerated(self) -> None:
        secret = totp.new_secret()
        code = _at(secret, totp.current_step())
        spaced = f"{code[:3]} {code[3:]}"
        assert totp.verify_code(secret, spaced, last_step=None) is not None

    @pytest.mark.parametrize("bad", ["", "abcdef", "12345", "1234567", "12 34", "００００００"])
    def test_malformed_input_is_refused_without_raising(self, bad: str) -> None:
        assert totp.verify_code(totp.new_secret(), bad, last_step=None) is None

    def test_a_code_from_another_secret_is_refused(self) -> None:
        a, b = totp.new_secret(), totp.new_secret()
        assert totp.verify_code(a, _at(b, totp.current_step()), last_step=None) is None


class TestProvisioning:
    def test_uri_carries_issuer_and_account(self) -> None:
        uri = totp.provisioning_uri(totp.new_secret(), account="admin@x", issuer="Magister")
        assert uri.startswith("otpauth://totp/")
        assert "issuer=Magister" in uri
        assert "digits=6" in uri or "digits" not in uri  # pyotp omits defaults

    def test_qr_is_an_inline_data_uri(self) -> None:
        """Inline so the CSP needs no change: img-src 'self' data: is allowed."""
        uri = totp.provisioning_uri(totp.new_secret(), account="admin@x", issuer="Magister")
        data_uri = totp.qr_data_uri(uri)
        assert data_uri.startswith("data:image/svg+xml")
        assert "http://" not in data_uri and "https://" not in data_uri


class TestRecoveryCodes:
    def test_ten_codes_in_a_readable_shape(self) -> None:
        codes = totp.new_recovery_codes()
        assert len(codes) == totp.RECOVERY_CODE_COUNT == 10
        assert len(set(codes)) == len(codes)
        for code in codes:
            assert len(code) == 9 and code[4] == "-"

    def test_alphabet_avoids_characters_that_get_misread(self) -> None:
        # Read off paper or over the phone: no 0/O, no 1/I/L.
        joined = "".join(totp.new_recovery_codes()).replace("-", "")
        assert not (set(joined) & set("01OIL"))

    @pytest.mark.parametrize(
        ("raw", "expected"), [("ab12-cd34", "AB12-CD34"), (" AB12-CD34 ", "AB12-CD34")]
    )
    def test_normalisation_is_forgiving(self, raw: str, expected: str) -> None:
        assert totp.normalize_recovery_code(raw) == expected


def test_current_step_tracks_the_clock() -> None:
    assert totp.current_step(now=0) == 0
    assert totp.current_step(now=totp.PERIOD - 0.001) == 0
    assert totp.current_step(now=totp.PERIOD) == 1
    assert totp.current_step() == int(time.time() // totp.PERIOD)
