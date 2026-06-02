import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from cockpit_api.routers import instances, update_requests
from cockpit_api.services.health_poller import health_poller_loop
from cockpit_api.services.release_poller import release_poller_loop


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    tasks = [
        asyncio.create_task(health_poller_loop()),
        asyncio.create_task(release_poller_loop()),
    ]
    try:
        yield
    finally:
        for t in tasks:
            t.cancel()


app = FastAPI(title="Vita Brevis Cockpit", version="0.2.0", lifespan=lifespan)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(instances.router, prefix="/api")
app.include_router(update_requests.router, prefix="/api")
