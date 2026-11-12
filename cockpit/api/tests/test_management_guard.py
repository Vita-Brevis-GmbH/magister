"""The console is only reachable through the management listener (ADR-0015 D1)."""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from cockpit_api.config import settings
from cockpit_api.management_guard import (
    MARKER_HEADER,
    ManagementListenerRequiredError,
    check_configuration,
)


class TestGuard:
    def test_a_request_through_the_listener_passes(self, client: TestClient) -> None:
        # 401 = it reached the auth layer, which is the point: not blocked here.
        assert client.get("/api/instances").status_code == 401

    def test_a_request_from_the_public_origin_gets_404(self, public_client: TestClient) -> None:
        """404, not 403: probing must not reveal that a console lives here."""
        resp = public_client.get("/api/instances")
        assert resp.status_code == 404
        assert resp.json() == {"detail": "not_found"}

    def test_a_wrong_marker_is_refused(self, public_client: TestClient) -> None:
        resp = public_client.get("/api/instances", headers={MARKER_HEADER: "guessed"})
        assert resp.status_code == 404

    def test_an_empty_marker_never_matches(self, public_client: TestClient) -> None:
        """A blank configured marker must not turn into "anything goes"."""
        settings.management_marker = ""
        assert public_client.get("/api/instances", headers={MARKER_HEADER: ""}).status_code == 404

    def test_a_marker_with_odd_bytes_is_refused_not_crashed(
        self, public_client: TestClient
    ) -> None:
        """A high byte in the header must be a 404, never a 500.

        Starlette decodes header values as latin-1, and ``compare_digest``
        raises TypeError on non-ASCII ``str`` — comparing bytes keeps a probe
        with one odd byte indistinguishable from any other wrong marker.
        """
        # Sent as raw bytes: that is what a client on the wire can put there,
        # and Starlette hands it to the app latin-1-decoded.
        resp = public_client.get("/api/instances", headers={MARKER_HEADER: b"gu\xffessed"})
        assert resp.status_code == 404

    def test_the_health_probe_stays_reachable(self, public_client: TestClient) -> None:
        # The container healthcheck has no marker, and the body is just "ok".
        resp = public_client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_a_refusal_keeps_the_security_headers(self, public_client: TestClient) -> None:
        resp = public_client.get("/api/instances")
        assert resp.status_code == 404
        assert resp.headers["X-Frame-Options"] == "DENY"

    def test_a_refusal_is_logged_with_the_path(
        self, public_client: TestClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The response says nothing, so the reason has to be in the log."""
        with caplog.at_level(logging.WARNING, logger="cockpit_api.management_guard"):
            public_client.get("/api/instances")
        assert any("/api/instances" in r.getMessage() for r in caplog.records)

    def test_guard_off_lets_everything_through(self, public_client: TestClient) -> None:
        settings.require_management_listener = False
        assert public_client.get("/api/instances").status_code == 401


class TestStartupConfiguration:
    def test_a_sane_configuration_passes(self) -> None:
        check_configuration(required=True, marker="m", published_address="10.0.0.5:4444")

    def test_a_missing_marker_aborts_the_start(self) -> None:
        """Otherwise the guard locks every operator out instead of protecting."""
        with pytest.raises(ManagementListenerRequiredError, match="MANAGEMENT_MARKER"):
            check_configuration(required=True, marker="   ", published_address="10.0.0.5:4444")

    @pytest.mark.parametrize(
        "address",
        [
            "0.0.0.0:4444",
            "0.0.0.0",  # noqa: S104
            ":::4444",
            "[::]:4444",
            "*:4444",
            ":4444",
        ],
    )
    def test_a_wildcard_address_aborts_the_start(self, address: str) -> None:
        with pytest.raises(ManagementListenerRequiredError, match="every interface"):
            check_configuration(required=True, marker="m", published_address=address)

    def test_the_address_is_still_checked_when_the_guard_is_off(self) -> None:
        # Turning the marker guard off is a choice; publishing the console on
        # every interface is not one this code helps you make.
        with pytest.raises(ManagementListenerRequiredError, match="every interface"):
            check_configuration(required=False, marker="", published_address="0.0.0.0:4444")

    def test_an_ipv6_management_address_passes(self) -> None:
        check_configuration(required=True, marker="m", published_address="[fd00::5]:4444")
