"""SQLAlchemy ORM models for Magister.

Importing this package registers all tables on ``Base.metadata``. Alembic's
env.py imports it for autogeneration target metadata.
"""

from magister_api.models.ad_group import AdGroupCache
from magister_api.models.ad_sync_state import AdSyncState
from magister_api.models.app_settings import AppSettings
from magister_api.models.audit import AuditEvent
from magister_api.models.auth import AdUserCache, RoleAssignment, Session
from magister_api.models.base import Base
from magister_api.models.class_membership import ClassMembership
from magister_api.models.class_teacher_role import ClassTeacherRole
from magister_api.models.department import Department
from magister_api.models.department_membership import DepartmentMembership
from magister_api.models.device import Device
from magister_api.models.document_template import DocumentTemplate
from magister_api.models.import_job import ImportJob, ImportStagedRow
from magister_api.models.local_admin import LocalAdmin
from magister_api.models.manager_role import ManagerRole
from magister_api.models.rbac import Role, RoleCapability
from magister_api.models.school import School
from magister_api.models.school_class import SchoolClass
from magister_api.models.subject_teacher_role import SubjectTeacherRole
from magister_api.models.user_preferences import UserPreference

__all__ = [
    "AdGroupCache",
    "AdSyncState",
    "AdUserCache",
    "AppSettings",
    "AuditEvent",
    "Base",
    "ClassMembership",
    "ClassTeacherRole",
    "Department",
    "DepartmentMembership",
    "Device",
    "DocumentTemplate",
    "ImportJob",
    "ImportStagedRow",
    "LocalAdmin",
    "ManagerRole",
    "Role",
    "RoleAssignment",
    "RoleCapability",
    "School",
    "SchoolClass",
    "Session",
    "SubjectTeacherRole",
    "UserPreference",
]
