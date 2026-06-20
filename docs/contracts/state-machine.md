# State Machine Contract v1

## Decision-cycle states

```text
DRAFT -> FREEZING -> FROZEN -> CALCULATING
      -> RECOMMENDATION_READY -> AWAITING_APPROVAL
      -> APPROVED -> REPORTED
```

Terminal/alternate states: `FREEZE_REJECTED`, `CALCULATION_FAILED`, `REJECTED`, `SUPERSEDED`.

## Normative transitions

| From | Command | To | Required conditions |
|---|---|---|---|
| DRAFT | freeze | FREEZING | Strong ETag matches; idempotency accepted |
| FREEZING | freeze accepted | FROZEN | Critical validation passes; bundles pinned; manifest committed |
| FREEZING | freeze rejected | FREEZE_REJECTED | Structured errors persisted; no snapshot published |
| FROZEN | start pipeline | CALCULATING | Pipeline definition approved |
| CALCULATING | publish all required stages | RECOMMENDATION_READY | Every required output immutable and successful |
| RECOMMENDATION_READY | request approval | AWAITING_APPROVAL | Recommendation immutable |
| AWAITING_APPROVAL | approve | APPROVED | Authenticated independent human approver |
| AWAITING_APPROVAL | reject | REJECTED | Reason required |
| APPROVED | render current package | REPORTED | Decision is active for cycle |
| APPROVED/REPORTED | supersede | SUPERSEDED | New final decision created; history retained |

No state is inferred by timestamp ordering. Invalid transitions fail with problem code `INVALID_STATE_TRANSITION`.

