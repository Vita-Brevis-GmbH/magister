"""Welche Domains darf der UPN eines Kontos tragen?

Das AD selbst kennt mehr UPN-Suffixe als die Mail-Domains: den DNS-Namen der
Domäne und die alternativen Suffixe der Gesamtstruktur ("Active Directory-
Domänen und -Vertrauensstellungen"). Die Gesamtstruktur liest Magister nicht
(der Connector darf nur unter den Suchbasen lesen). Was es sicher weiss:

* die Mail-Domains aus den Einstellungen,
* den DNS-Namen der Domäne aus der Benutzer-Suchbasis (``DC=schule,DC=local``
  → ``schule.local``),
* jedes Suffix, das ein abgeglichenes Konto schon trägt — das AD hat es
  angenommen.

Für die Mail-Adresse gelten weiter nur die Mail-Domains: dort geht es um
Zustellung, nicht um die Anmeldung.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.models.auth import AdUserCache


def domain_of_search_base(search_base: str | None) -> str | None:
    """``OU=Benutzer,DC=schule,DC=local`` → ``schule.local``; ohne DC-Teile ``None``."""
    parts = [
        p.strip()[3:].strip().lower()
        for p in (search_base or "").split(",")
        if p.strip().upper().startswith("DC=")
    ]
    return ".".join(parts) if parts else None


async def upn_domains(
    session: AsyncSession,
    *,
    mail_domains: list[str],
    users_search_base: str | None,
    extra: tuple[str, ...] | list[str] = (),
) -> list[str]:
    """Erlaubte UPN-Suffixe: Mail-Domains, dann die eingetragenen UPN-Domains,
    dann was das AD kennt (alphabetisch)."""
    # scope-bypass: nur der Domain-Teil aller UPNs — eine Eigenschaft des AD,
    # keine Personendaten; die Liste ist für jeden Standort dieselbe.
    stmt = select(func.distinct(func.lower(func.split_part(AdUserCache.upn, "@", 2))))
    in_use = {str(d) for d in (await session.execute(stmt)).scalars().all() if d}
    first = [d.lower() for d in mail_domains]
    first += [d.lower() for d in extra if d.lower() not in first]
    rest = set(in_use)
    base = domain_of_search_base(users_search_base)
    if base:
        rest.add(base)
    return first + sorted(rest - set(first))


__all__ = ["domain_of_search_base", "upn_domains"]
