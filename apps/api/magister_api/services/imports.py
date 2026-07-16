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
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, AsyncSessionTransaction

from magister_api.ad.client import AdClient
from magister_api.ad.ou import (
    select_provision_groups,
    select_student_ou,
    zyklus_for_jahrgangsstufe,
)
from magister_api.ad.password import generate_readable_password, generate_teacher_password
from magister_api.audit.service import AuditService
from magister_api.config import Settings
from magister_api.models.app_settings import AppSettings
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
    IMPORT_KIND_STUDENTS,
    IMPORT_KIND_TEACHERS,
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

logger = logging.getLogger(__name__)

# sAMAccountName is capped at 20 chars in AD; UPN local part beyond that must
# be shortened by an explicit column value.
_SAM_MAX_LEN = 20
_FORCE_CHANGE_TRUE = {"true", "1", "ja", "yes", "x", "wahr"}
_FORCE_CHANGE_FALSE = {"false", "0", "nein", "no", "falsch"}

# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

TEMPLATES: dict[str, tuple[list[str], list[list[str]]]] = {
    IMPORT_KIND_CLASSES: (
        # jahrgangsstufe = untere/primäre Stufe; jahrgangsstufe_bis = optionale
        # obere Stufe für Mehrjahrgangsklassen/Basisstufe (leer = Einzelklasse).
        # Kindergarten: -1 = 1. KG, 0 = 2. KG, 1..13 = Klassen.
        ["name", "kuerzel", "jahrgangsstufe", "jahrgangsstufe_bis"],
        [
            ["3a", "3a", "3", ""],
            ["Mehrjahrgang 1-3", "M13", "1", "3"],
            ["Basisstufe A", "BSA", "-1", "1"],
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
    IMPORT_KIND_STUDENTS: (
        # Provisioning: creates NEW AD accounts. display_name/sam_account_name
        # are optional (derived when blank); mail is set equal to the UPN.
        # jahrgangsstufe (optional, last column) sets the student's own grade;
        # blank = the class's lower grade. -1 = 1. KG, 0 = 2. KG, 1..13.
        [
            "given_name",
            "surname",
            "display_name",
            "upn",
            "sam_account_name",
            "class",
            "valid_from",
            "force_change",
            "jahrgangsstufe",
            "cannot_change_password",
            "password_never_expires",
        ],
        [
            [
                "Anna",
                "Muster",
                "",
                "anna.muster@schule.ch",
                "",
                "3a",
                "2026-08-12",
                "true",
                "3",
                "",
                "",
            ],  # noqa: E501
            [
                "Ben",
                "Beispiel",
                "Ben B.",
                "ben.beispiel@schule.ch",
                "ben.beispiel",
                "3a",
                "2026-08-12",
                "false",
                "3",
                "true",
                "true",
            ],
            ["Clara", "Frey", "", "clara.frey@schule.ch", "", "3b", "2026-08-12", "", "", "", ""],
        ],
    ),
    IMPORT_KIND_TEACHERS: (
        # Provisioning: creates NEW AD teacher accounts in the teacher OU.
        # No class membership and no grade — teachers are assigned to classes
        # separately via the class_teachers import or the UI.
        [
            "given_name",
            "surname",
            "display_name",
            "upn",
            "sam_account_name",
            "force_change",
            "cannot_change_password",
            "password_never_expires",
        ],
        [
            ["Erika", "Lehrer", "", "erika.lehrer@schule.ch", "", "true", "", ""],
            [
                "Max",
                "Kollege",
                "Max K.",
                "max.kollege@schule.ch",
                "max.kollege",
                "false",
                "",
                "true",
            ],  # noqa: E501
            ["Sven", "Vertret", "", "sven.vertret@schule.ch", "", "", "", ""],
        ],
    ),
}


# Columns that may be omitted from the uploaded CSV (appended, in order).
# Old files without them still validate; the template ships them included.
OPTIONAL_HEADERS: dict[str, list[str]] = {
    IMPORT_KIND_CLASSES: ["jahrgangsstufe_bis"],
    IMPORT_KIND_STUDENTS: [
        "jahrgangsstufe",
        "cannot_change_password",
        "password_never_expires",
    ],
    IMPORT_KIND_TEACHERS: ["cannot_change_password", "password_never_expires"],
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


@dataclass(frozen=True)
class ProvisionedCredential:
    """One-time credential for a freshly provisioned student.

    Never persisted and never audited — surfaced once in the apply response so
    the caller can render the hand-out PDFs, then discarded.
    """

    upn: str
    display_name: str
    class_name: str
    password: str
    force_change: bool


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


def _parse_force_change(s: str) -> bool:
    """Parse the ``force_change`` CSV column. Empty defaults to True (safer)."""
    v = (s or "").strip().lower()
    if not v:
        return True
    if v in _FORCE_CHANGE_TRUE:
        return True
    if v in _FORCE_CHANGE_FALSE:
        return False
    raise ValueError(f"force_change must be true/false, got {s!r}")


def _parse_bool_flag(s: str, *, column: str) -> bool:
    """Parse an optional boolean CSV column. Empty defaults to False."""
    v = (s or "").strip().lower()
    if not v:
        return False
    if v in _FORCE_CHANGE_TRUE:
        return True
    if v in _FORCE_CHANGE_FALSE:
        return False
    raise ValueError(f"{column} must be true/false, got {s!r}")


def _derive_sam(upn: str, explicit: str) -> str:
    """sAMAccountName: explicit value if given, else the UPN local part."""
    return (explicit or "").strip() or upn.split("@", 1)[0]


def _norm_name(name: str) -> str:
    """Normalise a display name for duplicate detection (case + whitespace)."""
    return " ".join(name.split()).casefold()


class ImportService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        scope: ScopeContext,
        ad: AdClient | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.scope = scope
        self.ad = ad
        self.audit = AuditService(session, settings)
        # One-time credentials for the ``students`` provisioning import; read by
        # the router after apply() to build the hand-out PDFs. Never persisted.
        self.provisioned: list[ProvisionedCredential] = []
        self._app_settings: AppSettings | None = None
        # Intra-file duplicate guards for the ``students`` import — reset at the
        # start of each stage() so two rows can't both claim the same UPN /
        # sAMAccountName (AD would reject the second only at apply time).
        self._seen_upns: set[str] = set()
        self._seen_sams: set[str] = set()
        # Intra-file duplicate guard for the display name of provisioning
        # imports: the AD object's DN is ``CN=<display>,<OU>`` and CN must be
        # unique within the OU, so two rows with the same name would collide at
        # apply time (the second ``conn.add`` fails). Caught here so the operator
        # sees a clear "duplicate name" error instead of a cryptic AD failure.
        self._seen_names: set[str] = set()

    async def _app_settings_row(self) -> AppSettings:
        if self._app_settings is None:
            row = await self.session.get(AppSettings, 1)
            if row is None:
                raise ValueError("app_settings not initialised")
            self._app_settings = row
        return self._app_settings

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
        self._seen_upns = set()
        self._seen_sams = set()
        self._seen_names = set()
        template_header = TEMPLATES[kind][0]
        optional = OPTIONAL_HEADERS.get(kind, [])
        required = [h for h in template_header if h not in optional]
        reader = csv.DictReader(io.StringIO(csv_text))
        got = [(h or "").strip().lower() for h in (reader.fieldnames or [])]
        # Accept the required columns, optionally followed by the optional
        # columns in order (so both the old and the new template validate).
        accepted = [[h.lower() for h in required + optional[:k]] for k in range(len(optional) + 1)]
        if got not in accepted:
            raise InvalidCsvError(
                f"csv header must be {required} (optional: {optional}), got {reader.fieldnames!r}"
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
            if kind == IMPORT_KIND_STUDENTS:
                return await self._classify_student(school_id, row)
            if kind == IMPORT_KIND_TEACHERS:
                return await self._classify_teacher_provision(row)
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
        jahrgangsstufe: int | None = None
        try:
            jahrgangsstufe = int(jahrgangsstufe_raw)
            # -1 = 1. Kindergarten, 0 = 2. Kindergarten, 1..13 = Klassen.
            if not -1 <= jahrgangsstufe <= 13:
                errors.append("jahrgangsstufe must be -1..13")
        except ValueError:
            errors.append("jahrgangsstufe must be an integer")

        # Optional upper bound for multi-grade classes / Basisstufe.
        bis_raw = row.get("jahrgangsstufe_bis", "").strip()
        jahrgangsstufe_bis: int | None = None
        if bis_raw:
            try:
                jahrgangsstufe_bis = int(bis_raw)
                if not -1 <= jahrgangsstufe_bis <= 13:
                    errors.append("jahrgangsstufe_bis must be -1..13")
                elif jahrgangsstufe is not None and jahrgangsstufe_bis < jahrgangsstufe:
                    errors.append("jahrgangsstufe_bis must be >= jahrgangsstufe")
            except ValueError:
                errors.append("jahrgangsstufe_bis must be an integer")

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
        if (
            existing.kuerzel == kuerzel
            and existing.jahrgangsstufe == jahrgangsstufe
            and existing.jahrgangsstufe_bis == jahrgangsstufe_bis
        ):
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

    async def _classify_student(self, school_id: int, row: dict[str, str]) -> tuple[str, list[str]]:
        errors: list[str] = []
        given = row.get("given_name", "").strip()
        surname = row.get("surname", "").strip()
        upn = row.get("upn", "").strip().lower()
        class_name = row.get("class", "").strip()

        if not given:
            errors.append("given_name is required")
        if not surname:
            errors.append("surname is required")
        if not upn or "@" not in upn or "." not in upn.split("@", 1)[1]:
            errors.append("upn is required and must look like name@domain.tld")
        if not class_name:
            errors.append("class is required")
        grade_raw = row.get("jahrgangsstufe", "").strip()
        if grade_raw:
            try:
                grade = int(grade_raw)
                if not -1 <= grade <= 13:
                    errors.append("jahrgangsstufe must be -1..13")
            except ValueError:
                errors.append("jahrgangsstufe must be an integer")
        try:
            _parse_date(row.get("valid_from", ""))
        except ValueError as exc:
            errors.append(str(exc))
        try:
            _parse_force_change(row.get("force_change", ""))
        except ValueError as exc:
            errors.append(str(exc))
        for flag_col in ("cannot_change_password", "password_never_expires"):
            try:
                _parse_bool_flag(row.get(flag_col, ""), column=flag_col)
            except ValueError as exc:
                errors.append(str(exc))
        if upn and "@" in upn:
            sam = _derive_sam(upn, row.get("sam_account_name", ""))
            if len(sam) > _SAM_MAX_LEN:
                errors.append(
                    f"sam_account_name {sam!r} exceeds {_SAM_MAX_LEN} chars — set an explicit one"
                )
        if errors:
            return IMPORT_ACTION_ERROR, errors

        sam = _derive_sam(upn, row.get("sam_account_name", ""))
        # Intra-file duplicates: catch two rows claiming the same identity here,
        # rather than letting the second one fail cryptically at apply time.
        if upn in self._seen_upns:
            return IMPORT_ACTION_ERROR, [f"duplicate upn {upn} in this file"]
        self._seen_upns.add(upn)
        if sam in self._seen_sams:
            return IMPORT_ACTION_ERROR, [f"duplicate sam_account_name {sam!r} in this file"]
        self._seen_sams.add(sam)

        settings_row = await self._app_settings_row()
        domain = upn.split("@", 1)[1]
        if settings_row.mail_domains and domain not in settings_row.mail_domains:
            return IMPORT_ACTION_ERROR, [f"upn domain {domain!r} not in allowed mail domains"]

        cls = await self._lookup_class(school_id, class_name)
        if cls is None:
            return IMPORT_ACTION_ERROR, [f"class {class_name!r} not found in school"]

        ou = select_student_ou(
            jahrgangsstufe=cls.jahrgangsstufe,
            ou_zyklus3=settings_row.ad_ou_students_zyklus3,
            ou_other=settings_row.ad_ou_students_other,
            zyklus1_max=settings_row.zyklus1_max_grade,
            zyklus2_max=settings_row.zyklus2_max_grade,
        )
        if not ou:
            zyklus = zyklus_for_jahrgangsstufe(
                cls.jahrgangsstufe,
                zyklus1_max=settings_row.zyklus1_max_grade,
                zyklus2_max=settings_row.zyklus2_max_grade,
            )
            return IMPORT_ACTION_ERROR, [
                f"target OU for Zyklus {zyklus} not configured in settings"
            ]

        # scope-bypass: UPN is an AD-global identifier — a new account must be
        # unique across ALL schools, so this existence check is intentionally
        # not school_id-filtered.
        existing = (
            await self.session.execute(select(AdUserCache).where(AdUserCache.upn == upn))
        ).scalar_one_or_none()
        if existing is not None:
            return IMPORT_ACTION_ERROR, [f"upn {upn} already exists"]

        # scope-bypass: sAMAccountName is likewise AD-global and must be unique
        # across all schools.
        existing_sam = (
            await self.session.execute(
                select(AdUserCache).where(AdUserCache.sam_account_name == sam)
            )
        ).scalar_one_or_none()
        if existing_sam is not None:
            return IMPORT_ACTION_ERROR, [f"sam_account_name {sam!r} already exists"]

        return IMPORT_ACTION_CREATE, []

    async def _classify_teacher_provision(self, row: dict[str, str]) -> tuple[str, list[str]]:
        """Validate a teacher-provisioning row (create a NEW AD teacher account).

        Like students but without a class or grade; the account lands in the
        configured teacher OU (``ad_ou_teachers``).
        """
        errors: list[str] = []
        given = row.get("given_name", "").strip()
        surname = row.get("surname", "").strip()
        upn = row.get("upn", "").strip().lower()

        if not given:
            errors.append("given_name is required")
        if not surname:
            errors.append("surname is required")
        if not upn or "@" not in upn or "." not in upn.split("@", 1)[1]:
            errors.append("upn is required and must look like name@domain.tld")
        try:
            _parse_force_change(row.get("force_change", ""))
        except ValueError as exc:
            errors.append(str(exc))
        for flag_col in ("cannot_change_password", "password_never_expires"):
            try:
                _parse_bool_flag(row.get(flag_col, ""), column=flag_col)
            except ValueError as exc:
                errors.append(str(exc))
        if upn and "@" in upn:
            sam = _derive_sam(upn, row.get("sam_account_name", ""))
            if len(sam) > _SAM_MAX_LEN:
                errors.append(
                    f"sam_account_name {sam!r} exceeds {_SAM_MAX_LEN} chars — set an explicit one"
                )
        if errors:
            return IMPORT_ACTION_ERROR, errors

        sam = _derive_sam(upn, row.get("sam_account_name", ""))
        if upn in self._seen_upns:
            return IMPORT_ACTION_ERROR, [f"duplicate upn {upn} in this file"]
        self._seen_upns.add(upn)
        if sam in self._seen_sams:
            return IMPORT_ACTION_ERROR, [f"duplicate sam_account_name {sam!r} in this file"]
        self._seen_sams.add(sam)

        # Display name = the AD CN. All teachers land in the single teacher OU,
        # so two rows with the same name collide on the DN at apply time. Flag
        # the duplicate here (in-file) so the operator fixes it up front.
        display = (row.get("display_name") or "").strip() or f"{given} {surname}"
        name_key = _norm_name(display)
        if name_key in self._seen_names:
            return IMPORT_ACTION_ERROR, [
                f"duplicate name {display!r} in this file — CN must be unique in the teacher OU; "
                "give one an explicit display_name"
            ]
        self._seen_names.add(name_key)

        settings_row = await self._app_settings_row()
        domain = upn.split("@", 1)[1]
        if settings_row.mail_domains and domain not in settings_row.mail_domains:
            return IMPORT_ACTION_ERROR, [f"upn domain {domain!r} not in allowed mail domains"]
        if not settings_row.ad_ou_teachers:
            return IMPORT_ACTION_ERROR, ["teacher OU not configured in settings"]

        # scope-bypass: UPN + sAMAccountName are AD-global; uniqueness must be
        # checked across all schools, not just the import's school.
        existing = (
            await self.session.execute(select(AdUserCache).where(AdUserCache.upn == upn))
        ).scalar_one_or_none()
        if existing is not None:
            return IMPORT_ACTION_ERROR, [f"upn {upn} already exists"]
        existing_sam = (
            await self.session.execute(
                select(AdUserCache).where(AdUserCache.sam_account_name == sam)
            )
        ).scalar_one_or_none()
        if existing_sam is not None:
            return IMPORT_ACTION_ERROR, [f"sam_account_name {sam!r} already exists"]

        # An existing teacher with the same CN would also collide in the OU.
        # scope-bypass: the teacher OU is global (one OU for all schools).
        existing_name = (
            await self.session.execute(
                select(AdUserCache).where(
                    AdUserCache.kind == "teacher",
                    func.lower(AdUserCache.display_name) == display.lower(),
                )
            )
        ).first()
        if existing_name is not None:
            return IMPORT_ACTION_ERROR, [f"a teacher named {display!r} already exists"]

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
            raise ImportJobBadStateError("import_job_not_staged")

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

            cred: ProvisionedCredential | None = None
            # begin_nested() is opened *inside* the try so that a savepoint that
            # cannot be started (e.g. a connection that a prior row left in a bad
            # state) degrades to a per-row failure instead of a request-wide 500
            # that would roll back — and thereby discard from Magister — every
            # teacher already provisioned in AD this run.
            sp: AsyncSessionTransaction | None = None
            try:
                sp = await self.session.begin_nested()
                if job.kind == IMPORT_KIND_CLASSES:
                    await self._apply_class(job.school_id, staged)
                elif job.kind == IMPORT_KIND_CLASS_MEMBERSHIPS:
                    await self._apply_membership(job.school_id, staged)
                elif job.kind == IMPORT_KIND_CLASS_TEACHERS:
                    await self._apply_teacher_role(job.school_id, staged)
                elif job.kind == IMPORT_KIND_STUDENTS:
                    cred = await self._apply_student(job.school_id, staged, ip, request_id)
                elif job.kind == IMPORT_KIND_TEACHERS:
                    cred = await self._apply_teacher_provision(
                        job.school_id, staged, ip, request_id
                    )
                else:
                    raise ValueError(f"unsupported kind {job.kind}")
                await sp.commit()
                # Count + append only AFTER the row's savepoint commits, so a
                # failed flush never leaves the row double-counted (created AND
                # failed) or leaks a credential into the hand-out list.
                staged.applied_at = now
                if staged.action == IMPORT_ACTION_CREATE:
                    applied_counts["created"] += 1
                else:
                    applied_counts["updated"] += 1
                if cred is not None:
                    self.provisioned.append(cred)
            except Exception as exc:  # noqa: BLE001
                if sp is not None:
                    try:
                        await sp.rollback()
                    except Exception as rb_exc:  # noqa: BLE001
                        # Savepoint already gone (connection dropped mid-row) —
                        # nothing to release; keep going so other rows and the
                        # summary still get a chance to complete.
                        logger.warning(
                            "savepoint rollback failed for row %s: %s", staged.id, rb_exc
                        )
                staged.applied_at = now
                staged.applied_error = str(exc)[:512]
                applied_counts["failed"] += 1

        job.status = IMPORT_STATUS_APPLIED
        job.applied_at = now
        job.summary = {**job.summary, "applied": applied_counts}
        await self.session.flush()

        # The actual mutations (teacher_provisioned / student_provisioned, or
        # the class/membership writes) are already audited inside each committed
        # per-row savepoint. This ``import_applied`` event is a *summary* — so
        # isolate it in its own savepoint. An audit-infra failure here (e.g. a
        # pgcrypto / audit-key problem at encrypt time) must never propagate out
        # of apply(), because the request session would then roll back the WHOLE
        # transaction and discard from Magister every account already created in
        # AD this run — leaving orphaned teachers (the reported bulk-import bug).
        sp_audit: AsyncSessionTransaction | None = None
        try:
            sp_audit = await self.session.begin_nested()
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
            await sp_audit.commit()
        except Exception as exc:  # noqa: BLE001
            if sp_audit is not None:
                try:
                    await sp_audit.rollback()
                except Exception as rb_exc:  # noqa: BLE001
                    logger.warning("import_applied audit rollback failed: %s", rb_exc)
            logger.error("import_applied audit emit failed for job %s: %s", job.id, exc)
        return job

    async def _apply_class(self, school_id: int, staged: ImportStagedRow) -> None:
        row = staged.raw_data
        name = row["name"].strip()
        kuerzel = (row.get("kuerzel") or "").strip() or None
        jahrgangsstufe = int(row["jahrgangsstufe"])
        bis_raw = (row.get("jahrgangsstufe_bis") or "").strip()
        jahrgangsstufe_bis = int(bis_raw) if bis_raw else None

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
                    jahrgangsstufe_bis=jahrgangsstufe_bis,
                    status=CLASS_STATUS_ACTIVE,
                )
            )
        else:
            existing.kuerzel = kuerzel
            existing.jahrgangsstufe = jahrgangsstufe
            existing.jahrgangsstufe_bis = jahrgangsstufe_bis

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

    async def _apply_student(
        self, school_id: int, staged: ImportStagedRow, ip: str | None, request_id: str
    ) -> ProvisionedCredential:
        if self.ad is None:
            raise ValueError("ad_client_unavailable")
        row = staged.raw_data
        given = row["given_name"].strip()
        surname = row["surname"].strip()
        upn = row["upn"].strip().lower()
        class_name = row["class"].strip()
        display = (row.get("display_name") or "").strip() or f"{given} {surname}"
        sam = _derive_sam(upn, row.get("sam_account_name", ""))
        force_change = _parse_force_change(row.get("force_change", ""))
        cannot_change_password = _parse_bool_flag(
            row.get("cannot_change_password", ""), column="cannot_change_password"
        )
        password_never_expires = _parse_bool_flag(
            row.get("password_never_expires", ""), column="password_never_expires"
        )
        valid_from = _parse_date(row.get("valid_from", "")) or utcnow()

        grade_raw = (row.get("jahrgangsstufe") or "").strip()

        cls = await self._lookup_class(school_id, class_name)
        if cls is None:
            raise ValueError(f"class {class_name!r} not found")
        # Per-student grade: explicit value, else the class's lower/primary grade.
        jahrgangsstufe = int(grade_raw) if grade_raw else cls.jahrgangsstufe
        settings_row = await self._app_settings_row()
        ou = select_student_ou(
            jahrgangsstufe=cls.jahrgangsstufe,
            ou_zyklus3=settings_row.ad_ou_students_zyklus3,
            ou_other=settings_row.ad_ou_students_other,
            zyklus1_max=settings_row.zyklus1_max_grade,
            zyklus2_max=settings_row.zyklus2_max_grade,
        )
        if not ou:
            raise ValueError("target_ou_not_configured")

        zyklus = zyklus_for_jahrgangsstufe(
            jahrgangsstufe,
            zyklus1_max=settings_row.zyklus1_max_grade,
            zyklus2_max=settings_row.zyklus2_max_grade,
        )
        group_dns = select_provision_groups(
            kind="student",
            zyklus=zyklus,
            groups_teacher=settings_row.ad_groups_teacher,
            groups_student_zyklus1=settings_row.ad_groups_student_zyklus1,
            groups_student_zyklus2=settings_row.ad_groups_student_zyklus2,
            groups_student_zyklus3=settings_row.ad_groups_student_zyklus3,
        )

        password = generate_readable_password()
        guid = await self.ad.create_user(
            ou_dn=ou,
            common_name=display,
            sam_account_name=sam,
            user_principal_name=upn,
            mail=upn,  # mail equals UPN by policy
            given_name=given,
            surname=surname,
            display_name=display,
            password=password,
            force_change=force_change,
            password_never_expires=password_never_expires,
            cannot_change_password=cannot_change_password,
            group_dns=group_dns,
        )

        self.session.add(
            AdUserCache(
                ad_object_guid=guid,
                school_id=school_id,
                upn=upn,
                sam_account_name=sam,
                given_name=given,
                surname=surname,
                display_name=display,
                mail=upn,
                kind="student",
                enabled=True,
                last_sync_at=utcnow(),
                jahrgangsstufe=jahrgangsstufe,
                password_never_expires=password_never_expires,
                cannot_change_password=cannot_change_password,
            )
        )
        self.session.add(
            ClassMembership(
                class_id=cls.id,
                ad_object_guid=guid,
                valid_from=valid_from,
                valid_to=None,
                created_by=self.scope.upn,
            )
        )
        # Audit the provisioning — never the password (allowlist would reject it).
        await self.audit.emit(
            action="student_provisioned",
            target_kind="ad_user",
            target_id=guid,
            actor_upn=self.scope.upn,
            actor_object_guid=self.scope.ad_object_guid,
            school_id=school_id,
            ip=ip,
            request_id=request_id,
            payload={"upn": upn, "class_name": class_name, "force_change": force_change},
        )
        return ProvisionedCredential(
            upn=upn,
            display_name=display,
            class_name=class_name,
            password=password,
            force_change=force_change,
        )

    async def _apply_teacher_provision(
        self, school_id: int, staged: ImportStagedRow, ip: str | None, request_id: str
    ) -> ProvisionedCredential:
        if self.ad is None:
            raise ValueError("ad_client_unavailable")
        row = staged.raw_data
        given = row["given_name"].strip()
        surname = row["surname"].strip()
        upn = row["upn"].strip().lower()
        display = (row.get("display_name") or "").strip() or f"{given} {surname}"
        sam = _derive_sam(upn, row.get("sam_account_name", ""))
        force_change = _parse_force_change(row.get("force_change", ""))
        cannot_change_password = _parse_bool_flag(
            row.get("cannot_change_password", ""), column="cannot_change_password"
        )
        password_never_expires = _parse_bool_flag(
            row.get("password_never_expires", ""), column="password_never_expires"
        )

        settings_row = await self._app_settings_row()
        ou = settings_row.ad_ou_teachers
        if not ou:
            raise ValueError("teacher_ou_not_configured")

        group_dns = select_provision_groups(
            kind="teacher",
            zyklus=None,
            groups_teacher=settings_row.ad_groups_teacher,
            groups_student_zyklus1=settings_row.ad_groups_student_zyklus1,
            groups_student_zyklus2=settings_row.ad_groups_student_zyklus2,
            groups_student_zyklus3=settings_row.ad_groups_student_zyklus3,
        )

        # Teachers get a 12-char password with all four charset classes, using
        # only keyboard-friendly special chars (.,!$-_+*:;) — not the kid-
        # friendly word password students receive.
        password = generate_teacher_password()
        guid = await self.ad.create_user(
            ou_dn=ou,
            common_name=display,
            sam_account_name=sam,
            user_principal_name=upn,
            mail=upn,
            given_name=given,
            surname=surname,
            display_name=display,
            password=password,
            force_change=force_change,
            password_never_expires=password_never_expires,
            cannot_change_password=cannot_change_password,
            group_dns=group_dns,
        )

        self.session.add(
            AdUserCache(
                ad_object_guid=guid,
                school_id=school_id,
                upn=upn,
                sam_account_name=sam,
                given_name=given,
                surname=surname,
                display_name=display,
                mail=upn,
                kind="teacher",
                enabled=True,
                last_sync_at=utcnow(),
                password_never_expires=password_never_expires,
                cannot_change_password=cannot_change_password,
            )
        )
        await self.audit.emit(
            action="teacher_provisioned",
            target_kind="ad_user",
            target_id=guid,
            actor_upn=self.scope.upn,
            actor_object_guid=self.scope.ad_object_guid,
            school_id=school_id,
            ip=ip,
            request_id=request_id,
            payload={"upn": upn, "force_change": force_change},
        )
        return ProvisionedCredential(
            upn=upn,
            display_name=display,
            class_name="",
            password=password,
            force_change=force_change,
        )

    # ----- Cancel -------------------------------------------------------

    async def cancel(self, *, job_id: int, ip: str | None, request_id: str) -> ImportJob:
        job = await self.session.get(ImportJob, job_id)
        if job is None:
            raise ImportJobNotFoundError(str(job_id))
        if job.status != IMPORT_STATUS_STAGED:
            raise ImportJobBadStateError("import_job_not_staged")
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
