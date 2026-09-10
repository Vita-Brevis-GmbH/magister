"""Kopf-Version des Schemas, gegen die der Code geschrieben ist (ADR-0013 D7).

Warum eine Konstante und nicht ein Blick ins Alembic-Verzeichnis zur Laufzeit:
die Anwendung soll die Version kennen, ohne Alembic zu importieren oder das
Dateisystem zu befragen — im Container liegen die Migrationen unter Umständen
gar nicht mit. Dass die Konstante stimmt, prüft ein Test gegen den echten
Alembic-Kopf; Abweichung fällt damit in CI auf und nicht im Betrieb.
"""

from __future__ import annotations

#: Alembic-Revision, die zum aktuellen Modellstand gehört.
HEAD_REVISION = "0045_platform_document_templates"
