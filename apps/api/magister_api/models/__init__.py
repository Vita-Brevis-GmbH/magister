"""SQLAlchemy ORM models for Magister.

Importing this package registers all tables on ``Base.metadata``. Alembic's
env.py imports it for autogeneration target metadata.
"""

from magister_api.models.ad_sync_state import AdSyncState
from magister_api.models.app_settings import AppSettings
from magister_api.models.audit import AuditEvent
from magister_api.models.auth import AdUserCache, RoleAssignment, Session
from magister_api.models.base import Base
from magister_api.models.class_membership import ClassMembership
from magister_api.models.class_teacher_role import ClassTeacherRole
from magister_api.models.device import Device
from magister_api.models.import_job import ImportJob, ImportStagedRow
from magister_api.models.local_admin import LocalAdmin
from magister_api.models.school import School
from magister_api.models.school_class import SchoolClass
from magister_api.models.subject_teacher_role import SubjectTeacherRole
from magister_api.models.user_preferences import UserPreference

__all__ = [
    "AdSyncState",
    "AdUserCache",
    "AppSettings",
    "AuditEvent",
    "Base",
    "ClassMembership",
    "ClassTeacherRole",
    "Device",
    "ImportJob",
    "ImportStagedRow",
    "LocalAdmin",
    "RoleAssignment",
    "School",
    "SchoolClass",
    "Session",
    "SubjectTeacherRole",
    "UserPreference",
]
