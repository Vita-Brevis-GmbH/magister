"""Classes module — the school superstructure (M6 #5).

Klassen, Klassenlehrer/Fachlehrer, Klassenmitgliedschaften und
Stellvertretungen. On by default in the school profile.
"""

from __future__ import annotations

from magister_api.modules.manifest import ModuleManifest
from magister_api.routers.class_memberships import router as class_memberships_router
from magister_api.routers.class_teachers import router as class_teachers_router
from magister_api.routers.classes import router as classes_router
from magister_api.routers.subject_teachers import router as subject_teachers_router
from magister_api.routers.substitutions import router as substitutions_router

CLASSES_MODULE = ModuleManifest(
    id="classes",
    routers=(
        classes_router,
        class_teachers_router,
        subject_teachers_router,
        class_memberships_router,
        substitutions_router,
    ),
)
