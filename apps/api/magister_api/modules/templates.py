"""Templates module — Vorlagen/Texte (M6, ADR-0008).

Editable document/text templates plus the mail-merge letter generation that
consumes them. A switchable fachfunction (default on for both school and
company); with it off, the Vorlagen surface disappears from the nav and its
routes 404 at request time.
"""

from __future__ import annotations

from magister_api.modules.manifest import ModuleManifest
from magister_api.routers.admin_document_templates import router as admin_document_templates_router
from magister_api.routers.letters import router as letters_router

TEMPLATES_MODULE = ModuleManifest(
    id="templates",
    routers=(
        letters_router,
        admin_document_templates_router,
    ),
)
