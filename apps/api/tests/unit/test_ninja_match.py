"""Matching policy: hostname first, then serial, ties → ambiguous."""

from __future__ import annotations

from magister_api.ninja.match import match_device, ninja_hostnames, ninja_serial


def _dev(id_: int, **kw: object) -> dict[str, object]:
    return {"id": id_, **kw}


def test_hostname_match_strips_domain_and_ignores_case() -> None:
    ninja = [_dev(1, systemName="PC-1.ad.local"), _dev(2, systemName="PC-2")]
    r = match_device(name="pc-1", serial_number=None, ninja_devices=ninja)
    assert r.matched and r.ninja_device_id == 1 and r.via == "hostname"


def test_hostname_wins_over_serial() -> None:
    # Serial would point elsewhere, but a hostname hit is preferred.
    ninja = [
        _dev(1, systemName="pc-1", biosSerialNumber="ZZZ"),
        _dev(2, systemName="other", biosSerialNumber="ABC123"),
    ]
    r = match_device(name="PC-1", serial_number="abc123", ninja_devices=ninja)
    assert r.ninja_device_id == 1 and r.via == "hostname"


def test_falls_back_to_serial_when_no_hostname_hit() -> None:
    ninja = [_dev(7, dnsName="unrelated", system={"serialNumber": "abc-123"})]
    r = match_device(name="not-present", serial_number="ABC-123", ninja_devices=ninja)
    assert r.ninja_device_id == 7 and r.via == "serial"


def test_ambiguous_hostname_yields_no_link() -> None:
    ninja = [_dev(1, systemName="pc-1"), _dev(2, dnsName="pc-1.other.local")]
    r = match_device(name="pc-1", serial_number=None, ninja_devices=ninja)
    assert not r.matched and r.ambiguous and r.via == "hostname"


def test_ambiguous_serial_yields_no_link() -> None:
    ninja = [_dev(1, biosSerialNumber="DUP"), _dev(2, serialNumber="dup")]
    r = match_device(name=None, serial_number="dup", ninja_devices=ninja)
    assert not r.matched and r.ambiguous and r.via == "serial"


def test_no_match_returns_empty() -> None:
    ninja = [_dev(1, systemName="a", biosSerialNumber="x")]
    r = match_device(name="b", serial_number="y", ninja_devices=ninja)
    assert not r.matched and r.via is None and not r.ambiguous


def test_blank_keys_never_match() -> None:
    # A Magister device with no name and no serial must never link.
    ninja = [_dev(1, systemName="", biosSerialNumber="")]
    r = match_device(name="", serial_number=None, ninja_devices=ninja)
    assert not r.matched


def test_hostname_and_serial_extractors_read_nested_system() -> None:
    dev = {"id": 3, "system": {"serialNumber": "s-9", "netbiosName": "HOST9"}}
    assert "host9" in ninja_hostnames(dev)
    assert ninja_serial(dev) == "S-9"
