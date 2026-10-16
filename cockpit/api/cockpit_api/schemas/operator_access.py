"""Schemata für den Operator-Zugriff (ADR-0019)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from cockpit_api.services.operator_access import MIN_REASON_LENGTH


class OperatorAccessRequest(BaseModel):
    """Was der Betreiber angibt — **nicht** wer er ist.

    Das Feld `operator` stand hier und ist mit ADR-0020 D3 verschwunden: der
    Name reist signiert mit und landet im Audit des Kunden. Solange der
    Aufrufer ihn selbst setzt, ist die Auskunft „wer hat zugesehen" eine
    Behauptung. Er kommt jetzt aus der angemeldeten Sitzung.
    """

    #: Ein mitgeschicktes `operator` ist ein Fehler und kein stiller
    #: Nicht-Effekt: ein alter Aufrufer glaubte sonst, sein Name sei
    #: angekommen, und im Audit des Kunden stünde ein anderer.
    model_config = ConfigDict(extra="forbid")

    #: Die Mindestlänge steht auch im Dienst — dort ist sie die Autorität
    #: (sie muss für ein CLI gelten). Hier, damit die Oberfläche den Fehler
    #: bekommt, bevor der Zugriff ausgestellt wird.
    reason: str = Field(min_length=MIN_REASON_LENGTH, max_length=2000)
    ticket: str | None = Field(default=None, max_length=64)


class OperatorAccessOut(BaseModel):
    """Der Einlöseschein. Er wird **einmal** ausgeliefert und nicht gespeichert."""

    jti: str
    #: Die Assertion selbst. Sie steht in keiner Antwort ein zweites Mal: die
    #: Konsole speichert sie nicht, und sie ist nach sechzig Sekunden wertlos.
    assertion: str
    expires_at: datetime
    #: Die Adresse, die der Operator öffnet. Die Assertion steht im
    #: **Fragment** und nicht in der Abfrage: ein Fragment erreicht keinen
    #: Server-Log und keinen Referer-Header.
    redeem_url: str


class OperatorAccessGrantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    jti: str
    operator: str
    reason: str
    ticket: str | None
    issued_at: datetime
    expires_at: datetime


__all__ = ["OperatorAccessGrantOut", "OperatorAccessOut", "OperatorAccessRequest"]
