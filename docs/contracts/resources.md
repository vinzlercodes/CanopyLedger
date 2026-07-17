# Resource Model v1

## Mutable aggregates

- `FacilityWorkingState`, versioned by integer and strong ETag.
- Draft lots, receivables, documents, candidate facts, mappings, and corrections.

## Immutable inputs

- `FacilitySnapshot`, `SnapshotManifest`, `SnapshotInputReference`.
- `MarketSnapshot`, `PolicyBundle`, `ComputationBundle`.

## Immutable outputs

- `CollateralValuationRun`.
- `InventoryEligibilityAssessment`.
- `ReceivablesEligibilityAssessment`.
- `ContractualReserveAssessment`.
- `ContractualBorrowingBaseAssessment`.
- `HedgeExposureAssessment`, `LiquidityAssessment`, `ScenarioAssessment`.
- `InternalRiskCapacityAssessment`.
- `DecisionRecommendation`, `ApprovalAction`, `DecisionOverride`, `FinalDecision`.
- `ReportModel`, `ReportArtifact`.
- `DocumentExtraction` and `CandidateFactExtractionProvenance`. Extraction records source-byte
  digest, classification/parser/extractor versions, text digest, advisory reconciliation state, and
  candidate-only confidence. They never carry approval authority.
- `AgentRun`, `TaskPlan`, `AgentTask`, `ToolCallRecord`, `ToolResultRecord`, `HandoffRecord`, and
  `TraceEvent`. Agent records retain planner/version, resolved principal, typed tool inputs and
  output digests, authorization outcome, retry identity, and human-routing context. They are
  immutable audit records and cannot represent a credit approval or evidence promotion.

## Operational integrity

- `PipelineRun`, `PipelineStage`, `PipelineStageAttempt`, `PipelineStageOutput`.
- `OutboxMessage`, `InboxReceipt`, `IdempotencyRecord`, `IdempotencyTombstone`, `AuditEvent`.

IDs use a lowercase resource prefix plus UUIDv7. All immutable resources include canonical digest and parent references.
