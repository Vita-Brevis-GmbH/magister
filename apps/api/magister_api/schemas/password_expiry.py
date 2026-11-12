"""Übersicht Passwort-Ablauf."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class PasswordExpiryRow(BaseModel):
    ad_object_guid: str
    display_name: str | None
    given_name: str | None
    surname: str | None
    upn: str
    kind: str
    school_id: int | None
    jahrgangsstufe: int | None
    group_template_name: str | None
    mail: str | None
    password_expires_at: datetime | None
    #: Ganze Tage bis zum Ablauf; negativ heisst "seit … Tagen abgelaufen".
    days_left: int | None
    #: Wann das Passwort zuletzt gesetzt wurde und wie alt es ist (Tage).
    #: None: Änderung bei der nächsten Anmeldung verlangt — oder unbekannt.
    password_last_set: datetime | None = None
    age_days: int | None = None
    password_never_expires: bool = False
    #: Ob der Abgleich den Ablauf schon gelesen hat (sonst "unbekannt").
    password_known: bool = False
    #: Letzte Erinnerung zum aktuellen Ablauf: sent / failed / no_mail.
    notice_status: str | None = None
    notice_at: datetime | None = None
    notice_threshold_days: int | None = None


class PasswordExpiryOverview(BaseModel):
    view: str
    within_days: int
    rows: list[PasswordExpiryRow]
    #: Alle Treffer (für die Seitenwahl in der Ansicht "Passwortalter").
    total: int = 0
    offset: int = 0
    limit: int = 0
    #: Ob die Erinnerung eingeschaltet und der Mailversand bereit ist —
    #: sonst steht über der Liste ein Hinweis.
    notice_enabled: bool
    mail_ready: bool
    #: Wann der Abgleich den Ablauf zuletzt gelesen hat (None: noch nie —
    #: dann ist die Liste leer, weil Magister es nicht weiss).
    info_as_of: datetime | None
