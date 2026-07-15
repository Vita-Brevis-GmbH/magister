"""Byte-level tests for the DACL editor behind "user cannot change password".

The live AD write can't run against the ldap3 mock, so these tests are the
safety net for the self-relative security-descriptor transform.
"""

from __future__ import annotations

import struct

from magister_api.ad.security_descriptor import (
    CHANGE_PASSWORD_RIGHT,
    SE_DACL_PRESENT,
    SE_SELF_RELATIVE,
    SID_SELF,
    SID_WORLD,
    encode_sid,
    has_cannot_change_password,
    set_cannot_change_password,
)

_SD_HEADER = struct.Struct("<BBHIIII")
_ACL_HEADER = struct.Struct("<BBHHH")


def _allow_ace(sid: str) -> bytes:
    """A plain ACCESS_ALLOWED_ACE (type 0) granting some mask to ``sid``."""
    sid_bytes = encode_sid(sid)
    size = 4 + 4 + len(sid_bytes)
    return (
        bytes([0x00, 0x00])
        + struct.pack("<H", size)
        + struct.pack("<I", 0x00020000)
        + sid_bytes
    )


def _dacl_only_sd(aces: list[bytes]) -> bytes:
    body = b"".join(aces)
    acl = _ACL_HEADER.pack(4, 0, _ACL_HEADER.size + len(body), len(aces), 0) + body
    control = SE_SELF_RELATIVE | SE_DACL_PRESENT
    header = _SD_HEADER.pack(1, 0, control, 0, 0, 0, _SD_HEADER.size)
    return header + acl


def test_encode_sid_self_and_world() -> None:
    assert encode_sid(SID_SELF) == bytes([1, 1, 0, 0, 0, 0, 0, 5, 10, 0, 0, 0])
    assert encode_sid(SID_WORLD) == bytes([1, 1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0])


def test_change_password_guid_is_binary_le() -> None:
    assert CHANGE_PASSWORD_RIGHT.bytes_le[:4] == bytes([0x53, 0x1A, 0x72, 0xAB])


def test_set_deny_adds_two_aces_and_is_detected() -> None:
    sd = _dacl_only_sd([_allow_ace("S-1-5-21-1-2-3-1000")])
    assert has_cannot_change_password(sd) is False

    denied = set_cannot_change_password(sd, deny=True)
    assert has_cannot_change_password(denied) is True

    # The pre-existing ACE is preserved; two deny ACEs were prepended.
    _, _, _, _, _, _, off = _SD_HEADER.unpack_from(denied, 0)
    _, _, _, count, _ = _ACL_HEADER.unpack_from(denied, off)
    assert count == 3


def test_clear_removes_deny_and_keeps_others() -> None:
    keep = _allow_ace("S-1-5-21-1-2-3-1000")
    denied = set_cannot_change_password(_dacl_only_sd([keep]), deny=True)

    cleared = set_cannot_change_password(denied, deny=False)
    assert has_cannot_change_password(cleared) is False

    _, _, _, _, _, _, off = _SD_HEADER.unpack_from(cleared, 0)
    _, _, _, count, _ = _ACL_HEADER.unpack_from(cleared, off)
    assert count == 1
    # The surviving ACE is exactly the one we kept.
    assert cleared[off + _ACL_HEADER.size :] == keep


def test_set_deny_is_idempotent() -> None:
    sd = _dacl_only_sd([_allow_ace("S-1-5-21-1-2-3-1000")])
    once = set_cannot_change_password(sd, deny=True)
    twice = set_cannot_change_password(once, deny=True)
    assert once == twice
    assert has_cannot_change_password(twice) is True


def test_clear_on_already_clear_is_noop_equivalent() -> None:
    sd = _dacl_only_sd([_allow_ace("S-1-5-21-1-2-3-1000")])
    cleared = set_cannot_change_password(sd, deny=False)
    assert has_cannot_change_password(cleared) is False
    # Same ACE count as the input (nothing removed, nothing added).
    _, _, _, _, _, _, off = _SD_HEADER.unpack_from(cleared, 0)
    _, _, _, count, _ = _ACL_HEADER.unpack_from(cleared, off)
    assert count == 1


def test_client_reads_sd_from_safe_sync_tuple() -> None:
    """Regression: under SAFE_SYNC the SD read must come from the returned
    tuple (res[2]), not conn.response — otherwise it mis-reports
    ldap_read_sd_failed on real AD (the mock keeps state on the connection)."""
    from types import SimpleNamespace

    from magister_api.ad.client import AdClient
    from magister_api.ad.security_descriptor import has_cannot_change_password

    sd_bytes = _dacl_only_sd([_allow_ace("S-1-5-21-1-2-3-1000")])

    class _FakeConn:
        def __init__(self) -> None:
            self.modified: bytes | None = None

        def search(self, *_a: object, **_k: object) -> tuple[object, ...]:
            entry = {
                "type": "searchResEntry",
                "raw_attributes": {"nTSecurityDescriptor": [sd_bytes]},
            }
            return (True, {"result": 0}, [entry], None)

        def modify(
            self,
            _dn: str,
            changes: dict[str, list[tuple[object, list[bytes]]]],
            controls: object = None,
        ) -> tuple[object, ...]:
            self.modified = changes["nTSecurityDescriptor"][0][1][0]
            return (True, {"result": 0}, [], None)

    client = AdClient(SimpleNamespace(ad_use_mock=False))  # type: ignore[arg-type]
    fake = _FakeConn()
    client._acquire_connection = lambda: (fake, False)  # type: ignore[assignment,method-assign]
    client._sync_set_cannot_change_password("CN=x,DC=t", True)

    assert fake.modified is not None
    assert has_cannot_change_password(fake.modified) is True
