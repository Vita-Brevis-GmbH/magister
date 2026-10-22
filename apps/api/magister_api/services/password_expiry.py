"""Erinnerung vor dem Passwort-Ablauf — per Mail, an alle mit Mailadresse.

Windows und Microsoft 365 melden einen nahen Ablauf kaum noch. Magister kennt
das Ablaufdatum aus dem AD (``msDS-UserPasswordExpiryTimeComputed``) und
schreibt an den Schwellen (Vorgabe 14, 7 und 1 Tag vorher) eine Mail. Den
Text — samt Anleitung, wie das Passwort geändert wird — pflegt der Kunde als
Vorlage ``password_expiry_notice``.

Jede Schwelle geht genau einmal hinaus: das Versandprotokoll
(``password_expiry_notices``) hält Konto, Ablaufzeitpunkt und Schwelle fest.
Setzt jemand ein neues Passwort, ändert sich der Ablauf und es beginnt von
vorn. Konten ohne Mailadresse werden protokolliert und erscheinen in der
Übersicht, damit jemand sie anders erreicht.
"""

from __future__ import annotations

import asyncio
import html
import logging
import math
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from magister_api.audit.service import AuditService
from magister_api.config import Settings
from magister_api.mail import MailConfig, MailError, MailMessage, mail_config_from, send_mail
from magister_api.models.auth import AdUserCache
from magister_api.models.base import utcnow
from magister_api.models.password_expiry_notice import (
    NOTICE_FAILED,
    NOTICE_NO_MAIL,
    NOTICE_SENT,
    PasswordExpiryNotice,
)
from magister_api.models.school import School
from magister_api.models.user_preferences import DEFAULT_LANGUAGE, UserPreference
from magister_api.services.app_settings import AppSettingsService
from magister_api.services.document_templates import (
    PLACEHOLDERS,
    DocumentTemplateService,
    TemplateRenderError,
    starters_for_profile,
)
from magister_api.tenancy.context import get_engines, get_registry
from magister_api.tenancy.keys import attach_keys, resolve_tenant_keys
from magister_api.tenancy.registry import Tenant, TenantRegistry
from magister_api.tenancy.scope import apply_tenant_scope

logger = logging.getLogger(__name__)

TEMPLATE_KEY = "password_expiry_notice"
ACTOR = "system:password-expiry"
#: Höchstens so viele Mails je Kunde und Lauf — der Rest folgt im nächsten.
MAX_PER_RUN = 300
#: Ein gescheiterter Versand wird frühestens nach dieser Zeit wiederholt.
RETRY_AFTER = timedelta(hours=1)
#: Gesendet wird tagsüber (Schweizer Zeit), nicht um drei Uhr nachts.
SEND_WINDOW = (7, 19)
LOCAL_TZ = ZoneInfo("Europe/Zurich")
RUN_EVERY_SECONDS = 3600.0
TICK_SECONDS = 60.0

Sender = Callable[[MailConfig, MailMessage], Awaitable[None]]


@dataclass
class NoticeRunResult:
    sent: int = 0
    failed: int = 0
    no_mail: int = 0
    #: Warum nichts geschah ("disabled", "not_configured"), sonst None.
    skipped: str | None = None
    errors: list[str] = field(default_factory=list)


def days_left(expires_at: datetime, now: datetime) -> int:
    """Ganze Tage bis zum Ablauf, aufgerundet (in 6 Stunden = 1 Tag)."""
    return max(0, math.ceil((expires_at - now).total_seconds() / 86400))


def due_threshold(left: int, thresholds: tuple[int, ...]) -> int | None:
    """Die engste erreichte Schwelle: bei 5 Tagen und (14, 7, 1) ist es 7."""
    reached = [t for t in thresholds if left <= t]
    return min(reached) if reached else None


def _plain_text(body_html: str) -> str:
    text = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</h\d>", "\n", body_html)
    text = re.sub(r"(?i)<li[^>]*>", "- ", text)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\n{3,}", "\n\n", html.unescape(text)).strip()


def _blank_context() -> dict[str, object]:
    """Jeder deklarierte Platzhalter mit einem leeren Wert.

    Eine eigene Vorlage darf jeden Platzhalter benutzen (der Editor prüft
    gegen alle); im Versand fehlte sonst etwa ``class_.name`` und die
    StrictUndefined-Sandbox bräche ab.
    """
    ctx: dict[str, object] = {}
    for name in PLACEHOLDERS:
        head, _, tail = name.partition(".")
        if tail:
            sub = ctx.setdefault(head, {})
            assert isinstance(sub, dict)
            sub[tail] = ""  # type: ignore[index]
        else:
            ctx[head] = ""
    ctx["recipient"] = []
    return ctx


