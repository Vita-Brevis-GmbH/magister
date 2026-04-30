"""Top-level pytest configuration.

- Sets minimal MAGISTER_* env vars before any module imports them.
- Provides a Postgres-or-skip fixture for integration tests that need pgcrypto.
"""

from __future__ import annotations

import os

import pytest

# Set required runtime secrets BEFORE magister_api modules are imported anywhere.
os.environ.setdefault("MAGISTER_ENVIRONMENT", "test")
os.environ.setdefault("MAGISTER_AUDIT_KEY", "unit-test-audit-key-not-for-prod")
os.environ.setdefault("MAGISTER_SESSION_SECRET", "unit-test-session-secret")
os.environ.setdefault("MAGISTER_CSRF_SECRET", "unit-test-csrf-secret")
os.environ.setdefault("MAGISTER_OIDC_ISSUER", "https://login.example.test/v2.0")
os.environ.setdefault("MAGISTER_OIDC_CLIENT_ID", "test-client-id")
os.environ.setdefault("MAGISTER_OIDC_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("MAGISTER_SESSION_COOKIE_SECURE", "false")


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> None:
    from magister_api.config import reset_settings_cache

    reset_settings_cache()


def _postgres_url() -> str | None:
    return os.environ.get("MAGISTER_TEST_DATABASE_URL")


@pytest.fixture(scope="session")
def postgres_url() -> str:
    url = _postgres_url()
    if not url:
        pytest.skip("MAGISTER_TEST_DATABASE_URL not set — skipping pgcrypto integration tests")
    return url
