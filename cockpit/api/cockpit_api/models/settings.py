"""Systemeinstellungen und Rechte-Matrix als Soll-Zustand (ADR-0017).

Was hier steht, ist **die Absicht** — nicht der Zustand. Die Datenebene holt
sie ab und materialisiert sie in das Schema des Kunden (ADR-0017 D3); was
tatsächlich gilt, steht dort und im Audit des Kunden.

Zwei Dinge stehen hier **nicht**, und das ist der Kern von ADR-0017 D2:

* **Kein Geheimnis.** Kein AD-Bind-Passwort, kein OIDC-Client-Secret, kein
  privater Webserver-Schlüssel. Die liegen ausschliesslich im Kundenschema, mit
  dem Kundenschlüssel verschlüsselt, und werden auf dem Anwendungsserver
  gesetzt. Die Konsole ist der eine Ort, an dem die Geheimnisse **aller**
  Kunden zusammenkämen — deshalb kommen sie dort nicht hin.
* **Keine Personendaten.** Die Konsolen-Datenbank bleibt frei davon
  (ADR-0013). `bootstrap_admins` ist die eine Ausnahme, die begründet ist: es
  sind UPNs von Betreiber-Konten, keine Daten von Schülern oder Lehrpersonen,
  und ohne sie käme niemand in eine frisch angelegte Installation.

Die Prüfung, die das hält, liegt im Dienst (`services/settings.py`): eine
Allowlist der erlaubten Schlüssel, die jeden Namen ablehnt, der wie ein
Geheimnis aussieht.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from cockpit_api.models.base import Base


class PlatformSettings(Base):
    """Die Vorgaben, die für **alle** Kunden gelten. Genau eine Zeile.

    Ein Singleton wie `app_settings` in der Datenebene, und aus demselben
    Grund: es gibt genau eine Plattform. Die `id`-Spalte ist immer 1, damit
    ein `UPDATE` ohne `WHERE` nicht zwei Zeilen erzeugt, die sich
    widersprechen.
    """

    __tablename__ = "platform_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # immer 1

    #: Die Politik-Vorgaben, als Dokument. Ein JSONB und keine vierzig
    #: Spalten: die Felder gehören der Datenebene, und jedes neue Feld dort
    #: wäre sonst eine Migration hier. Was erlaubt ist, prüft der Dienst gegen
    #: eine Allowlist — nicht das Schema.
    defaults: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )

    #: Die globale Rechte-Matrix: {rollen_schlüssel: [capability, ...]}.
    #: Leer heisst „nicht vorgegeben" — dann bleibt die Matrix des Kunden
    #: unangetastet. Das ist der Unterschied zwischen „keine Vorgabe" und
    #: „Vorgabe: keine Rechte", und er entscheidet, ob ein leeres Dokument
    #: eine ganze Installation entrechtet.
    rbac: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    updated_by: Mapped[str | None] = mapped_column(String(320), nullable=True)


class TenantSettings(Base):
    """Abweichungen für einen einzelnen Kunden.

    Nur die Felder, die von der Vorgabe abweichen. Der wirksame Stand ist die
    Vorgabe, überschrieben von diesen Feldern — feldweise, nicht als Ganzes:
    sonst müsste jede Abweichung die vollständige Vorgabe mitschleppen und
    würde bei der nächsten Änderung der Vorgabe stillschweigend veralten.
    """

    __tablename__ = "tenant_settings"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )

    overrides: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )

    #: Abweichende Rechte-Matrix. Ersetzt die globale **ganz**, nicht
    #: feldweise: eine halb überschriebene Rechte-Matrix wäre eine, die
    #: niemand mehr lesen kann.
    rbac: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    updated_by: Mapped[str | None] = mapped_column(String(320), nullable=True)


__all__ = ["PlatformSettings", "TenantSettings"]
