"""Letters module — parent letters addressed to a student in a class (M6 #5).

Depends on ``classes``. NB: the editable *document/mail templates* editor
(``admin_document_templates``) is NOT here — it is generic admin config that
also underpins password handouts, so it lives in the always-on ``platform``
module and stays reachable in the company profile too (#2 fix).
"""

from __future__ import annotations

from magister_api.modules.manifest import ModuleManifest
from magister_api.routers.letters import router as letters_router

LETTERS_MODULE = ModuleManifest(
    id="letters",
    routers=(letters_router,),
)
