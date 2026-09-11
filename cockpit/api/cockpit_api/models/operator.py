"""Operatoren der Konsole und ihre Sitzungen (ADR-0020).

Zwei Tabellen, und die erste ist die eigentliche Neuigkeit: die Konsole weiss
ab hier, **wer** sie bedient. Vorher gab es einen Token und ein Freitextfeld
`actor`, in das der Aufrufer eintrug, wer er sei.

Die Identität ist der **SPKI-Fingerprint** des Client-Zertifikats und nicht
sein `CN` (ADR-0020 D1): ein Name im Zertifikat ist eine Zeichenkette, die bei
der Ausstellung entsteht. Der Fingerprint gehört zum Schlüsselpaar.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from cockpit_api.models.base import Base


class ConsoleOperator(Base):
    __tablename__ = "console_operators"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    #: Was im Protokoll steht — der Name, der in `actor` landet und bei einem
    #: Operator-Zugriff signiert ins Audit des Kunden geht (ADR-0019).
    upn: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)

    #: SHA-256 über den DER-kodierten öffentlichen Schlüssel des
    #: Client-Zertifikats, hex. Eindeutig: zwei Operatoren können nicht
    #: dasselbe Schlüsselpaar benutzen, und ein neues Zertifikat für dieselbe
    #: Person ist eine bewusste Änderung an dieser Zeile.
    spki_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    #: Das TOTP-Geheimnis, pgcrypto-verschlüsselt mit `COCKPIT_SECRET_KEY`.
    #: `NULL` heisst „noch nicht eingerichtet" — dann führt die Anmeldung ins
    #: Enrolment und stellt **keine** Sitzung aus. Es gibt damit keinen halb
    #: privilegierten Zustand.
    totp_secret_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    totp_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: Letzter akzeptierter 30-Sekunden-Schritt. Ein Code gilt **einmal**, auch
    #: innerhalb seines Fensters — sonst wäre ein abgelesener Code eine halbe
    #: Minute lang gültig.
    totp_last_step: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    #: argon2id-Hashes der zehn Einmal-Codes. Der Klartext erscheint einmal
    #: beim Einrichten und wird nirgends gespeichert.
    recovery_codes: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )

    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    #: Fehlversuche am zweiten Faktor. Eigener Zähler und nicht einer für
    #: alles: das Zertifikat ist kein Versuch, den man zählt — es gilt oder
    #: der Handschlag scheitert.
    mfa_failed_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ConsoleSession(Base):
    """Eine angemeldete Sitzung. Der Cookie trägt nur die Id.

    Serverseitig und nicht als signierter Cookie: eine Sitzung, die sich
    widerrufen lässt, braucht eine Zeile, die man löschen kann.
    """

    __tablename__ = "console_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    operator_id: Mapped[int] = mapped_column(
        ForeignKey("console_operators.id", ondelete="CASCADE"), nullable=False, index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    #: Der Fingerprint des Zertifikats, mit dem die Sitzung entstanden ist.
    #: Bei jeder Anfrage gegengeprüft: ein gestohlener Cookie allein nützt
    #: nichts, wenn das Zertifikat nicht dazu passt.
    spki_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)


__all__ = ["ConsoleOperator", "ConsoleSession"]
