"""Minimal self-relative Security-Descriptor DACL editor for the AD
"User cannot change password" setting.

In Active Directory "User cannot change password" is **not** a
``userAccountControl`` bit — it is enforced by two *deny* ACEs on the object's
DACL for the "User-Change-Password" control-access right, granted to
``NT AUTHORITY\\SELF`` (S-1-5-10) and ``Everyone`` (S-1-1-0). See MS-ADTS
3.1.1.5.3.3 and the ADUC "Account" tab checkbox.

This module edits **only the DACL**: callers read the ``nTSecurityDescriptor``
with the ``LDAP_SERVER_SD_FLAGS`` control set to ``DACL_SECURITY_INFORMATION``
(0x04), so the blob AD returns carries only the DACL (owner/group/SACL offsets
are zero). The edited blob is written back with the same control, so AD merges
only the DACL and never touches ownership/auditing.

The byte layout is small and fully unit-tested (`tests/unit/test_security_descriptor.py`)
so the transform is trustworthy even though the *live* AD write cannot be
exercised against a mock LDAP server.
"""

from __future__ import annotations

import struct
import uuid

# Control-access right GUID "User-Change-Password" (MS-ADTS 5.1.3.2.1).
CHANGE_PASSWORD_RIGHT = uuid.UUID("ab721a53-1e2f-11d0-9819-00aa0040529b")

# Well-known trustee SIDs that AD's ADUC toggles for this setting.
SID_SELF = "S-1-5-10"  # NT AUTHORITY\SELF
SID_WORLD = "S-1-1-0"  # Everyone

# ACE type / mask / flags for an object-specific deny ACE.
ACCESS_DENIED_OBJECT_ACE_TYPE = 0x06
ADS_RIGHT_DS_CONTROL_ACCESS = 0x00000100
ACE_OBJECT_TYPE_PRESENT = 0x00000001
ACE_INHERITED_OBJECT_TYPE_PRESENT = 0x00000002

# Self-relative SD control flags we care about.
SE_DACL_PRESENT = 0x0004
SE_SELF_RELATIVE = 0x8000

_SD_HEADER = struct.Struct("<BBHIIII")  # rev, sbz1, control, off_owner/group/sacl/dacl
_ACL_HEADER = struct.Struct("<BBHHH")  # rev, sbz1, size, ace_count, sbz2


def encode_sid(sid: str) -> bytes:
    """Encode a string SID (``S-1-5-10``) into its binary form."""
    parts = sid.split("-")
    if len(parts) < 3 or parts[0] != "S":
        raise ValueError(f"not a SID: {sid!r}")
    revision = int(parts[1])
    authority = int(parts[2])
    sub_auths = [int(p) for p in parts[3:]]
    out = bytearray()
    out.append(revision)
    out.append(len(sub_auths))
    out += authority.to_bytes(6, "big")
    for sa in sub_auths:
        out += sa.to_bytes(4, "little")
    return bytes(out)


def _sid_length(buf: bytes, offset: int) -> int:
    sub_count = buf[offset + 1]
    return 8 + 4 * sub_count


def _build_deny_ace(sid: str) -> bytes:
    """Build one ACCESS_DENIED_OBJECT_ACE denying Change-Password to ``sid``."""
    sid_bytes = encode_sid(sid)
    object_type = CHANGE_PASSWORD_RIGHT.bytes_le
    size = 4 + 4 + 4 + len(object_type) + len(sid_bytes)  # header+mask+flags+guid+sid
    ace = bytearray()
    ace.append(ACCESS_DENIED_OBJECT_ACE_TYPE)
    ace.append(0x00)  # AceFlags: no inheritance
    ace += struct.pack("<H", size)
    ace += struct.pack("<I", ADS_RIGHT_DS_CONTROL_ACCESS)
    ace += struct.pack("<I", ACE_OBJECT_TYPE_PRESENT)
    ace += object_type
    ace += sid_bytes
    return bytes(ace)


