"""Student password-reset request/response schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class StudentPasswordResetRequest(BaseModel):
    mode: Literal["generate", "manual"]
    manual_password: str | None = Field(
        default=None,
        min_length=12,
        max_length=128,
        description="Required when mode='manual'.",
    )
    force_change: bool = Field(
        default=True,
        description=(
            "Sets pwdLastSet=0 in AD so the student must change the PW at next logon. "
            "Default true; the KL may switch it off in manual mode (e.g. when the PW "
            "is already a memorable hand-out)."
        ),
    )

    @model_validator(mode="after")
    def _check_manual_password(self) -> StudentPasswordResetRequest:
        if self.mode == "manual" and not self.manual_password:
            raise ValueError("manual_password is required when mode='manual'")
        if self.mode == "generate" and self.manual_password is not None:
            raise ValueError("manual_password must be omitted when mode='generate'")
        return self


class StudentPasswordResetResponse(BaseModel):
    """Successful reset.

    The temporary password is returned ONCE in generate-mode so the KL can
    hand it to the student. It is never persisted in audit, never logged,
    and never returned a second time.
    """

    mode: Literal["generate", "manual"]
    force_change: bool
    temp_password: str | None = Field(
        default=None,
        description="Set only when mode='generate'. Omitted in manual mode.",
    )


# Teacher-PW-reset shares the exact same request/response shape as the
# student endpoint (mode/manual_password/force_change → temp_password). The
# subclasses exist only so OpenAPI emits distinct model names per resource.
class TeacherPasswordResetRequest(StudentPasswordResetRequest):
    pass


class TeacherPasswordResetResponse(StudentPasswordResetResponse):
    pass


__all__ = [
    "StudentPasswordResetRequest",
    "StudentPasswordResetResponse",
    "TeacherPasswordResetRequest",
    "TeacherPasswordResetResponse",
]
