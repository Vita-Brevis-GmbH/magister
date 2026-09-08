"""Shared fixtures.

Since ADR-0015 D1 the console refuses anything that did not come through the
management listener, so the default test client speaks through it — otherwise
every test would only ever see the guard's 404. The guard itself is tested
explicitly in ``test_management_guard.py``.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from cockpit_api.config import settings
from cockpit_api.main import app
from cockpit_api.management_guard import MARKER_HEADER

TEST_MARKER = "test-management-marker"


@pytest.fixture(autouse=True)
def _management_config() -> Iterator[None]:
    """Configure a marker so the app starts and the guard is exercisable."""
    previous = (
        settings.require_management_listener,
        settings.management_marker,
        settings.published_address,
    )
    settings.require_management_listener = True
    settings.management_marker = TEST_MARKER
    settings.published_address = "10.0.0.5:4444"
    yield
    (
        settings.require_management_listener,
        settings.management_marker,
        settings.published_address,
    ) = previous


@pytest.fixture
def client() -> Iterator[TestClient]:
    """A client that arrives through the management listener, like Caddy does."""
    with TestClient(app, headers={MARKER_HEADER: TEST_MARKER}) as c:
        yield c


@pytest.fixture
def public_client() -> Iterator[TestClient]:
    """A client that does NOT — i.e. someone probing the public origin."""
    with TestClient(app) as c:
        yield c
