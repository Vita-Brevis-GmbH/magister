"""Platform module — the domain-neutral base (M6 Phase 0, ADR-0008).

Identity/AD, accounts, password reset, devices, audit, privacy, reporting,
self-service and the admin/config surfaces. School and company editions share
this module unchanged; only the superstructure above it (the ``school`` /
future ``company`` module) differs.

The platform/school split here is organisational only — Phase 0 mounts every
module, so behaviour is identical to the previous hard-coded router list. The
exact placement of a few edge routers (imports, reports) is provisional and
refined in later phases.
"""

from __future__ import annotations

from magister_api.modules.manifest import ModuleManifest
from magister_api.routers.admin_ad_groups import router as admin_ad_groups_router
from magister_api.routers.admin_local_admin import router as admin_local_admin_router
from magister_api.routers.admin_maintenance import router as admin_maintenance_router
from magister_api.routers.admin_modules import router as admin_modules_router
from magister_api.routers.admin_roles import router as admin_roles_router
from magister_api.routers.admin_settings import router as admin_settings_router
from magister_api.routers.admin_sync import router as admin_sync_router
from magister_api.routers.admin_system import router as admin_system_router
from magister_api.routers.admin_users import router as admin_users_router
from magister_api.routers.audit import router as audit_router
from magister_api.routers.auth import router as auth_router
from magister_api.routers.devices import router as devices_router
from magister_api.routers.me import router as me_router
from magister_api.routers.privacy import router as privacy_router
from magister_api.routers.reports import router as reports_router
from magister_api.routers.schools import router as schools_router
from magister_api.routers.student_password_reset import router as student_pw_reset_router
from magister_api.routers.teacher_password_reset import router as teacher_pw_reset_router
from magister_api.routers.users import router as users_router

PLATFORM_MODULE = ModuleManifest(
    id="platform",
    routers=(
        auth_router,
        schools_router,
        users_router,
        devices_router,
        me_router,
        student_pw_reset_router,
        teacher_pw_reset_router,
        audit_router,
        privacy_router,
        reports_router,
        admin_sync_router,
        admin_local_admin_router,
        admin_settings_router,
        admin_ad_groups_router,
        admin_roles_router,
        admin_users_router,
        admin_maintenance_router,
        admin_system_router,
        admin_modules_router,
    ),
)
