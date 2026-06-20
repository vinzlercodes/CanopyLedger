# Calculation Contracts v1

## Numeric policy

- Money: `NUMERIC(24,6)` persistence; output scale declared by contract.
- Quantity: `NUMERIC(24,8)` with controlled unit.
- Rate: `NUMERIC(18,12)`.
- Default rounding: half-even at explicit final stage; intermediate scale declared per calculation.
- Authoritative decimal calculations reject NaN, infinity, and negative zero.

## CBB

Contractual eligibility, advance rates, reserves, facility limit, and sublimits only. No informal caution, LLM/agent opinion, or unapproved model overlay.

## IRC

Independent internal risk capacity. It may use hedge/liquidity/scenario/data/credit overlays approved by internal policy. Its uncapped result is retained even when above CBB.

## Decision comparison

Compare commitment, CBB, IRC, liquidity cap, and policy caps without mutating source assessments. Record binding constraint and safe additional draw after outstanding and approved-unfunded exposure.

## Option models

Black-76 is European reference. Authoritative American valuation uses futures-adapted recombining lattice with contract-specific exercise/settlement/calendar rules.

