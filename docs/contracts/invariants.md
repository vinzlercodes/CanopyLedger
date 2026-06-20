# Architecture Invariant Catalog v1

| ID | Invariant |
|---|---|
| INV-001 | Frozen snapshot is immutable. |
| INV-002 | Snapshot pins exactly one market, policy, and computation bundle. |
| INV-003 | Stage output references one frozen snapshot and computation bundle. |
| INV-004 | Published stage output cannot update or delete. |
| INV-005 | Recommendation requires every policy-required stage output. |
| INV-006 | Final decision requires authenticated human approval. |
| INV-007 | Override never mutates recommendation. |
| INV-008 | Official report never reads mutable working data. |
| INV-009 | CBB and IRC remain independent uncapped resources. |
| INV-010 | Recommended exposure cap records every compared limit and binding constraint. |
| INV-011 | Copilot cannot access operational write tables. |
| INV-012 | Model output cannot affect authoritative values except approved M6 statistical signal inputs explicitly permitted by policy. |
| INV-013 | Agent cannot approve, override, or expand its capabilities. |
| INV-014 | Idempotency key reused with changed fingerprint fails. |
| INV-015 | Failed/stale stage attempt cannot publish output. |
| INV-016 | Stale/missing precondition cannot mutate versioned aggregate. |
| INV-017 | Every published calculation stores input, output, and computation digests. |
| INV-018 | Canonical replay produces matching digests inside declared envelope. |
| INV-019 | At most one non-superseded final decision exists per decision cycle. |
| INV-020 | Candidate evidence cannot satisfy an approved-fact requirement. |

