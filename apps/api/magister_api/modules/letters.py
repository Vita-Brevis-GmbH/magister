"""Letters module — parent letters + their editable templates (M6 #5).

Depends on ``classes``: the letters are addressed to a student in a class.
"""

from __future__ import annotations

from magister_api.modules.manifest import ModuleManifest
from magister_api.routers.admin_document_templates import router as admin_document_templates_router
from magister_api.routers.letters import router as letters_router

LETTERS_MODULE = ModuleManifest(
    id="letters",
    routers=(letters_router, admin_document_templates_router),
)
