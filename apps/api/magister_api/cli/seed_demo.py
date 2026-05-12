"""Idempotent demo-data seed for empty deployments.

Run as ``python -m magister_api.cli.seed_demo`` (inside the API container or
venv) or via the ``magister-cli seed-demo`` wrapper. Refuses to write to a
DB that already contains classes unless ``--force`` is set.

What it inserts:
- 1 school (``BSP`` — Schule Beispiel)
- 3 teachers + 12 students in ``ad_user_cache``
- 2 active classes (``4a``, ``4b``) with one KL each
- 12 active memberships, students alternated between the two classes

The CLI deliberately writes through plain SQLAlchemy + the existing models
rather than going via HTTP — empty deployments don't have any user that
could authenticate to ``POST /classes`` yet, and the demo is operator-only
anyway.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from magister_api.config import get_settings
from magister_api.models.auth import AdUserCache
from magister_api.models.base import utcnow
from magister_api.models.class_membership import ClassMembership
from magister_api.models.class_teacher_role import KL_ROLE_HAUPT, ClassTeacherRole
from magister_api.models.school import School
from magister_api.models.school_class import CLASS_STATUS_ACTIVE, SchoolClass

TEACHERS_SPEC: list[tuple[str, str, str]] = [
    ("anna.lehrer@bsp.example.ch", "Anna", "Lehrer"),
    ("beat.mueller@bsp.example.ch", "Beat", "Müller"),
    ("corinne.weber@bsp.example.ch", "Corinne", "Weber"),
]

STUDENTS_SPEC: list[tuple[str, str, str]] = [
    ("aaron.amsler@bsp.example.ch", "Aaron", "Amsler"),
    ("bea.brunner@bsp.example.ch", "Bea", "Brunner"),
    ("chiara.caduff@bsp.example.ch", "Chiara", "Caduff"),
    ("david.disler@bsp.example.ch", "David", "Disler"),
    ("elias.eberle@bsp.example.ch", "Elias", "Eberle"),
    ("fabia.frei@bsp.example.ch", "Fabia", "Frei"),
    ("gian.gerber@bsp.example.ch", "Gian", "Gerber"),
    ("hanna.huber@bsp.example.ch", "Hanna", "Huber"),
    ("ivan.imhof@bsp.example.ch", "Ivan", "Imhof"),
    ("jana.jenni@bsp.example.ch", "Jana", "Jenni"),
    ("kim.kaufmann@bsp.example.ch", "Kim", "Kaufmann"),
    ("luca.lang@bsp.example.ch", "Luca", "Lang"),
]


def _new_guid() -> str:
    """Return a 36-char canonical UUID — same shape as Entra's ``oid`` claim."""
    return str(uuid.uuid4())


