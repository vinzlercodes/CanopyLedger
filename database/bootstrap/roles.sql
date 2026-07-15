\set ON_ERROR_STOP on

-- Cluster-scoped capability roles. Deployments grant these roles to separate
-- credential-bearing login principals; the capability roles never log in.
SELECT format(
  'CREATE ROLE %I NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS',
  role_name
)
FROM (
  VALUES
    ('migration_owner'),
    ('application_writer'),
    ('pipeline_writer'),
    ('analytics_reader'),
    ('report_reader'),
    ('audit_reader')
) AS required_roles(role_name)
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = role_name)
\gexec

ALTER ROLE migration_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;
ALTER ROLE application_writer NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;
ALTER ROLE pipeline_writer NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;
ALTER ROLE analytics_reader NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;
ALTER ROLE report_reader NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;
ALTER ROLE audit_reader NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;

REVOKE ALL PRIVILEGES ON DATABASE :"DBNAME" FROM PUBLIC;
GRANT CONNECT ON DATABASE :"DBNAME" TO
  migration_owner,
  application_writer,
  pipeline_writer,
  analytics_reader,
  report_reader,
  audit_reader;

REVOKE ALL ON SCHEMA public FROM PUBLIC;

CREATE SCHEMA IF NOT EXISTS canopyledger AUTHORIZATION migration_owner;
CREATE SCHEMA IF NOT EXISTS analytics AUTHORIZATION migration_owner;
CREATE SCHEMA IF NOT EXISTS reporting AUTHORIZATION migration_owner;
CREATE SCHEMA IF NOT EXISTS audit AUTHORIZATION migration_owner;

ALTER SCHEMA canopyledger OWNER TO migration_owner;
ALTER SCHEMA analytics OWNER TO migration_owner;
ALTER SCHEMA reporting OWNER TO migration_owner;
ALTER SCHEMA audit OWNER TO migration_owner;

REVOKE ALL ON SCHEMA canopyledger, analytics, reporting, audit FROM PUBLIC;
GRANT USAGE ON SCHEMA canopyledger TO application_writer, pipeline_writer;
GRANT USAGE ON SCHEMA analytics TO analytics_reader;
GRANT USAGE ON SCHEMA reporting TO report_reader;
GRANT USAGE ON SCHEMA audit TO audit_reader;

ALTER ROLE migration_owner SET search_path = pg_catalog, canopyledger;
ALTER ROLE application_writer SET search_path = pg_catalog, canopyledger;
ALTER ROLE pipeline_writer SET search_path = pg_catalog, canopyledger;
ALTER ROLE analytics_reader SET search_path = pg_catalog, analytics;
ALTER ROLE report_reader SET search_path = pg_catalog, reporting;
ALTER ROLE audit_reader SET search_path = pg_catalog, audit;

-- M8 sets this transaction-local resource ceiling after switching to the
-- read-only capability role. PostgreSQL otherwise reserves it to superusers.
GRANT SET ON PARAMETER temp_file_limit TO analytics_reader;

-- Curated reader schemas are read-only by construction. Operational grants are
-- deliberately table-specific and arrive with the M1A resource schema.
ALTER DEFAULT PRIVILEGES FOR ROLE migration_owner
  IN SCHEMA analytics GRANT SELECT ON TABLES TO analytics_reader;
ALTER DEFAULT PRIVILEGES FOR ROLE migration_owner
  IN SCHEMA reporting GRANT SELECT ON TABLES TO report_reader;
ALTER DEFAULT PRIVILEGES FOR ROLE migration_owner
  IN SCHEMA audit GRANT SELECT ON TABLES TO audit_reader;
ALTER DEFAULT PRIVILEGES FOR ROLE migration_owner
  REVOKE EXECUTE ON ROUTINES FROM PUBLIC;
