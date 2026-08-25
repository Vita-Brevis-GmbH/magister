"""Guided name-change assistant (M6 Feature C, ADR-0009).

Thin orchestration on top of :class:`UserAttributesService`: it proposes the
cascaded identity attributes from a new surname (``preview``) and applies the
operator-confirmed values in one audited ``user_renamed`` operation
(``apply``), preserving the old primary address as an alias via the
proxyAddresses mechanism (Feature A).
"""

from __future__ import annotations

import unicodedata

from pydantic import ValidationError

from magister_api.models.auth import AdUserCache
from magister_api.schemas.user_attrs import UserAttributesUpdate
from magister_api.schemas.user_rename import (
    RenameApplyRequest,
    RenamePreviewOut,
    RenamePreviewRequest,
)
from magister_api.services.user_attrs import UserAttributesResult, UserAttributesService

# Common German/Swiss digraph expansions applied before ASCII-folding so a
# surname like "Müller" slugs to "mueller", not "muller".
_DIGRAPHS = {
    "ä": "ae",
    "ö": "oe",
    "ü": "ue",
    "ß": "ss",
    "æ": "ae",
    "ø": "oe",
    "å": "aa",
}

# sAMAccountName is capped at 20 chars (see schemas.user_attrs.SAM_ACCOUNT_RE).
_SAM_MAX = 20


class RenameInvalidError(ValueError):
    """A confirmed rename value failed attribute validation."""


def _slug(value: str) -> str:
    v = value.strip().lower()
    for k, r in _DIGRAPHS.items():
        v = v.replace(k, r)
    v = unicodedata.normalize("NFKD", v).encode("ascii", "ignore").decode("ascii")
    return "".join(ch for ch in v if ch.isalnum())


def _domain_of(addr: str | None) -> str | None:
    if addr and "@" in addr:
        return addr.rsplit("@", 1)[1]
    return None


class UserRenameService:
    def __init__(self, attr_service: UserAttributesService) -> None:
        self.attr = attr_service

    @staticmethod
    def preview(*, target: AdUserCache, req: RenamePreviewRequest) -> RenamePreviewOut:
        """Propose cascaded values. Pure computation — no AD/DB writes."""
        given = (req.new_given_name if req.new_given_name is not None else target.given_name) or ""
        surname = req.new_surname.strip()
        display = f"{given} {surname}".strip()

        local = ".".join(p for p in (_slug(given), _slug(surname)) if p)
        upn_domain = _domain_of(target.upn)
        mail_domain = _domain_of(target.mail) or upn_domain
        upn = f"{local}@{upn_domain}" if local and upn_domain else target.upn
        mail = f"{local}@{mail_domain}" if local and mail_domain else target.mail
        sam = local[:_SAM_MAX] if local else target.sam_account_name

        return RenamePreviewOut(
            given_name=given or None,
            surname=surname,
            display_name=display,
            upn=upn,
            mail=mail,
            sam_account_name=sam,
            old_mail_kept_as_alias=target.mail,
        )

    async def apply(
        self,
        *,
        target: AdUserCache,
        req: RenameApplyRequest,
        mail_domains: list[str],
        ip: str | None,
        request_id: str,
    ) -> UserAttributesResult:
        provided = req.model_dump(exclude_unset=True)
        provided.pop("keep_old_mail_as_alias", None)

        # Keep the old primary as an alias when the primary actually changes, so
        # mail to the former address still reaches the mailbox (Feature A).
        new_mail = provided.get("mail")
        if req.keep_old_mail_as_alias and target.mail and new_mail and new_mail != target.mail:
            aliases = list(target.mail_aliases or [])
            if target.mail not in aliases:
                aliases.append(target.mail)
            provided["mail_aliases"] = aliases

        try:
            payload = UserAttributesUpdate(**provided)
        except ValidationError as exc:
            raise RenameInvalidError(str(exc)) from exc

        return await self.attr.update(
            target=target,
            payload=payload,
            mail_domains=mail_domains,
            ip=ip,
            request_id=request_id,
            audit_action="user_renamed",
        )


__all__ = ["RenameInvalidError", "UserRenameService"]
