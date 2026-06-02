import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from cockpit_api.routers import instances
from cockpit_api.services.health_poller import health_poller_loop


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    task = asyncio.create_task(health_poller_loop())
    try:
        yield
    finally:
        task.cancel()


app = FastAPI(title="Vita Brevis Cockpit", version="0.1.0", lifespan=lifespan)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(instances.router, prefix="/api")
