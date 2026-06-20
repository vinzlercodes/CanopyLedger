# Version Bundle Schemas v1

## Market bundle

Prices, FX, freight, rates, volatility, margin assumptions, observation/source metadata, digest.

## Policy bundle

Eligibility rules, advance rates, reserves, thresholds, covenants, internal overlays, decision rules, critical-fact definitions, approval policy, effective dates, digest.

Typed Python defines safe rule primitives. YAML supplies validated parameters and cannot execute arbitrary expressions.

## Computation bundle

Engine versions, unit table, calculation contracts, dependency-lock digest, runtime image digest, PRNG/seed policy, float envelope, optional governed M6 artifact digests.

Copilot/agent provider versions are logged separately and never alter authoritative snapshot or financial digests.

