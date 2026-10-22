-- schema-move-to-tenant.sql
--
-- Zieht eine bestehende Magister-Installation von `public` in ein
-- Mandantenschema um (ADR-0013 D1, Phase 1). Einmalig, mit Betriebsunterbruch.
--
-- Aufruf:
--   psql -v schema=t_default -v role=r_default -v ON_ERROR_STOP=1 \
--        -f scripts/schema-move-to-tenant.sql -d magister
--
-- Es werden KEINE Daten kopiert: `ALTER TABLE ... SET SCHEMA` verschiebt die
-- Tabelle mitsamt Indizes, Constraints und Inhalt. Der Umzug ist deshalb
-- schnell und unabhängig von der Datenmenge — er braucht aber eine exklusive
-- Sperre auf jede Tabelle, also einen Moment ohne laufende Anwendung.
--
-- Rückweg: dasselbe Skript mit -v schema=public. Vorher trotzdem einen Dump
-- ziehen (magister-cli tenants migrate --dump-dir ... zieht ihn automatisch;
-- hier muss er von Hand kommen, weil der Umzug vor der Registry passiert).
--
-- Voraussetzung: die Rolle existiert und das Zielschema gehört ihr. Beides legt
-- das Onboarding an, nicht dieses Skript — siehe docs/runbooks/kunden-onboarding.md.

\set ON_ERROR_STOP on

BEGIN;

-- Die psql-Variablen in Sitzungsparameter überführen: die DO-Blöcke unten
-- laufen als PL/pgSQL und sehen :schema nicht, wohl aber current_setting().
-- SET LOCAL, damit nichts über die Transaktion hinaus stehen bleibt.
SET LOCAL magister.target_schema = :'schema';
SET LOCAL magister.target_role = :'role';

-- 1 · Voraussetzungen prüfen, bevor irgendetwas bewegt wird.
DO $$
DECLARE
    target_schema text := current_setting('magister.target_schema');
    target_role   text := current_setting('magister.target_role');
    n_existing    int;
BEGIN
    IF target_schema !~ '^[a-z][a-z0-9_]{0,62}$' THEN
        RAISE EXCEPTION 'Schemaname % ist kein zulässiger Bezeichner.', target_schema;
    END IF;
    IF target_role !~ '^[a-z][a-z0-9_]{0,62}$' THEN
        RAISE EXCEPTION 'Rollenname % ist kein zulässiger Bezeichner.', target_role;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = target_role) THEN
        RAISE EXCEPTION
            'Rolle % existiert nicht. Sie wird beim Onboarding angelegt, nicht hier.',
            target_role;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.schemata WHERE schema_name = target_schema) THEN
        RAISE EXCEPTION
            'Schema % existiert nicht. Es wird beim Onboarding angelegt, nicht hier.',
            target_schema;
    END IF;

    -- Ein Zielschema, in dem schon Tabellen liegen, ist fast immer ein
    -- zweiter Versuch nach einem halben Umzug. Dann lieber anhalten als
    -- zwei Bestände vermischen.
    SELECT count(*) INTO n_existing
      FROM information_schema.tables
     WHERE table_schema = target_schema AND table_type = 'BASE TABLE';
    IF n_existing > 0 THEN
        RAISE EXCEPTION
            'Schema % enthält bereits % Tabelle(n). Abbruch — erst aufräumen.',
            target_schema, n_existing;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'public' AND table_name = 'alembic_version') THEN
        RAISE EXCEPTION
            'In public steht keine alembic_version. Hier ist keine Magister-Installation.';
    END IF;
END $$;

-- 2 · Alles aus public ins Zielschema verschieben.
--     Tabellen zuerst, dann was übrig bleibt: eigenständige Sequenzen (die zu
--     einer Spalte gehörenden wandern mit ihrer Tabelle), Views, Typen.
DO $$
DECLARE
    target_schema text := current_setting('magister.target_schema');
    obj record;
    moved int := 0;