def _split_aces(acl: bytes) -> list[bytes]:
    """Return the raw ACE blobs inside an ACL body (after its 8-byte header)."""
    _rev, _sbz1, _size, count, _sbz2 = _ACL_HEADER.unpack_from(acl, 0)
    aces: list[bytes] = []
    pos = _ACL_HEADER.size
    for _ in range(count):
        if pos + 4 > len(acl):
            break
        ace_size = struct.unpack_from("<H", acl, pos + 2)[0]
        aces.append(acl[pos : pos + ace_size])
        pos += ace_size
    return aces


def _ace_is_change_password_deny(ace: bytes, sid: str) -> bool:
    """True if ``ace`` is a deny-Change-Password object ACE for ``sid``."""
    if len(ace) < 12 or ace[0] != ACCESS_DENIED_OBJECT_ACE_TYPE:
        return False
    mask = struct.unpack_from("<I", ace, 4)[0]
    flags = struct.unpack_from("<I", ace, 8)[0]
    if not (mask & ADS_RIGHT_DS_CONTROL_ACCESS):
        return False
    if not (flags & ACE_OBJECT_TYPE_PRESENT):
        return False
    pos = 12
    object_type = ace[pos : pos + 16]
    if object_type != CHANGE_PASSWORD_RIGHT.bytes_le:
        return False
    pos += 16
    if flags & ACE_INHERITED_OBJECT_TYPE_PRESENT:
        pos += 16
    ace_sid = ace[pos:]
    return ace_sid == encode_sid(sid)


def _pack_acl(revision: int, aces: list[bytes]) -> bytes:
    body = b"".join(aces)
    size = _ACL_HEADER.size + len(body)
    return _ACL_HEADER.pack(revision, 0, size, len(aces), 0) + body


def set_cannot_change_password(sd: bytes, *, deny: bool) -> bytes:
    """Return a new DACL-only self-relative SD with the deny-ACEs added/removed.

    ``sd`` must be a self-relative security descriptor carrying only a DACL
    (owner/group/SACL offsets zero), as returned by AD when read with the
    ``DACL_SECURITY_INFORMATION`` SD-flag. Idempotent: setting a value that is
    already in effect returns an equivalent SD.
    """
    if len(sd) < _SD_HEADER.size:
        raise ValueError("security descriptor too short")
    rev, sbz1, control, _off_owner, _off_group, _off_sacl, off_dacl = _SD_HEADER.unpack_from(sd, 0)
    if not (control & SE_SELF_RELATIVE):
        raise ValueError("not a self-relative security descriptor")
    if off_dacl == 0 or not (control & SE_DACL_PRESENT):
        raise ValueError("security descriptor has no DACL")

    acl = sd[off_dacl:]
    acl_rev = acl[0]
    aces = _split_aces(acl)

    # Drop any existing deny-Change-Password ACEs for SELF/WORLD; we rebuild them.
    kept = [
        a
        for a in aces
        if not (
            _ace_is_change_password_deny(a, SID_SELF) or _ace_is_change_password_deny(a, SID_WORLD)
        )
    ]

    if deny:
        # Explicit deny ACEs precede everything else (Windows canonical order).
        new_aces = [_build_deny_ace(SID_SELF), _build_deny_ace(SID_WORLD), *kept]
    else:
        new_aces = kept

    new_acl = _pack_acl(acl_rev, new_aces)
    new_off_dacl = _SD_HEADER.size
    header = _SD_HEADER.pack(rev, sbz1, control, 0, 0, 0, new_off_dacl)
    return header + new_acl


def has_cannot_change_password(sd: bytes) -> bool:
    """True if the DACL denies Change-Password to SELF or WORLD."""
    if len(sd) < _SD_HEADER.size:
        return False
    _, _, control, _, _, _, off_dacl = _SD_HEADER.unpack_from(sd, 0)
    if off_dacl == 0 or not (control & SE_DACL_PRESENT):
        return False
    for ace in _split_aces(sd[off_dacl:]):
        if _ace_is_change_password_deny(ace, SID_SELF) or _ace_is_change_password_deny(
            ace, SID_WORLD
        ):
            return True
    return False
