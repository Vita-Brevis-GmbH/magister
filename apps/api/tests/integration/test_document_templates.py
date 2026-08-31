"""M6 Feature B: editable document templates — admin CRUD + letter override.

Skipped unless MAGISTER_TEST_DATABASE_URL is set (see integration conftest).
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.config import Settings
from magister_api.models.auth import AdUserCache
from magister_api.models.base import utcnow
from magister_api.models.class_membership import ClassMembership
from magister_api.models.school_class import SchoolClass
from magister_api.repositories.base import ScopeContext
from magister_api.services.document_templates import DocumentTemplateService
from magister_api.services.letters import LetterContext, LetterService

pytestmark = pytest.mark.postgres


async def test_admin_save_list_and_preview(as_admin: AsyncClient) -> None:
    r = await as_admin.put(
        "/templates",
        json={
            "key": "enrollment",
            "language": "de",
            "school_id": None,
            "subject": "Eintritt {{ class_.name }}",
            "body_html": "<p>Hallo {{ student.display_name }}</p>",
            "is_active": True,
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["key"] == "enrollment"

    listing = (await as_admin.get("/templates")).json()
    assert any(t["key"] == "enrollment" for t in listing["templates"])
    assert "enrollment" in listing["meta"]["keys"]
    assert "student.display_name" in listing["meta"]["placeholders"]

    prev = await as_admin.post(
        "/templates/preview",
        json={"subject": "S {{ class_.name }}", "body_html": "<p>{{ student.display_name }}</p>"},
    )
    assert prev.status_code == 200, prev.text
    body = prev.json()
    assert "Max Muster" in body["html"]
    assert body["subject"] == "S 4a"


async def test_save_broken_template_rejected(as_admin: AsyncClient) -> None:
    r = await as_admin.put(
        "/templates",
        json={"key": "enrollment", "language": "de", "body_html": "<p>{{ oops "},
    )
    assert r.status_code == 422
    assert r.json()["detail"].startswith("template_invalid")


async def test_save_unknown_key_rejected(as_admin: AsyncClient) -> None:
    r = await as_admin.put(
        "/templates",
        json={"key": "not_a_template", "language": "de", "body_html": "<p>x</p>"},
    )
    assert r.status_code == 422
    assert r.json()["detail"].startswith("unknown_key")


async def test_non_admin_forbidden(as_smi_a: AsyncClient) -> None:
    assert (await as_smi_a.get("/templates")).status_code == 403


async def _seed_student(db: AsyncSession, *, school_id: int) -> str:
    cls = SchoolClass(school_id=school_id, name="4a", kuerzel="4a", jahrgangsstufe=4)
    db.add(cls)
    await db.flush()
    student = AdUserCache(
        ad_object_guid="00000000-0000-0000-0000-0000000000cc",
        school_id=school_id,
        upn="lea@schule.example.ch",
        display_name="Lea Beispiel",
        kind="student",
        enabled=True,
    )
    db.add(student)
    db.add(
        ClassMembership(class_id=cls.id, ad_object_guid=student.ad_object_guid, valid_from=utcnow())
    )
    await db.commit()
    return student.ad_object_guid


async def test_custom_template_overrides_builtin_letter(
    db_session: AsyncSession, app_settings: Settings, school_a: int
) -> None:
    guid = await _seed_student(db_session, school_id=school_a)
    scope = ScopeContext(
        ad_object_guid="00000000-0000-0000-0000-0000000000ad",
        upn="admin@schule.example.ch",
        is_admin=True,
    )

    letters = LetterService(db_session, app_settings, scope)
    ctx = LetterContext(school_year="2026/27", first_day="12.08.2026")

    # Without an override → built-in template (no custom marker).
    html_builtin = await letters.prepare(
        template="enrollment", student_guid=guid, ctx=ctx, ip=None, request_id="r1"
    )
    assert "ZZ-CUSTOM-MARKER" not in html_builtin

    # Save a global override, then the same letter renders the custom body.
    await DocumentTemplateService(db_session, app_settings).save(
        key="enrollment",
        language="de",
        school_id=None,
        subject="Eintritt {{ class_.name }}",
        body_html="<p>ZZ-CUSTOM-MARKER für {{ student.display_name }} in {{ class_.name }}</p>",
        is_active=True,
        actor_upn="admin@schule.example.ch",
        actor_object_guid="00000000-0000-0000-0000-0000000000ad",
        ip=None,
        request_id="r2",
    )
    await db_session.commit()

    html_custom = await letters.prepare(
        template="enrollment", student_guid=guid, ctx=ctx, ip=None, request_id="r3"
    )
    assert "ZZ-CUSTOM-MARKER für Lea Beispiel in 4a" in html_custom
