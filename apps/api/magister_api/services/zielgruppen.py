"""Zielgruppen: Standardvorgaben je Kontoart und Passwortart je Konto.

Eine Zielgruppe (Tabelle ``group_templates``) legt fest, wie ein Konto angelegt
wird: Ablage-OU über ``kind``, AD-Gruppen, Passwortart und Konto-Einstellungen.
Jede Schule bekommt die Standard-Zielgruppen Schüler:in Zyklus 1/2/3 und
Lehrperson, eine Firma die Zielgruppe Mitarbeiter:in — beim Anlegen des
Standorts, per Migration 0047 für bestehende, und auf Knopfdruck
(``ensure_defaults``), falls jemand eine archiviert hat und sie zurück will.

Die Werte hier sind die Vorgabe beim Anlegen; danach gehört die Zielgruppe der
Schule und wird im Portal gepflegt. Migration 0047 trägt dieselben Werte —
bewusst kopiert und nicht importiert, damit eine spätere Änderung hier nicht
rückwirkend eine alte Migration verändert.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.ad.password import default_profile_for_kind
from magister_api.models.auth import AdUserCache
from magister_api.models.group_template import GroupTemplate
from magister_api.models.school import School
from magister_api.repositories.group_templates import GroupTemplateRepository


@dataclass(frozen=True)
class ZielgruppenVorgabe:
    kind: str
    name: str
    school_column: str
    password_profile: str
    force_change: bool
    cannot_change_password: bool
    password_never_expires: bool
    store_password: bool


#: Unterstufe (Zyklus 1/2): lesbares Passwort, das das Kind nicht ändern kann
#: und das nicht abläuft — die Lehrperson druckt es bei Bedarf aus der
#: Klassen-Passwortliste nach (Tresor). Zyklus 3 und Lehrpersonen ändern ihr
#: Passwort bei der ersten Anmeldung.
def _v(
    kind: str,
    name: str,
    profile: str,
    *,
    force_change: bool,
    cannot_change: bool,
    never_expires: bool,
    store: bool,
) -> ZielgruppenVorgabe:
    return ZielgruppenVorgabe(
        kind=kind,
        name=name,
        school_column=f"ad_groups_{kind}",
        password_profile=profile,
        force_change=force_change,
        cannot_change_password=cannot_change,
        password_never_expires=never_expires,
        store_password=store,
    )


_UNTERSTUFE = {"force_change": False, "cannot_change": True, "never_expires": True, "store": True}
_AENDERT_SELBST = {
    "force_change": True,
    "cannot_change": False,
    "never_expires": False,
    "store": False,
}

VORGABEN: dict[str, ZielgruppenVorgabe] = {
    v.kind: v
    for v in (
        _v("student_zyklus1", "Schüler:in Zyklus 1", "readable", **_UNTERSTUFE),
        _v("student_zyklus2", "Schüler:in Zyklus 2", "readable", **_UNTERSTUFE),
        _v("student_zyklus3", "Schüler:in Zyklus 3", "readable", **_AENDERT_SELBST),
        _v("teacher", "Lehrperson", "teacher", **_AENDERT_SELBST),
        _v("company", "Mitarbeiter:in", "teacher", **_AENDERT_SELBST),
    )
}

#: Welche Standard-Zielgruppen ein Profil bekommt. ``neutral`` keine: dort
#: gibt es weder Schüler noch eine feste Kontoart.
KINDS_FOR_PROFILE: dict[str, tuple[str, ...]] = {
    "school": ("student_zyklus1", "student_zyklus2", "student_zyklus3", "teacher"),
    "company": ("company",),
    "neutral": (),
}


async def ensure_defaults(
    session: AsyncSession, *, school: School, instance_profile: str
) -> list[GroupTemplate]:
    """Fehlende Standard-Zielgruppen für ``school`` anlegen; gibt die neuen zurück.

    „Fehlend" heisst: keine aktive Zielgruppe dieser Kontoart, die an diesem
    Standort angeboten wird (verknüpft oder global). Bestehende werden nicht
    angefasst — auch nicht, wenn ihre Werte von der Vorgabe abweichen.
    """
    repo = GroupTemplateRepository(session)
    offered = await repo.list_for_school(school.id)
    have = {t.kind for t in offered}
    created: list[GroupTemplate] = []
    for kind in KINDS_FOR_PROFILE.get(instance_profile, KINDS_FOR_PROFILE["school"]):
        if kind in have:
            continue
        v = VORGABEN[kind]
        groups = list(getattr(school, v.school_column) or [])
        row = await repo.create(
            name=v.name,
            description=None,
            kind=kind,
            ad_groups=groups,
            school_ids=[school.id],
            options={
                "password_profile": v.password_profile,
                "force_change": v.force_change,
                "cannot_change_password": v.cannot_change_password,
                "password_never_expires": v.password_never_expires,
                "store_password": v.store_password,
            },
        )
        created.append(row)
    return created


async def password_profile_for(session: AsyncSession, user: AdUserCache) -> str:
    """Passwortart für einen Reset: die der Zielgruppe, sonst nach Kontoart."""
    if user.group_template_id is not None:
        profile = (
            await session.execute(
                select(GroupTemplate.password_profile).where(
                    GroupTemplate.id == user.group_template_id
                )
            )
        ).scalar_one_or_none()
        if profile:
            return profile
    return default_profile_for_kind(user.kind)


__all__ = [
    "KINDS_FOR_PROFILE",
    "VORGABEN",
    "ZielgruppenVorgabe",
    "ensure_defaults",
    "password_profile_for",
]
