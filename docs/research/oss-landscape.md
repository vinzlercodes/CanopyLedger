# OSS Landscape Evidence Review

**Reviewed:** 2026-06-21

**Decision scope:** M0 architecture and dependency choices

**Outcome:** No unresolved material research contradiction.

## Method

The review used upstream project repositories, documentation, and license statements. Each project
was assessed for direct product overlap, reusable implementation or validation ideas, licensing,
and whether adoption would weaken CanopyLedger's immutable snapshots, deterministic calculation
authority, independent CBB/IRC semantics, or human approval boundary.

## Findings

| Project | Upstream scope and license | CanopyLedger overlap | Decision |
|---|---|---|---|
| [Apache Fineract](https://github.com/apache/fineract) | Apache-2.0 core-banking and lending platform | Loan accounts, APIs, permissions, and audit patterns; it does not provide CanopyLedger's evidence-frozen commodity borrowing-base decision cycle | Reference API and authorization patterns; do not adopt as the domain or persistence core |
| [OpenGamma Strata](https://github.com/OpenGamma/Strata) | Apache-2.0 Java market-risk analytics library | Market data, product models, pricing, and risk measures overlap later hedge work | Use as an independent reference candidate for M3 validation; do not add a Java runtime dependency |
| [QuantLib](https://www.quantlib.org/) | Modified BSD quantitative-finance library | Option and market-risk calculations overlap M3 | Use as an independent CI/reference comparison where appropriate; never as the sole untested authority |
| [OpenLineage](https://github.com/OpenLineage/OpenLineage) | Apache-2.0 standard for job and dataset lineage metadata | Run, job, dataset, and facet concepts overlap pipeline observability | Reference vocabulary and interoperability ideas; retain CanopyLedger's content-addressed financial lineage as authoritative |
| [Evidently](https://github.com/evidentlyai/evidently) | Apache-2.0 ML/LLM evaluation and observability framework | Evaluation, drift, and monitoring overlap the later M6 advisory model | Reassess as an optional M6 evaluation dependency; it cannot define calculations, policy, or decisions |
| [Hyperledger FireFly](https://github.com/hyperledger/firefly) | Apache-2.0 multiparty/Web3 application stack | Shared data flows, identities, events, and document exchange partially overlap workflow infrastructure | Reject for v1: blockchain and multiparty consensus conflict with the single-bank modular-monolith scope and add no required authority control |

## Architectural conclusion

No reviewed project supplies the complete CanopyLedger contract:

```text
mutable working facility
-> immutable bundle-pinned snapshot
-> deterministic CBB
-> separately typed IRC
-> immutable recommendation
-> authorized human final decision
-> reproducible official report
```

The review supports selective use of independent quantitative references and established lineage,
evaluation, API, and authorization patterns. It does not justify replacing the domain model,
outsourcing authoritative financial calculations, merging CBB with IRC, introducing blockchain,
or delegating approval authority to a model or workflow engine.
