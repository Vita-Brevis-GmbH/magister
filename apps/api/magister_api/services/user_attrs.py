"""User-attribute mutation service (LDAP MODIFY + DB upsert + audit).

Backs ``PATCH /users/{ad_object_guid}``. Splits the payload into AD-bound
fields (written via LDAP MODIFY) and Magister-only fields
(``temp_device_name``), then mirrors the AD-bound changes into
``ad_user_cache`` so the listing endpoint reflects them immediately
without waiting for the next sync.

Per-field RBAC: ``upn`` and ``sam_account_name`` require admin. The
route's outer dependency (``require_user_writer``) admits admin OR SMI;
SMI sending one of the login-relevant fields is refused here with 403.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import update as sqla_update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.ad.client import AdClient
from magister_api.ad.errors import AdUnavailableError
from magister_api.audit.service import AuditService
from magister_api.config import Settings
from magister_api.models.auth import AdUserCache
from magister_api.repositories.base import ScopeContext
from magister_api.schemas.user_attrs import UserAttributesUpdate

# AD attribute name → ad_user_cache column name. Magister-only fields
# (``temp_device_name``) are handled separately.
_AD_ATTR_TO_COLUMN: dict[str, str] = {
    "displayName": "display_name",
    "userPrincipalName": "upn",
    "sAMAccountName": "sam_account_name",
    "mail": "mail",
    "streetAddress": "street_address",
    "l": "locality",
    "postalCode": "postal_code",
    "co": "country",
}

# Payload field → AD attribute name.
_PAYLOAD_TO_AD_ATTR: dict[str, str] = {
    "display_name": "displayName",
    "upn": "userPrincipalName",
    "sam_account_name": "sAMAccountName",
    "mail": "mail",
    "street_address": "streetAddress",
    "locality": "l",
    "postal_code": "postalCode",
    "country": "co",
}

# Fields a non-admin (SMI) is NOT allowed to change — login-relevant.
ADMIN_ONLY_FIELDS: frozenset[str] = frozenset({"upn", "sam_account_name"})

# Fields that hit AD; the rest go to Magister-DB only.
AD_FIELDS: frozenset[str] = frozenset(_PAYLOAD_TO_AD_ATTR.keys())
MAGISTER_ONLY_FIELDS: frozenset[str] = frozenset({"temp_device_name"})


class DomainNotAllowedError(ValueError):
    """The UPN/mail domain is not in app_settings.mail_domains."""


class DomainAllowlistEmptyError(ValueError):
    """A UPN/mail change was attempted while mail_domains is empty."""


class UpnConflictError(ValueError):
    """A UPN change collides with an existing ad_user_cache.upn (unique)."""


class UserNotInAdError(LookupError):
    """No DN was found in AD for the user's objectGUID."""


class AdminOnlyFieldError(PermissionError):
    """SMI attempted to change a field reserved to admins."""


@dataclass(frozen=True)
class UserAttributesResult:
    changed_keys: list[str]


