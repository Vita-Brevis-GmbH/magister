"""School module — the school-specific superstructure (M6 Phase 0, ADR-0008).

Klassen, Klassenlehrer/Fachlehrer, Klassenmitgliedschaften, Stellvertretungen,
Eltern-Briefe und die (schul-geprägten) CSV-Importe. In a company edition this
module is swapped for a ``company`` module (Abteilungen/Vorgesetzte/…) while the
platform below stays identical.
"""

from __future__ import annotations

from magister_api.modules.manifest import ModuleManifest
from magister_api.routers.class_memberships import router as class_memberships_router
from magister_api.routers.class_teachers import router as class_teachers_router
from magister_api.routers.classes import router as classes_router
from magister_api.routers.imports import router as imports_router
from magister_api.routers.letters import router as letters_router
from magister_api.routers.subject_teachers import router as subject_teachers_router
from magister_api.routers.substitutions import router as substitutions_router

SCHOOL_MODULE = ModuleManifest(
    id="school",
    routers=(
        classes_router,
        class_teachers_router,
        subject_teachers_router,
        class_memberships_router,
        substitutions_router,
        letters_router,
        imports_router,
    ),
)
