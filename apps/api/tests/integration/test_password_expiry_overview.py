"""Übersicht Passwort-Ablauf, Klassenliste und Mail-Status/Testmail."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.mail import MailConfig, MailError, MailMessage
from magister_api.models.app_settings import AppSettings
from magister_api.models.auth import AdUserCache
from magister_api.models.base import utcnow
from magister_api.models.class_membership import ClassMembership
from magister_api.models.password_expiry_notice import PasswordExpiryNotice
from magister_api.models.school_class import SchoolClass

pytestmark = pytest.mark.postgres


def _guid(n: int) -> str:
    return f"00000000-0000-0000-0000-0000000e2{n:03d}"


async def _seed(db: AsyncSession, school_a: int, school_b: int) -> int:
    now = utcnow()
    people: list[tuple[int, int, str | None, int | None, dict[str, Any]]] = [
        (1, school_a, "lea@schule.ch", 3, {}),
        (2, school_a, None, 10, {}),  # kein Postfach
        (3, school_a, "tim@schule.ch", 40, {}),  # noch weit weg
        (4, school_a, None, None, {"password_never_expires": True}),
        (5, school_a, "alt@schule.ch", -2, {}),  # schon abgelaufen
        (6, school_b, None, 2, {}),  # fremder Standort
    ]
    for n, school, mail, days, extra in people:
        db.add(
            AdUserCache(
                ad_object_guid=_guid(n),
                school_id=school,
                upn=f"e{n}@schule.ch",
                surname=f"Person{n}",
                mail=mail,
                kind="student",
                enabled=True,
                password_expires_at=now + timedelta(days=days, hours=1) if days else None,
                password_info_at=now,
                **extra,
            )
        )
    cls = SchoolClass(school_id=school_a, name="5a", kuerzel="5a", jahrgangsstufe=5)
    db.add(cls)
    await db.flush()
    db.add(ClassMembership(class_id=cls.id, ad_object_guid=_guid(2), valid_from=now))
    user = await db.get(AdUserCache, _guid(1))
    assert user is not None and user.password_expires_at is not None
    db.add(
        PasswordExpiryNotice(
            ad_object_guid=_guid(1),
            expires_at=user.password_expires_at,
            threshold_days=7,
            status="sent",
            recipient="lea@schule.ch",
        )
    )
    await db.commit()
    return cls.id


async def test_overview_expiring_and_without_mail_in_scope(
    as_schulleitung_a: AsyncClient, db_session: AsyncSession, school_a: int, school_b: int
) -> None:
    class_id = await _seed(db_session, school_a, school_b)
    r = await as_schulleitung_a.get("/password-expiry", params={"days": 14})
    assert r.status_code == 200, r.text
    body = r.json()
    rows = {row["surname"]: row for row in body["rows"]}
    # Abgelaufen zuerst, dann nach Ablauf; Schule B und "nie" fehlen.
    assert [row["surname"] for row in body["rows"]] == ["Person5", "Person1", "Person2"]
    assert rows["Person5"]["days_left"] == -1
    assert rows["Person1"]["notice_status"] == "sent"
    assert rows["Person1"]["notice_threshold_days"] == 7
    assert rows["Person2"]["mail"] is None
    assert body["notice_enabled"] is False and body["mail_ready"] is False
    assert body["info_as_of"] is not None

    r = await as_schulleitung_a.get("/password-expiry", params={"view": "no_mail"})
    names = [row["surname"] for row in r.json()["rows"]]
    # Ohne Mail: mit Ablauf zuerst, "läuft nie ab" danach — Schule B nicht.
    assert names[:2] == ["Person2", "Person4"]
    assert "Person6" not in names
    assert all(row["mail"] is None for row in r.json()["rows"])

    # Klassenliste: Ablauf und ob ein Postfach da ist.
    r = await as_schulleitung_a.get(f"/classes/{class_id}/students")
    member = r.json()[0]
    assert member["has_mail"] is False
    assert member["password_expires_at"] is not None


async def test_mail_status_and_test_mail(
    as_admin: AsyncClient,
    app: FastAPI,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    r = await as_admin.get("/admin/mail/status")
    assert r.status_code == 200, r.text
    assert r.json()["ready"] is False
    assert r.json()["missing"] == ["mail_transport"]

    await db_session.execute(
        update(AppSettings)
        .where(AppSettings.id == 1)
        .values(mail_transport="smtp", mail_from="noreply@schule.ch", smtp_host="mail.schule.ch")
    )
    await db_session.commit()
    sent: list[MailMessage] = []

    async def fake_send(config: MailConfig, message: MailMessage) -> None:
        if message.to == "kaputt@schule.ch":
            raise MailError("smtp: recipient refused")
        sent.append(message)

    monkeypatch.setattr("magister_api.routers.admin_mail.send_mail", fake_send)
    r = await as_admin.post("/admin/mail/test", json={"to": "it@schule.ch"})
    assert r.json() == {"ok": True, "error": None}
    assert sent[0].subject == "Magister: Testmail"
    r = await as_admin.post("/admin/mail/test", json={"to": "kaputt@schule.ch"})
    assert r.json() == {"ok": False, "error": "smtp: recipient refused"}
    assert (await as_admin.post("/admin/mail/test", json={"to": "keine"})).status_code == 422


async def test_reading_needs_a_role(as_schulleitung_a: AsyncClient) -> None:
    # Schulleitung liest die Übersicht, aber nicht den Mail-Status (nur Admin).
    assert (await as_schulleitung_a.get("/password-expiry")).status_code == 200
    assert (await as_schulleitung_a.get("/admin/mail/status")).status_code == 403
