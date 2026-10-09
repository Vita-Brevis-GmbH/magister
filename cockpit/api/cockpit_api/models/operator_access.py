"""Ausgestellte Operator-Assertions (ADR-0019).

Die Konsole hält hier fest, **dass** sie einen Zugriff ausgestellt hat, mit
Grund und Ablauf. Ob er eingelöst wurde, weiss sie nicht — das steht im
Kundenschema (ADR-0019 D4), und die Konsole hat dorthin keinen Zugang.

Der Eintrag ist trotzdem nötig: eine ausgestellte und **nicht** eingelöste
Assertion ist eine Auskunft, die man sonst nirgends bekäme.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from cockpit_api.models.base import Base


class OperatorAccessGrant(Base):
    __tablename__ = "operator_access_grants"

    #: Dieselbe Id, die in der Assertion als `jti` steht. Kein zweiter
    #: Schlüssel: so ist die Zeile hier und die Zeile im Kundenschema über
    #: denselben Wert verbunden, ohne dass jemand sie zuordnen muss.
    jti: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    #: Wer den Zugriff angefordert hat. Ein UPN und kein Fremdschlüssel: die
    #: Konsole führt (bis E21) keine Benutzertabelle.
    operator: Mapped[str] = mapped_column(String(320), nullable=False)
    #: Grund oder Ticketnummer — Pflicht (ADR-0019 D7). Er reist in der
    #: signierten Assertion mit und kann unterwegs nicht geändert werden.
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    ticket: Mapped[str | None] = mapped_column(String(64), nullable=True)

    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    #: Ablauf der **Assertion**, nicht der Sitzung. Sechzig Sekunden: sie ist
    #: ein Einlöseschein und kein Zugang.
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_operator_access_grants_tenant", "tenant_id", "issued_at"),)


__all__ = ["OperatorAccessGrant"]
