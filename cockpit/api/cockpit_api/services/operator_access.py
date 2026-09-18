"""Operator-Assertions ausstellen (ADR-0019).

Die Konsole stellt **keine** Kunden-Session aus. Sie stellt einen
Einlöseschein aus: sechzig Sekunden gültig, einmal verwendbar, mit dem Grund
darin. Die Kunden-API tauscht ihn gegen eine befristete Sitzung und schreibt
den Zugriff in das Protokoll des Kunden.

Zum Format siehe ADR-0019 D2: `mgop1.<payload>.<signatur>`, Ed25519, und
**kein** Algorithmus-Feld im Dokument. Das Verfahren steht in dieser Datei und
im Präfix — nicht in Daten, die von aussen kommen.
"""

from __future__ import annotations

import base64
import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cockpit_api.models.operator_access import OperatorAccessGrant
from cockpit_api.models.tenant import Tenant, TenantStatus

#: Versions-Präfix **und** Verfahrensangabe in einem (ADR-0019 D2).
ASSERTION_PREFIX = "mgop1"

#: Gültigkeit des Einlöseschein. Kurz, weil er unterwegs ist: in einer
#: Zwischenablage, in einer Adresszeile, vielleicht in einem Chat.
ASSERTION_TTL = timedelta(seconds=60)

#: Kürzer als das geht als Begründung nicht durch. „test", „x" und „-" sind
#: die Eingaben, die ein Pflichtfeld ohne Mindestlänge bekommt.
MIN_REASON_LENGTH = 10


class OperatorAccessError(ValueError):
    """Ein Zugriff, der so nicht ausgestellt werden darf."""


def _b64(raw: bytes) -> str:
    # Ohne Polsterung: die Zeichen `=` müssten in einer URL kodiert werden,
    # und die Assertion reist in einem Fragment.
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def load_signing_key(path_value: str) -> ed25519.Ed25519PrivateKey:
    """Den privaten Schlüssel aus einer PEM-Datei laden.

    Ein Pfad und nicht der Schlüssel selbst in einer Variablen — dieselbe
    Bauart wie beim Intermediate der Connector-CA: so steht er in einer Datei
    mit Dateirechten und nicht in der Prozessumgebung, die jedes `ps` und jeder
    Absturzbericht mitnimmt.
    """
    if not path_value:
        raise OperatorAccessError(
            "COCKPIT_OPERATOR_SIGNING_KEY ist nicht gesetzt. Ohne Signaturschlüssel "
            "kann kein Operator-Zugriff ausgestellt werden (ADR-0019 D3)."
        )
    path = Path(path_value)
    if not path.is_file():
        raise OperatorAccessError(f"Signaturschlüssel {path} fehlt.")
    key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    if not isinstance(key, ed25519.Ed25519PrivateKey):
        # Ein anderer Typ wäre nicht „auch gut": die Datenebene prüft
        # ausschliesslich Ed25519, und die Assertion würde dort abgewiesen.
        raise OperatorAccessError(
            f"Signaturschlüssel ist {type(key).__name__}, erwartet wird Ed25519."
        )
    return key


def sign_assertion(payload: dict[str, Any], key: ed25519.Ed25519PrivateKey) -> str:
    """Den Einlöseschein bauen und signieren.

    `separators` und `sort_keys` sind nicht Kosmetik: signiert wird genau die
    Bytefolge, die übertragen wird, und eine Bibliothek, die dasselbe Dokument
    anders serialisiert, erzeugte sonst eine Signatur über etwas anderes.
    """
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    signature = key.sign(body)
    return f"{ASSERTION_PREFIX}.{_b64(body)}.{_b64(signature)}"


class OperatorAccessService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def issue(
        self,
        tenant: Tenant,
        *,
        operator: str,
        reason: str,
        ticket: str | None,
        signing_key_path: str,
        now: datetime | None = None,
    ) -> tuple[str, OperatorAccessGrant]:
        reason = reason.strip()
        if len(reason) < MIN_REASON_LENGTH:
            raise OperatorAccessError(
                f"Der Grund muss mindestens {MIN_REASON_LENGTH} Zeichen haben. Er steht "
                "im Protokoll des Kunden, und er soll dort etwas aussagen (ADR-0019 D7)."
            )
        if not operator.strip():
            raise OperatorAccessError("Ohne Operator-UPN kein Zugriff.")
        if tenant.status is not TenantStatus.active:
            # Ein gesperrter oder in Kündigung befindlicher Kunde bedient keine
            # Anfragen; eine Assertion dafür wäre ein Schein, der nicht
            # einlösbar ist — und die Fehlermeldung stünde dann beim Kunden
            # statt hier.
            raise OperatorAccessError(
                f"Kunde {tenant.slug} ist im Zustand '{tenant.status.value}' und wird nicht "
                "bedient. Ein Zugriff ist erst nach dem Entsperren möglich."
            )

        key = load_signing_key(signing_key_path)
        moment = now or datetime.now(UTC)
        jti = uuid.uuid4()
        expires_at = moment + ASSERTION_TTL
        assertion = sign_assertion(
            {
                "jti": str(jti),
                "tenant": tenant.slug,
                "operator": operator.strip(),
                "reason": reason,
                "ticket": (ticket or "").strip() or None,
                "iat": int(moment.timestamp()),
                "exp": int(expires_at.timestamp()),
            },
            key,
        )
        row = OperatorAccessGrant(
            jti=jti,
            tenant_id=tenant.id,
            operator=operator.strip(),
            reason=reason,
            ticket=(ticket or "").strip() or None,
            issued_at=moment,
            expires_at=expires_at,
        )
        self.session.add(row)
        await self.session.flush()
        return assertion, row

    async def history(self, tenant_id: uuid.UUID, limit: int = 50) -> list[OperatorAccessGrant]:
        stmt = (
            select(OperatorAccessGrant)
            .where(OperatorAccessGrant.tenant_id == tenant_id)
            .order_by(OperatorAccessGrant.issued_at.desc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())


__all__ = [
    "ASSERTION_PREFIX",
    "ASSERTION_TTL",
    "MIN_REASON_LENGTH",
    "OperatorAccessError",
    "OperatorAccessService",
    "load_signing_key",
    "sign_assertion",
]
