from __future__ import annotations

import logging
import shlex
import subprocess
from urllib.parse import urlparse

import httpx

from cockpit_runner.cockpit_client import ClaimedRequest
from cockpit_runner.config import settings

logger = logging.getLogger(__name__)


class UpdateFailed(Exception):  # noqa: N818 — domain term, kept for log readability
    pass


def _instance_host(base_url: str) -> str:
    parsed = urlparse(base_url)
    if not parsed.hostname:
        raise UpdateFailed(f"cannot parse host from base_url: {base_url}")
    return parsed.hostname


def _ssh(host: str, command: str) -> tuple[int, str, str]:
    full = ["ssh", "-o", "BatchMode=yes", f"{settings.ssh_user}@{host}", command]
    if settings.dry_run:
        logger.info("[dry-run] %s", shlex.join(full))
        return 0, "", ""
    proc = subprocess.run(full, capture_output=True, text=True, timeout=600, check=False)
    return proc.returncode, proc.stdout, proc.stderr


def _run(host: str, command: str, *, step: str) -> None:
    rc, _out, _err = _ssh(host, command)
    if rc != 0:
        # Only the step name and rc are persisted via UpdateFailed → cockpit
        # last_error. Stdout/stderr can contain operational secrets
        # (paths, env values) and stays in the runner's journald log only
        # (hardening-audit M-02).
        logger.error("%s failed on %s (rc=%d): %s", step, host, rc, _err.strip() or _out.strip())
        raise UpdateFailed(f"{step}_failed (rc={rc})")


def execute_update(req: ClaimedRequest) -> None:
    host = _instance_host(req.instance_base_url)
    logger.info("update %s → %s on %s", req.instance_slug, req.target_version, host)

    _run(
        host,
        "cd /opt/magister && pg_dump -U magister magister "
        f"| gzip > /backup/before-{req.target_version}-$(date +%Y%m%d-%H%M).sql.gz",
        step="pg_dump",
    )
    _run(
        host,
        f"cd /opt/magister && IMAGE_TAG={shlex.quote(req.target_version)} docker compose pull",
        step="docker pull",
    )
    _run(
        host,
        f"cd /opt/magister && IMAGE_TAG={shlex.quote(req.target_version)} docker compose up -d",
        step="docker up",
    )

    if settings.dry_run:
        return

    healthz = req.instance_base_url.rstrip("/") + "/api/healthz"
    try:
        r = httpx.get(healthz, timeout=settings.http_timeout_s)
        r.raise_for_status()
        deployed = r.json().get("version")
        if deployed != req.target_version:
            raise UpdateFailed("smoke_test_version_mismatch")
    except httpx.HTTPError as e:
        logger.error("smoke-test http error: %s", e)
        raise UpdateFailed("smoke_test_http_error") from e