async def seed_demo_data(*, force: bool) -> int:
    """Insert the demo data set. Returns a process exit code."""
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sm() as session:
            existing_classes = (
                (await session.execute(select(SchoolClass).limit(1))).scalars().first()
            )
            if existing_classes is not None and not force:
                sys.stderr.write(
                    "Refusing to seed: the DB already contains classes. Pass --force to override.\n"
                )
                return 1

            school = (
                (await session.execute(select(School).where(School.kuerzel == "BSP")))
                .scalars()
                .first()
            )
            if school is None:
                school = School(
                    name="Schule Beispiel",
                    kuerzel="BSP",
                    scope_short="BSP",
                )
                session.add(school)
                await session.flush()
                print(f"+ school: {school.kuerzel} (id={school.id})")
            else:
                print(f"= school: {school.kuerzel} (id={school.id})")

            now = utcnow()

            teacher_guids: dict[str, str] = {}
            for upn, given, surname in TEACHERS_SPEC:
                cached = (
                    (await session.execute(select(AdUserCache).where(AdUserCache.upn == upn)))
                    .scalars()
                    .first()
                )
                if cached is None:
                    cached = AdUserCache(
                        ad_object_guid=_new_guid(),
                        school_id=school.id,
                        upn=upn,
                        given_name=given,
                        surname=surname,
                        mail=upn,
                        kind="teacher",
                        enabled=True,
                        last_sync_at=now,
                    )
                    session.add(cached)
                    print(f"+ teacher: {upn}")
                else:
                    print(f"= teacher: {upn}")
                teacher_guids[upn] = cached.ad_object_guid

            student_guids: list[str] = []
            for upn, given, surname in STUDENTS_SPEC:
                cached = (
                    (await session.execute(select(AdUserCache).where(AdUserCache.upn == upn)))
                    .scalars()
                    .first()
                )
                if cached is None:
                    cached = AdUserCache(
                        ad_object_guid=_new_guid(),
                        school_id=school.id,
                        upn=upn,
                        given_name=given,
                        surname=surname,
                        mail=upn,
                        kind="student",
                        enabled=True,
                        last_sync_at=now,
                    )
                    session.add(cached)
                    print(f"+ student: {upn}")
                else:
                    print(f"= student: {upn}")
                student_guids.append(cached.ad_object_guid)

            await session.flush()

            classes_spec = [
                ("4a", "4a", 4, teacher_guids["anna.lehrer@bsp.example.ch"]),
                ("4b", "4b", 4, teacher_guids["beat.mueller@bsp.example.ch"]),
            ]
            class_ids_by_name: dict[str, int] = {}
            for name, kuerzel, jahrgang, kl_guid in classes_spec:
                klass = (
                    (
                        await session.execute(
                            select(SchoolClass)
                            .where(SchoolClass.school_id == school.id)
                            .where(SchoolClass.name == name)
                            .where(SchoolClass.status == CLASS_STATUS_ACTIVE)
                        )
                    )
                    .scalars()
                    .first()
                )
                if klass is None:
                    klass = SchoolClass(
                        school_id=school.id,
                        name=name,
                        kuerzel=kuerzel,
                        jahrgangsstufe=jahrgang,
                        status=CLASS_STATUS_ACTIVE,
                    )
                    session.add(klass)
                    await session.flush()
                    print(f"+ class: {name} (id={klass.id})")
                else:
                    print(f"= class: {name} (id={klass.id})")
                class_ids_by_name[name] = klass.id

                existing_kl = (
                    (
                        await session.execute(
                            select(ClassTeacherRole)
                            .where(ClassTeacherRole.class_id == klass.id)
                            .where(ClassTeacherRole.ad_object_guid == kl_guid)
                            .where(ClassTeacherRole.valid_to.is_(None))
                        )
                    )
                    .scalars()
                    .first()
                )
                if existing_kl is None:
                    session.add(
                        ClassTeacherRole(
                            class_id=klass.id,
                            ad_object_guid=kl_guid,
                            role=KL_ROLE_HAUPT,
                            valid_from=now,
                            valid_to=None,
                            created_by="demo-seed",
                        )
                    )
                    print(f"  + KL {kl_guid[:8]}… on {name}")

            for idx, student_guid in enumerate(student_guids):
                target_class_name = "4a" if idx % 2 == 0 else "4b"
                target_class_id = class_ids_by_name[target_class_name]
                existing_membership = (
                    (
                        await session.execute(
                            select(ClassMembership)
                            .where(ClassMembership.class_id == target_class_id)
                            .where(ClassMembership.ad_object_guid == student_guid)
                            .where(ClassMembership.valid_to.is_(None))
                        )
                    )
                    .scalars()
                    .first()
                )
                if existing_membership is None:
                    session.add(
                        ClassMembership(
                            class_id=target_class_id,
                            ad_object_guid=student_guid,
                            valid_from=now,
                            valid_to=None,
                            created_by="demo-seed",
                        )
                    )
                    print(f"  + {student_guid[:8]}… → {target_class_name}")

            await session.commit()

        print(
            "\nDemo data seeded. Sign in as the local admin and head to /classes; "
            "you should see '4a' and '4b' with KL + students."
        )
        return 0
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="magister-seed-demo",
        description="Populate the DB with the Magister demo data set.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Seed even if the DB already contains classes. Use with care.",
    )
    args = parser.parse_args(argv)
    return asyncio.run(seed_demo_data(force=args.force))


if __name__ == "__main__":
    raise SystemExit(main())
