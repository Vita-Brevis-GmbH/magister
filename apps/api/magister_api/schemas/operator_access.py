"""Schemata für den Operator-Zugriff (ADR-0019)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class OperatorRedeemRequest(BaseModel):
    #: Der Einlöseschein, wie die Konsole ihn ausgestellt hat. Die Obergrenze
    #: ist grosszügig und endlich: ohne sie wäre ein Megabyte Text eine
    #: Einladung, die Signaturprüfung zu beschäftigen.
    assertion: str = Field(min_length=32, max_length=4096)


class OperatorRedeemOut(BaseModel):
    """Was der Operator nach dem Einlösen sieht.

    Mit Grund und Ticket: wer mehrere Fälle gleichzeitig bearbeitet, soll im
    Fenster sehen, in welchem er gerade ist.
    """

    operator: str
    reason: str
    ticket: str | None
    expires_at: datetime


class OperatorAccessOut(BaseModel):
    """Ein Zugriff in der Liste, die der Kunde sieht."""

    jti: str
    operator: str
    reason: str
    ticket: str | None
    started_at: datetime
    expires_at: datetime
    #: `null` heisst „läuft noch oder ist abgelaufen". Welches von beidem,
    #: entscheidet `expires_at` — ein beendeter und ein abgelaufener Zugriff
    #: sind für den Kunden nicht dasselbe.
    ended_at: datetime | None


__all__ = ["OperatorAccessOut", "OperatorRedeemOut", "OperatorRedeemRequest"]
