# Document Intelligence Contract v1

## Authority boundary

Document parsing and optional extractor adapters return `candidate` facts only. Neither an
extraction confidence score, a deterministic reconciliation result, nor an extraction benchmark
can approve, supersede, freeze, calculate, or alter an authoritative value. Human review through
the evidence lifecycle remains the only promotion path.

## Supported classification catalog

The deterministic classifier recognizes warehouse receipts, inventory statements, purchase
contracts, sales invoices, receivables aging reports, borrower financial statements, insurance
certificates, inspection reports, origin/traceability declarations, hedge statements, and facility
notices. Known text templates have deterministic parsers. Other recognized or unknown documents
may remain candidate-free and are available for human review or a deployment-configured extractor
adapter.

## Security and isolation

- Original bytes remain immutable M2 evidence records.
- Parser inputs are bounded to 5 MiB and 100 PDF pages.
- ZIP/gzip/RAR archives, encrypted PDFs, invalid signatures, malformed PDFs, non-UTF-8 text, and
  unsupported content types are rejected before extraction.
- PDF text is decoded through a bounded `pypdf` reader; the application never executes PDF actions,
  scripts, embedded instructions, or document content.
- The parser and optional adapter interface have no database, shell, network, approval, or
  authoritative-calculation capability.

## Provenance and reconciliation

Every extraction records its source document version/byte digest, request digest, classification
method/version, extractor version, text digest, completion time, and candidate-to-run confidence.
Candidate quantity reconciliation is explicitly advisory (`blocks_freeze=false`); M2 approved-fact
reconciliation remains the only freeze-relevant evidence control.

## Benchmark

`uv run python scripts/run_document_extraction_benchmark.py` produces deterministic JSON for the
checked-in known-template benchmark. The benchmark measures classification accuracy and candidate
fact-type exactness; it never uses approval state.
