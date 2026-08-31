"""Lightweight per-process runtime facts for a container-split deployment.

Answers "what is THIS container doing?" — which modules it mounts, whether it
owns the AD sync loop, its DB-pool footprint and resident memory — without any
extra dependency. Exposed by ``main`` at ``GET /runtime`` (internal only, like
``/healthz``) so each split container is individually inspectable.
"""

from __future__ import annotations

import resource
from typing import Any

from sqlalchemy.pool import QueuePool

from magister_api import db
from magister_api.config import Settings
from magister_api.modules.registry import enabled_modules


def _rss_mb() -> float:
    # ru_maxrss is kilobytes on Linux, bytes on macOS. We run on Linux.
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)


def _pool_stats() -> dict[str, int]:
    engine = db._engine  # noqa: SLF001 — read-only introspection of the process pool
    if engine is None:
        return {}
    pool = engine.pool
    # The default async pool is AsyncAdaptedQueuePool (a QueuePool subclass); a
    # NullPool (tests) exposes none of these counters, so report nothing.
    if not isinstance(pool, QueuePool):
        return {}
    return {
        "size": pool.size(),
        "checkedout": pool.checkedout(),
        "overflow": pool.overflow(),
        "checkedin": pool.checkedin(),
    }


def runtime_snapshot(settings: Settings) -> dict[str, Any]:
    """Facts about this running container: mounted modules, scheduler ownership,
    DB-pool footprint and resident memory."""
    return {
        "modules": [m.id for m in enabled_modules(settings.container_modules)],
        "scheduler_owner": settings.run_scheduler,
        "db_pool": _pool_stats(),
        "rss_mb": _rss_mb(),
    }


__all__ = ["runtime_snapshot"]
