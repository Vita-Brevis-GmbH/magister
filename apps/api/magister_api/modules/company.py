"""Company module — the company-edition superstructure (M6 Phase 2, ADR-0008).

Parallel to the school module: departments (Abteilungen/Teams) as the mid-level
org unit. Enabled by default in the ``company`` profile; the platform below is
shared unchanged. Memberships, manager roles and on-/offboarding are follow-up
slices layered on the same pattern.
"""

from __future__ import annotations

from magister_api.modules.manifest import ModuleManifest
from magister_api.routers.department_people import router as department_people_router
from magister_api.routers.departments import router as departments_router

COMPANY_MODULE = ModuleManifest(
    id="company",
    routers=(departments_router, department_people_router),
)
