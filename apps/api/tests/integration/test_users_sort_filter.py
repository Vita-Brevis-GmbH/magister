"""Benutzerliste: Jahrgang und Zielgruppe als Spalten, sortieren und filtern.

Sortiert wird in der Datenbank — die Liste ist seitenweise, eine Sortierung
nur der geladenen Seite wäre falsch. Leere Werte stehen immer am Schluss.
"""

from __future__ import annotations

from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.models.auth import AdUserCache
from magister_api.models.group_template import GroupTemplate, GroupTemplateSchool

pytestmark = pytest.mark.postgres


def _guid(n: int) -> str:
    return f"00000000-0000-0000-0000-0000000d{n:04d}"


@pytest_asyncio.fixture
async def seeded(db_session: AsyncSession, school_a: int, school_b: int) -> dict[str, int]:
    z1 = GroupTemplate(name="Zyklus 1", kind="student_zyklus1", ad_groups=[])
    lp = GroupTemplate(name="Lehrperson", kind="teacher", ad_groups=[])
    fremd = GroupTemplate(name="Nur B", kind="custom", ad_groups=[])
    db_session.add_all([z1, lp, fremd])
    await db_session.flush()
    db_session.add_all(
        [
            GroupTemplateSchool(group_template_id=z1.id, school_id=school_a),
            GroupTemplateSchool(group_template_id=lp.id, school_id=school_a),
            GroupTemplateSchool(group_template_id=fremd.id, school_id=school_b),
        ]
    )
    people: list[tuple[str, str, int | None, int | None, dict[str, Any]]] = [
        ("Adler", "student", 3, z1.id, {"cannot_change_password": True}),
        ("Berger", "student", 1, z1.id, {"password_never_expires": True}),
        ("Curti", "student", None, None, {}),
        ("Dober", "teacher", None, lp.id, {"enabled": False}),
        ("Egli", "student", 3, None, {"store_password": True, "cannot_change_password": True}),
    ]
    for i, (surname, kind, grade, tpl, extra) in enumerate(people, start=1):
        db_session.add(
            AdUserCache(
                ad_object_guid=_guid(i),
                school_id=school_a,
                upn=f"{surname.lower()}@schule.ch",
                given_name="X",
                surname=surname,
                kind=kind,
                enabled=extra.pop("enabled", True),
                jahrgangsstufe=grade,
                group_template_id=tpl,
                **extra,
            )
        )
    # Ein Konto an Schule B mit "Nur B": darf in A weder erscheinen noch als Filter.
    db_session.add(
        AdUserCache(
            ad_object_guid=_guid(99),
            school_id=school_b,
            upn="fremd@schule.ch",
            surname="Fremd",
            kind="student",
            enabled=True,
            group_template_id=fremd.id,
        )
    )
    await db_session.commit()
    return {"z1": z1.id, "lp": lp.id, "fremd": fremd.id}


async def _names(client: AsyncClient, **params: Any) -> list[str]:
    r = await client.get("/users", params={"limit": 200, **params})
    assert r.status_code == 200, r.text
    return [u["surname"] for u in r.json()["items"] if u["upn"].endswith("@schule.ch")]


@pytest.mark.asyncio
async def test_columns_carry_grade_and_zielgruppe(
    as_schulleitung_a: AsyncClient, seeded: dict[str, int]
) -> None:
    r = await as_schulleitung_a.get("/users", params={"limit": 200})
    assert r.status_code == 200, r.text
    body = r.json()
    adler = next(u for u in body["items"] if u["surname"] == "Adler")
    assert adler["jahrgangsstufe"] == 3
    assert adler["group_template_name"] == "Zyklus 1"
    # Filter-Auswahl: nur Zielgruppen aus dem eigenen Sichtbereich.
    options = {o["name"] for o in body["zielgruppen"]}
    assert options == {"Zyklus 1", "Lehrperson"}


@pytest.mark.asyncio
async def test_sort_by_grade_and_zielgruppe_keeps_empty_last(
    as_schulleitung_a: AsyncClient, seeded: dict[str, int]
) -> None:
    c = as_schulleitung_a
    assert await _names(c, sort="jahrgangsstufe") == ["Berger", "Adler", "Egli", "Curti", "Dober"]
    desc = await _names(c, sort="jahrgangsstufe", dir="desc")
    assert desc[:3] == ["Adler", "Egli", "Berger"]
    assert set(desc[3:]) == {"Curti", "Dober"}  # leer bleibt hinten
    assert await _names(c, sort="zielgruppe") == ["Dober", "Adler", "Berger", "Curti", "Egli"]
    assert (await _names(c, sort="status"))[-1] == "Dober"  # deaktiviert zuletzt
    assert (await _names(c, sort="policy"))[0] == "Egli"  # zwei Richtlinien
    assert await _names(c, sort="name", dir="desc") == [
        "Egli",
        "Dober",
        "Curti",
        "Berger",
        "Adler",
    ]


@pytest.mark.asyncio
async def test_filters(as_schulleitung_a: AsyncClient, seeded: dict[str, int]) -> None:
    c = as_schulleitung_a
    assert await _names(c, jahrgangsstufe=3) == ["Adler", "Egli"]
    assert await _names(c, group_template_id=seeded["z1"]) == ["Adler", "Berger"]
    assert await _names(c, group_template_id=0) == ["Curti", "Egli"]  # keine Zielgruppe
    assert await _names(c, policy="cannot_change") == ["Adler", "Egli"]
    assert await _names(c, policy="stored") == ["Egli"]
    r = await c.get("/users", params={"group_template_id": seeded["z1"], "limit": 200})
    assert r.json()["total"] == 2
    bad = await c.get("/users", params={"sort": "passwort"})
    assert bad.status_code == 422


@pytest.mark.asyncio
async def test_name_sort_follows_the_shown_name(
    as_schulleitung_a: AsyncClient, db_session: AsyncSession, school_a: int
) -> None:
    """Sortiert wird nach dem, was die Liste zeigt — Anzeigename vor Nachname."""
    for i, (given, surname, display) in enumerate(
        [
            ("Anna", "Zürcher", None),  # zeigt "Anna Zürcher"
            ("Beat", "Arnold", "Zeno Arnold"),  # zeigt "Zeno Arnold"
            ("Carla", "Meier", "carla meier"),  # klein geschrieben
        ],
        start=50,
    ):
        db_session.add(
            AdUserCache(
                ad_object_guid=_guid(i),
                school_id=school_a,
                upn=f"{given.lower()}@schule.ch",
                given_name=given,
                surname=surname,
                display_name=display,
                kind="student",
                enabled=True,
            )
        )
    await db_session.commit()
    r = await as_schulleitung_a.get("/users", params={"limit": 200, "sort": "name"})
    shown = [
        u["display_name"] or f"{u['given_name']} {u['surname']}"
        for u in r.json()["items"]
        if u["upn"].endswith("@schule.ch")
    ]
    assert shown == ["Anna Zürcher", "carla meier", "Zeno Arnold"]
