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

## Operational integrity

- `PipelineRun`, `PipelineStage`, `PipelineStageAttempt`, `PipelineStageOutput`.
- `OutboxMessage`, `InboxReceipt`, `IdempotencyRecord`, `IdempotencyTombstone`, `AuditEvent`.

IDs use a lowercase resource prefix plus UUIDv7. All immutable resources include canonical digest and parent references.
