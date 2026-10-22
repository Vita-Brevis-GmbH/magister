"""``/admin/mail`` — Stand des Mailversands und Testmail.

Immer gemountet, auch gehostet: die Einstellungen selbst kommen dort aus der
Konsole, aber ob der Versand funktioniert, will der Kunden-Admin prüfen können.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.audit.service import AuditService
from magister_api.auth.current_user import AuthenticatedUser
from magister_api.auth.rbac import require_admin
from magister_api.config import Settings, get_settings
from magister_api.db import get_session
from magister_api.mail import MailError, MailMessage, mail_config_from, send_mail
from magister_api.routers._helpers import _ip_request_id
from magister_api.services.app_settings import AppSettingsService
from magister_api.services.user_preferences import UserPreferenceService

router = APIRouter(prefix="/admin/mail", tags=["admin"])


class MailStatusOut(BaseModel):
    transport: str
    sender: str | None
    sender_name: str | None
    ready: bool
    # Welche Angaben fehlen (Feldnamen), leer = bereit.
    missing: list[str]
    expiry_notice_enabled: bool
    expiry_notice_days: list[int]
    platform_managed: bool


class TestMailIn(BaseModel):
    to: str = Field(max_length=320)

    @field_validator("to")
    @classmethod
    def _addr(cls, v: str) -> str:
        v = v.strip()
        if "@" not in v or " " in v or "." not in v.rsplit("@", 1)[-1]:
            raise ValueError("to must be an e-mail address")
        return v


class TestMailOut(BaseModel):
    ok: bool
    error: str | None = None


_TEST_TEXT = {
    "de": ("Magister: Testmail", "Diese Testmail bestätigt, dass Magister Mails versenden kann."),
    "fr": ("Magister : e-mail de test", "Cet e-mail de test confirme que Magister peut envoyer."),
    "it": (
        "Magister: e-mail di prova",
        "Questa e-mail di prova conferma che Magister può inviare.",
    ),
    "en": ("Magister: test e-mail", "This test e-mail confirms that Magister can send e-mail."),
}


@router.get("/status", response_model=MailStatusOut)
async def mail_status(
    user: AuthenticatedUser = Depends(require_admin),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> MailStatusOut:
    eff = await AppSettingsService(session, settings).get_effective()
    cfg = mail_config_from(eff)
    missing = cfg.missing()
    return MailStatusOut(
        transport=cfg.transport,
        sender=cfg.sender,
        sender_name=cfg.sender_name,
        ready=not missing,
        missing=missing,
        expiry_notice_enabled=eff.expiry_notice_enabled,
        expiry_notice_days=list(eff.expiry_notice_days),
        platform_managed=bool(settings.console_registry_url),
    )


@router.post("/test", response_model=TestMailOut)
async def send_test_mail(
    request: Request,
    payload: TestMailIn,
    user: AuthenticatedUser = Depends(require_admin),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> TestMailOut:
    eff = await AppSettingsService(session, settings).get_effective()
    cfg = mail_config_from(eff)
    lang = "de"
    if user.ad_object_guid:
        lang = (await UserPreferenceService(session, settings).get(user.ad_object_guid)).language
    subject, text = _TEST_TEXT.get(lang, _TEST_TEXT["de"])
    error: str | None = None
    try:
        await send_mail(
            cfg, MailMessage(to=payload.to, subject=subject, html=f"<p>{text}</p>", text=text)
        )
    except MailError as exc:
        error = str(exc)
    ip, request_id = _ip_request_id(request)
    await AuditService(session, settings).emit(
        action="mail_test_sent",
        target_kind="mail",
        target_id="test",
        actor_upn=user.upn,
        actor_object_guid=user.ad_object_guid,
        school_id=None,
        ip=ip,
        request_id=request_id,
        payload={
            "transport": cfg.transport,
            "recipient": payload.to,
            "ok": error is None,
            "error": error,
        },
    )
    return TestMailOut(ok=error is None, error=error)


__all__ = ["router"]
