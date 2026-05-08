"""SQLAlchemy ORM models for Magister.

Importing this package registers all tables on ``Base.metadata``. Alembic's
env.py imports it for autogeneration target metadata.
"""

from magister_api.models.audit import AuditEvent
from magister_api.models.auth import AdUserCache, RoleAssignment, Session
from magister_api.models.base import Base
from magister_api.models.class_membership import ClassMembership
from magister_api.models.class_teacher_role import ClassTeacherRole
from magister_api.models.local_admin import LocalAdmin
from magister_api.models.school import School
from magister_api.models.school_class import SchoolClass

__all__ = [
    "AdUserCache",
    "AuditEvent",
    "Base",
    "ClassMembership",
    "ClassTeacherRole",
    "LocalAdmin",
    "RoleAssignment",
    "School",
    "SchoolClass",
    "Session",
]
