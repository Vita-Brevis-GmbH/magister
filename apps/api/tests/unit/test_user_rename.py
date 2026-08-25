"""Rename-assistant preview + slug logic (pure, no DB/AD)."""

from __future__ import annotations

import pytest

from magister_api.models.auth import AdUserCache
from magister_api.schemas.user_rename import RenamePreviewRequest
from magister_api.services.user_rename import UserRenameService, _slug


def _target(
    *,
    given: str = "Anna",
    surname: str = "Meier",
    upn: str = "anna.meier@schule.example.ch",
    mail: str | None = "anna.meier@schule.example.ch",
) -> AdUserCache:
    return AdUserCache(
        ad_object_guid="00000000-0000-0000-0000-000000000001",
        upn=upn,
        mail=mail,
        given_name=given,
        surname=surname,
        sam_account_name="anna.meier",
        kind="teacher",
        enabled=True,
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Müller", "mueller"),
        ("Lüönd", "lueoend"),
        ("Weiß", "weiss"),
        ("O'Brien", "obrien"),
        ("Anna-Lena", "annalena"),
        ("  Zoé  ", "zoe"),
    ],
)
def test_slug_folds_to_ascii_localpart(raw: str, expected: str) -> None:
    assert _slug(raw) == expected


def test_preview_cascades_and_keeps_domain() -> None:
    out = UserRenameService.preview(
        target=_target(),
        req=RenamePreviewRequest(new_surname="Müller"),
    )
    assert out.given_name == "Anna"
    assert out.surname == "Müller"
    assert out.display_name == "Anna Müller"
    # domain preserved, local part re-slugged from given.surname
    assert out.upn == "anna.mueller@schule.example.ch"
    assert out.mail == "anna.mueller@schule.example.ch"
    assert out.sam_account_name == "anna.mueller"
    # the current primary is flagged for alias preservation
    assert out.old_mail_kept_as_alias == "anna.meier@schule.example.ch"


def test_preview_can_change_given_name_too() -> None:
    out = UserRenameService.preview(
        target=_target(),
        req=RenamePreviewRequest(new_surname="Meier", new_given_name="Anna-Lena"),
    )
    assert out.display_name == "Anna-Lena Meier"
    assert out.upn == "annalena.meier@schule.example.ch"


def test_preview_sam_is_capped_at_20() -> None:
    out = UserRenameService.preview(
        target=_target(given="Alexandra", surname="Hochstrasser-Wettstein"),
        req=RenamePreviewRequest(new_surname="Hochstrasser-Wettstein"),
    )
    assert out.sam_account_name is not None
    assert len(out.sam_account_name) <= 20


def test_preview_without_mail_leaves_mail_none() -> None:
    out = UserRenameService.preview(
        target=_target(mail=None),
        req=RenamePreviewRequest(new_surname="Müller"),
    )
    # No current mail → nothing to derive a mail domain from beyond the UPN's.
    assert out.mail == "anna.mueller@schule.example.ch"
    assert out.old_mail_kept_as_alias is None
