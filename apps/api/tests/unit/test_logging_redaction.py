"""Logging filter must redact secrets — no PW/token/cookie strings shall ever land in logs."""

from __future__ import annotations

import io
import json
import logging

from magister_api.logging_config import (
    REDACTED,
    JsonFormatter,
    SecretRedactionFilter,
)


def _make_logger() -> tuple[logging.Logger, io.StringIO]:
    logger = logging.getLogger(f"test.{id(object())}")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(SecretRedactionFilter())
    logger.addHandler(handler)
    logger.propagate = False
    return logger, buf


def _last_record(buf: io.StringIO) -> dict[str, object]:
    return json.loads(buf.getvalue().splitlines()[-1])


class TestSecretRedaction:
    def test_redacts_extra_password(self) -> None:
        logger, buf = _make_logger()
        logger.info("audit emit", extra={"password": "hunter2", "user": "alice@x.ch"})
        rec = _last_record(buf)
        assert rec["password"] == REDACTED
        assert rec["user"] == "alice@x.ch"

    def test_redacts_extra_token_variants(self) -> None:
        logger, buf = _make_logger()
        logger.info(
            "ldap bind",
            extra={
                "id_token": "eyJ.toplongtoken",
                "access_token": "abc",
                "csrf_cookie": "x.y",
                "cookie": "session=...",
            },
        )
        rec = _last_record(buf)
        for key in ("id_token", "access_token", "csrf_cookie", "cookie"):
            assert rec[key] == REDACTED, key

    def test_redacts_bearer_in_message(self) -> None:
        logger, buf = _make_logger()
        logger.info("got Authorization Bearer abc123def456ghi789")
        rec = _last_record(buf)
        assert "abc123def456ghi789" not in str(rec)
        assert REDACTED in rec["msg"]  # type: ignore[operator]

    def test_redacts_password_kv_in_message(self) -> None:
        logger, buf = _make_logger()
        logger.info("ldap bind: password=hunter2 dn=CN=svc")
        rec = _last_record(buf)
        assert "hunter2" not in str(rec)

    def test_does_not_break_normal_messages(self) -> None:
        logger, buf = _make_logger()
        logger.info("hello", extra={"action": "login", "school_id": 1})
        rec = _last_record(buf)
        assert rec["msg"] == "hello"
        assert rec["action"] == "login"
        assert rec["school_id"] == 1
