# State Machine Contract v1

## Decision-cycle states

```text
DRAFT -> FREEZING -> FROZEN -> CALCULATING
      -> RECOMMENDATION_READY -> AWAITING_APPROVAL
      -> APPROVED -> REPORTED
```

Terminal/alternate states: `FREEZE_REJECTED`, `CALCULATION_FAILED`, `REJECTED`, `SUPERSEDED`.

## Normative transitions

| From | Event | Command | To | Required conditions |
|---|---|---|---|---|
| DRAFT | `FREEZE_REQUESTED` | freeze | FREEZING | Strong ETag matches; idempotency accepted |
| FREEZING | `FREEZE_ACCEPTED` | freeze accepted | FROZEN | Critical validation passes; bundles pinned; manifest committed |
| FREEZING | `FREEZE_REJECTED` | freeze rejected | FREEZE_REJECTED | Structured errors persisted; no snapshot published |
| FROZEN | `PIPELINE_STARTED` | start pipeline | CALCULATING | Pipeline definition approved |
| CALCULATING | `REQUIRED_STAGES_PUBLISHED` | publish all required stages | RECOMMENDATION_READY | Every required output immutable and successful |
| RECOMMENDATION_READY | `APPROVAL_REQUESTED` | request approval | AWAITING_APPROVAL | Recommendation immutable |
| AWAITING_APPROVAL | `APPROVED` | approve | APPROVED | Authenticated independent human approver |
| AWAITING_APPROVAL | `REJECTED` | reject | REJECTED | Reason required |
| APPROVED | `PACKAGE_RENDERED` | render current package | REPORTED | Decision is active for cycle |
| APPROVED | `SUPERSEDED` | supersede | SUPERSEDED | New final decision created; history retained |
| REPORTED | `SUPERSEDED` | supersede | SUPERSEDED | New final decision created; history retained |

The application validates required conditions before emitting an event. The pure domain transition
function accepts only the event identifiers above. No state is inferred by timestamp ordering, and
every unlisted state/event pair fails with problem code `INVALID_STATE_TRANSITION`.
