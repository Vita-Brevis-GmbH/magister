"""Authentication & authorization layer.

- OIDC against the customer's Keycloak realm (Authorization Code + PKCE, ADR-0025)
- Server-side opaque sessions (SHA-256 of random bytes; cookie carries id only)
- RBAC dependencies (`require_role`)
- CSRF double-submit cookie
- Login accounts + bootstrap-admin grant on OIDC login
"""

from magister_api.auth.csrf import CsrfMiddleware, issue_csrf_token, verify_csrf_token
from magister_api.auth.current_user import (
    AuthenticatedUser,
    get_current_user,
    get_optional_user,
)
from magister_api.auth.rbac import (
    require_admin,
    require_role,
    require_schulleitung,
    require_smi,
)
from magister_api.auth.sessions import (
    SESSION_ID_BYTES,
    new_session_id,
)

__all__ = [
    "AuthenticatedUser",
    "CsrfMiddleware",
    "SESSION_ID_BYTES",
    "get_current_user",
    "get_optional_user",
    "issue_csrf_token",
    "new_session_id",
    "require_admin",
    "require_role",
    "require_schulleitung",
    "require_smi",
    "verify_csrf_token",
]
