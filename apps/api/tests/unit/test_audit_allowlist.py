"""Unit tests for the audit-payload allowlist validator."""

from __future__ import annotations

import pytest

from magister_api.audit.allowlist import (
    SecretInPayloadError,
    validate_audit_payload,
)


class TestForbiddenKeys:
    @pytest.mark.parametrize(
        "key",
        [
            "password",
            "Password",
            "passwort",
            "manual_password",
            "temp_password",
            "user_pwd",
            "client_secret",
            "id_token",
            "access_token",
            "refresh_token",
            "session_id",
            "csrf",
            "csrf_token",
            "Authorization",
            "Cookie",
            "unicodePwd",
        ],
    )
    def test_rejects_forbidden_top_level_key(self, key: str) -> None:
        with pytest.raises(SecretInPayloadError):
            validate_audit_payload({key: "anything"})

    def test_rejects_nested_forbidden_key(self) -> None:
        with pytest.raises(SecretInPayloadError):
            validate_audit_payload({"reset": {"mode": "manual", "password": "x"}})

    def test_rejects_forbidden_inside_list(self) -> None:
        with pytest.raises(SecretInPayloadError):
            validate_audit_payload({"changes": [{"old": {}, "new": {"token": "x"}}]})


class TestSecretishValues:
    def test_rejects_bearer_value(self) -> None:
        with pytest.raises(SecretInPayloadError):
            validate_audit_payload({"note": "received Bearer abc123def456ghi"})

    def test_rejects_jwt_value(self) -> None:
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ0ZXN0In0.x_signature_x"
        with pytest.raises(SecretInPayloadError):
            validate_audit_payload({"note": f"id_token was {jwt}"})

    def test_rejects_password_kv_in_string(self) -> None:
        with pytest.raises(SecretInPayloadError):
            validate_audit_payload({"note": "password=hunter2"})


class TestStructure:
    def test_accepts_clean_payload(self) -> None:
        validate_audit_payload(
            {
                "mode": "generate",
                "force_change": True,
                "target_kind": "student",
                "school_id": 12,
                "tags": ["audit", "reset"],
                "details": {"old_class": "3a", "new_class": "4a"},
            }
        )

    def test_rejects_excessive_depth(self) -> None:
        nested: dict[str, object] = {"x": {}}
        cur: dict[str, object] = nested["x"]  # type: ignore[assignment]
        for _ in range(10):
            child: dict[str, object] = {}
            cur["x"] = child
            cur = child
        with pytest.raises(SecretInPayloadError):
            validate_audit_payload(nested)

    def test_rejects_huge_string(self) -> None:
        with pytest.raises(SecretInPayloadError):
            validate_audit_payload({"note": "x" * 5000})

    def test_rejects_unsupported_value_type(self) -> None:
        class Custom:
            pass

        with pytest.raises(SecretInPayloadError):
            validate_audit_payload({"x": Custom()})
