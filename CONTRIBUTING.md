# Contributing

Thanks for improving CanopyLedger. This repository is a synthetic reference implementation, so please
do not include real borrower, farmer, market, trading, document, or credential data in an issue, pull
request, fixture, or test.

Before opening a pull request, read the [versioned API contract](docs/api/openapi-v1.json) when it
applies and preserve the project's core boundaries: frozen snapshots are immutable, calculations are
deterministic, CBB and IRC are separate, and final decisions require authorized human approval.

Requirements:

1. Add a failing behavior test before changing behavior.
2. Document public API or contract changes in the relevant public documentation.
3. Run `make verify` before opening a pull request. Run `make test-postgres` when changing
   persistence, migrations, roles, or durable workflow behavior.
4. Keep authoritative calculations on the server. Browser code may format and display issued values,
   but must not recalculate CBB, IRC, hedge, scenario, recommendation, or decision values.
5. For report changes, demonstrate canonical replay, missing-font failure, normalized metadata, and
   enforcement that only a current approved final decision can produce an official report.

Use the [demo guide](DEMO.md) to exercise the synthetic application and
[the security policy](SECURITY.md) to report vulnerabilities safely.
