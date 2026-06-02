from __future__ import annotations

import logging
import time

from cockpit_runner.cockpit_client import CockpitClient
from cockpit_runner.config import settings
from cockpit_runner.executor import UpdateFailed, execute_update

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("cockpit-runner")


def _process_once(client: CockpitClient) -> bool:
    req = client.claim_next()
    if req is None:
        return False
    logger.info("claimed request %s for %s", req.id, req.instance_slug)
    try:
        execute_update(req)
    except UpdateFailed as e:
        logger.error("update failed: %s", e)
        client.fail(req.id, str(e))
        return True
    except Exception as e:
        logger.exception("unexpected error")
        client.fail(req.id, f"unexpected: {e}")
        return True
    client.complete(req.id)
    logger.info("update %s completed", req.id)
    return True


def run() -> None:
    logger.info(
        "starting cockpit-runner (cockpit=%s, interval=%ds, dry_run=%s)",
        settings.cockpit_url,
        settings.poll_interval_s,
        settings.dry_run,
    )
    client = CockpitClient()
    try:
        while True:
            try:
                while _process_once(client):
                    pass
            except Exception:
                logger.exception("poll iteration failed")
            time.sleep(settings.poll_interval_s)
    finally:
        client.close()


if __name__ == "__main__":
    run()
