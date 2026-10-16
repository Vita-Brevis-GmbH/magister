"""argon2id für die Passwörter der Operatoren (ADR-0023 D1).

Dieselben Parameter wie beim lokalen Notkonto der Datenebene
(`magister_api/auth/passwords.py`): t=3, m=64 MiB, p=4, OWASP-Grundlinie,
rund 50 ms auf einer Server-CPU. Bewusst dieselben und nicht neu gewählt —
zwei Zahlensätze für dieselbe Aufgabe wären zwei Stellen, an denen einer
veraltet.

Eine eigene Datei und nicht ein Import aus der Datenebene: die Konsole ist
ein eigenes Deployable und hängt nicht an deren Paket. Das kostet diese
zwanzig Zeilen und spart eine Abhängigkeit, die es sonst nur hierfür gäbe.
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

#: Weniger ist kein Passwort, sondern ein Merkzettel. Mehr erzwingt die
#: Anwendung nicht: Länge ist die einzige Regel, die ohne Wörterbuch etwas
#: bringt, und alles Weitere gehört in die Betriebsanweisung (ADR-0023).
MIN_LENGTH = 12

_HASHER = PasswordHasher(
    time_cost=3,
    memory_cost=65_536,  # 64 MiB
    parallelism=4,
    hash_len=32,
    salt_len=16,
)


def hash_password(plain: str) -> str:
    return _HASHER.hash(plain)


def verify_password(plain: str, hash_: str) -> bool:
    """`True`, wenn das Passwort passt — und `False` statt einer Ausnahme.

    Ein kaputter Hash in der Datenbank ist kein Absturz der Anmeldung: er
    ist eine gescheiterte Anmeldung, und der Unterschied gehört ins Log,
    nicht in die Antwort.
    """
    try:
        return _HASHER.verify(hash_, plain)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(hash_: str) -> bool:
    return _HASHER.check_needs_rehash(hash_)


__all__ = ["MIN_LENGTH", "hash_password", "needs_rehash", "verify_password"]
