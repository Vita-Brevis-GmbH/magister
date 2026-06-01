"""CSV-Import service: stage → diff → apply for classes / memberships / KL-roles.

The service does **not** create AD users — UPNs are matched against the
``ad_user_cache`` (the result of the periodic AD sync). Missing users are
reported as row-level errors so the importer can fix them in AD first.

Each ``apply`` runs every staged row inside its own savepoint so partial
failures don't roll back the whole batch (same pattern as M2 bulk endpoints).
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.audit.service import AuditService
from magister_api.config import Settings
from magister_api.models.auth import AdUserCache
from magister_api.models.base import utcnow
from magister_api.models.class_membership import ClassMembership
from magister_api.models.class_teacher_role import (
    ALLOWED_KL_ROLES,
    ClassTeacherRole,
)
from magister_api.models.import_job import (
    IMPORT_ACTION_CREATE,
    IMPORT_ACTION_ERROR,
    IMPORT_ACTION_SKIP,
    IMPORT_ACTION_UPDATE,
    IMPORT_KIND_CLASS_MEMBERSHIPS,
    IMPORT_KIND_CLASS_TEACHERS,
    IMPORT_KIND_CLASSES,
    IMPORT_STATUS_APPLIED,
    IMPORT_STATUS_CANCELLED,
    IMPORT_STATUS_STAGED,
    ImportJob,
    ImportStagedRow,
)
from magister_api.models.school_class import (
    CLASS_STATUS_ACTIVE,
    SchoolClass,
)
from magister_api.repositories.base import ScopeContext

# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

TEMPLATES: dict[str, tuple[list[str], list[list[str]]]] = {
    IMPORT_KIND_CLASSES: (
        ["name", "kuerzel", "jahrgangsstufe"],
        [
            ["3a", "3a", "3"],
            ["3b", "3b", "3"],
            ["Werken Gruppe Rot", "", "4"],
        ],
    ),
    IMPORT_KIND_CLASS_MEMBERSHIPS: (
        ["student_upn", "class_name", "valid_from", "valid_to"],
        [
            ["anna.beispiel@schule.ch", "3a", "2026-08-12", ""],
            ["ben.muster@schule.ch", "3a", "2026-08-12", ""],
            ["clara.frey@schule.ch", "3b", "2026-08-12", "2027-07-04"],
        ],
    ),
    IMPORT_KIND_CLASS_TEACHERS: (
        ["teacher_upn", "class_name", "role", "valid_from", "valid_to"],
        [
            ["erika.lehrer@schule.ch", "3a", "haupt", "2026-08-12", ""],
            ["max.kollege@schule.ch", "3a", "co", "2026-08-12", ""],
            ["sven.vertret@schule.ch", "3a", "stellvertretung", "2026-11-01", "2026-12-31"],
        ],
    ),
}


def render_template(kind: str) -> str:
    """Render a CSV template for the given import kind."""
    if kind not in TEMPLATES:
        raise ValueError(f"unknown import kind: {kind}")
    header, rows = TEMPLATES[kind]
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(header)
    for row in rows:
        writer.writerow(row)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ImportJobNotFoundError(LookupError):
    pass


class ImportJobBadStateError(ValueError):
    """Apply/cancel called on a job that's not in 'staged'."""


class InvalidCsvError(ValueError):
    """CSV header doesn't match the expected template for the kind."""


@dataclass(frozen=True)
class StageSummary:
    job: ImportJob
    counts: dict[str, int]


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


def _parse_date(s: str) -> datetime | None:
    s = (s or "").strip()
    if not s:
        return None
    # Accept "YYYY-MM-DD" or full ISO.
    try:
        if "T" in s:
            return datetime.fromisoformat(s)
        return datetime.fromisoformat(s + "T00:00:00+00:00")
    except ValueError as exc:
        raise ValueError(f"invalid date {s!r} (expected YYYY-MM-DD)") from exc


