"""Schemata für die Konsolen-Anmeldung (ADR-0020, ADR-0023)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from cockpit_api.services.console_auth import AuthStage


class ConsoleWhoamiOut(BaseModel):
    """Welcher Schritt fehlt — und bei wem, sobald das feststeht."""

    stage: AuthStage
    #: `None`, solange das Zertifikat unbekannt ist. Die Antwort verrät dann
    #: nichts über die Operatoren, die es gibt.
    upn: str | None = None
    name: str | None = None
    expires_at: datetime | None = None


class ConsoleLoginRequest(BaseModel):
    """Erster Faktor: Benutzername und Passwort (ADR-0023 D1)."""

    upn: str = Field(min_length=3, max_length=320)
    #: Obergrenze, weil auch eine Prüfung, die scheitert, Arbeit kostet —
    #: argon2 rechnet über die volle Eingabe.
    password: str = Field(min_length=1, max_length=1024)


class ConsoleTotpRequest(BaseModel):
    #: Sechs Stellen, oder ein Wiederherstellungscode in der Form `XXXX-XXXX`.
    #: Eine Obergrenze, weil auch eine Prüfung, die scheitert, Arbeit kostet.
    code: str = Field(min_length=6, max_length=32)


class ConsoleEnrolmentOut(BaseModel):
    """Was genau **einmal** zu sehen ist.

    Es steht in keiner zweiten Antwort: das Geheimnis liegt danach nur
    verschlüsselt in der Datenbank, und von den Wiederherstellungscodes nur
    ihre Hashes.
    """

    secret: str
    provisioning_uri: str
    qr_data_uri: str
    recovery_codes: list[str]


__all__ = ["ConsoleEnrolmentOut", "ConsoleTotpRequest", "ConsoleWhoamiOut"]
