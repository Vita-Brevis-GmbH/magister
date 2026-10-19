"""Zielgruppen: Passwortart und Konto-Vorgaben, Standardgruppen je Schule

Revision ID: 0047_zielgruppen
Revises: 0046_operator_access
Create Date: 2026-10-19

Die bisherigen "Zielrollen" (``group_templates``) trugen nur AD-Gruppen. Das
einzelne Anlegen gab deshalb jedem Konto das komplexe 14-stellige Passwort —
auch Kindern im Zyklus 1, die der CSV-Import längst mit ``Tiger-Wolke-47``
versorgte. Jetzt legt die Zielgruppe fest:

* ``password_profile`` — readable | teacher | complex
* ``force_change``, ``cannot_change_password``, ``password_never_expires``
* ``store_password`` — Passwort im Tresor (Klassen-Passwortliste)

Bestehende Zielgruppen bekommen die Vorgabe ihrer Kontoart (``kind``). Jede
Schule bekommt die fehlenden Standard-Zielgruppen Schüler:in Zyklus 1/2/3 und
Lehrperson (Firma: Mitarbeiter:in), mit den Gruppen aus den ``ad_groups_*``-
Spalten des Standorts.

``ad_user_cache.group_template_id`` merkt sich, nach welcher Zielgruppe ein
Konto angelegt wurde — für die Passwortart späterer Resets und dafür, welche
Gruppen ein Wechsel der Zielgruppe entfernt.

Die Vorgaben sind aus ``services/zielgruppen.py`` kopiert, nicht importiert:
eine Migration beschreibt den Stand ihres Tages.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0047_zielgruppen"
down_revision: str | Sequence[str] | None = "0046_operator_access"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# kind -> (Name, Passwortart, force_change, cannot_change, never_expires, store)
_VORGABEN: dict[str, tuple[str, str, bool, bool, bool, bool]] = {
    "student_zyklus1": ("Schüler:in Zyklus 1", "readable", False, True, True, True),
    "student_zyklus2": ("Schüler:in Zyklus 2", "readable", False, True, True, True),
    "student_zyklus3": ("Schüler:in Zyklus 3", "readable", True, False, False, False),
    "teacher": ("Lehrperson", "teacher", True, False, False, False),
    "company": ("Mitarbeiter:in", "teacher", True, False, False, False),
}
_KINDS_FOR_PROFILE: dict[str, tuple[str, ...]] = {
    "school": ("student_zyklus1", "student_zyklus2", "student_zyklus3", "teacher"),
    "company": ("company",),
    "neutral": (),
}


def upgrade() -> None:
    op.add_column(
        "group_templates",
        sa.Column(
            "password_profile", sa.String(length=16), nullable=False, server_default="complex"
        ),
    )
    for name, default in (
        ("force_change", "true"),
        ("cannot_change_password", "false"),
        ("password_never_expires", "false"),
        ("store_password", "false"),
    ):
        op.add_column(
            "group_templates",
            sa.Column(name, sa.Boolean(), nullable=False, server_default=default),
        )
    op.create_check_constraint(
        "ck_group_templates_password_profile",
        "group_templates",
        "password_profile IN ('readable', 'teacher', 'complex')",
    )
    op.add_column(
        "ad_user_cache",
        sa.Column(
            "group_template_id",
            sa.Integer(),
            sa.ForeignKey("group_templates.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    conn = op.get_bind()
    upd = sa.text(
        "UPDATE group_templates SET password_profile = :p, force_change = :f, "
        "cannot_change_password = :c, password_never_expires = :n, store_password = :s "
        "WHERE kind = :k"
    )
    for kind, (_, p, f, c, n, s) in _VORGABEN.items():
        conn.execute(upd, {"p": p, "f": f, "c": c, "n": n, "s": s, "k": kind})

    profile = conn.execute(
        sa.text("SELECT instance_profile FROM app_settings WHERE id = 1")
    ).scalar_one_or_none() or "school"
    kinds = _KINDS_FOR_PROFILE.get(profile, _KINDS_FOR_PROFILE["school"])
    if not kinds:
        return
    cols = ", ".join(f"ad_groups_{k}" for k in kinds)
    schools = conn.execute(sa.text(f"SELECT id, {cols} FROM schools")).mappings().all()
    # Angeboten = an diesen Standort gebunden oder global (ohne Bindung).
    offered = sa.text(
        "SELECT 1 FROM group_templates t WHERE t.status = 'active' AND t.kind = :k AND ("
        " NOT EXISTS (SELECT 1 FROM group_template_schools l WHERE l.group_template_id = t.id)"
        " OR EXISTS (SELECT 1 FROM group_template_schools l"
        "            WHERE l.group_template_id = t.id AND l.school_id = :sid)) LIMIT 1"
    )
    insert = sa.text(
        "INSERT INTO group_templates (name, kind, ad_groups, status, password_profile, "
        "force_change, cannot_change_password, password_never_expires, store_password, "
        "created_at, updated_at) VALUES (:name, :k, CAST(:groups AS jsonb), 'active', :p, "
        ":f, :c, :n, :s, now(), now()) RETURNING id"
    )
    link = sa.text(
        "INSERT INTO group_template_schools (group_template_id, school_id) VALUES (:tid, :sid)"
    )
    for school in schools:
        for kind in kinds:
            if conn.execute(offered, {"k": kind, "sid": school["id"]}).first():
                continue
            name, p, f, c, n, s = _VORGABEN[kind]
            raw = school[f"ad_groups_{kind}"]
            groups = raw if isinstance(raw, list) else (json.loads(raw) if raw else [])
            tid = conn.execute(
                insert,
                {
                    "name": name,
                    "k": kind,
                    "groups": json.dumps(groups),
                    "p": p,
                    "f": f,
                    "c": c,
                    "n": n,
                    "s": s,
                },
            ).scalar_one()
            conn.execute(link, {"tid": tid, "sid": school["id"]})


def downgrade() -> None:
    op.drop_column("ad_user_cache", "group_template_id")
    op.drop_constraint("ck_group_templates_password_profile", "group_templates", type_="check")
    for name in (
        "store_password",
        "password_never_expires",
        "cannot_change_password",
        "force_change",
        "password_profile",
    ):
        op.drop_column("group_templates", name)
