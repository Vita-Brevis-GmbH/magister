from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from cockpit_api.models.tenant import (
    SLUG_PATTERN,
    IsolationMode,
    TenantProfile,
    TenantStatus,
)


class TenantCreate(BaseModel):
    slug: str
    name: str = Field(min_length=1, max_length=200)
    hostname: str = Field(min_length=3, max_length=253)
    customer_no: str | None = Field(default=None, max_length=64)
    profile: TenantProfile = TenantProfile.school
    isolation_mode: IsolationMode = IsolationMode.schema_only

    @field_validator("slug")
    @classmethod
    def _check_slug(cls, value: str) -> str:
        # Dasselbe Muster wie in der Datenebene: aus dem Slug werden Schema-
        # und Rollenname, und die gehen unquotiert in SQL.
        if not SLUG_PATTERN.match(value):
            raise ValueError(
                "slug muss 2 bis 31 Zeichen lang sein, nur Kleinbuchstaben, Ziffern "
                "und Unterstrich enthalten und mit einem Buchstaben beginnen"
            )
        return value

    @field_validator("hostname")
    @classmethod
    def _normalize_hostname(cls, value: str) -> str:
        return value.strip().lower()


class TenantSuspend(BaseModel):
    # Pflichtfeld: der Grund ist für den Kunden sichtbar. Sperren ohne
    # Begründung ist der Anfang von Willkür.
    reason: str = Field(min_length=3, max_length=500)


class TenantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    slug: str
    name: str
    customer_no: str | None
    hostname: str
    status: TenantStatus
    profile: TenantProfile
    isolation_mode: IsolationMode
    dsn_ref: str
    schema_name: str
    db_role: str
    schema_version: str | None
    suspended_at: datetime | None
    suspended_reason: str | None
    created_at: datetime
    updated_at: datetime


class ProvisioningJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    status: str
    last_completed_step: str | None
    steps: list[dict[str, Any]]
    last_error: str | None
    attempts: int
    created_at: datetime
    updated_at: datetime


class TenantProvisionResult(BaseModel):
    """Ergebnis eines Bereitstellungslaufs.

    ``role_password`` kommt **genau einmal** — beim Anlegen der Rolle oder beim
    Drehen. Es steht nicht in der Konsolen-Datenbank und ist über die API
    später nicht mehr abrufbar. Wer es verliert, dreht es neu.
    """

    tenant: TenantOut
    job: ProvisioningJobOut
    role_password: str | None = None
    next_step: str | None = None


class TenantRegistryEntry(BaseModel):
    """Eine Zeile der Registry, wie die Datenebene sie braucht.

    Bewusst **ohne** DSN: nur der Verweis. Die Datenebene setzt den DSN aus
    ihrem eigenen Geheimnisspeicher zusammen — ein Abruf dieser Liste gibt
    also niemandem Datenbankzugang (ADR-0013 D4).
    """

    #: Die Id in der Konsole. Kein Geheimnis, aber die Datenebene braucht sie,
    #: um Connector-Aufträge zu adressieren (ADR-0014).
    id: UUID
    slug: str
    name: str
    hostname: str
    status: TenantStatus
    dsn_ref: str
    schema_name: str
    db_role: str
    schema_version: str | None
