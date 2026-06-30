"""`python -m magister_api.cli.hash_password` stdin → argon2id hash."""

from __future__ import annotations

import io

import pytest

from magister_api.auth.passwords import verify_password
from magister_api.cli import hash_password as cli


def test_emits_verifiable_argon2_hash(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("correct horse battery\n"))
    rc = cli.main()
    out = capsys.readouterr().out.strip()
    assert rc == 0
    assert out.startswith("$argon2id$")
    assert verify_password("correct horse battery", out) is True


def test_strips_trailing_newline_only(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # A password with internal spaces must survive verbatim (only the line's
    # trailing \n is stripped).
    monkeypatch.setattr("sys.stdin", io.StringIO("pw with spaces!!\n"))
    cli.main()
    out = capsys.readouterr().out.strip()
    assert verify_password("pw with spaces!!", out) is True


def test_rejects_short_password(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("short\n"))
    rc = cli.main()
    captured = capsys.readouterr()
    assert rc == 1
    assert captured.out == ""  # no hash leaked to stdout
    assert "12 characters" in captured.err
