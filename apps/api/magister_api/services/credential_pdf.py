"""Per-user credential PDF (username + password) for the user-detail page.

Passwords are never stored, so the PDF only carries a real password at the
moment one is set. Policy (see the feature discussion):

- For accounts flagged ``cannot_change_password`` the download resets the
  password (generate) and prints it in clear text — those users keep this
  password permanently. ``force_change`` is *not* set (they may not change it).
- For every other account nothing is reset; the password is rendered masked
  (``••••••••``). Operators hand the real password over via the reset dialog.

Students additionally get their assigned devices (name / type / serial) and an
optional free-text block (heading + body). Teachers get neither a device list
nor any class/student roster — just the credential slip (+ optional custom
text).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from sqlalchemy.ext.asyncio import AsyncSession
from weasyprint import HTML

from magister_api.ad.client import AdClient
from magister_api.ad.password import generate_readable_password, passes_default_complexity
from magister_api.audit.service import AuditService
from magister_api.config import Settings
from magister_api.models.auth import AdUserCache
from magister_api.models.school import School
from magister_api.repositories.base import ScopeContext
from magister_api.repositories.devices import DeviceRepository

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "letters" / "templates"

_STRINGS: dict[str, dict[str, str]] = {
    "de": {
        "title": "Zugangsdaten",
        "username": "Benutzername",
        "password": "Passwort",
        "keep_safe": "Bewahren Sie diesen Zettel sicher auf und geben Sie ihn niemandem weiter.",
        "password_masked_note": (
            "Das Passwort ist hier aus Sicherheitsgründen nicht abgedruckt. "
            "Setzen Sie es bei Bedarf über «Passwort zurücksetzen»."
        ),
        "devices_title": "Gerät",
        "device_name": "Bezeichnung",
        "device_type": "Typ",
        "device_serial": "Serien-/Inventarnr.",
    },
    "fr": {
        "title": "Identifiants",
        "username": "Nom d'utilisateur",
        "password": "Mot de passe",
        "keep_safe": "Conservez cette feuille en lieu sûr et ne la donnez à personne.",
        "password_masked_note": (
            "Le mot de passe n'est pas imprimé ici pour des raisons de sécurité. "
            "Définissez-le au besoin via « Réinitialiser le mot de passe »."
        ),
        "devices_title": "Appareil",
        "device_name": "Désignation",
        "device_type": "Type",
        "device_serial": "N° de série/inventaire",
    },
    "it": {
        "title": "Credenziali",
        "username": "Nome utente",
        "password": "Password",
        "keep_safe": "Conservi questo foglio in un luogo sicuro e non lo dia a nessuno.",
        "password_masked_note": (
            "Per motivi di sicurezza la password non è stampata qui. "
            "Impostala se necessario tramite «Reimposta password»."
        ),
        "devices_title": "Dispositivo",
        "device_name": "Denominazione",
        "device_type": "Tipo",
        "device_serial": "N. di serie/inventario",
    },
}


def _strings_for(language: str) -> dict[str, str]:
    return _STRINGS.get((language or "de").lower()[:2], _STRINGS["de"])


class UserNotInAdError(LookupError):
    """No DN found in AD for the user's objectGUID (needed to reset the PW)."""


class UserDisabledError(RuntimeError):
    """Refuse to reset the password of a disabled account."""


@dataclass(frozen=True)
class _DeviceRow:
    name: str
    device_type: str | None
    serial_number: str | None


class CredentialPdfService:
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

    async def generate(
        self,
        *,
        target: AdUserCache,
        custom_heading: str | None,
        custom_body: str | None,
        language: str,
        generated_on: str,
        ip: str | None,
        request_id: str,
    ) -> bytes:
        # Reset only for accounts that cannot change their own password; those
        # keep this password permanently so it must be printed in clear text.
        do_reset = bool(target.cannot_change_password)
        shown_password: str | None = None
        if do_reset:
            if not target.enabled:
                raise UserDisabledError(target.ad_object_guid)
            user_dn = await self.ad.find_user_dn(target.ad_object_guid)
            if not user_dn:
                raise UserNotInAdError(target.ad_object_guid)
            # Readable ("Tiger-Wolke-47"): easy for students to read + type,
            # matching the provisioning hand-out style.
            new_password = generate_readable_password()
            assert passes_default_complexity(new_password)
            # force_change=False: the account may not change its password.
            await self.ad.modify_password(
                user_dn=user_dn, new_password=new_password, force_change=False
            )
            shown_password = new_password

        # Devices only for students; teachers never get a device/roster block.
        devices: list[_DeviceRow] = []
        if target.kind == "student":
            rows = await DeviceRepository(self.session, self.scope).list_for_person(
                target.ad_object_guid
            )
            devices = [
                _DeviceRow(name=d.name, device_type=d.device_type, serial_number=d.serial_number)
                for d in rows
            ]

        school_name = ""
        if target.school_id is not None:
            school = await self.session.get(School, target.school_id)
            if school is not None:
                school_name = school.name

        pdf = await self._render(
            target=target,
            password=shown_password,
            devices=devices,
            custom_heading=(custom_heading or "").strip() or None,
            custom_body=(custom_body or "").strip() or None,
            language=language,
            school_name=school_name,
            generated_on=generated_on,
        )

        await self.audit.emit(
            action="credential_pdf_generated",
            target_kind="ad_user",
            target_id=target.ad_object_guid,
            actor_upn=self.scope.upn,
            actor_object_guid=self.scope.ad_object_guid,
            school_id=target.school_id,
            ip=ip,
            request_id=request_id,
            payload={
                "kind": target.kind,
                "did_reset": do_reset,
                "device_count": len(devices),
                "custom_text": bool(custom_heading or custom_body),
            },
        )
        return pdf

    async def _render(
        self,
        *,
        target: AdUserCache,
        password: str | None,
        devices: list[_DeviceRow],
        custom_heading: str | None,
        custom_body: str | None,
        language: str,
        school_name: str,
        generated_on: str,
    ) -> bytes:
        env = Environment(
            loader=FileSystemLoader(str(_TEMPLATES_DIR)),
            autoescape=select_autoescape(["html", "xml"]),
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        html = env.get_template("credential_slip.html").render(
            t=_strings_for(language),
            display_name=target.display_name or target.upn,
            upn=target.upn,
            password=password,
            devices=devices,
            custom_heading=custom_heading,
            custom_body=custom_body,
            school_name=school_name,
            generated_on=generated_on,
        )
        return await _html_to_pdf(html)


async def _html_to_pdf(html: str) -> bytes:
    from starlette.concurrency import run_in_threadpool

    return await run_in_threadpool(_sync_html_to_pdf, html)


def _sync_html_to_pdf(html: str) -> bytes:
    pdf = HTML(string=html, base_url=str(_TEMPLATES_DIR)).write_pdf()
    if pdf is None:  # pragma: no cover - WeasyPrint always returns bytes
        raise RuntimeError("WeasyPrint returned no PDF bytes")
    return pdf


__all__ = [
    "CredentialPdfService",
    "UserDisabledError",
    "UserNotInAdError",
]
