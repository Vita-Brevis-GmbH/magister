"""Was in einen Kundenexport gehört — und was ausdrücklich nicht (ADR-0016 D7).

Ein Export ist kein umbenanntes Backup. Ein Backup enthält alles, auch
Interna, und ist verschlüsselt. Ein Export enthält **die Daten des Kunden**,
liegt im Klartext und ist ohne Magister lesbar. Genau deshalb ist die Liste
hier eine Allowlist und keine Denylist: eine neue Tabelle landet nicht
versehentlich im Export, sondern erst, wenn jemand sie einträgt.

Zwei Sicherungen dagegen, dass hier ein Geheimnis durchrutscht:

1. **``forbidden_column``** — ein zweiter Gürtel über die Spaltennamen. Was auf
   ``_enc`` endet, ``secret``/``token``/``_hash`` enthält oder ``payload``
   heisst, darf in keinem Export stehen, auch wenn jemand es hier einträgt.
2. **Der Test ``test_export.py``** hält beide Listen gegen das echte Schema:
   jede Tabelle muss entweder exportiert oder mit Begründung ausgeschlossen
   sein. Eine neue Migration bricht den Test, bis jemand entscheidet — und das
   ist die Absicht.

``NOT_EXPORTED`` ist deshalb kein Kommentar, sondern Teil der Prüfung.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Spaltennamen, die niemals in einen Export gehören. Absichtlich eng
#: formuliert: ``password_never_expires`` und ``store_password`` sind Flags und
#: harmlos, ``password_hash`` und ``ad_bind_password_enc`` sind es nicht.
FORBIDDEN_COLUMN = re.compile(
    r"(_enc$|secret|token|_hash$|^payload$|^recovery_codes$|^rolpassword$)", re.IGNORECASE
)


def forbidden_column(name: str) -> bool:
    return FORBIDDEN_COLUMN.search(name) is not None


@dataclass(frozen=True, slots=True)
class ExportTable:
    """Eine Tabelle im Export."""

    table: str
    #: Spalten in Ausgabereihenfolge. Ausdrücklich aufgeführt, nicht
    #: ``SELECT *``: sonst wächst der Export mit jeder Migration, und die
    #: nächste neue Spalte könnte ein Geheimnis sein.
    columns: tuple[str, ...]
    #: Wofür der Kunde die Datei liest. Landet im Manifest.
    description: str
    #: Spalte, nach der sortiert wird — damit zwei Exporte desselben Stands
    #: dieselbe Datei ergeben und ein Kunde sie vergleichen kann.
    order_by: str = "id"


#: Freitext je Spalte, wo der Name allein nicht reicht. Der Kunde soll die
#: Datei ohne uns verstehen — das ist der Zweck des Manifests.
COLUMN_NOTES: dict[str, str] = {
    "ad_object_guid": (
        "objectGUID des AD-Objekts, hex. Der stabile Schlüssel für Personen — "
        "Namen ändern sich, diese Kennung nicht."
    ),
    "school_id": "Verweis auf schools.id.",
    "class_id": "Verweis auf classes.id.",
    "department_id": "Verweis auf departments.id.",
    "device_id": "Verweis auf devices.id.",
    "valid_from": "Beginn der Zuordnung (ISO 8601).",
    "valid_to": (
        "Ende der Zuordnung (ISO 8601) oder leer für „läuft noch“. "
        "Zuordnungen werden beendet, nicht gelöscht."
    ),
    "jahrgangsstufe": "Jahrgangsstufe nach Lehrplan 21 (1 bis 11).",
    "kuerzel": "Kurzbezeichnung, wie sie in AD-Namen verwendet wird.",
    "scope_short": "Kürzel des Schulträgers im AD-Namensschema.",
    "key_id": (
        "Kennung des Kundenschlüssels, mit dem der (hier nicht enthaltene) "
        "Audit-Payload verschlüsselt ist."
    ),
}


PERSON = (
    "ad_object_guid",
    "upn",
    "sam_account_name",
    "given_name",
    "surname",
    "display_name",
    "mail",
    "kind",
    "enabled",
    "school_id",
    "jahrgangsstufe",
    "title",
    "department",
    "company",
    "telephone_number",
    "mobile",
    "office",
    "description",
    "employee_id",
    "street_address",
    "locality",
    "postal_code",
    "country",
    "device_name",
    "temp_device_name",
    "ad_groups",
    "mail_aliases",
    "ms_ds_consistency_guid",
    "password_never_expires",
    "cannot_change_password",
    "store_password",
    "last_sync_at",
    "ad_missing_since",
)


EXPORT_TABLES: tuple[ExportTable, ...] = (
    ExportTable(
        table="schools",
        columns=(
            "id",
            "name",
            "kuerzel",
            "scope_short",
            "street",
            "postal_code",
            "city",
            "phone",
            "description",
            "latitude",
            "longitude",
            "ad_ou_students_zyklus3",
            "ad_ou_students_other",
            "ad_ou_teachers",
            "ad_ou_devices",
            "ad_ou_company_users",
            "ad_groups_company",
            "ad_groups_teacher",
            "ad_groups_student_zyklus1",
            "ad_groups_student_zyklus2",
            "ad_groups_student_zyklus3",
            "created_at",
            "updated_at",
        ),
        description="Schulen des Schulträgers, mit den AD-Pfaden, die zu ihnen gehören.",
    ),
    ExportTable(
        table="classes",
        columns=(
            "id",
            "school_id",
            "name",
            "kuerzel",
            "jahrgangsstufe",
            "jahrgangsstufe_bis",
            "details",
            "status",
            "created_at",
            "updated_at",
        ),
        description="Klassen. Magister ist hierfür die führende Quelle, nicht das AD.",
    ),
    ExportTable(
        table="class_memberships",
        columns=(
            "id",
            "class_id",
            "ad_object_guid",
            "valid_from",
            "valid_to",
            "created_by",
            "created_at",
        ),
        description="Wer wann in welcher Klasse war. Historisiert.",
    ),
    ExportTable(
        table="class_teacher_roles",
        columns=(
            "id",
            "class_id",
            "ad_object_guid",
            "role",
            "valid_from",
            "valid_to",
            "created_by",
            "created_at",
        ),
        description="Klassenlehrpersonen und Stellvertretungen, historisiert.",
    ),
    ExportTable(
        table="subject_teacher_roles",
        columns=(
            "id",
            "class_id",
            "ad_object_guid",
            "subject",
            "valid_from",
            "valid_to",
            "created_by",
            "created_at",
        ),
        description="Fachlehrpersonen je Klasse und Fach, historisiert.",
    ),
    ExportTable(
        table="departments",
        columns=(
            "id",
            "school_id",
            "name",
            "kuerzel",
            "details",
            "ad_groups",
            "status",
            "created_at",
            "updated_at",
        ),
        description="Abteilungen und Betriebe.",
    ),
    ExportTable(
        table="department_memberships",
        columns=(
            "id",
            "department_id",
            "ad_object_guid",
            "valid_from",
            "valid_to",
            "created_by",
            "created_at",
        ),
        description="Zugehörigkeit von Personen zu Abteilungen, historisiert.",
    ),
    ExportTable(
        table="manager_roles",
        columns=(
            "id",
            "department_id",
            "ad_object_guid",
            "role",
            "valid_from",
            "valid_to",
            "created_by",
            "created_at",
        ),
        description="Leitungsfunktionen in Abteilungen, historisiert.",
    ),
    ExportTable(
        table="ad_user_cache",
        columns=PERSON,
        description=(
            "Personen (Lehrpersonen, Schülerinnen und Schüler), gespiegelt aus dem AD. "
            "Ohne password_enc: gespeicherte Passwörter verlassen Magister nicht im "
            "Klartext, auch nicht in einem Export für den Kunden."
        ),
        order_by="ad_object_guid",
    ),
    ExportTable(
        table="ad_group_cache",
        columns=(
            "ad_object_guid",
            "distinguished_name",
            "cn",
            "sam_account_name",
            "description",
            "last_sync_at",
        ),
        description="AD-Gruppen, gespiegelt. Zeigt, worauf sich die Gruppenangaben beziehen.",
        order_by="ad_object_guid",
    ),
    ExportTable(
        table="devices",
        columns=(
            "id",
            "name",
            "device_type",
            "serial_number",
            "notes",
            "school_id",
            "class_id",
            "assigned_person_guid",
            "is_loan",
            "ad_object_guid",
            "source",
            "created_at",
            "updated_at",
        ),
        description="Geräteinventar.",
    ),
    ExportTable(
        table="device_assignments",
        columns=(
            "id",
            "device_id",
            "assignment_type",
            "assigned_person_guid",
            "class_id",
            "school_id",
            "label",
            "is_loan",
            "valid_from",
            "valid_to",
            "created_at",
        ),
        description="Gerätezuweisungen, historisiert.",
    ),
    ExportTable(
        table="group_templates",
        columns=(
            "id",
            "name",
            "description",
            "kind",
            "ad_groups",
            "status",
            "created_at",
            "updated_at",
        ),
        description="Gruppenvorlagen: welche AD-Gruppen bei einer Rolle gesetzt werden.",
    ),
    ExportTable(
        table="group_template_schools",
        columns=("group_template_id", "school_id"),
        description="Welche Gruppenvorlage für welche Schule gilt.",
        order_by="group_template_id",
    ),
    ExportTable(
        table="roles",
        columns=("id", "key", "name", "is_system", "is_admin", "is_derived", "created_at"),
        description="Rollen. is_system markiert die von Magister mitgelieferten.",
    ),
    ExportTable(
        table="role_capabilities",
        columns=("id", "role_key", "capability"),
        description="Welche Rolle welche Berechtigung hat.",
    ),
    ExportTable(
        table="role_assignments",
        columns=(
            "id",
            "ad_object_guid",
            "school_id",
            "role",
            "granted_by",
            "granted_at",
            "revoked_at",
        ),
        description="Wer welche Rolle hat oder hatte. Entzug wird vermerkt, nicht gelöscht.",
    ),
    ExportTable(
        table="user_preferences",
        columns=("ad_object_guid", "language", "region", "date_format", "time_format"),
        description="Persönliche Anzeigeeinstellungen.",
        order_by="ad_object_guid",
    ),
    ExportTable(
        table="document_templates",
        columns=("id", "key", "language", "school_id", "subject", "is_active", "updated_at"),
        description=(
            "Dokumentvorlagen — hier nur die Kopfdaten. Der Text jeder Vorlage liegt als "
            "eigene HTML-Datei unter vorlagen/ (ADR-0016 D7: „Vorlagen als Dateien“)."
        ),
    ),
    ExportTable(
        table="platform_document_templates",
        columns=("id", "key", "language", "subject", "may_override", "version", "delivered_at"),
        description=(
            "Vorlagen, die Vita Brevis für diese Installation vorgegeben hat (ADR-0018) — "
            "hier die Kopfdaten. Der Text liegt unter vorlagen/plattform/. Sie stehen im "
            "Export, weil mit ihnen gedruckt wurde: wer geht, nimmt seine Briefe mit."
        ),
    ),
    ExportTable(
        table="audit_events",
        columns=(
            "id",
            "ts",
            "actor_upn",
            "actor_object_guid",
            "action",
            "target_kind",
            "target_id",
            "school_id",
            "ip",
            "request_id",
            "key_id",
        ),
        description=(
            "Protokoll der Änderungen — wer, wann, was. **Ohne payload**: der ist mit dem "
            "Kundenschlüssel verschlüsselt, und den hat der Exportprozess nicht "
            "(ADR-0016 D2). Wer die Details braucht, braucht auch den Schlüssel."
        ),
        order_by="id",
    ),
)


#: Tabellen, die absichtlich **nicht** exportiert werden, mit Begründung. Der
#: Text landet im Manifest: der Kunde soll sehen, was fehlt und warum, statt
#: es zu vermuten.
NOT_EXPORTED: dict[str, str] = {
    "sessions": (
        "Aktive Anmeldesitzungen. Die Zeilen sind Zugangsmittel, keine Daten — "
        "und mit dem Export wären sie es doppelt."
    ),
    "local_admins": (
        "Notfallzugang zur Installation: Passwort-Hash, TOTP-Geheimnis, "
        "Wiederherstellungscodes. Plattform-Interna, und kein Inhalt, den man "
        "in eine CSV schreibt."
    ),
    "app_settings": (
        "Konfiguration der Installation, inklusive verschlüsselter Geheimnisse "
        "(AD-Bind-Passwort, OIDC-Client-Secret, TLS-Schlüssel). Plattform-Interna."
    ),
    "ad_sync_state": "Merkposten des AD-Abgleichs (Zeitstempel, Zähler). Kein Inhalt.",
    "import_jobs": (
        "Importläufe. Arbeitsstand eines Vorgangs; das Ergebnis steht in den exportierten Tabellen."
    ),
    "import_staged_rows": (
        "Rohzeilen eines noch nicht angewandten Imports. Arbeitsstand, und die "
        "Rohdaten können alles enthalten, was jemand in eine Datei geschrieben hat."
    ),
    "alembic_version": "Schemastand der Datenbank. Steht im Manifest als schema_version.",
}


def exported_table_names() -> frozenset[str]:
    return frozenset(entry.table for entry in EXPORT_TABLES)


__all__ = [
    "COLUMN_NOTES",
    "EXPORT_TABLES",
    "FORBIDDEN_COLUMN",
    "NOT_EXPORTED",
    "ExportTable",
    "exported_table_names",
    "forbidden_column",
]
