"""PW generator and policy gate."""

from __future__ import annotations

import pytest

from magister_api.ad.password import (
    DEFAULT_LENGTH,
    MIN_LENGTH,
    count_charset_classes,
    generate_password,
    passes_default_complexity,
)


class TestGeneratePassword:
    def test_default_length(self) -> None:
        pw = generate_password()
        assert len(pw) == DEFAULT_LENGTH

    def test_custom_length(self) -> None:
        pw = generate_password(length=20)
        assert len(pw) == 20

    def test_too_short_rejected(self) -> None:
        with pytest.raises(ValueError):
            generate_password(length=MIN_LENGTH - 1)

    def test_each_call_unique(self) -> None:
        pws = {generate_password() for _ in range(50)}
        assert len(pws) == 50

    def test_satisfies_complexity(self) -> None:
        for _ in range(100):
            pw = generate_password()
            assert passes_default_complexity(pw)
            assert count_charset_classes(pw) >= 3

    def test_no_confusable_chars(self) -> None:
        for _ in range(50):
            pw = generate_password()
            for c in "0Oo1lI":
                assert c not in pw, f"confusable char {c!r} appeared in {pw!r}"


class TestPolicyGate:
    @pytest.mark.parametrize(
        "pw",
        [
            "Hunter2!Apple9",
            "abc!ABC123def456",
        ],
    )
    def test_accepts_compliant(self, pw: str) -> None:
        assert passes_default_complexity(pw)

    @pytest.mark.parametrize(
        "pw",
        [
            "short!1",
            "alllowercaseonly",
            "ALLUPPERCASEONLY",
            "1234567890123456",
        ],
    )
    def test_rejects_non_compliant(self, pw: str) -> None:
        assert not passes_default_complexity(pw)