class ImportService:
    def __init__(self, session: AsyncSession, settings: Settings, scope: ScopeContext) -> None:
        self.session = session
        self.settings = settings
        self.scope = scope
        self.audit = AuditService(session, settings)

    # ----- Stage --------------------------------------------------------

    async def stage(
        self,
        *,
        school_id: int,
        kind: str,
        csv_text: str,
        filename: str | None,
        ip: str | None,
        request_id: str,
    ) -> StageSummary:
        if kind not in TEMPLATES:
            raise InvalidCsvError(f"unknown import kind: {kind}")
        expected_header = TEMPLATES[kind][0]
        reader = csv.DictReader(io.StringIO(csv_text))
        if reader.fieldnames is None or [(h or "").strip().lower() for h in reader.fieldnames] != [
            h.lower() for h in expected_header
        ]:
            raise InvalidCsvError(
                f"csv header must be exactly {expected_header}, got {reader.fieldnames!r}"
            )

        job = ImportJob(
            school_id=school_id,
            kind=kind,
            status=IMPORT_STATUS_STAGED,
            filename=filename,
            created_by_upn=self.scope.upn,
            summary={},
        )
        self.session.add(job)
        await self.session.flush()

        counts = {
            IMPORT_ACTION_CREATE: 0,
            IMPORT_ACTION_UPDATE: 0,
            IMPORT_ACTION_SKIP: 0,
            IMPORT_ACTION_ERROR: 0,
        }

        for i, raw in enumerate(reader, start=2):  # start=2 → header is row 1
            # Normalize whitespace.
            row = {k: (v or "").strip() for k, v in raw.items() if k}
            action, errors = await self._classify(school_id, kind, row)
            counts[action] += 1
            staged = ImportStagedRow(
                job_id=job.id,
                row_num=i,
                raw_data=row,
                action=action,
                errors=errors,
            )
            self.session.add(staged)

        job.summary = dict(counts)
        await self.session.flush()

        await self.audit.emit(
            action="import_staged",
            target_kind="import_job",
            target_id=str(job.id),
            actor_upn=self.scope.upn,
            actor_object_guid=self.scope.ad_object_guid,
            school_id=school_id,
            ip=ip,
            request_id=request_id,
            payload={"kind": kind, "filename": filename, "counts": counts},
        )
        return StageSummary(job=job, counts=counts)

    async def _classify(
        self, school_id: int, kind: str, row: dict[str, str]
    ) -> tuple[str, list[str]]:
        """Compute the apply-action for a single CSV row.

        Returns ``(action, errors)``. Errors are present on action=error and may
        also be present on warnings (currently unused).
        """
        try:
            if kind == IMPORT_KIND_CLASSES:
                return await self._classify_class(school_id, row)
            if kind == IMPORT_KIND_CLASS_MEMBERSHIPS:
                return await self._classify_membership(school_id, row)
            if kind == IMPORT_KIND_CLASS_TEACHERS:
                return await self._classify_teacher_role(school_id, row)
        except Exception as exc:  # noqa: BLE001 — defensive fallback
            return IMPORT_ACTION_ERROR, [str(exc)]
        return IMPORT_ACTION_ERROR, ["unsupported kind"]

    async def _classify_class(self, school_id: int, row: dict[str, str]) -> tuple[str, list[str]]:
        errors: list[str] = []
        name = row.get("name", "").strip()
        kuerzel = row.get("kuerzel", "").strip() or None
        jahrgangsstufe_raw = row.get("jahrgangsstufe", "").strip()

        if not name:
            errors.append("name is required")
        try:
            jahrgangsstufe = int(jahrgangsstufe_raw)
            if not 1 <= jahrgangsstufe <= 13:
                errors.append("jahrgangsstufe must be 1..13")
        except ValueError:
            errors.append("jahrgangsstufe must be an integer")

        if errors:
            return IMPORT_ACTION_ERROR, errors

        existing = (
            await self.session.execute(
                select(SchoolClass).where(
                    SchoolClass.school_id == school_id,
                    SchoolClass.name == name,
                )
            )
        ).scalar_one_or_none()

        if existing is None:
            return IMPORT_ACTION_CREATE, []
        if existing.kuerzel == kuerzel and existing.jahrgangsstufe == int(jahrgangsstufe_raw):
            return IMPORT_ACTION_SKIP, []
        return IMPORT_ACTION_UPDATE, []

    async def _classify_membership(
        self, school_id: int, row: dict[str, str]
    ) -> tuple[str, list[str]]:
        errors: list[str] = []
        student_upn = row.get("student_upn", "").strip().lower()
        class_name = row.get("class_name", "").strip()

        if not student_upn:
            errors.append("student_upn is required")
        if not class_name:
            errors.append("class_name is required")
        try:
            _parse_date(row.get("valid_from", ""))
            _parse_date(row.get("valid_to", ""))
        except ValueError as exc:
            errors.append(str(exc))
        if errors:
            return IMPORT_ACTION_ERROR, errors

        user = await self._lookup_user(student_upn, kind="student")
        if user is None:
            return IMPORT_ACTION_ERROR, [f"student {student_upn} not in AD cache"]

        cls = await self._lookup_class(school_id, class_name)
        if cls is None:
            return IMPORT_ACTION_ERROR, [f"class {class_name!r} not found in school"]

        # Already an active membership in *this* class? → skip.
        now = utcnow()
        active_here = (
            await self.session.execute(
                select(ClassMembership).where(
                    ClassMembership.ad_object_guid == user.ad_object_guid,
                    ClassMembership.class_id == cls.id,
                    ClassMembership.valid_from <= now,
                    (ClassMembership.valid_to.is_(None)) | (ClassMembership.valid_to > now),
                )
            )
        ).scalar_one_or_none()
        if active_here is not None:
            return IMPORT_ACTION_SKIP, []
        return IMPORT_ACTION_CREATE, []

    async def _classify_teacher_role(
        self, school_id: int, row: dict[str, str]
    ) -> tuple[str, list[str]]:
        errors: list[str] = []
        teacher_upn = row.get("teacher_upn", "").strip().lower()
        class_name = row.get("class_name", "").strip()
        role = row.get("role", "").strip().lower()

        if not teacher_upn:
            errors.append("teacher_upn is required")
        if not class_name:
            errors.append("class_name is required")
        if role not in ALLOWED_KL_ROLES:
            errors.append(f"role must be one of {sorted(ALLOWED_KL_ROLES)}")
        try:
            _parse_date(row.get("valid_from", ""))
            _parse_date(row.get("valid_to", ""))
        except ValueError as exc:
            errors.append(str(exc))
        if errors:
            return IMPORT_ACTION_ERROR, errors

        user = await self._lookup_user(teacher_upn, kind="teacher")
        if user is None:
            return IMPORT_ACTION_ERROR, [f"teacher {teacher_upn} not in AD cache"]
        cls = await self._lookup_class(school_id, class_name)
        if cls is None:
            return IMPORT_ACTION_ERROR, [f"class {class_name!r} not found in school"]

        # Already active in same role? → skip.
        now = utcnow()
        active = (
            await self.session.execute(
                select(ClassTeacherRole).where(
                    ClassTeacherRole.ad_object_guid == user.ad_object_guid,
                    ClassTeacherRole.class_id == cls.id,
                    ClassTeacherRole.role == role,
                    ClassTeacherRole.valid_from <= now,
                    (ClassTeacherRole.valid_to.is_(None)) | (ClassTeacherRole.valid_to > now),
                )
            )
        ).scalar_one_or_none()
        if active is not None:
            return IMPORT_ACTION_SKIP, []
        return IMPORT_ACTION_CREATE, []

    async def _lookup_user(self, upn: str, *, kind: str) -> AdUserCache | None:
        stmt = select(AdUserCache).where(
            AdUserCache.upn == upn,
            AdUserCache.kind == kind,
            AdUserCache.enabled.is_(True),
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def _lookup_class(self, school_id: int, class_name: str) -> SchoolClass | None:
        stmt = select(SchoolClass).where(
            SchoolClass.school_id == school_id,
            SchoolClass.name == class_name,
            SchoolClass.status == CLASS_STATUS_ACTIVE,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    # ----- Apply --------------------------------------------------------

    async def apply(
        self,
        *,
        job_id: int,
        ip: str | None,
        request_id: str,
    ) -> ImportJob:
        job = await self.session.get(ImportJob, job_id)
        if job is None:
            raise ImportJobNotFoundError(str(job_id))
        if job.status != IMPORT_STATUS_STAGED:
            raise ImportJobBadStateError(f"job is {job.status}, expected staged")

        rows = (
            (
                await self.session.execute(
                    select(ImportStagedRow)
                    .where(ImportStagedRow.job_id == job.id)
                    .order_by(ImportStagedRow.row_num)
                )
            )
            .scalars()
            .all()
        )

        applied_counts = {"created": 0, "updated": 0, "skipped": 0, "failed": 0}
        now = utcnow()

        for staged in rows:
            if staged.action in (IMPORT_ACTION_ERROR, IMPORT_ACTION_SKIP):
                staged.applied_at = now
                applied_counts["skipped"] += 1
                continue

            sp = await self.session.begin_nested()
            try:
                if job.kind == IMPORT_KIND_CLASSES:
                    await self._apply_class(job.school_id, staged)
                elif job.kind == IMPORT_KIND_CLASS_MEMBERSHIPS:
                    await self._apply_membership(job.school_id, staged)
                elif job.kind == IMPORT_KIND_CLASS_TEACHERS:
                    await self._apply_teacher_role(job.school_id, staged)
                else:
                    raise ValueError(f"unsupported kind {job.kind}")
                staged.applied_at = now
                if staged.action == IMPORT_ACTION_CREATE:
                    applied_counts["created"] += 1
                else:
                    applied_counts["updated"] += 1
                await sp.commit()
            except Exception as exc:  # noqa: BLE001
                await sp.rollback()
                staged.applied_at = now
                staged.applied_error = str(exc)[:512]
                applied_counts["failed"] += 1

        job.status = IMPORT_STATUS_APPLIED
        job.applied_at = now
        job.summary = {**job.summary, "applied": applied_counts}
        await self.session.flush()

        await self.audit.emit(
            action="import_applied",
            target_kind="import_job",
            target_id=str(job.id),
            actor_upn=self.scope.upn,
            actor_object_guid=self.scope.ad_object_guid,
            school_id=job.school_id,
            ip=ip,
            request_id=request_id,
            payload={"kind": job.kind, "applied": applied_counts},
        )
        return job

    async def _apply_class(self, school_id: int, staged: ImportStagedRow) -> None:
        row = staged.raw_data
        name = row["name"].strip()
        kuerzel = (row.get("kuerzel") or "").strip() or None
        jahrgangsstufe = int(row["jahrgangsstufe"])

        existing = (
            await self.session.execute(
                select(SchoolClass).where(
                    SchoolClass.school_id == school_id,
                    SchoolClass.name == name,
                )
            )
        ).scalar_one_or_none()

        if existing is None:
            self.session.add(
                SchoolClass(
                    school_id=school_id,
                    name=name,
                    kuerzel=kuerzel,
                    jahrgangsstufe=jahrgangsstufe,
                    status=CLASS_STATUS_ACTIVE,
                )
            )
        else:
            existing.kuerzel = kuerzel
            existing.jahrgangsstufe = jahrgangsstufe

    async def _apply_membership(self, school_id: int, staged: ImportStagedRow) -> None:
        row = staged.raw_data
        upn = row["student_upn"].strip().lower()
        class_name = row["class_name"].strip()
        valid_from = _parse_date(row.get("valid_from", "")) or utcnow()
        valid_to = _parse_date(row.get("valid_to", ""))

        user = await self._lookup_user(upn, kind="student")
        cls = await self._lookup_class(school_id, class_name)
        if user is None or cls is None:
            raise ValueError("user or class missing")

        # Close active memberships in OTHER classes (same mid-year semantics
        # as POST /classes/{id}/students).
        clamp_at = valid_from - timedelta(seconds=1)
        now = utcnow()
        prev = (
            (
                await self.session.execute(
                    select(ClassMembership).where(
                        ClassMembership.ad_object_guid == user.ad_object_guid,
                        ClassMembership.class_id != cls.id,
                        ClassMembership.valid_from <= now,
                        (ClassMembership.valid_to.is_(None))
                        | (ClassMembership.valid_to > valid_from),
                    )
                )
            )
            .scalars()
            .all()
        )
        for r in prev:
            r.valid_to = clamp_at

        self.session.add(
            ClassMembership(
                class_id=cls.id,
                ad_object_guid=user.ad_object_guid,
                valid_from=valid_from,
                valid_to=valid_to,
                created_by=self.scope.upn,
            )
        )

    async def _apply_teacher_role(self, school_id: int, staged: ImportStagedRow) -> None:
        row = staged.raw_data
        upn = row["teacher_upn"].strip().lower()
        class_name = row["class_name"].strip()
        role = row["role"].strip().lower()
        valid_from = _parse_date(row.get("valid_from", "")) or utcnow()
        valid_to = _parse_date(row.get("valid_to", ""))

        user = await self._lookup_user(upn, kind="teacher")
        cls = await self._lookup_class(school_id, class_name)
        if user is None or cls is None:
            raise ValueError("user or class missing")

        self.session.add(
            ClassTeacherRole(
                class_id=cls.id,
                ad_object_guid=user.ad_object_guid,
                role=role,
                valid_from=valid_from,
                valid_to=valid_to,
                created_by=self.scope.upn,
            )
        )

    # ----- Cancel -------------------------------------------------------

    async def cancel(self, *, job_id: int, ip: str | None, request_id: str) -> ImportJob:
        job = await self.session.get(ImportJob, job_id)
        if job is None:
            raise ImportJobNotFoundError(str(job_id))
        if job.status != IMPORT_STATUS_STAGED:
            raise ImportJobBadStateError(f"job is {job.status}, expected staged")
        job.status = IMPORT_STATUS_CANCELLED
        await self.session.flush()
        await self.audit.emit(
            action="import_cancelled",
            target_kind="import_job",
            target_id=str(job.id),
            actor_upn=self.scope.upn,
            actor_object_guid=self.scope.ad_object_guid,
            school_id=job.school_id,
            ip=ip,
            request_id=request_id,
            payload={"kind": job.kind},
        )
        return job

    # ----- Read ---------------------------------------------------------

    async def get_with_rows(
        self, *, job_id: int
    ) -> tuple[ImportJob, list[ImportStagedRow], dict[str, int]]:
        job = await self.session.get(ImportJob, job_id)
        if job is None:
            raise ImportJobNotFoundError(str(job_id))
        rows = (
            (
                await self.session.execute(
                    select(ImportStagedRow)
                    .where(ImportStagedRow.job_id == job.id)
                    .order_by(ImportStagedRow.row_num)
                )
            )
            .scalars()
            .all()
        )
        counts = {
            IMPORT_ACTION_CREATE: 0,
            IMPORT_ACTION_UPDATE: 0,
            IMPORT_ACTION_SKIP: 0,
            IMPORT_ACTION_ERROR: 0,
        }
        for r in rows:
            counts[r.action] = counts.get(r.action, 0) + 1
        return job, list(rows), counts

    async def list_jobs(self, *, school_ids: list[int] | None) -> list[ImportJob]:
        stmt = select(ImportJob).order_by(ImportJob.created_at.desc())
        if school_ids is not None:
            stmt = stmt.where(ImportJob.school_id.in_(school_ids))
        return list((await self.session.execute(stmt)).scalars().all())
