"""Gemeinsame Methodenfläche für alle *entfernten* AD-Rücken (ADR-0011, ADR-0014).

Es gibt drei Wege, wie Magister an das AD kommt:

1. **direkt** — ``AdClient`` mit ldap3, im AD-eigenen Container;
2. **eingehender RPC** — ``AdRpcClient`` gegen den AD-Container (ADR-0011);
3. **ausgehende Warteschlange** — ``AdConnectorClient`` über den
   Connector-Agenten im Kundennetz (ADR-0014).

Die Wege 2 und 3 unterscheiden sich **nur im Transport**: derselbe
Methodenname, dieselbe Nutzlast, dieselben Ausnahmen. Deshalb liegen die
Methodenkörper hier und nicht zweimal daneben — zwei Kopien von siebzehn
Wrappern wären zwei Stände, die über Jahre auseinanderlaufen. Ein Rücken
implementiert genau eine Methode: ``_call``.

Kein Aufrufer im Fachcode kennt den Unterschied. Das ist die Zusage aus
ADR-0014: der Connector kommt als dritter Rücken hinter dieselbe
Schnittstelle, und keine Service-Klasse wird angefasst.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Any

from magister_api.ad.client import AdClient


class RemoteAdClient(AdClient):
    """AD-Zugriff über einen Transport statt über ldap3.

    Die Namen sind wörtlich die aus ``magister_api.ad.rpc.ALLOWED_METHODS`` —
    ein Test hält das zusammen, damit ein neuer Rücken nicht eine Methode
    anbietet, die die Gegenseite nicht kennt.
    """

    @abstractmethod
    async def _call(self, method: str, payload: dict[str, Any]) -> Any:
        """Eine Operation ausführen und das Ergebnis liefern.

        Fehler werden als dieselben Ausnahmen erwartet, die der direkte Client
        wirft (``AdUnavailableError`` und Verwandte) — der Aufrufer soll einen
        Netzwerkausfall nicht von einem AD-Ausfall unterscheiden müssen.
        """

    # --- reads ---------------------------------------------------------------

    async def find_user_dn(self, ad_object_guid: str) -> str | None:
        return await self._call("find_user_dn", {"ad_object_guid": ad_object_guid})

    async def fetch_user_groups(self, ad_object_guid: str) -> list[str] | None:
        return await self._call("fetch_user_groups", {"ad_object_guid": ad_object_guid})

    async def probe_service_connection(self) -> bool:
        return bool(await self._call("probe_service_connection", {}))

    async def probe_service_connection_detailed(self) -> tuple[bool, str]:
        ok, reason = await self._call("probe_service_connection_detailed", {})
        return bool(ok), str(reason)

    async def probe_bind_as_user(self, *, user_dn: str, password: str) -> bool:
        return bool(
            await self._call("probe_bind_as_user", {"user_dn": user_dn, "password": password})
        )

    async def modify_password(self, *, user_dn: str, new_password: str, force_change: bool) -> None:
        await self._call(
            "modify_password",
            {"user_dn": user_dn, "new_password": new_password, "force_change": force_change},
        )

    async def modify_user_attributes(
        self, *, user_dn: str, attributes: dict[str, str | None]
    ) -> None:
        await self._call("modify_user_attributes", {"user_dn": user_dn, "attributes": attributes})

    async def rename_user(self, *, user_dn: str, new_common_name: str) -> str:
        return await self._call(
            "rename_user", {"user_dn": user_dn, "new_common_name": new_common_name}
        )

    async def set_proxy_addresses(
        self, *, user_dn: str, primary: str | None, aliases: list[str]
    ) -> None:
        await self._call(
            "set_proxy_addresses",
            {"user_dn": user_dn, "primary": primary, "aliases": aliases},
        )

    async def set_account_enabled(self, *, user_dn: str, enabled: bool) -> tuple[bool, bool]:
        changed, now_enabled = await self._call(
            "set_account_enabled", {"user_dn": user_dn, "enabled": enabled}
        )
        return bool(changed), bool(now_enabled)

    async def set_password_never_expires(self, *, user_dn: str, value: bool) -> None:
        await self._call("set_password_never_expires", {"user_dn": user_dn, "value": value})

    async def set_cannot_change_password(self, *, user_dn: str, value: bool) -> None:
        await self._call("set_cannot_change_password", {"user_dn": user_dn, "value": value})

    async def delete_user_object(self, *, user_dn: str) -> None:
        await self._call("delete_user_object", {"user_dn": user_dn})

    async def add_user_to_groups(self, *, user_dn: str, group_dns: list[str]) -> list[str]:
        return await self._call("add_user_to_groups", {"user_dn": user_dn, "group_dns": group_dns})

    async def remove_user_from_groups(self, *, user_dn: str, group_dns: list[str]) -> list[str]:
        return await self._call(
            "remove_user_from_groups", {"user_dn": user_dn, "group_dns": group_dns}
        )

    async def create_user(
        self,
        *,
        ou_dn: str,
        common_name: str,
        sam_account_name: str,
        user_principal_name: str,
        mail: str | None,
        given_name: str,
        surname: str,
        display_name: str,
        password: str,
        force_change: bool,
        password_never_expires: bool = False,
        cannot_change_password: bool = False,
        group_dns: list[str] | None = None,
    ) -> str:
        return await self._call(
            "create_user",
            {
                "ou_dn": ou_dn,
                "common_name": common_name,
                "sam_account_name": sam_account_name,
                "user_principal_name": user_principal_name,
                "mail": mail,
                "given_name": given_name,
                "surname": surname,
                "display_name": display_name,
                "password": password,
                "force_change": force_change,
                "password_never_expires": password_never_expires,
                "cannot_change_password": cannot_change_password,
                "group_dns": list(group_dns or []),
            },
        )


__all__ = ["RemoteAdClient"]
