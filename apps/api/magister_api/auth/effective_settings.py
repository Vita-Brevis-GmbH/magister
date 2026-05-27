"""Per-request effective settings: env-Settings overlaid with the DB row.

Why: the OIDC + AD config moved out of env into the ``app_settings`` table
(M1.5b). Existing code paths (OIDC client, AD client, AuthService bootstrap)
still consume :class:`magister_api.config.Settings`. The cheapest way to
keep them unchanged is to overlay DB values onto a clone of the env Settings
on each request, then hand that clone down through the existing dependency
graph.

The clone is cached per-request — and the OIDC/AD client itself is cached
across requests on ``app.state``, keyed by ``app_settings.version``, so a
GUI write invalidates it without a process restart.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Request
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.config import Settings, get_settings
from magister_api.db import get_session
from magister_api.services.app_settings import AppSettingsService, EffectiveAppSettings


def _overlay(base: Settings, eff: EffectiveAppSettings) -> Settings:
    """Return a new Settings with DB values overlaid on top of *base*.

    None / empty DB values keep the underlying env value; concrete DB values
    win. Once the DB row is seeded (lifespan), this means env can be removed
    safely.
    """
    update: dict[str, object] = {}
    if eff.oidc_issuer:
        update["oidc_issuer"] = eff.oidc_issuer
    if eff.oidc_client_id:
        update["oidc_client_id"] = eff.oidc_client_id
    if eff.oidc_client_secret:
        update["oidc_client_secret"] = SecretStr(eff.oidc_client_secret)
    if eff.oidc_redirect_uri:
        update["oidc_redirect_uri"] = eff.oidc_redirect_uri
    if eff.oidc_scopes:
        update["oidc_scopes"] = list(eff.oidc_scopes)
    if eff.bootstrap_admins:
        update["bootstrap_admins"] = list(eff.bootstrap_admins)
    if eff.ad_dcs:
        update["ad_dcs"] = list(eff.ad_dcs)
    if eff.ad_bind_dn:
        update["ad_bind_dn"] = eff.ad_bind_dn
    if eff.ad_bind_password:
        update["ad_bind_password"] = SecretStr(eff.ad_bind_password)
    if eff.ad_users_search_base:
        update["ad_users_search_base"] = eff.ad_users_search_base
    if eff.ad_computers_search_base:
        update["ad_computers_search_base"] = eff.ad_computers_search_base
    if eff.ad_sync_interval_minutes:
        update["ad_sync_interval_minutes"] = eff.ad_sync_interval_minutes
    return base.model_copy(update=update)


@dataclass(frozen=True)
class _SettingsCacheEntry:
    version: int
    settings: Settings


async def get_effective_settings(
    request: Request,
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> Settings:
    """Return env-Settings overlaid with the current ``app_settings`` row.

    Cached on ``app.state.effective_settings_cache`` keyed by ``version`` —
    one cheap ``SELECT version`` per request; full reload only on bumps.
    """
    svc = AppSettingsService(session, settings)
    version = await svc.get_version()
    cache: _SettingsCacheEntry | None = getattr(request.app.state, "effective_settings_cache", None)
    if cache is not None and cache.version == version:
        return cache.settings
    eff = await svc.get_effective()
    overlaid = _overlay(settings, eff)
    request.app.state.effective_settings_cache = _SettingsCacheEntry(
        version=version, settings=overlaid
    )
    return overlaid


__all__ = ["get_effective_settings"]
