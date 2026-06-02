from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, HttpUrl

from cockpit_api.models.instance import InstanceChannel


class InstanceCreate(BaseModel):
    slug: str
    display_name: str
    base_url: HttpUrl
    channel: InstanceChannel = InstanceChannel.stable


class InstanceUpdate(BaseModel):
    display_name: str | None = None
    base_url: HttpUrl | None = None
    channel: InstanceChannel | None = None


class InstanceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    slug: str
    display_name: str
    base_url: str
    channel: InstanceChannel
    deployed_version: str | None
    last_health_status: str | None
    last_health_at: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime
