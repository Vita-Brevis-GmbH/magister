"""Mail- und UPN-Domains: Systemeinstellungen → Domänen (gehört dem Kunden)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.models.app_settings import AppSettings
from magister_api.models.auth import AdUserCache

pytestmark = pytest.mark.postgres


async def test_admin_maintains_mail_and_upn_domains(
    as_admin: AsyncClient, db_session: AsyncSession, school_a: int
) -> None:
    await db_session.execute(
        update(AppSettings)
        .where(AppSettings.id == 1)
        .values(ad_users_search_base="OU=Benutzer,DC=schule,DC=local")
    )
    db_session.add(
        AdUserCache(
            ad_object_guid="00000000-0000-0000-0000-0000000f1001",
            school_id=school_a,
            upn="kind@sus-alt.ch",
            mail="Kind@Mail-Alt.ch",
            kind="student",
            enabled=True,
        )
    )
    await db_session.commit()

    r = await as_admin.put(
        "/admin/domains",
        json={
            "mail_domains": [" Schule.CH ", "schule.ch", "lp.schule.ch"],
            "upn_domains": ["@sus-schule.ch"],
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mail_domains"] == ["schule.ch", "lp.schule.ch"]
    assert body["upn_domains"] == ["sus-schule.ch"]
    # Auswahl: Mail-Domains, eingetragene UPN-Domains, dann was das AD kennt.
    assert body["upn_choices"][:3] == ["schule.ch", "lp.schule.ch", "sus-schule.ch"]
    # Aus dem AD: DNS-Name der Domäne und vorhandene Suffixe (alphabetisch;
    # example.ch trägt das Konto der Admin-Fixture).
    assert {"schule.local", "sus-alt.ch"} <= set(body["upn_choices"][3:])
    # Mail-Domains aus dem AD nur als Vorschlag, nicht von selbst wählbar.
    assert "mail-alt.ch" in body["mail_suggestions"]
    assert "mail-alt.ch" not in body["upn_choices"]
    # Das Benutzerformular bekommt dieselbe Auswahl.
    r = await as_admin.get("/users/mail-domains")
    assert r.json()["domains"] == ["schule.ch", "lp.schule.ch"]
    assert r.json()["upn_domains"][:3] == ["schule.ch", "lp.schule.ch", "sus-schule.ch"]

    bad = await as_admin.put(
        "/admin/domains", json={"mail_domains": ["keine domain"], "upn_domains": []}
    )
    assert bad.status_code == 422


async def test_only_admins(as_schulleitung_a: AsyncClient) -> None:
    assert (await as_schulleitung_a.get("/admin/domains")).status_code == 403
