"""Die Schlüssel, deren Signatur ein Agenten-Update tragen muss (ADR-0014 Nachtrag 2026-10).

Ed25519, öffentlicher Teil, 32 Byte Base64 — je Eintrag ``Schlüssel-ID →
Schlüssel``. Die ID ist der Anfang der SHA-256 über den Schlüssel
(``packaging/signieren.py schluessel`` nennt beide).

**Warum hier im Quelltext und nirgends sonst:** der Agent läuft als
LocalSystem auf dem Domänencontroller. Käme der Schlüssel von der Plattform,
könnte eine übernommene Plattform ihren eigenen schicken und damit Code auf
den DCs aller Kunden ausführen. So muss ein Angreifer den privaten Schlüssel
haben — und der liegt offline bei Vita Brevis, nicht auf der Plattform und
nicht in der CI.

Zwei Einträge sind für den Wechsel gedacht: neuen Schlüssel hier eintragen,
ausliefern, dann mit dem neuen signieren, später den alten streichen.

Leer heisst: kein Selbstupdate. ``magister-connector update`` von Hand geht
weiter (Prüfsumme wie bisher) und sagt, dass keine Signatur geprüft wurde.
"""

from __future__ import annotations

TRUSTED_KEYS: dict[str, str] = {"52b0d6783021b7c5": "lFEpDxN7TeLGbRqkLWNVUewmojBABoCuc4t/MCesv8U="}

__all__ = ["TRUSTED_KEYS"]
