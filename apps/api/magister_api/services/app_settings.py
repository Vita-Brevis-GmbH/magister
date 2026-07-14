"""DB-backed application settings service.

Mirrors the pgcrypto pattern of :class:`magister_api.audit.service.AuditService`
to read/write the encrypted secret columns: per-statement
``func.pgp_sym_encrypt(plaintext, MAGISTER_AUDIT_KEY)`` on writes and
``func.pgp_sym_decrypt(column, MAGISTER_AUDIT_KEY)`` on reads.

Cache invalidation: every :meth:`update` bumps ``app_settings.version``. The
OIDC/AD client deps in :mod:`magister_api.routers.auth` and
:mod:`magister_api.routers.admin_sync` cache the constructed clients on
``app.state`` keyed by that version; when the version changes a fresh client
is built without a process restart.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy import update as sqla_update
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.audit.service import AuditService
from magister_api.config import Settings
from magister_api.models.app_settings import AppSettings
from magister_api.schemas.app_settings import AppSettingsOut, AppSettingsUpdate

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EffectiveAppSettings:
    """Decrypted, in-memory view of the app_settings row.

    Returned by :meth:`AppSettingsService.get_effective`. Carries the
    ``version`` so callers can cache derived clients keyed by it.
    """

    version: int
    oidc_issuer: str | None
    oidc_client_id: str | None
    oidc_client_secret: str | None
    oidc_redirect_uri: str | None
    oidc_scopes: list[str]
    bootstrap_admins: list[str]
    mail_domains: list[str]
    ad_dcs: list[str]
    ad_bind_mode: str
    ad_bind_dn: str | None
    ad_bind_password: str | None
    ad_tls_verify: bool
    ad_tls_ca_pem: str | None
    ad_login_enabled: bool
    ad_login_group: str | None
    ad_users_search_base: str | None
    ad_computers_search_base: str | None
    ad_sync_interval_minutes: int


class AppSettingsService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self._settings = settings

    @property
    def _key(self) -> str:
        # Dedicated secrets key when configured, else the audit key (default).
        key = self._settings.app_secrets_key()
        if not key:
            raise RuntimeError(
                "neither MAGISTER_SECRETS_KEY nor MAGISTER_AUDIT_KEY is set — "
                "settings-secret access refused"
            )
        return key

    # ---------- reads ----------

    async def get_version(self) -> int:
        """One indexed scalar read; cheap enough to do per request."""
        stmt = select(AppSettings.version).where(AppSettings.id == 1)
        result = await self.session.execute(stmt)
        row = result.scalar_one_or_none()
        return int(row) if row is not None else 0

    async def get_effective(self) -> EffectiveAppSettings:
        """Decrypt secrets and return the in-memory view.

        # scope-bypass: app_settings is a global singleton (no school scope).
        """
        stmt = select(
            AppSettings.version,
            AppSettings.oidc_issuer,
            AppSettings.oidc_client_id,
            func.pgp_sym_decrypt(AppSettings.oidc_client_secret_enc, self._key).label(
                "oidc_client_secret"
            ),
            AppSettings.oidc_redirect_uri,
            AppSettings.oidc_scopes,
            AppSettings.bootstrap_admins,
            AppSettings.mail_domains,
            AppSettings.ad_dcs,
            AppSettings.ad_bind_mode,
            AppSettings.ad_bind_dn,
            func.pgp_sym_decrypt(AppSettings.ad_bind_password_enc, self._key).label(
                "ad_bind_password"
            ),
            AppSettings.ad_tls_verify,
            AppSettings.ad_tls_ca_pem,
            AppSettings.ad_login_enabled,
            AppSettings.ad_login_group,
            AppSettings.ad_users_search_base,
            AppSettings.ad_computers_search_base,
            AppSettings.ad_sync_interval_minutes,
        ).where(AppSettings.id == 1)
        result = await self.session.execute(stmt)
        row = result.one_or_none()
        if row is None:
            return _empty_effective()
        return EffectiveAppSettings(
            version=row.version,
            oidc_issuer=row.oidc_issuer,
            oidc_client_id=row.oidc_client_id,
            oidc_client_secret=row.oidc_client_secret,
            oidc_redirect_uri=row.oidc_redirect_uri,
            oidc_scopes=list(row.oidc_scopes or []),
            bootstrap_admins=list(row.bootstrap_admins or []),
            mail_domains=list(row.mail_domains or []),
            ad_dcs=list(row.ad_dcs or []),
            ad_bind_mode=row.ad_bind_mode,
            ad_bind_dn=row.ad_bind_dn,
            ad_bind_password=row.ad_bind_password,
            ad_tls_verify=bool(row.ad_tls_verify),
            ad_tls_ca_pem=row.ad_tls_ca_pem,
            ad_login_enabled=bool(row.ad_login_enabled),
            ad_login_group=row.ad_login_group,
            ad_users_search_base=row.ad_users_search_base,
            ad_computers_search_base=row.ad_computers_search_base,
            ad_sync_interval_minutes=row.ad_sync_interval_minutes,
        )

    async def get_redacted_for_api(self) -> AppSettingsOut:
        """GUI-facing payload — never carries plaintext secrets."""
        stmt = select(
            AppSettings.version,
            AppSettings.oidc_issuer,
            AppSettings.oidc_client_id,
            (AppSettings.oidc_client_secret_enc.is_not(None)).label("oidc_client_secret_set"),
            AppSettings.oidc_redirect_uri,
            AppSettings.oidc_scopes,
            AppSettings.bootstrap_admins,
            AppSettings.mail_domains,
            AppSettings.ad_dcs,
            AppSettings.ad_bind_mode,
            AppSettings.ad_bind_dn,
            (AppSettings.ad_bind_password_enc.is_not(None)).label("ad_bind_password_set"),
            AppSettings.ad_tls_verify,
            AppSettings.ad_tls_ca_pem,
            AppSettings.ad_login_enabled,
            AppSettings.ad_login_group,
            AppSettings.ad_users_search_base,
            AppSettings.ad_computers_search_base,
            AppSettings.ad_sync_interval_minutes,
            AppSettings.ad_ou_students_zyklus3,
            AppSettings.ad_ou_students_other,
            AppSettings.ad_ou_teachers,
            AppSettings.zyklus1_max_grade,
            AppSettings.zyklus2_max_grade,
            AppSettings.password_store_enabled,
            AppSettings.updated_at,
            AppSettings.updated_by_upn,
        ).where(AppSettings.id == 1)
        result = await self.session.execute(stmt)
        row = result.one()
        return AppSettingsOut(
            version=row.version,
            oidc_issuer=row.oidc_issuer,
            oidc_client_id=row.oidc_client_id,
            oidc_client_secret_set=bool(row.oidc_client_secret_set),
            oidc_redirect_uri=row.oidc_redirect_uri,
            oidc_scopes=list(row.oidc_scopes or []),
            bootstrap_admins=list(row.bootstrap_admins or []),
            mail_domains=list(row.mail_domains or []),
            ad_dcs=list(row.ad_dcs or []),
            ad_bind_mode=row.ad_bind_mode,
            ad_bind_dn=row.ad_bind_dn,
            ad_bind_password_set=bool(row.ad_bind_password_set),
            ad_tls_verify=bool(row.ad_tls_verify),
            ad_tls_ca_pem=row.ad_tls_ca_pem,
            ad_login_enabled=bool(row.ad_login_enabled),
            ad_login_group=row.ad_login_group,
            ad_users_search_base=row.ad_users_search_base,
            ad_computers_search_base=row.ad_computers_search_base,
            ad_sync_interval_minutes=row.ad_sync_interval_minutes,
            ad_ou_students_zyklus3=row.ad_ou_students_zyklus3,
            ad_ou_students_other=row.ad_ou_students_other,
            ad_ou_teachers=row.ad_ou_teachers,
            zyklus1_max_grade=row.zyklus1_max_grade,
            zyklus2_max_grade=row.zyklus2_max_grade,
            password_store_enabled=bool(row.password_store_enabled),
            updated_at=row.updated_at,
            updated_by_upn=row.updated_by_upn,
        )

    # ---------- writes ----------

    async def update(
        self,
        payload: AppSettingsUpdate,
        *,
        actor_upn: str,
        actor_object_guid: str | None,
        ip: str | None,
        request_id: str,
    ) -> AppSettingsOut:
        """Apply non-None fields, encrypt secrets only when payload sends them.

        Bumps ``version`` in the same transaction. Emits an audit event with
        the diff (secrets stripped — the allowlist would refuse them anyway).
        """
        values: dict[str, object] = {}
        diff: dict[str, object] = {}

        # Non-secret fields — None means "leave alone", anything else writes.
        plain_fields = {
            "oidc_issuer": payload.oidc_issuer,
            "oidc_client_id": payload.oidc_client_id,
            "oidc_redirect_uri": payload.oidc_redirect_uri,
            "oidc_scopes": payload.oidc_scopes,
            "bootstrap_admins": payload.bootstrap_admins,
            "mail_domains": payload.mail_domains,
            "ad_dcs": payload.ad_dcs,
            "ad_bind_mode": payload.ad_bind_mode,
            "ad_bind_dn": payload.ad_bind_dn,
            "ad_tls_verify": payload.ad_tls_verify,
            "ad_login_enabled": payload.ad_login_enabled,
            "ad_login_group": payload.ad_login_group,
            "ad_users_search_base": payload.ad_users_search_base,
            "ad_computers_search_base": payload.ad_computers_search_base,
            "ad_sync_interval_minutes": payload.ad_sync_interval_minutes,
            "ad_ou_students_zyklus3": payload.ad_ou_students_zyklus3,
            "ad_ou_students_other": payload.ad_ou_students_other,
            "ad_ou_teachers": payload.ad_ou_teachers,
            "zyklus1_max_grade": payload.zyklus1_max_grade,
            "zyklus2_max_grade": payload.zyklus2_max_grade,
        }
        for col, val in plain_fields.items():
            if val is not None:
                values[col] = val
                diff[col] = val

        # The vault master switch is applied like a plain field, but its diff
        # key is neutral: the audit-payload allowlist forbids any key containing
        # "password".
        if payload.password_store_enabled is not None:
            values["password_store_enabled"] = payload.password_store_enabled
            diff["vault_toggle"] = payload.password_store_enabled

        # Secret fields — only update when a non-empty string is sent.
        # The diff flags use neutral key names ("rotated_oidc_credential" /
        # "rotated_ad_credential") rather than ``oidc_client_secret_changed``
        # so they pass the audit-payload allowlist (which forbids any key
        # containing ``secret`` or ``password``).
        if payload.oidc_client_secret:
            values["oidc_client_secret_enc"] = func.pgp_sym_encrypt(
                payload.oidc_client_secret, self._key
            )
            diff["rotated_oidc_credential"] = True
        if payload.ad_bind_password:
            values["ad_bind_password_enc"] = func.pgp_sym_encrypt(
                payload.ad_bind_password, self._key
            )
            diff["rotated_ad_credential"] = True

        # CA PEM is not a secret, but it is bulky — record only whether a cert
        # is now present in the audit diff, never the PEM body. None = leave
        # unchanged; empty string = clear (store NULL).
        if payload.ad_tls_ca_pem is not None:
            pem = payload.ad_tls_ca_pem.strip() or None
            values["ad_tls_ca_pem"] = pem
            diff["ad_tls_ca_pem_set"] = pem is not None

        # Always bump version + updated_*.
        values["version"] = AppSettings.version + 1
        values["updated_at"] = func.now()
        values["updated_by_upn"] = actor_upn

        await self.session.execute(
            sqla_update(AppSettings).where(AppSettings.id == 1).values(**values)
        )

        await AuditService(self.session, self._settings).emit(
            action="app_settings_updated",
            target_kind="app_settings",
            target_id="1",
            actor_upn=actor_upn,
            actor_object_guid=actor_object_guid,
            school_id=None,
            ip=ip,
            request_id=request_id,
            payload=diff or {"noop": True},
        )

        return await self.get_redacted_for_api()

    # ---------- bootstrap ----------

    async def seed_from_env_if_empty(self, settings: Settings) -> bool:
        """One-shot copy of ``MAGISTER_OIDC_*`` + ``MAGISTER_AD_*`` env into the
        DB row on first boot, when the row exists but is still all-NULLs.

        Returns True iff anything was written. Idempotent: a second call with
        a non-empty row is a no-op.
        """
        row = (
            await self.session.execute(
                select(
                    AppSettings.oidc_issuer,
                    AppSettings.oidc_client_id,
                    AppSettings.ad_dcs,
                    AppSettings.ad_bind_dn,
                ).where(AppSettings.id == 1)
            )
        ).one_or_none()
        if row is None:
            # Migration didn't insert the singleton — shouldn't happen, but
            # bail out rather than silently masking a deeper inconsistency.
            return False
        already_seeded = bool(row.oidc_issuer or row.oidc_client_id or row.ad_dcs or row.ad_bind_dn)
        if already_seeded:
            return False

        values: dict[str, object] = {}
        if settings.oidc_issuer:
            values["oidc_issuer"] = settings.oidc_issuer
        if settings.oidc_client_id:
            values["oidc_client_id"] = settings.oidc_client_id
        client_secret = settings.oidc_client_secret.get_secret_value()
        if client_secret:
            values["oidc_client_secret_enc"] = func.pgp_sym_encrypt(client_secret, self._key)
        if settings.oidc_redirect_uri:
            values["oidc_redirect_uri"] = settings.oidc_redirect_uri
        if settings.oidc_scopes:
            values["oidc_scopes"] = settings.oidc_scopes
        if settings.bootstrap_admins:
            values["bootstrap_admins"] = settings.bootstrap_admins
        if settings.ad_dcs:
            values["ad_dcs"] = settings.ad_dcs
        if settings.ad_bind_dn:
            values["ad_bind_dn"] = settings.ad_bind_dn
        if settings.ad_bind_password is not None:
            bind_pw = settings.ad_bind_password.get_secret_value()
            if bind_pw:
                values["ad_bind_password_enc"] = func.pgp_sym_encrypt(bind_pw, self._key)
        if settings.ad_users_search_base:
            values["ad_users_search_base"] = settings.ad_users_search_base
        if settings.ad_computers_search_base:
            values["ad_computers_search_base"] = settings.ad_computers_search_base
        if settings.ad_tls_ca_pem:
            values["ad_tls_ca_pem"] = settings.ad_tls_ca_pem
        if not settings.ad_tls_verify:
            values["ad_tls_verify"] = False
        if settings.ad_login_enabled:
            values["ad_login_enabled"] = True
        if settings.ad_login_group:
            values["ad_login_group"] = settings.ad_login_group
        if settings.ad_sync_interval_minutes:
            values["ad_sync_interval_minutes"] = settings.ad_sync_interval_minutes

        if not values:
            return False

        values["version"] = AppSettings.version + 1
        values["updated_by_upn"] = "lifespan-seed"
        values["updated_at"] = func.now()
        await self.session.execute(
            sqla_update(AppSettings).where(AppSettings.id == 1).values(**values)
        )
        await self.session.commit()
        logger.warning(
            "app_settings seeded from MAGISTER_OIDC_* / MAGISTER_AD_* env — "
            "those env vars can now be removed; the DB is authoritative."
        )
        return True


def _empty_effective() -> EffectiveAppSettings:
    return EffectiveAppSettings(
        version=0,
        oidc_issuer=None,
        oidc_client_id=None,
        oidc_client_secret=None,
        oidc_redirect_uri=None,
        oidc_scopes=[],
        bootstrap_admins=[],
        mail_domains=[],
        ad_dcs=[],
        ad_bind_mode="simple",
        ad_bind_dn=None,
        ad_bind_password=None,
        ad_tls_verify=True,
        ad_tls_ca_pem=None,
        ad_login_enabled=False,
        ad_login_group=None,
        ad_users_search_base=None,
        ad_computers_search_base=None,
        ad_sync_interval_minutes=15,
    )


__all__ = ["AppSettingsService", "EffectiveAppSettings"]


# Make the symbol stable for static analysers — `datetime` is referenced via
# Pydantic in the `Out` schema only.
_ = datetime
