"""Match a Magister device to a NinjaOne device — hostname first, then serial.

Pure functions, no I/O, so the matching policy is unit-tested in isolation.

Match order (the user's chosen strategy):
1. **Hostname** — Magister ``Device.name`` vs the NinjaOne device's
   ``systemName``/``dnsName`` (domain suffix stripped, case-insensitive).
2. **Serial** — Magister ``Device.serial_number`` vs the NinjaOne serial
   (read defensively from a few known keys), case-insensitive.

A key that would match *more than one* NinjaOne device is treated as
**ambiguous** and yields no automatic link — the admin links those by hand,
rather than the connector guessing.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

# NinjaOne payload keys we read hostnames / serials from, most-specific first.
_HOSTNAME_KEYS = ("systemName", "dnsName", "netbiosName", "name")
_SERIAL_KEYS = ("biosSerialNumber", "serialNumber", "chassisSerialNumber")


def _norm_host(value: str | None) -> str:
    """Lowercase, trimmed, domain-suffix stripped (``pc1.ad.local`` → ``pc1``)."""
    host = (value or "").strip().lower()
    return host.split(".", 1)[0] if host else ""


def _norm_serial(value: str | None) -> str:
    return (value or "").strip().upper()


def _get_nested(dev: dict[str, Any], key: str) -> Any:
    """Read ``key`` from the device dict or its ``system`` sub-object."""
    if key in dev:
        return dev[key]
    system = dev.get("system")
    if isinstance(system, dict) and key in system:
        return system[key]
    return None


def ninja_hostnames(dev: dict[str, Any]) -> set[str]:
    """Every normalized hostname a NinjaOne device is known by."""
    out: set[str] = set()
    for key in _HOSTNAME_KEYS:
        val = _get_nested(dev, key)
        if isinstance(val, str):
            norm = _norm_host(val)
            if norm:
                out.add(norm)
    return out


def ninja_serial(dev: dict[str, Any]) -> str:
    """The first non-empty normalized serial found on a NinjaOne device."""
    for key in _SERIAL_KEYS:
        val = _get_nested(dev, key)
        if isinstance(val, str):
            norm = _norm_serial(val)
            if norm:
                return norm
    return ""


@dataclass(frozen=True)
class MatchResult:
    """Outcome of matching one Magister device against the NinjaOne inventory."""

    ninja_device_id: int | None
    via: str | None  # "hostname" | "serial" | None
    ambiguous: bool = False

    @property
    def matched(self) -> bool:
        return self.ninja_device_id is not None


def _device_id(dev: dict[str, Any]) -> int | None:
    val = dev.get("id")
    return val if isinstance(val, int) else None


def match_device(
    *,
    name: str | None,
    serial_number: str | None,
    ninja_devices: Iterable[dict[str, Any]],
) -> MatchResult:
    """Find the single NinjaOne device for a Magister device, or none.

    Hostname is tried first; only if it finds nothing is serial tried. A tie at
    either stage returns ``ambiguous`` with no id.
    """
    devices = list(ninja_devices)

    mhost = _norm_host(name)
    if mhost:
        hits = [d for d in devices if mhost in ninja_hostnames(d)]
        if len(hits) == 1:
            return MatchResult(ninja_device_id=_device_id(hits[0]), via="hostname")
        if len(hits) > 1:
            return MatchResult(ninja_device_id=None, via="hostname", ambiguous=True)

    mserial = _norm_serial(serial_number)
    if mserial:
        hits = [d for d in devices if ninja_serial(d) == mserial]
        if len(hits) == 1:
            return MatchResult(ninja_device_id=_device_id(hits[0]), via="serial")
        if len(hits) > 1:
            return MatchResult(ninja_device_id=None, via="serial", ambiguous=True)

    return MatchResult(ninja_device_id=None, via=None)


__all__ = ["MatchResult", "match_device", "ninja_hostnames", "ninja_serial"]