class UserAttributesService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        scope: ScopeContext,
        ad: AdClient,
    ) -> None:
        self.session = session
        self.settings = settings
        self.scope = scope
        self.ad = ad
        self.audit = AuditService(session, settings)

    async def update(
        self,
        *,
        target: AdUserCache,
        payload: UserAttributesUpdate,
        mail_domains: list[str],
        ip: str | None,
        request_id: str,
    ) -> UserAttributesResult:
        # ------------------------------------------------------------------
        # 1) Slice the payload into "what the caller actually wants to change".
        #    Pydantic's model_fields_set keeps the set of explicitly-provided
        #    fields (model_dump(exclude_unset=True) gives us the values).
        # ------------------------------------------------------------------
        provided: dict[str, str | None] = payload.model_dump(exclude_unset=True)
        if not provided:
            return UserAttributesResult(changed_keys=[])

        # ------------------------------------------------------------------
        # 2) Per-field RBAC: admin-only fields refused for non-admin callers.
        # ------------------------------------------------------------------
        if not self.scope.is_admin:
            forbidden = ADMIN_ONLY_FIELDS & provided.keys()
            if forbidden:
                raise AdminOnlyFieldError(",".join(sorted(forbidden)))

        # ------------------------------------------------------------------
        # 3) Domain allowlist: UPN + mail (when present and non-empty).
        # ------------------------------------------------------------------
        for field in ("upn", "mail"):
            if field not in provided:
                continue
            new_val = provided[field]
            if not new_val:
                # Empty / None for `mail` clears the field — allowed.
                continue
            domain = new_val.rsplit("@", 1)[1]
            if not mail_domains:
                raise DomainAllowlistEmptyError(field)
            if domain not in {d.lower() for d in mail_domains}:
                raise DomainNotAllowedError(f"{field}:{domain}")

        # ------------------------------------------------------------------
        # 4) Drop no-op changes (value identical to current cache row).
        #    For UPN: also check the upn unique-conflict before touching AD.
        # ------------------------------------------------------------------
        actual_changes: dict[str, str | None] = {}
        for field, new_val in provided.items():
            current_val = getattr(target, field, None)
            # Treat empty string as None for comparison (cache stores None).
            normalised = new_val if new_val not in ("", None) else None
            if normalised == current_val:
                continue
            actual_changes[field] = normalised

        if not actual_changes:
            return UserAttributesResult(changed_keys=[])

        if "upn" in actual_changes:
            await self._check_upn_unique(actual_changes["upn"], target.ad_object_guid)

        # ------------------------------------------------------------------
        # 5) Write AD-bound fields via LDAP MODIFY (if any).
        # ------------------------------------------------------------------
        ad_changes = {
            _PAYLOAD_TO_AD_ATTR[f]: v
            for f, v in actual_changes.items()
            if f in AD_FIELDS
        }
        if ad_changes:
            user_dn = await self.ad.find_user_dn(target.ad_object_guid)
            if not user_dn:
                raise UserNotInAdError(target.ad_object_guid)
            try:
                await self.ad.modify_user_attributes(user_dn=user_dn, attributes=ad_changes)
            except AdUnavailableError:
                await self._emit_audit_failed(
                    target=target,
                    changed_keys=sorted(actual_changes.keys()),
                    reason="ldap_unavailable",
                    ip=ip,
                    request_id=request_id,
                )
                raise

        # ------------------------------------------------------------------
        # 6) Mirror into ad_user_cache so the listing reflects the change.
        # ------------------------------------------------------------------
        try:
            await self.session.execute(
                sqla_update(AdUserCache)
                .where(AdUserCache.ad_object_guid == target.ad_object_guid)
                .values(**actual_changes)
            )
        except IntegrityError as exc:
            raise UpnConflictError("upn") from exc

        # ------------------------------------------------------------------
        # 7) Audit. Payload carries only the *list* of changed keys — no
        #    before/after values to keep PII out of the audit trail.
        # ------------------------------------------------------------------
        await self.audit.emit(
            action="user_attribute_changed",
            target_kind="ad_user",
            target_id=target.ad_object_guid,
            actor_upn=self.scope.upn,
            actor_object_guid=self.scope.ad_object_guid,
            school_id=target.school_id,
            ip=ip,
            request_id=request_id,
            payload={"changed_keys": sorted(actual_changes.keys())},
        )
        return UserAttributesResult(changed_keys=sorted(actual_changes.keys()))

    # ----------------------------------------------------------------------

    async def _check_upn_unique(self, new_upn: str | None, own_guid: str) -> None:
        if not new_upn:
            return
        # scope-bypass: uniqueness check across all users is the point.
        from sqlalchemy import select

        stmt = select(AdUserCache.ad_object_guid).where(AdUserCache.upn == new_upn)
        result = await self.session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is not None and row != own_guid:
            raise UpnConflictError(new_upn)

    async def _emit_audit_failed(
        self,
        *,
        target: AdUserCache,
        changed_keys: list[str],
        reason: str,
        ip: str | None,
        request_id: str,
    ) -> None:
        await self.audit.emit(
            action="user_attribute_change_failed",
            target_kind="ad_user",
            target_id=target.ad_object_guid,
            actor_upn=self.scope.upn,
            actor_object_guid=self.scope.ad_object_guid,
            school_id=target.school_id,
            ip=ip,
            request_id=request_id,
            payload={"changed_keys": changed_keys, "reason": reason},
        )


__all__ = [
    "AdminOnlyFieldError",
    "DomainAllowlistEmptyError",
    "DomainNotAllowedError",
    "UpnConflictError",
    "UserAttributesResult",
    "UserAttributesService",
    "UserNotInAdError",
    "ADMIN_ONLY_FIELDS",
    "AD_FIELDS",
    "MAGISTER_ONLY_FIELDS",
]
