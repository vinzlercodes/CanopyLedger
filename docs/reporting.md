# Canonical reporting

The M10 source of truth is `ReportModel` canonical JSON. It is compiled only from a frozen
snapshot, published stage outputs, a recommendation, and the current approved final decision.
HTML and PDF are deterministic renderings of that model, never calculation inputs.

`CURRENT_OFFICIAL` requires an approved, non-superseded final decision. `HISTORICAL_AUDIT`
identifies a retained historical package and is never presented as the current official package.

The compiler keeps contractual borrowing base, contractual availability, internal risk capacity,
recommended incremental draw, and final decision context as separate fields. Renderers pin template,
renderer, locale, timezone, and font digest; missing or digest-mismatched fonts fail closed. Renderer
metadata is normalized to the Unix epoch. A canonical replay therefore compares report-model digests,
while byte-level PDF replay additionally requires the declared renderer environment.

The API exposes report packages at `POST /api/v1/decisions/{id}/reports` and immutable artifact bytes
at `GET /api/v1/reports/{id}/artifacts/{format}`. The Reports UI only displays API-issued package
data and never generates an authoritative report from browser state.
