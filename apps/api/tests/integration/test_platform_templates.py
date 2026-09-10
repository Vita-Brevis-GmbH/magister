"""Globale Vorlagen im Kundenschema: materialisieren und auflösen (ADR-0018).

Vier Zusagen, die sich nur gegen eine echte Datenbank prüfen lassen:

1. **Ein Kunde mit eigenem Text behält ihn.** Das ist der Grund für die zweite
   Tabelle (D2), und wenn es nicht stimmt, ist Phase 4 nicht brauchbar.
2. **Der zweite Lauf schreibt nichts.** Kein neuer `delivered_at`, kein
   Audit-Ereignis. Sonst wäre der Abgleich eine Schleife, die alle fünf
   Minuten dasselbe schiebt.
3. **Eine gesperrte Vorlage gewinnt, löscht aber nicht.** Wird die Sperre
   zurückgenommen, ist der Text des Kunden wieder da (D3).
4. **Was nicht geliefert wird, verschwindet** — aber nur, wenn die Konsole
   überhaupt etwas über Vorlagen gesagt hat (D6).
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.audit.service import AuditService
from magister_api.config import Settings
from magister_api.models.audit import AuditEvent
from magister_api.models.auth import AdUserCache
from magister_api.models.base import utcnow
from magister_api.models.class_membership import ClassMembership
from magister_api.models.document_template import DocumentTemplate
from magister_api.models.platform_template import PlatformDocumentTemplate
from magister_api.models.school_class import SchoolClass
from magister_api.services.document_templates import DocumentTemplateService
from magister_api.services.reconciler import RECONCILER_ACTOR, Reconciler
from magister_api.tenancy.desired_state import DesiredState, DesiredTemplate

pytestmark = pytest.mark.postgres

PLATFORM_BODY = "<p>Fassung des Betreibers</p>"
OWN_BODY = "<p>Selbst geschrieben, seit drei Jahren</p>"


def _template(**over: object) -> DesiredTemplate:
    fields: dict[str, object] = {
        "key": "enrollment",
        "language": "de",
        "subject": "Eintritt",
        "body_html": PLATFORM_BODY,
        "may_override": True,
        "version": 1,
    }
    fields.update(over)
    return DesiredTemplate(**fields)  # type: ignore[arg-type]


async def _reconcile(
    session: AsyncSession, settings: Settings, *templates: DesiredTemplate, **kw: object
) -> object:
    state = DesiredState(settings={}, templates=tuple(templates), **kw)  # type: ignore[arg-type]
    result = await Reconciler(session, settings).reconcile(state, tenant_slug="alpha")
    await session.commit()
    return result


async def _own_template(session: AsyncSession, *, body: str = OWN_BODY) -> DocumentTemplate:
    row = DocumentTemplate(
        key="enrollment", language="de", school_id=None, subject="Eigener Betreff", body_html=body
    )
    session.add(row)
    await session.flush()
    await session.commit()
    return row


async def _seed_student(session: AsyncSession, *, school_id: int) -> str:
    """Eine Schülerin mit aktiver Klassenzugehörigkeit — das Minimum für einen Brief."""
    cls = SchoolClass(school_id=school_id, name="3a", kuerzel="3a", jahrgangsstufe=3)
    session.add(cls)
    await session.flush()
    guid = "00000000-0000-0000-0000-0000000000aa"
    session.add(
        AdUserCache(
            ad_object_guid=guid,
            school_id=school_id,
            upn="anna@example.ch",
            display_name="Anna Beispiel",
            kind="student",
            enabled=True,
            ms_ds_consistency_guid=guid,
        )
    )
    session.add(ClassMembership(class_id=cls.id, ad_object_guid=guid, valid_from=utcnow()))
    await session.commit()
    return guid


async def _delivered(session: AsyncSession) -> list[PlatformDocumentTemplate]:
    stmt = select(PlatformDocumentTemplate).order_by(PlatformDocumentTemplate.key)
    return list((await session.execute(stmt)).scalars().all())


async def _template_events(session: AsyncSession) -> int:
    stmt = (
        select(func.count())
        .select_from(AuditEvent)
        .where(AuditEvent.action == "platform_templates_reconciled")
    )
    return (await session.execute(stmt)).scalar_one()


class TestMaterialising:
    async def test_a_delivered_template_lands_in_its_own_table(
        self, db_session: AsyncSession, app_settings: Settings
    ) -> None:
        result = await _reconcile(db_session, app_settings, _template())
        assert result.added_templates == ["enrollment/de"]  # type: ignore[attr-defined]
        (row,) = await _delivered(db_session)
        assert (row.key, row.version, row.body_html) == ("enrollment", 1, PLATFORM_BODY)

    async def test_the_second_run_writes_nothing(
        self, db_session: AsyncSession, app_settings: Settings
    ) -> None:
        await _reconcile(db_session, app_settings, _template())
        (first,) = await _delivered(db_session)
        delivered_at = first.delivered_at
        events_before = await _template_events(db_session)

        result = await _reconcile(db_session, app_settings, _template())

        assert not result.changed_templates  # type: ignore[attr-defined]
        (second,) = await _delivered(db_session)
        # Derselbe Zeitstempel: sonst sähe die Oberfläche bei jedem Lauf eine
        # „neue" Lieferung, und das Audit-Protokoll wäre voll.
        assert second.delivered_at == delivered_at
        assert await _template_events(db_session) == events_before

    async def test_a_new_version_updates_and_audits(
        self, db_session: AsyncSession, app_settings: Settings
    ) -> None:
        await _reconcile(db_session, app_settings, _template())
        result = await _reconcile(
            db_session, app_settings, _template(version=2, body_html="<p>neu</p>")
        )
        assert result.updated_templates == ["enrollment/de"]  # type: ignore[attr-defined]
        (row,) = await _delivered(db_session)
        assert (row.version, row.body_html) == (2, "<p>neu</p>")
        assert await _template_events(db_session) == 2

    async def test_the_audit_event_names_what_changed(
        self, db_session: AsyncSession, app_settings: Settings
    ) -> None:
        """Nicht „etwas hat sich geändert", sondern welche Vorlage.

        Wer im Protokoll des Kunden liest, soll nicht die Datenbank befragen
        müssen, um zu wissen, was der Betreiber geliefert hat.
        """
        await _reconcile(db_session, app_settings, _template())
        stmt = select(AuditEvent.id).where(AuditEvent.action == "platform_templates_reconciled")
        event_id = (await db_session.execute(stmt)).scalars().one()
        # Über den Audit-Dienst gelesen und nicht per SELECT: die Spalte ist
        # verschlüsselt, und der Dienst ist der eine Ort mit dem Schlüssel.
        record = await AuditService(db_session, app_settings).read(event_id)
        assert record is not None
        assert record.payload["added"] == ["enrollment/de"]
        assert record.actor_upn == RECONCILER_ACTOR


class TestWithdrawal:
    async def test_what_is_no_longer_delivered_disappears(
        self, db_session: AsyncSession, app_settings: Settings
    ) -> None:
        await _reconcile(db_session, app_settings, _template())
        result = await _reconcile(db_session, app_settings)
        assert result.removed_templates == ["enrollment/de"]  # type: ignore[attr-defined]
        assert await _delivered(db_session) == []

    async def test_no_statement_touches_nothing(
        self, db_session: AsyncSession, app_settings: Settings
    ) -> None:
        """Der Fall, der ohne den Unterschied `null`/`[]` ein Datenverlust wäre.

        Eine Konsole, die das Feld nicht kennt (oder es nach einem Fehler
        weglässt), darf die gelieferten Vorlagen nicht entfernen.
        """
        await _reconcile(db_session, app_settings, _template())
        state = DesiredState(settings={}, templates=None)
        result = await Reconciler(db_session, app_settings).reconcile(state, tenant_slug="alpha")
        await db_session.commit()
        assert not result.changed_templates
        assert len(await _delivered(db_session)) == 1


class TestTheOwnTextSurvives:
    async def test_a_delivery_does_not_touch_the_tenant_row(
        self, db_session: AsyncSession, app_settings: Settings
    ) -> None:
        own = await _own_template(db_session)
        await _reconcile(db_session, app_settings, _template())
        await db_session.refresh(own)
        assert own.body_html == OWN_BODY

    async def test_the_own_row_survives_a_withdrawal(
        self, db_session: AsyncSession, app_settings: Settings
    ) -> None:
        own = await _own_template(db_session)
        await _reconcile(db_session, app_settings, _template())
        await _reconcile(db_session, app_settings)
        await db_session.refresh(own)
        assert own.body_html == OWN_BODY


class TestTheResolutionChain:
    async def _resolve(
        self, session: AsyncSession, settings: Settings, *, school_id: int | None = None
    ) -> object:
        return await DocumentTemplateService(session, settings).resolve_effective(
            key="enrollment", language="de", school_id=school_id
        )

    async def test_nothing_at_all_falls_back_to_the_built_in(
        self, db_session: AsyncSession, app_settings: Settings
    ) -> None:
        assert await self._resolve(db_session, app_settings) is None

    async def test_the_platform_version_applies_when_the_tenant_has_none(
        self, db_session: AsyncSession, app_settings: Settings
    ) -> None:
        await _reconcile(db_session, app_settings, _template())
        resolved = await self._resolve(db_session, app_settings)
        assert resolved.origin == "platform"  # type: ignore[attr-defined]
        assert resolved.body_html == PLATFORM_BODY  # type: ignore[attr-defined]
        assert resolved.locked is False  # type: ignore[attr-defined]

    async def test_the_tenant_version_wins_over_a_released_platform_version(
        self, db_session: AsyncSession, app_settings: Settings
    ) -> None:
        await _own_template(db_session)
        await _reconcile(db_session, app_settings, _template())
        resolved = await self._resolve(db_session, app_settings)
        assert resolved.origin == "tenant"  # type: ignore[attr-defined]
        assert resolved.body_html == OWN_BODY  # type: ignore[attr-defined]

    async def test_a_locked_platform_version_wins(
        self, db_session: AsyncSession, app_settings: Settings
    ) -> None:
        await _own_template(db_session)
        await _reconcile(db_session, app_settings, _template(may_override=False))
        resolved = await self._resolve(db_session, app_settings)
        assert resolved.origin == "platform"  # type: ignore[attr-defined]
        assert resolved.locked is True  # type: ignore[attr-defined]

    async def test_lifting_the_lock_brings_the_own_text_back(
        self, db_session: AsyncSession, app_settings: Settings
    ) -> None:
        """Der Kern von D3: die Sperre kehrt den Vorrang um, sie löscht nicht.

        Ein `DELETE` im Namen einer Richtlinie wäre ein Datenverlust, den
        niemand angeordnet hat — und beim Zurücknehmen der Sperre stünde der
        Kunde vor einem leeren Editor.
        """
        await _own_template(db_session)
        await _reconcile(db_session, app_settings, _template(may_override=False))
        await _reconcile(db_session, app_settings, _template(version=2, may_override=True))
        resolved = await self._resolve(db_session, app_settings)
        assert resolved.origin == "tenant"  # type: ignore[attr-defined]
        assert resolved.body_html == OWN_BODY  # type: ignore[attr-defined]

    async def test_a_school_row_wins_over_the_own_global_row(
        self, db_session: AsyncSession, app_settings: Settings, school_a: int
    ) -> None:
        await _own_template(db_session)
        db_session.add(
            DocumentTemplate(
                key="enrollment",
                language="de",
                school_id=school_a,
                subject="Standort",
                body_html="<p>nur für diesen Standort</p>",
            )
        )
        await db_session.commit()
        await _reconcile(db_session, app_settings, _template())
        resolved = await self._resolve(db_session, app_settings, school_id=school_a)
        assert resolved.body_html == "<p>nur für diesen Standort</p>"  # type: ignore[attr-defined]

    async def test_a_lock_beats_even_a_school_row(
        self, db_session: AsyncSession, app_settings: Settings, school_a: int
    ) -> None:
        # Die Sperre ist die oberste Stufe der Kette; ein Standort hebt sie
        # nicht auf. Sonst wäre „nicht verhandelbar" eine Frage der Ebene.
        db_session.add(
            DocumentTemplate(
                key="enrollment",
                language="de",
                school_id=school_a,
                subject="Standort",
                body_html="<p>Standort</p>",
            )
        )
        await db_session.commit()
        await _reconcile(db_session, app_settings, _template(may_override=False))
        resolved = await self._resolve(db_session, app_settings, school_id=school_a)
        assert resolved.origin == "platform"  # type: ignore[attr-defined]

    async def test_an_inactive_own_row_does_not_win(
        self, db_session: AsyncSession, app_settings: Settings
    ) -> None:
        row = await _own_template(db_session)
        row.is_active = False
        await db_session.commit()
        await _reconcile(db_session, app_settings, _template())
        resolved = await self._resolve(db_session, app_settings)
        assert resolved.origin == "platform"  # type: ignore[attr-defined]


class TestPrintingUsesTheChain:
    """Der Beweis, dass die Kette nicht nur in einem Dienst steht.

    Ein Test über `resolve_effective` prüft die Reihenfolge. Er prüft nicht,
    dass der Weg zum Drucker sie auch benutzt — und genau dort war der Text
    vorher an einer Stelle festgelegt, an der es kein Plattform-Konzept gab.
    """

    async def test_a_letter_comes_out_of_the_platform_version(
        self,
        as_schulleitung_a: AsyncClient,
        db_session: AsyncSession,
        app_settings: Settings,
        school_a: int,
    ) -> None:
        student_guid = await _seed_student(db_session, school_id=school_a)
        await _reconcile(
            db_session,
            app_settings,
            _template(
                subject="Vom Betreiber",
                body_html="<h1>{{ subject }}</h1><p>{{ student.display_name }}</p>",
            ),
        )
        response = await as_schulleitung_a.post(
            "/letters/enrollment",
            json={
                "student_guid": student_guid,
                "school_year": "2026/27",
                "first_day": "12.08.2026",
            },
        )
        # Ein PDF, kein 500er: die Plattformfassung geht durch dieselbe
        # Jinja-Sandbox wie eine eigene, mit demselben Kontext.
        assert response.status_code == 200, response.text
        assert response.content.startswith(b"%PDF-")

    async def test_a_broken_platform_body_never_reaches_the_printer(
        self,
        as_schulleitung_a: AsyncClient,
        db_session: AsyncSession,
        app_settings: Settings,
        school_a: int,
    ) -> None:
        """Eine Vorlage mit einem Platzhalter, den es nicht gibt.

        Der erste Entwurf materialisierte sie und der Brief endete in einer
        Ausnahme — der erste Ort, an dem der Tippfehler aufgefallen wäre, war
        der Drucker eines Kunden. Der Abgleich rendert deshalb gegen den
        Beispielkontext und weist ab, was nicht durchkommt.
        """
        student_guid = await _seed_student(db_session, school_id=school_a)
        result = await _reconcile(
            db_session, app_settings, _template(body_html="<p>{{ gibt_es_nicht }}</p>")
        )
        assert "enrollment/de" in result.rejected_templates  # type: ignore[attr-defined]
        assert await _delivered(db_session) == []

        response = await as_schulleitung_a.post(
            "/letters/enrollment",
            json={
                "student_guid": student_guid,
                "school_year": "2026/27",
                "first_day": "12.08.2026",
            },
        )
        # Der Brief kommt — aus der eingebauten Vorlage. Eine kaputte Lieferung
        # nimmt dem Kunden nicht das Drucken.
        assert response.status_code == 200, response.text
        assert response.content.startswith(b"%PDF-")

    async def test_a_broken_subject_is_refused_too(
        self, db_session: AsyncSession, app_settings: Settings
    ) -> None:
        result = await _reconcile(db_session, app_settings, _template(subject="{{ auch_nicht }}"))
        assert "enrollment/de" in result.rejected_templates  # type: ignore[attr-defined]

    async def test_a_broken_new_version_leaves_the_working_one_in_place(
        self, db_session: AsyncSession, app_settings: Settings
    ) -> None:
        """Der letzte gute Stand bleibt in Kraft.

        Dieselbe Zusage wie beim Ausfall der Konsole — und der Grund, aus dem
        eine Abweisung die vorhandene Fassung nicht als „nicht mehr geliefert"
        behandelt.
        """
        await _reconcile(db_session, app_settings, _template())
        await _reconcile(
            db_session, app_settings, _template(version=2, body_html="<p>{{ kaputt }}</p>")
        )
        (row,) = await _delivered(db_session)
        assert (row.version, row.body_html) == (1, PLATFORM_BODY)
