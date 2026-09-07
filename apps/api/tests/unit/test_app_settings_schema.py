"""AppSettingsUpdate field validators (no DB)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from magister_api.schemas.app_settings import AppSettingsUpdate


class TestNinjaRegion:
    @pytest.mark.parametrize("region", ["us", "us2", "eu", "ca", "oc"])
    def test_accepts_valid_regions(self, region: str) -> None:
        assert AppSettingsUpdate(ninja_region=region).ninja_region == region

    def test_none_and_empty_are_allowed(self) -> None:
        # None = leave unchanged; "" = clear.
        assert AppSettingsUpdate(ninja_region=None).ninja_region is None
        assert AppSettingsUpdate(ninja_region="").ninja_region == ""

    def test_rejects_unknown_region(self) -> None:
        with pytest.raises(ValidationError):
            AppSettingsUpdate(ninja_region="mars")

    def test_enabled_and_ids_pass_through(self) -> None:
        u = AppSettingsUpdate(ninja_enabled=True, ninja_client_id="abc", ninja_client_secret="s")
        assert u.ninja_enabled is True
        assert u.ninja_client_id == "abc"
        assert u.ninja_client_secret == "s"
