"""Departments module — the company superstructure (M6 #5).

Abteilungen/Teams als mittlere Org-Einheit, Mitgliedschaften, Kader-Rollen und
On-/Offboarding. On by default in the company profile.
"""

from __future__ import annotations

from magister_api.modules.manifest import ModuleManifest
from magister_api.routers.company_lifecycle import router as company_lifecycle_router
from magister_api.routers.department_people import router as department_people_router
from magister_api.routers.departments import router as departments_router

DEPARTMENTS_MODULE = ModuleManifest(
    id="departments",
    routers=(departments_router, department_people_router, company_lifecycle_router),
)