BEGIN
    FOR obj IN
        SELECT c.relname, c.relkind
          FROM pg_class c
          JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = 'public'
           AND c.relkind IN ('r', 'p', 'v', 'm', 'S')
           -- Sequenzen mit Spaltenbindung wandern automatisch mit der Tabelle.
           AND NOT (c.relkind = 'S' AND EXISTS (
                 SELECT 1 FROM pg_depend d
                  WHERE d.objid = c.oid AND d.deptype = 'a'))
         ORDER BY CASE c.relkind WHEN 'r' THEN 0 WHEN 'p' THEN 0 ELSE 1 END, c.relname
    LOOP
        EXECUTE format(
            CASE obj.relkind
                WHEN 'S' THEN 'ALTER SEQUENCE public.%I SET SCHEMA %I'
                WHEN 'v' THEN 'ALTER VIEW public.%I SET SCHEMA %I'
                WHEN 'm' THEN 'ALTER MATERIALIZED VIEW public.%I SET SCHEMA %I'
                ELSE 'ALTER TABLE public.%I SET SCHEMA %I'
            END, obj.relname, target_schema);
        moved := moved + 1;
    END LOOP;
    RAISE NOTICE '% Objekt(e) nach % verschoben.', moved, target_schema;
END $$;

-- 3 · Eigentum an die Mandantenrolle übergeben.
--     Ohne diesen Schritt gehören die Tabellen weiter dem Migrations-Benutzer
--     und die Mandantenrolle bekommt beim ersten Query „permission denied for
--     table" — nachgemessen, nicht vermutet.
DO $$
DECLARE
    target_schema text := current_setting('magister.target_schema');
    target_role   text := current_setting('magister.target_role');
    obj record;
BEGIN
    FOR obj IN
        SELECT c.relname, c.relkind
          FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = target_schema
           AND c.relkind IN ('r', 'p', 'v', 'm', 'S')
           -- Spaltengebundene Sequenzen (serial/identity) haben keinen eigenen
           -- Eigentümer: Postgres lehnt ALTER SEQUENCE ... OWNER TO für sie ab
           -- ("is linked to table"). Sie folgen der Tabelle automatisch.
           AND NOT (c.relkind = 'S' AND EXISTS (
                 SELECT 1 FROM pg_depend d
                  WHERE d.objid = c.oid AND d.deptype = 'a'))
    LOOP
        EXECUTE format(
            CASE obj.relkind
                WHEN 'S' THEN 'ALTER SEQUENCE %I.%I OWNER TO %I'
                WHEN 'v' THEN 'ALTER VIEW %I.%I OWNER TO %I'
                WHEN 'm' THEN 'ALTER MATERIALIZED VIEW %I.%I OWNER TO %I'
                ELSE 'ALTER TABLE %I.%I OWNER TO %I'
            END, target_schema, obj.relname, target_role);
    END LOOP;
    EXECUTE format('ALTER SCHEMA %I OWNER TO %I', target_schema, target_role);
    EXECUTE format('REVOKE ALL ON SCHEMA %I FROM PUBLIC', target_schema);
    EXECUTE format('GRANT USAGE, CREATE ON SCHEMA %I TO %I', target_schema, target_role);
END $$;

-- 4 · Nachprüfen: in public darf keine Anwendungstabelle mehr liegen.
--     Sonst könnte eine im Mandantenschema fehlende Tabelle über den
--     search_path still auf den Rest in public zurückfallen — genau der
--     Fehler, den die Trennung verhindern soll.
DO $$
DECLARE
    target_schema text := current_setting('magister.target_schema');
    leftover text;
    n_target int;
BEGIN
    SELECT string_agg(table_name, ', ') INTO leftover
      FROM information_schema.tables
     WHERE table_schema = 'public' AND table_type = 'BASE TABLE';
    IF leftover IS NOT NULL THEN
        RAISE EXCEPTION 'In public liegen noch Tabellen: %. Abbruch.', leftover;
    END IF;

    SELECT count(*) INTO n_target
      FROM information_schema.tables
     WHERE table_schema = target_schema AND table_type = 'BASE TABLE';
    RAISE NOTICE 'Umzug fertig: % Tabelle(n) in %, public ist leer.', n_target, target_schema;
    RAISE NOTICE 'Nächster Schritt: MAGISTER_TENANTS auf schema_name=% und db_role setzen.',
        target_schema;
END $$;

COMMIT;
