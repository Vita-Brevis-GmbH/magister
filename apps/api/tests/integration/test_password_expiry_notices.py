"""Erinnerung vor dem Passwort-Ablauf: Schwellen, genau einmal, ohne Postfach, Fehler."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.config import Settings
from magister_api.mail import MailConfig, MailError, MailMessage
from magister_api.models.app_settings import AppSettings
from magister_api.models.audit import AuditEvent
from magister_api.models.auth import AdUserCache
from magister_api.models.password_expiry_notice import PasswordExpiryNotice
from magister_api.services.document_templates import DocumentTemplateService
from magister_api.services.password_expiry import (
    PasswordExpiryNotifier,
    days_left,
    due_threshold,
    in_send_window,
)

pytestmark = pytest.mark.postgres

NOW = datetime(2026, 10, 22, 8, 0, tzinfo=UTC)


class Outbox:
    def __init__(self, fail: bool = False) -> None:
        self.sent: list[MailMessage] = []
        self.fail = fail

    async def __call__(self, config: MailConfig, message: MailMessage) -> None:
        if self.fail:
            raise MailError("smtp: authentication failed")
        self.sent.append(message)


def _guid(n: int) -> str:
    return f"00000000-0000-0000-0000-0000000e1{n:03d}"


async def _setup(db: AsyncSession, school_a: int, *, enabled: bool = True) -> None:
    await db.execute(
        update(AppSettings)
        .where(AppSettings.id == 1)
        .values(
            expiry_notice_enabled=enabled,
            expiry_notice_days=[14, 7, 1],
            mail_transport="smtp",
            mail_from="noreply@schule.ch",
            smtp_host="mail.schule.ch",
        )
    )
    people = [
        # (n, mail, Tage bis Ablauf, never_expires, enabled)
        (1, "lea@schule.ch", 5, False, True),  # Schwelle 7
        (2, None, 6, False, True),  # kein Postfach
        (3, "tim@schule.ch", 30, False, True),  # noch nicht fällig
        (4, "off@schule.ch", 3, False, False),  # deaktiviert
        (5, "nie@schule.ch", 3, True, True),  # läuft nie ab
    ]
    for n, mail, days, never, enabled_ in people:
        db.add(
            AdUserCache(
                ad_object_guid=_guid(n),
                school_id=school_a,
                upn=f"p{n}@schule.ch",
                given_name="Lea" if n == 1 else "X",
                surname="Muster",
                mail=mail,
                kind="teacher",
                enabled=enabled_,
                password_never_expires=never,
                password_expires_at=NOW + timedelta(days=days, hours=-2),
            )
        )
    await db.commit()


async def _notices(db: AsyncSession) -> list[tuple[str, int, str]]:
    rows = (await db.execute(select(PasswordExpiryNotice))).scalars().all()
    return sorted((r.ad_object_guid, r.threshold_days, r.status) for r in rows)


def test_threshold_and_window_helpers() -> None:
    assert days_left(NOW + timedelta(hours=6), NOW) == 1
    assert due_threshold(5, (14, 7, 1)) == 7
    assert due_threshold(1, (14, 7, 1)) == 1
    assert due_threshold(20, (14, 7, 1)) is None
    assert in_send_window(datetime(2026, 10, 22, 6, 0, tzinfo=UTC))  # 08:00 in Zürich
    assert not in_send_window(datetime(2026, 10, 22, 22, 0, tzinfo=UTC))


async def test_one_mail_per_threshold_and_no_mailbox_is_recorded(
    db_session: AsyncSession, app_settings: Settings, school_a: int
) -> None:
    await _setup(db_session, school_a)
    outbox = Outbox()
    result = await PasswordExpiryNotifier(db_session, app_settings, sender=outbox).run(now=NOW)
    await db_session.commit()
    assert (result.sent, result.no_mail, result.failed) == (1, 1, 0)
    mail = outbox.sent[0]
    assert mail.to == "lea@schule.ch"
    assert mail.subject == "Ihr Passwort läuft in 5 Tagen ab"
    # 27.10. 06:00 UTC ist 08:00 in Zürich — das Datum gilt in Schweizer Zeit.
    assert "27.10.2026" in mail.html and "Strg + Alt + Entf" in mail.text
    assert await _notices(db_session) == [(_guid(1), 7, "sent"), (_guid(2), 7, "no_mail")]

    # Zweiter Lauf am selben Tag: nichts Neues.
    again = await PasswordExpiryNotifier(db_session, app_settings, sender=outbox).run(now=NOW)
    assert (again.sent, again.no_mail) == (0, 0)

    # Vier Tage später: die Schwelle "1 Tag" ist erreicht.
    later = await PasswordExpiryNotifier(db_session, app_settings, sender=outbox).run(
        now=NOW + timedelta(days=4, hours=1)
    )
    await db_session.commit()
    assert later.sent == 1
    assert outbox.sent[-1].subject == "Ihr Passwort läuft in 1 Tagen ab"
    audited = (
        await db_session.execute(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.action == "expiry_notice_sent")
        )
    ).scalar_one()
    assert audited == 2


async def test_a_new_password_starts_over(
    db_session: AsyncSession, app_settings: Settings, school_a: int
) -> None:
    await _setup(db_session, school_a)
    outbox = Outbox()
    await PasswordExpiryNotifier(db_session, app_settings, sender=outbox).run(now=NOW)
    await db_session.commit()
    user = await db_session.get(AdUserCache, _guid(1))
    assert user is not None
    user.password_expires_at = NOW + timedelta(days=6)  # neu gesetzt, wieder bald fällig
    await db_session.commit()
    result = await PasswordExpiryNotifier(db_session, app_settings, sender=outbox).run(now=NOW)
    assert result.sent == 1


async def test_failures_are_recorded_and_retried_later(
    db_session: AsyncSession, app_settings: Settings, school_a: int
) -> None:
    await _setup(db_session, school_a)
    failing = Outbox(fail=True)
    result = await PasswordExpiryNotifier(db_session, app_settings, sender=failing).run(now=NOW)
    await db_session.commit()
    assert result.failed == 1
    assert result.errors == ["smtp: authentication failed"]
    # Gleich danach nicht nochmals, eine Stunde später schon — dann klappt es.
    ok = Outbox()
    soon = await PasswordExpiryNotifier(db_session, app_settings, sender=ok).run(
        now=NOW + timedelta(minutes=5)
    )
    assert soon.sent == 0
    await db_session.execute(
        update(PasswordExpiryNotice).values(created_at=NOW - timedelta(hours=2))
    )
    retried = await PasswordExpiryNotifier(db_session, app_settings, sender=ok).run(
        now=NOW + timedelta(hours=1)
    )
    await db_session.commit()
    assert retried.sent == 1
    assert (_guid(1), 7, "sent") in await _notices(db_session)


async def test_off_or_unconfigured_sends_nothing(
    db_session: AsyncSession, app_settings: Settings, school_a: int
) -> None:
    await _setup(db_session, school_a, enabled=False)
    outbox = Outbox()
    result = await PasswordExpiryNotifier(db_session, app_settings, sender=outbox).run(now=NOW)
    assert result.skipped == "disabled"
    await db_session.execute(
        update(AppSettings).values(expiry_notice_enabled=True, mail_transport="off")
    )
    result = await PasswordExpiryNotifier(db_session, app_settings, sender=outbox).run(now=NOW)
    assert result.skipped == "not_configured"
    assert outbox.sent == []


async def test_own_template_is_used(
    db_session: AsyncSession, app_settings: Settings, school_a: int
) -> None:
    await _setup(db_session, school_a)
    await DocumentTemplateService(db_session, app_settings).save(
        key="password_expiry_notice",
        language="de",
        school_id=None,
        subject="Achtung {{ person.display_name }}",
        body_html="<p>Bis {{ expires_on }}: im Portal ändern. {{ class_.name }}</p>",
        is_active=True,
        actor_upn="admin@schule.ch",
        actor_object_guid=None,
        ip=None,
        request_id="t",
    )
    await db_session.commit()
    outbox = Outbox()
    await PasswordExpiryNotifier(db_session, app_settings, sender=outbox).run(now=NOW)
    assert outbox.sent[0].subject == "Achtung Lea Muster"
    assert outbox.sent[0].text == "Bis 27.10.2026: im Portal ändern."
