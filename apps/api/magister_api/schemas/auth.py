"""Auth-related request/response schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from magister_api.schemas.common import ObjectGuidOrEmpty, UpnOrLoginName


class OperatorBannerOut(BaseModel):
    """Der laufende Operator-Zugriff — für den Hinweisbalken (ADR-0019 D6).

    Geht an **jeden** angemeldeten Benutzer und nicht nur an Admins. Wer
    arbeitet, während jemand zusieht, soll das sehen und nicht nachlesen
    müssen.
    """

    operator: str
    reason: str
    ticket: str | None
    until: datetime


class CurrentUserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    #: Leer bei einer Operator-Sitzung: sie gehört zu keinem AD-Objekt
    #: (ADR-0019 D5). Bei einer Keycloak-Sitzung die ``principal_guid`` des
    #: Anmeldekontos (ADR-0025) — eine objectGUID nur, wenn das Konto einer
    #: AD-Person zugeordnet ist.
    ad_object_guid: ObjectGuidOrEmpty
    #: Der Name, unter dem die Sitzung läuft: Keycloak-Benutzername (auch ohne
    #: ``@``, etwa ``automato-admin``), UPN aus dem AD oder der des Notkontos.
    upn: UpnOrLoginName
    given_name: str | None = None
    surname: str | None = None
    display_name: str | None = None
    is_admin: bool
    kind: str | None = Field(
        default=None,
        description="AD classification: 'teacher' | 'student' | 'admin'. None for the local admin.",
    )
    school_scope: list[int] = Field(
        default_factory=list,
        description="School IDs the user has Schulleitung-or-above scope on. Empty for KL-only.",
    )
    roles: list[str] = Field(default_factory=list)
    #: Darf das Konto überhaupt etwas sehen — eine Rolle, eine Klasse, ein
    #: Fach oder eine Leitung? Ein neues Anmeldekonto ohne all das meldet sich
    #: an und bekommt einen Hinweis statt leerer Seiten (ADR-0025).
    has_permissions: bool = True
    expires_at: datetime
    #: Diese Sitzung **ist** ein Operator-Zugriff (ADR-0019). Das Frontend
    #: zeigt dann eine andere Fassung des Balkens: „Sie sehen die Installation
    #: des Kunden" statt „jemand sieht zu".
    is_operator: bool = False
    #: Gesetzt, solange ein Zugriff läuft — für alle Benutzer, den Operator
    #: eingeschlossen.
    operator_active: OperatorBannerOut | None = None
