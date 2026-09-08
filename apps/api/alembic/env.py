"""Alembic env — async-aware, derives metadata from magister_api.models.

Migrations run **per schema** (ADR-0013 D7). Which one comes from
``MAGISTER_MIGRATE_SCHEMA`` (default ``public``, the estate before the move).
Two things follow from that:

- ``version_table_schema``: every tenant carries its own ``alembic_version``
  inside its own schema. A shared version table would make one tenant's
  migration look like everyone's.
- ``search_path`` on the connection, so unqualified DDL in the 44 existing
  migrations lands in the target schema without touching a single one of them.

The migration is driven by ``magister-cli tenants migrate``, which walks the
registry, takes a dump per tenant first and migrates the canary before the rest.
Calling ``alembic upgrade`` by hand migrates exactly one schema — the one in the
environment variable.
"""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from sqlalchemy import pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from magister_api.config import get_settings
from magister_api.models import Base
from magister_api.tenancy.scope import quote_identifier

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _resolve_url() -> str:
    """Pick the URL from env (preferred) or alembic.ini."""
    return os.environ.get("MAGISTER_DATABASE_URL") or get_settings().database_url


def _resolve_schema() -> str:
    """Target schema for this run. Validated, because it goes into SQL as text."""
    schema = (os.environ.get("MAGISTER_MIGRATE_SCHEMA") or "public").strip()
    quote_identifier(schema, field="MAGISTER_MIGRATE_SCHEMA")
    return schema


def _resolve_extension_schema() -> str:
    schema = (os.environ.get("MAGISTER_EXTENSION_SCHEMA") or "public").strip()
    quote_identifier(schema, field="MAGISTER_EXTENSION_SCHEMA")
    return schema


def run_migrations_offline() -> None:
    context.configure(
        url=_resolve_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        version_table_schema=_resolve_schema(),
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    schema = _resolve_schema()
    path = quote_identifier(schema, field="schema")
    ext = _resolve_extension_schema()
    if ext != schema:
        path = f"{path}, {quote_identifier(ext, field='extension_schema')}"

    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        version_table_schema=schema,
        include_schemas=False,
    )

    # ALLES ab hier muss innerhalb von ``begin_transaction()`` laufen. Alembic
    # macht daraus einen No-op, wenn die Verbindung schon in einer Transaktion
    # steckt — und dann committet am Ende niemand. Ein Statement vor diesem
    # Block (etwa das SET unten) genügt, damit alle Migrationen sauber
    # durchlaufen, beim Verbindungsschluss zurückgerollt werden und Alembic
    # trotzdem Erfolg meldet. Genau so beobachtet, nicht theoretisch.
    with context.begin_transaction():
        if schema != "public":
            # Kein CREATE SCHEMA hier: Anlegen samt Rolle und REVOKE gehört ins
            # Onboarding (docs/runbooks/kunden-onboarding.md). Ein Tippfehler
            # soll ein Fehler sein, nicht ein leeres neues Schema.
            # text() statt exec_driver_sql: asyncpg bindet positionell ($1),
            # nicht im pyformat des psycopg-Treibers.
            exists = connection.execute(
                text("SELECT 1 FROM information_schema.schemata WHERE schema_name = :s"),
                {"s": schema},
            ).scalar()
            if not exists:
                raise RuntimeError(
                    f"Schema {schema!r} existiert nicht. Ein Mandantenschema wird beim "
                    "Onboarding angelegt (samt eigener Rolle und entzogenem USAGE), "
                    "nicht von einer Migration — siehe docs/runbooks/kunden-onboarding.md."
                )

        # search_path so setzen, dass die bestehenden Migrationen unverändert im
        # Zielschema landen. Das Erweiterungsschema muss mit drauf, sonst findet
        # eine Migration ``gen_random_uuid`` und Co. nicht.
        connection.exec_driver_sql(f"SET search_path TO {path}")
        context.run_migrations()


async def run_migrations_online() -> None:
    config_section = config.get_section(config.config_ini_section, {})
    config_section["sqlalchemy.url"] = _resolve_url()
    connectable = async_engine_from_config(
        config_section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        future=True,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
