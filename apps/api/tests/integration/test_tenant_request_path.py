"""Der ganze Anfragepfad gegen ein echtes Mandantenschema (ADR-0013, Phase 1).

Die anderen Integrationstests überschreiben ``get_session`` und sehen die
Mandanten-Mechanik deshalb nicht. Hier läuft eine echte HTTP-Anfrage durch
Auflösungs-Middleware, Engine-Registry, ``apply_tenant_scope`` und den
Repository-Layer — mit einer eigenen Anmelderolle, einem eigenen Schema und
ohne jede Überschreibung.

``/auth/capabilities`` ist der Prüfstein: unauthentisiert, liest aber über den
Repository-Layer aus der Datenbank. Kommt dort eine Antwort zurück, hat die
ganze Kette gehalten.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine

from magister_api.config import Settings
from magister_api.main import create_app
from magister_api.models import Base
from magister_api.tenancy.context import dispose_tenancy, init_tenancy

pytestmark = pytest.mark.asyncio

SLUG = "e2e"
SCHEMA = f"t_{SLUG}"
ROLE = f"r_{SLUG}"

#: Frei erfunden, nur in dieser Datei gültig.
ROLE_PASSWORD = "test-rollenpasswort"  # noqa: S105
HOST = f"{SLUG}.magister.test"


@pytest_asyncio.fixture
async def tenant_schema(engine: AsyncEngine, database_url: str) -> AsyncIterator[str]:
    """Schema, Rolle und Tabellen anlegen — wie das Onboarding es tut."""
    async with engine.begin() as conn:
        await conn.exec_driver_sql(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
        await conn.exec_driver_sql(f"DROP ROLE IF EXISTS {ROLE}")
        create = f"CREATE ROLE {ROLE} LOGIN PASSWORD '{ROLE_PASSWORD}'"
        await conn.exec_driver_sql(create)
        await conn.exec_driver_sql(f"CREATE SCHEMA {SCHEMA} AUTHORIZATION {ROLE}")
        await conn.exec_driver_sql(f"REVOKE ALL ON SCHEMA {SCHEMA} FROM PUBLIC")
        await conn.exec_driver_sql(f"GRANT USAGE, CREATE ON SCHEMA {SCHEMA} TO {ROLE}")

    # Tabellen im Mandantenschema: schema_translate_map bildet das
    # schemalose Modell auf das Zielschema ab — dieselbe Wirkung wie
    # Alembic mit gesetztem search_path, nur ohne 44 Migrationen im Test.
    async with engine.connect() as conn:
        scoped = await conn.execution_options(schema_translate_map={None: SCHEMA})
        await scoped.run_sync(Base.metadata.create_all)
        await scoped.commit()

    # Eigentum an die Mandantenrolle. Ohne das gehören die Tabellen dem
    # Testbenutzer und die Rolle bekommt "permission denied for table" —
    # derselbe Fallstrick wie beim Migrieren als Superuser.
    # SCHEMA und ROLE sind Konstanten dieses Moduls, keine Eingabewerte;
    # die Bezeichner müssen als Text ins DDL, das nimmt keine Bind-Parameter.
    reassign = f"""
            DO $$
            DECLARE obj record;
            BEGIN
                FOR obj IN
                    SELECT c.relname, c.relkind FROM pg_class c
                      JOIN pg_namespace n ON n.oid = c.relnamespace
                     WHERE n.nspname = '{SCHEMA}' AND c.relkind IN ('r','p','S')
                       AND NOT (c.relkind = 'S' AND EXISTS (
                             SELECT 1 FROM pg_depend d
                              WHERE d.objid = c.oid AND d.deptype = 'a'))
                LOOP
                    EXECUTE format(
                        CASE obj.relkind WHEN 'S'
                            THEN 'ALTER SEQUENCE {SCHEMA}.%I OWNER TO {ROLE}'
                            ELSE 'ALTER TABLE {SCHEMA}.%I OWNER TO {ROLE}' END,
                        obj.relname);
                END LOOP;
            END $$;
    """  # noqa: S608
    seed_settings = (
        f"INSERT INTO {SCHEMA}.app_settings (id, version, oidc_scopes, "  # noqa: S608
        "bootstrap_admins, ad_dcs) VALUES (1, 1, '[]'::jsonb, '[]'::jsonb, "
        "'[]'::jsonb) ON CONFLICT DO NOTHING"
    )
    async with engine.begin() as conn:
        await conn.exec_driver_sql(reassign)
        await conn.exec_driver_sql(seed_settings)

    # hide_password=False, und überhaupt ein Passwort: ohne eines liefe dieser
    # Test nur auf einem Cluster mit trust-Authentisierung — eine unsichtbare
    # Annahme, die auf scram-sha-256 wie ein kaputtes Testkonto aussieht.
    yield (
        make_url(database_url)
        .set(username=ROLE, password=ROLE_PASSWORD)
        .render_as_string(hide_password=False)
    )

    async with engine.begin() as conn:
        await conn.exec_driver_sql(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
        await conn.exec_driver_sql(f"DROP ROLE IF EXISTS {ROLE}")


@pytest_asyncio.fixture
async def tenant_client(tenant_schema: str, app_settings: Settings) -> AsyncIterator[AsyncClient]:
    tenants = (
        f'[{{"slug": "{SLUG}", "hostname": "{HOST}", "dsn": "{tenant_schema}", '
        f'"db_role": "{ROLE}", "schema_name": "{SCHEMA}"}}]'
    )
    settings = app_settings.model_copy(update={"tenants": tenants})
    init_tenancy(settings)
    application = create_app(settings)
    # Bewusst KEIN dependency_overrides[get_session]: genau der Pfad ist der
    # Prüfgegenstand.
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url=f"http://{HOST}") as client:
        yield client
    await dispose_tenancy()


class TestTheWholeChain:
    async def test_a_request_reaches_the_tenant_schema(self, tenant_client: AsyncClient) -> None:
        """Auflösung → Engine → Zusicherung → Repository, ohne Überschreibung."""
        resp = await tenant_client.get("/auth/capabilities")
        assert resp.status_code == 200, resp.text
        assert "oidc_enabled" in resp.json()

    async def test_an_unknown_host_never_reaches_the_database(
        self, tenant_client: AsyncClient
    ) -> None:
        resp = await tenant_client.get(
            "/auth/capabilities", headers={"host": "fremder.magister.test"}
        )
        assert resp.status_code == 404
        assert resp.json() == {"detail": "unknown_tenant"}

    async def test_the_transaction_really_runs_as_the_tenant_role(
        self, tenant_client: AsyncClient, engine: AsyncEngine
    ) -> None:
        """Gegenprobe direkt an der Datenbank, nicht an der Anwendung.

        Die Anwendung hat gerade erfolgreich gelesen — hier wird bestätigt,
        dass sie das unter der Mandantenrolle getan hat und nicht unter dem
        Testbenutzer, der auf alles Zugriff hätte.
        """
        assert (await tenant_client.get("/auth/capabilities")).status_code == 200
        async with engine.connect() as conn:
            owner = (
                await conn.execute(
                    text("SELECT tableowner FROM pg_tables WHERE schemaname = :s LIMIT 1"),
                    {"s": SCHEMA},
                )
            ).scalar()
        assert owner == ROLE

    async def test_the_health_probe_answers_without_a_tenant(
        self, tenant_client: AsyncClient
    ) -> None:
        resp = await tenant_client.get("/healthz", headers={"host": "unbekannt.test"})
        assert resp.status_code == 200