class PasswordExpiryNotifier:
    def __init__(
        self, session: AsyncSession, settings: Settings, *, sender: Sender = send_mail
    ) -> None:
        self.session = session
        self.settings = settings
        self.sender = sender
        self.audit = AuditService(session, settings)
        self.templates = DocumentTemplateService(session, settings)

    async def run(self, *, now: datetime | None = None) -> NoticeRunResult:
        now = now or utcnow()
        result = NoticeRunResult()
        app = AppSettingsService(self.session, self.settings)
        eff = await app.get_effective()
        if not eff.expiry_notice_enabled:
            result.skipped = "disabled"
            return result
        config = mail_config_from(eff)
        if config.missing():
            result.skipped = "not_configured"
            return result
        thresholds = tuple(sorted(eff.expiry_notice_days, reverse=True)) or (14, 7, 1)
        profile = (await app.get_module_settings()).instance_profile
        horizon = now + timedelta(days=max(thresholds))

        # scope-bypass: Systemauftrag über alle Konten des Kunden, nicht
        # die Sicht einer Person; die Mandantentrennung leistet der
        # search_path dieser Sitzung.
        users = (
            (
                await self.session.execute(
                    select(AdUserCache)
                    .where(
                        AdUserCache.enabled.is_(True),
                        AdUserCache.password_never_expires.is_(False),
                        AdUserCache.ad_missing_since.is_(None),
                        AdUserCache.password_expires_at.is_not(None),
                        AdUserCache.password_expires_at > now,
                        AdUserCache.password_expires_at <= horizon,
                    )
                    .order_by(AdUserCache.password_expires_at)
                )
            )
            .scalars()
            .all()
        )
        schools: dict[int, School | None] = {}
        for user in users:
            if result.sent + result.failed >= MAX_PER_RUN:
                break
            assert user.password_expires_at is not None
            left = days_left(user.password_expires_at, now)
            threshold = due_threshold(left, thresholds)
            if threshold is None:
                continue
            existing = await self._notice(user, threshold)
            if existing is not None and not (
                existing.status == NOTICE_FAILED and now - existing.created_at >= RETRY_AFTER
            ):
                continue
            if not user.mail:
                if existing is None:
                    await self._record(user, threshold, NOTICE_NO_MAIL, None, None, left)
                    result.no_mail += 1
                continue
            if user.school_id is not None and user.school_id not in schools:
                schools[user.school_id] = await self.session.get(School, user.school_id)
            school = schools.get(user.school_id) if user.school_id is not None else None
            try:
                message = await self._message(user, school, left, profile)
                await self.sender(config, message)
            except (MailError, TemplateRenderError) as exc:
                error = str(exc)[:500]
                result.failed += 1
                result.errors.append(error)
                await self._record(user, threshold, NOTICE_FAILED, user.mail, error, left, existing)
                continue
            result.sent += 1
            await self._record(user, threshold, NOTICE_SENT, user.mail, None, left, existing)
        return result

    async def _notice(self, user: AdUserCache, threshold: int) -> PasswordExpiryNotice | None:
        return (
            await self.session.execute(
                select(PasswordExpiryNotice).where(
                    PasswordExpiryNotice.ad_object_guid == user.ad_object_guid,
                    PasswordExpiryNotice.expires_at == user.password_expires_at,
                    PasswordExpiryNotice.threshold_days == threshold,
                )
            )
        ).scalar_one_or_none()

    async def _record(
        self,
        user: AdUserCache,
        threshold: int,
        status: str,
        recipient: str | None,
        error: str | None,
        left: int,
        existing: PasswordExpiryNotice | None = None,
    ) -> None:
        assert user.password_expires_at is not None
        if existing is None:
            self.session.add(
                PasswordExpiryNotice(
                    ad_object_guid=user.ad_object_guid,
                    expires_at=user.password_expires_at,
                    threshold_days=threshold,
                    status=status,
                    recipient=recipient,
                    error=error,
                )
            )
        else:
            existing.status = status
            existing.recipient = recipient
            existing.error = error
            existing.created_at = utcnow()
        await self.session.flush()
        await self.audit.emit(
            action=f"expiry_notice_{status}",
            target_kind="ad_user",
            target_id=user.ad_object_guid,
            actor_upn=ACTOR,
            actor_object_guid=None,
            school_id=user.school_id,
            ip=None,
            request_id=f"expiry:{user.ad_object_guid}"[:36],
            payload={
                "threshold_days": threshold,
                "days_left": left,
                "expires_on": user.password_expires_at.date().isoformat(),
                "error": error,
            },
        )

    async def _message(
        self, user: AdUserCache, school: School | None, left: int, profile: str
    ) -> MailMessage:
        assert user.password_expires_at is not None and user.mail
        pref = await self.session.get(UserPreference, user.ad_object_guid)
        language = pref.language if pref is not None else DEFAULT_LANGUAGE
        resolved = await self.templates.resolve_effective(
            key=TEMPLATE_KEY, language=language, school_id=user.school_id
        )
        if resolved is None and language != DEFAULT_LANGUAGE:
            resolved = await self.templates.resolve_effective(
                key=TEMPLATE_KEY, language=DEFAULT_LANGUAGE, school_id=user.school_id
            )
        starter = starters_for_profile(profile)[TEMPLATE_KEY]
        subject_src = (resolved.subject if resolved else None) or starter["subject"]
        body_src = resolved.body_html if resolved else starter["body_html"]
        shown = (
            user.display_name
            or " ".join(p for p in (user.given_name, user.surname) if p)
            or user.upn
        )
        ctx = _blank_context()
        ctx.update(
            {
                "person": {"display_name": shown, "upn": user.upn},
                "expires_on": user.password_expires_at.astimezone(LOCAL_TZ).strftime("%d.%m.%Y"),
                "days_left": left,
                "today": utcnow().astimezone(LOCAL_TZ).strftime("%d.%m.%Y"),
                "school": {
                    "name": school.name if school else "",
                    "locality": (school.city or "") if school else "",
                    "address_line": (school.street or "") if school else "",
                    "contact": (school.phone or "") if school else "",
                },
            }
        )
        subject = DocumentTemplateService.render_body(subject_src, ctx).strip()
        ctx["subject"] = subject
        body = DocumentTemplateService.render_body(body_src, ctx)
        return MailMessage(to=user.mail, subject=subject, html=body, text=_plain_text(body))


