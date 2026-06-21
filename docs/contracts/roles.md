# Role and Privilege Matrix v1

| Role | Mutable facility data | Immutable outputs | Approve | Query analytics | Render reports |
|---|---|---|---|---|---|
| Analyst | Read/write permitted scope | Read | No | Yes | Draft only |
| Credit approver | Read | Read | Yes, subject to separation | Yes | Current official |
| Auditor | Read | Read | No | Yes | Historical audit |
| Pipeline worker | No | Insert via fenced publication | No | No | No |
| Report worker | Read approved package only | Insert report artifacts | No | No | Yes |
| Analytics reader DB role | Curated views only | Curated views only | No | Read only | No |

No self-approval. Override requires two distinct policy-qualified approvers. Runtime DB roles own no objects.

## Database capability roles

| Role | Schema access | Default object privileges |
|---|---|---|
| `migration_owner` | Owns `canopyledger`, `analytics`, `reporting`, and `audit` | Owns migration-created objects |
| `application_writer` | `USAGE` on `canopyledger` | None; M1A migrations grant mutable-table privileges explicitly |
| `pipeline_writer` | `USAGE` on `canopyledger` | None; M1A migrations grant fenced publication privileges explicitly |
| `analytics_reader` | `USAGE` on `analytics` | `SELECT` on migration-owner tables/views created there |
| `report_reader` | `USAGE` on `reporting` | `SELECT` on migration-owner tables/views created there |
| `audit_reader` | `USAGE` on `audit` | `SELECT` on migration-owner tables/views created there |

Capability roles are `NOLOGIN`, `NOSUPERUSER`, `NOCREATEDB`, `NOCREATEROLE`, `NOINHERIT`,
`NOREPLICATION`, and `NOBYPASSRLS`. Deployments create separate login principals, grant only the
required capability membership, and apply the same fixed `pg_catalog`-first search path. Public
schema creation, public database temporary-object creation, and public routine execution defaults
are revoked by `database/bootstrap/roles.sql`.
