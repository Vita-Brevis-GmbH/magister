"""Settings module — the administration/configuration surface (M6, ADR-0008).

App settings, local-admin fallback, roles + RBAC matrix, AD group templates
(Zielrollen), module toggles, maintenance and system (cert/restart/update). The
always-on ``/admin`` configuration base; toggling it off is not offered.
"""

from __future__ import annotations

from magister_api.modules.manifest import ModuleManifest
from magister_api.routers.admin_local_admin import router as admin_local_admin_router
from magister_api.routers.admin_maintenance import router as admin_maintenance_router
from magister_api.routers.admin_modules import router as admin_modules_router
from magister_api.routers.admin_rbac import router as admin_rbac_router
from magister_api.routers.admin_roles import router as admin_roles_router
from magister_api.routers.admin_settings import router as admin_settings_router
from magister_api.routers.admin_system import router as admin_system_router
from magister_api.routers.group_templates import router as group_templates_router

SETTINGS_MODULE = ModuleManifest(
    id="settings",
    routers=(
        admin_settings_router,
        admin_local_admin_router,
        group_templates_router,
        admin_roles_router,
        admin_rbac_router,
        admin_maintenance_router,
        admin_system_router,
        admin_modules_router,
    ),
)

#: Die Router, die dem **Betreiber** gehören, sobald es einen gibt
#: (ADR-0017 D1). Sie werden nicht gemountet, wenn die Datenebene ihre
#: Mandanten aus einer Konsole holt.
#:
#: Diese Liste steht hier und nicht in `main.py`, weil sie zum Wissen über
#: diese Router gehört: wer einen dazunimmt, sieht die Frage „gehört der dem
#: Kunden oder dem Betreiber?" an derselben Stelle, an der er ihn einträgt.
#:
#: **Nicht gemountet, nicht 403.** Ein Endpunkt, der antwortet „das darfst du
#: nicht", ist noch da: er kann eine Lücke haben, er steht im OpenAPI-Schema,
#: und ein späterer Umbau kann die Prüfung verlieren. Was nicht gemountet ist,
#: kann nichts.
#:
#: `admin_roles_router` steht ausdrücklich NICHT hier: das ist die
#: Rollen*zuweisung* an Personen und bleibt beim Kunden (Entscheid E2). Nur
#: die Rechte-*Matrix* — was eine Rolle darf — gehört dem Betreiber.
PLATFORM_OWNED_ROUTERS = (
    admin_settings_router,
    admin_rbac_router,
)
