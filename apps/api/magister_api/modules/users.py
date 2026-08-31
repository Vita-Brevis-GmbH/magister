"""Users module — the user overview (M6, ADR-0008).

Account listing/detail/edit plus student and teacher password resets. Always-on
base surface (an installation without user administration is nonsensical); AD
mutations it triggers go through the ``ad`` module.
"""

from __future__ import annotations

from magister_api.modules.manifest import ModuleManifest
from magister_api.routers.student_password_reset import router as student_pw_reset_router
from magister_api.routers.teacher_password_reset import router as teacher_pw_reset_router
from magister_api.routers.user_password_reset import router as user_pw_reset_router
from magister_api.routers.users import router as users_router

USERS_MODULE = ModuleManifest(
    id="users",
    routers=(
        users_router,
        student_pw_reset_router,
        teacher_pw_reset_router,
        user_pw_reset_router,
    ),
)
