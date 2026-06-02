"""In-process TTL cache for read-heavy repository queries.

Scope and limits:

- *Single-instance only* — entries are not shared across pods. For a
  horizontally-scaled deployment, swap this primitive for Redis behind
  the same interface.
- Version-stamped invalidation: mutating services call :func:`bump_kind`
  with the affected ``kind`` token; future reads will miss until refilled.
- Read-after-write within the same request is unaffected because the
  cache key embeds the current version *at read time*.

Typical usage:

.. code-block:: python

    from magister_api.cache import get_cache, cache_key_for_scope, bump_kind

    cache = get_cache()
    key = cache_key_for_scope("classes_active", school_ids)
    cached = cache.get(key)
    if cached is not None:
        return cached
    rows = await repo.list_active()
    cache.set(key, rows, ttl_s=30.0)
    return rows

    # in the mutating service:
    bump_kind("classes_active")
"""

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Iterable
from dataclasses import dataclass
from threading import RLock
from typing import Any

DEFAULT_MAX_ENTRIES = 1024


@dataclass(slots=True)
class _Entry:
    value: Any
    expires_at: float


class TtlCache:
    """Thread-safe LRU+TTL cache, bounded by ``max_entries``."""

    def __init__(self, max_entries: int = DEFAULT_MAX_ENTRIES) -> None:
        self._max = max_entries
        self._data: OrderedDict[str, _Entry] = OrderedDict()
        self._lock = RLock()

    def get(self, key: str) -> Any | None:
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return None
            if entry.expires_at < time.monotonic():
                self._data.pop(key, None)
                return None
            self._data.move_to_end(key)
            return entry.value

    def set(self, key: str, value: Any, ttl_s: float) -> None:
        with self._lock:
            self._data[key] = _Entry(value=value, expires_at=time.monotonic() + ttl_s)
            self._data.move_to_end(key)
            while len(self._data) > self._max:
                self._data.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


_cache = TtlCache()
_versions: dict[str, int] = {}
_versions_lock = RLock()


def get_cache() -> TtlCache:
    return _cache


def _current_version(kind: str) -> int:
    with _versions_lock:
        return _versions.get(kind, 0)


def bump_kind(kind: str) -> None:
    """Invalidate all cache entries derived from ``kind``."""
    with _versions_lock:
        _versions[kind] = _versions.get(kind, 0) + 1


def cache_key_for_scope(kind: str, scope_ids: Iterable[int] | None) -> str:
    """Stable key combining ``kind``, its current version, and an
    ordered scope signature.

    ``scope_ids=None`` is used for an admin-scope (no filter).
    """
    version = _current_version(kind)
    if scope_ids is None:
        scope_part = "all"
    else:
        scope_part = ",".join(str(i) for i in sorted(scope_ids))
    return f"{kind}@v{version}:{scope_part}"
