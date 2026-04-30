"""SQLAlchemy ORM models for Magister.

Importing this package registers all tables on ``Base.metadata``. Alembic's
env.py imports it for autogeneration target metadata.
"""

from magister_api.models.audit import AuditEvent
from magister_api.models.auth import AdUserCache, RoleAssignment, Session
from magister_api.models.base import Base
from magister_api.models.school import School

__all__ = [
    "AdUserCache",
    "AuditEvent",
    "Base",
    "RoleAssignment",
    "School",
    "Session",
]
