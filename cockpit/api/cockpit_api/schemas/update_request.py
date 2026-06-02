from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from cockpit_api.models.update_request import UpdateRequestStatus


class UpdateRequestCreate(BaseModel):
    target_version: str | None = None
    note: str | None = None


class UpdateRequestFail(BaseModel):
    error: str


class UpdateRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    instance_id: UUID
    target_version: str
    status: UpdateRequestStatus
    note: str | None
    requested_by: str | None
    requested_at: datetime
    completed_at: datetime | None
    last_error: str | None


class UpdateRequestRunnerOut(BaseModel):
    """Payload returned to the update-runner when claiming a request."""

    id: UUID
    instance_id: UUID
    instance_slug: str
    instance_base_url: str
    instance_channel: str
    target_version: str
    status: UpdateRequestStatus
    requested_at: datetime
