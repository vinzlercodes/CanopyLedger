# Release verification — v0.1.0

This release was verified with the following checks:

- [x] Python linting, strict typing, unit and API tests, OpenAPI and generated-client drift checks,
  TypeScript type and contract tests, web SSR tests, production build, package build, and a fresh
  PostgreSQL/PostGIS integration suite. Evidence: 446 Python pass/47 expected database skips; 48 fresh
  PostGIS pass; 14 TypeScript contract tests; 14 web unit tests; 5 SSR tests; source and wheel builds
  pass.
- [x] Canonical report replay, normalized render metadata, missing-font failure, superseded-decision,
  and non-final-decision tests. Evidence: `tests/test_reporting.py` and durable report acceptance pass.
- [x] `make demo-verify` was run and the report-model and artifact digests retained as release evidence.
  Model `sha256:043123f7663e61fe3a08201fd9d548804e764c4df2b3fae2b9f4bd3336ce5708`; HTML
  `sha256:98e1a5c09937d93de3f292cc50076e852b9f71a8942f822564faf4863febd782`; PDF
  `sha256:593636bfae90fa2ae56621ba28089397c7524b7fb76ba9981697e3116f614ca9`.
- [x] Verify Apache-2.0 license, `SECURITY.md`, `CONTRIBUTING.md`, checked-in credit model card, data
  card, release notes, and this checklist are included in the source archive. Python and web dependency
  audits report no known/high vulnerabilities.
- [x] Verify migration upgrade, Alembic drift, rollback review, and forward-recovery/backup procedure
  against a disposable PostgreSQL 17/PostGIS database. Evidence: `make test-postgres` migration,
  drift, role, and 48-marker gate pass.
- [x] The reviewed release commit is tagged `v0.1.0`.

Release packages must not contain real borrower, market, farmer, or credential data.
