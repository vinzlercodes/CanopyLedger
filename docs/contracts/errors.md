# API Error Catalog v1

Responses use `application/problem+json` with `type`, `title`, `status`, `detail`, `instance`, `code`, `trace_id`, and optional typed `errors`.

| Code | HTTP | Meaning |
|---|---:|---|
| PRECONDITION_REQUIRED | 428 | Required `If-Match` absent |
| PRECONDITION_FAILED | 412 | Strong ETag mismatch |
| IDEMPOTENCY_KEY_REUSED | 409 | Key scope exists with different fingerprint |
| IDEMPOTENCY_IN_PROGRESS | 409 | Matching command scope is currently owned by an unfinished request |
| FREEZE_REJECTED | 422 | Semantically valid request failed critical validation |
| INVALID_STATE_TRANSITION | 409 | Command invalid for resource state |
| RESOURCE_NOT_FOUND | 404 | Resource absent or invisible to principal |
| FORBIDDEN | 403 | Principal lacks capability |
| VALIDATION_FAILED | 422 | Typed field/domain validation errors |
| DOCUMENT_PROCESSING_REJECTED | 422 | Document is unsafe, malformed, encrypted, oversized, archived, or unsupported for bounded extraction |
| STAGE_PUBLICATION_FENCED | 409 | Attempt lost lease or epoch |
| QUERY_REJECTED | 422 | Analytics query violates semantic/SQL policy |
| AGENT_CAPABILITY_DENIED | 403 | Agent capability is absent from the code-owned registry or denied to its resolved principal |
| AGENT_RUN_FAILED | 422 | A registry-authorized typed tool failed; the immutable run trace records the sanitized failure |
