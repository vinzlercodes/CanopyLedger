#!/usr/bin/env bash
set -euo pipefail

: "${DATABASE_URL:?DATABASE_URL must point to a disposable PostgreSQL database}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PSQL=(psql "${DATABASE_URL}" -X -v ON_ERROR_STOP=1)

"${PSQL[@]}" -f "${ROOT}/database/bootstrap/roles.sql"
"${PSQL[@]}" -f "${ROOT}/database/bootstrap/roles.sql"

"${PSQL[@]}" -Atc "
SELECT count(*) = 6
FROM pg_roles
WHERE rolname IN (
  'migration_owner', 'application_writer', 'pipeline_writer',
  'analytics_reader', 'report_reader', 'audit_reader'
)
AND NOT rolcanlogin
AND NOT rolsuper
AND NOT rolcreatedb
AND NOT rolcreaterole
AND NOT rolinherit
AND NOT rolreplication
AND NOT rolbypassrls;
" | grep -qx t

"${PSQL[@]}" -Atc "
SELECT count(*) = 6
FROM pg_db_role_setting setting
JOIN pg_roles role ON role.oid = setting.setrole
CROSS JOIN LATERAL unnest(setting.setconfig) configuration
WHERE role.rolname IN (
  'migration_owner', 'application_writer', 'pipeline_writer',
  'analytics_reader', 'report_reader', 'audit_reader'
)
AND configuration LIKE 'search_path=pg_catalog, %';
" | grep -qx t

"${PSQL[@]}" -Atc "
SELECT count(*) = 4
FROM pg_namespace namespace
JOIN pg_roles owner ON owner.oid = namespace.nspowner
WHERE namespace.nspname IN ('canopyledger', 'analytics', 'reporting', 'audit')
AND owner.rolname = 'migration_owner';
" | grep -qx t

"${PSQL[@]}" -c "
SET ROLE migration_owner;
DROP TABLE IF EXISTS canopyledger.role_probe;
DROP TABLE IF EXISTS analytics.role_probe;
DROP TABLE IF EXISTS reporting.role_probe;
DROP TABLE IF EXISTS audit.role_probe;
CREATE TABLE canopyledger.role_probe (id integer PRIMARY KEY);
CREATE TABLE analytics.role_probe (id integer PRIMARY KEY);
CREATE TABLE reporting.role_probe (id integer PRIMARY KEY);
CREATE TABLE audit.role_probe (id integer PRIMARY KEY);
RESET ROLE;
"

expect_denied() {
  local sql="$1"
  if "${PSQL[@]}" -c "${sql}" >/dev/null 2>&1; then
    echo "expected permission denial: ${sql}" >&2
    return 1
  fi
}

"${PSQL[@]}" -c "SET ROLE analytics_reader; SELECT * FROM analytics.role_probe;"
"${PSQL[@]}" -c "SET ROLE report_reader; SELECT * FROM reporting.role_probe;"
"${PSQL[@]}" -c "SET ROLE audit_reader; SELECT * FROM audit.role_probe;"

expect_denied "SET ROLE analytics_reader; SELECT * FROM reporting.role_probe;"
expect_denied "SET ROLE report_reader; SELECT * FROM audit.role_probe;"
expect_denied "SET ROLE audit_reader; SELECT * FROM analytics.role_probe;"
expect_denied "SET ROLE analytics_reader; INSERT INTO analytics.role_probe VALUES (1);"
expect_denied "SET ROLE application_writer; CREATE TABLE canopyledger.denied (id integer);"
expect_denied "SET ROLE pipeline_writer; CREATE TABLE canopyledger.denied (id integer);"
expect_denied "SET ROLE application_writer; CREATE TEMP TABLE denied (id integer);"

"${PSQL[@]}" -Atc "
SELECT count(*) = 0
FROM pg_class relation
JOIN pg_roles owner ON owner.oid = relation.relowner
WHERE owner.rolname IN (
  'application_writer', 'pipeline_writer', 'analytics_reader', 'report_reader', 'audit_reader'
);
" | grep -qx t
