# Reports and audit packages

CanopyLedger creates an audit-ready decision package from one frozen facility snapshot and its
published results. A package includes a machine-readable `ReportModel`, plus HTML and PDF views for
people. The JSON model is the source of truth; the HTML and PDF are faithful renderings, not inputs to
any calculation.

## What a report contains

The report keeps the following values distinct so that a reader can understand both the contractual
position and the risk view:

- contractual borrowing base (CBB) and contractual availability;
- hedge and liquidity assessment;
- scenario results and internal risk capacity (IRC);
- recommendation, conditions, approval, override, and final decision context; and
- snapshot, bundle, output, renderer, font, and artifact digests needed for audit and replay.

Climate and EUDR fields describe the readiness and lineage of supplied evidence. They are not a legal
compliance or deforestation-free certification. Credit early-warning output is advisory and does not
change CBB, IRC, or a human decision.

## Create and view a report

Only a current, approved final decision can produce an official report. Create a package through the
API, then retrieve the package metadata or one of its immutable artifacts:

```text
POST /api/v1/decisions/{decision_id}/reports
GET  /api/v1/decisions/{decision_id}/reports
GET  /api/v1/reports/{report_id}/artifacts/{HTML|PDF}
```

In the web application, open the facility's **Reports** workspace after selecting its frozen snapshot.
The workspace displays API-issued package status, lineage, digests, and artifact links. It does not
recalculate values in the browser.

## Reproducibility and status

An official package is marked `CURRENT_OFFICIAL` only when its final decision is approved and has not
been superseded. Retained prior packages are marked `HISTORICAL_AUDIT`; they remain available for
audit but are never presented as the current decision.

To make rendering repeatable, every package records its template, renderer, locale, timezone, and font
digest. Rendering stops if a required font is missing or does not match its digest. Canonical replay
compares the report-model digest; byte-for-byte PDF replay also requires the recorded renderer
environment. See [the demo guide](../DEMO.md) for a runnable synthetic package.