# --- Zeitplan ------------------------------------------------------------------


def _default_session_factory(tenant: Tenant) -> async_sessionmaker[AsyncSession]:
    return get_engines().sessionmaker_for(tenant)


def in_send_window(now: datetime) -> bool:
    hour = now.astimezone(LOCAL_TZ).hour
    return SEND_WINDOW[0] <= hour < SEND_WINDOW[1]


async def notify_tenant(
    base_settings: Settings,
    tenant: Tenant,
    *,
    single_tenant: bool,
    session_factory: Callable[[Tenant], async_sessionmaker[AsyncSession]] = (
        _default_session_factory
    ),
    sender: Sender = send_mail,
) -> NoticeRunResult:
    keys = resolve_tenant_keys(
        tenant.slug,
        fallback_audit_key=base_settings.audit_key.get_secret_value(),
        fallback_audit_key_id=base_settings.audit_key_id,
        fallback_secrets_key=base_settings.app_secrets_key(),
        single_tenant=single_tenant,
    )
    async with session_factory(tenant)() as session:
        attach_keys(session, keys)
        await apply_tenant_scope(session, tenant, extension_schema=base_settings.extension_schema)
        result = await PasswordExpiryNotifier(session, base_settings, sender=sender).run()
        await session.commit()
    if result.sent or result.failed or result.no_mail:
        logger.info(
            "Ablauf-Erinnerung %s: %d gesendet, %d gescheitert, %d ohne Mailadresse",
            tenant.slug,
            result.sent,
            result.failed,
            result.no_mail,
        )
    return result


async def run_password_expiry_loop(
    base_settings: Settings,
    *,
    stop_event: asyncio.Event,
    read_registry: Callable[[], TenantRegistry] = get_registry,
) -> None:
    """Stündlich, tagsüber: jeden bedienten Kunden einmal durchgehen."""
    logger.info("Ablauf-Erinnerung gestartet")
    loop = asyncio.get_running_loop()
    next_run = loop.time() + 120.0  # nach dem Start erst den AD-Abgleich lassen
    while not stop_event.is_set():
        if loop.time() >= next_run:
            next_run = loop.time() + RUN_EVERY_SECONDS
            if in_send_window(utcnow()):
                try:
                    tenants = list(read_registry().tenants)
                except Exception:
                    logger.exception("Kundenliste für die Ablauf-Erinnerung nicht lesbar")
                    tenants = []
                for tenant in tenants:
                    if stop_event.is_set() or not tenant.status.serves_requests:
                        continue
                    try:
                        await notify_tenant(base_settings, tenant, single_tenant=len(tenants) == 1)
                    except Exception:
                        # Ein Kunde, der stolpert, hält die anderen nicht auf.
                        logger.exception("Ablauf-Erinnerung für %s gescheitert", tenant.slug)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=TICK_SECONDS)
        except TimeoutError:
            continue
    logger.info("Ablauf-Erinnerung gestoppt")


__all__ = [
    "NoticeRunResult",
    "PasswordExpiryNotifier",
    "days_left",
    "due_threshold",
    "in_send_window",
    "notify_tenant",
    "run_password_expiry_loop",
]
