"""Zeilenfehler eines Imports: nie SQL oder Parameter (Passwörter!) in der Oberfläche."""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError

from magister_api.services.imports import _row_error  # pyright: ignore[reportPrivateUsage]


class _OrigError(Exception):
    pass


def test_database_error_keeps_only_the_first_line() -> None:
    orig = _OrigError(
        'new row for relation "class_memberships" violates check constraint "x"\n'
        "DETAIL:  Failing row contains (…)"
    )
    exc = IntegrityError("INSERT INTO t (secret) VALUES ($1)", ("Loewe-Sofa-82",), orig)
    text = _row_error(exc)
    assert text == (
        'database rejected the row: new row for relation "class_memberships" '
        'violates check constraint "x"'
    )
    assert "Loewe-Sofa-82" not in text
    assert "INSERT" not in text


def test_other_errors_pass_through() -> None:
    assert _row_error(ValueError("password rejected by AD policy")) == (
        "password rejected by AD policy"
    )
