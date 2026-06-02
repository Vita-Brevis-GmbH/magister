"""German letter strings for PDF generation (M3 US-1).

Letters are physically printed and handed to parents — the language must
match the school's working language, which is *not* the user's UI locale.
We start with German only (the production language for current Schulträger);
FR/IT/EN follow when Vita Brevis onboards schools in those regions.
"""

from __future__ import annotations

from typing import Any

LETTER_STRINGS_DE: dict[str, Any] = {
    "address_label": "An die Eltern / Erziehungsberechtigten von",
    "kind_regards": "Freundliche Grüsse",
    "enrollment": {
        "subject": "Eintritt in die {class_name}",
        "salutation": "Sehr geehrte Eltern / Erziehungsberechtigte",
        "intro": (
            "Wir freuen uns, Ihre Tochter / Ihren Sohn {student_name} im "
            "kommenden Schuljahr {school_year} in unserer {class_name} "
            "willkommen zu heissen."
        ),
        "start": "Der erste Schultag ist am {first_day}.",
        "kl": "Klassenlehrperson ist {kl_name}.",
        "documents": "In den nächsten Tagen erhalten Sie folgende Unterlagen:",
        "doc_passwords": "Passwort-Übergabeschreiben für den Schul-Account",
        "doc_devices": "Informationen zum Schul-Gerät (falls verfügbar)",
        "doc_emergency": "Notfall-Kontaktformular",
        "questions": (
            "Bei Fragen wenden Sie sich an die Klassenlehrperson oder direkt an die Schulleitung."
        ),
    },
    "class_change": {
        "subject": "Klassenwechsel in die {class_name}",
        "salutation": "Sehr geehrte Eltern / Erziehungsberechtigte",
        "intro": (
            "Wir möchten Sie informieren, dass Ihre Tochter / Ihr Sohn "
            "{student_name} per {effective_date} von der {old_class} in die "
            "{new_class} wechselt."
        ),
        "kl": "Neue Klassenlehrperson ist {kl_name}.",
        "continuity": (
            "Der Schul-Account bleibt unverändert — keine neuen "
            "Anmeldedaten nötig. Schul-Geräte bleiben dem Kind zugeordnet."
        ),
        "questions": (
            "Bei Fragen oder offenen Punkten zum Übergang wenden Sie sich "
            "bitte an die bisherige oder die neue Klassenlehrperson."
        ),
    },
    "password_handout": {
        "subject": "Schul-Account: Anmeldedaten",
        "salutation": "Sehr geehrte Eltern / Erziehungsberechtigte",
        "intro": ("Anbei finden Sie die Anmeldedaten für den Schul-Account von {student_name}."),
        "credentials": "Die Anmeldedaten lauten:",
        "label_username": "Benutzername:",
        "label_password": "Passwort:",
        "note_change": (
            "Beim ersten Login wird Ihre Tochter / Ihr Sohn aufgefordert, "
            "ein eigenes Passwort zu setzen."
        ),
        "security": (
            "Bitte bewahren Sie dieses Schreiben sicher auf und geben Sie "
            "die Daten nicht weiter. Bei Verlust kann jederzeit ein neues "
            "Passwort gesetzt werden."
        ),
        "questions": (
            "Bei technischen Problemen oder Fragen wenden Sie sich an die Klassenlehrperson."
        ),
    },
}


__all__ = ["LETTER_STRINGS_DE"]
