"""Pure logic for department AD-group revocation on membership end.

No DB — exercises ``groups_to_revoke`` / ``_dedupe_strip`` directly.
"""

from __future__ import annotations

from magister_api.services.department_people import _dedupe_strip, groups_to_revoke


def test_dedupe_strip_trims_and_dedupes() -> None:
    assert _dedupe_strip(["  CN=A ", "CN=A", "", "  ", "CN=B"]) == ["CN=A", "CN=B"]


def test_revoke_all_when_no_other_membership_keeps_them() -> None:
    removed = ["CN=Tool-X,DC=x", "CN=Data-Y,DC=x"]
    assert groups_to_revoke(removed, keep=set()) == removed


def test_revoke_skips_groups_still_granted_elsewhere() -> None:
    removed = ["CN=Tool-X,DC=x", "CN=Data-Y,DC=x"]
    keep = {"CN=Tool-X,DC=x"}  # another active department still grants Tool-X
    assert groups_to_revoke(removed, keep) == ["CN=Data-Y,DC=x"]


def test_revoke_nothing_when_all_kept() -> None:
    removed = ["CN=Tool-X,DC=x", "CN=Data-Y,DC=x"]
    keep = {"CN=Tool-X,DC=x", "CN=Data-Y,DC=x"}
    assert groups_to_revoke(removed, keep) == []


def test_revoke_dedupes_and_strips_removed() -> None:
    removed = [" CN=A ", "CN=A", "CN=B", ""]
    assert groups_to_revoke(removed, keep={"CN=B"}) == ["CN=A"]
