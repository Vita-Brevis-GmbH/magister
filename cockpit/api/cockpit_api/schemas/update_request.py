from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from cockpit_api.models.update_request import UpdateRequestStatus


class UpdateRequestCreate(BaseModel):
    target_version: str | None = None
    note: str | None = None


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
