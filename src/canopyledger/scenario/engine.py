"""Deterministic scenario, Monte Carlo, and IRC calculations for M4A."""

from __future__ import annotations

import math
import random
import re
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

from canopyledger.domain.money import Money
from canopyledger.integrity.canonical import canonical_json_bytes, domain_digest
from canopyledger.integrity.snapshot import RESOURCE_ID_PATTERN


class ScenarioCapacityError(ValueError):
    """Raised when a scenario-capacity input violates its frozen contract."""


@dataclass(frozen=True)
class ScenarioDefinition:
    scenario_id: str
    family: str
    price_shock: Decimal
    cbb_haircut: Decimal
    margin_multiplier: Decimal
    added_reserve: Decimal

    def __post_init__(self) -> None:
        if not self.scenario_id or not self.family:
            raise ScenarioCapacityError("scenario ID and family are required")
        if not all(value.is_finite() for value in self.values()):
            raise ScenarioCapacityError("scenario shock values must be finite")
        if self.cbb_haircut < 0 or self.margin_multiplier < 0 or self.added_reserve < 0:
            raise ScenarioCapacityError(
                "scenario haircuts, margin multiplier, and reserves cannot be negative"
            )

    def values(self) -> tuple[Decimal, ...]:
        return (self.price_shock, self.cbb_haircut, self.margin_multiplier, self.added_reserve)

    def to_canonical_dict(self) -> dict[str, str]:
        return {
            "scenario_id": self.scenario_id,
            "family": self.family,
            "price_shock": _decimal(self.price_shock),
            "cbb_haircut": _decimal(self.cbb_haircut),
            "margin_multiplier": _decimal(self.margin_multiplier),
            "added_reserve": _decimal(self.added_reserve),
        }


@dataclass(frozen=True)
class IrcPolicy:
    tail_loss_multiplier: Decimal = Decimal("1")
    liquidity_multiplier: Decimal = Decimal("1")
    counterparty_buffer: Decimal = Decimal("0")
    climate_evidence_buffer: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if not all(value.is_finite() and value >= 0 for value in self.values()):
            raise ScenarioCapacityError("IRC policy buffers must be finite and non-negative")

    def values(self) -> tuple[Decimal, ...]:
        return (
            self.tail_loss_multiplier,
            self.liquidity_multiplier,
            self.counterparty_buffer,
            self.climate_evidence_buffer,
        )

    def to_canonical_dict(self) -> dict[str, str]:
        return {
            "tail_loss_multiplier": _decimal(self.tail_loss_multiplier),
            "liquidity_multiplier": _decimal(self.liquidity_multiplier),
            "counterparty_buffer": _decimal(self.counterparty_buffer),
            "climate_evidence_buffer": _decimal(self.climate_evidence_buffer),
        }


@dataclass(frozen=True)
class ScenarioCapacityInput:
    assessment_id: str
    snapshot_id: str
    cbb_output_digest: str
    hedge_liquidity_output_digest: str
    market_bundle_digest: str
    policy_bundle_digest: str
    computation_bundle_digest: str
    scenario_version: str
    prng_family: str
    seed: int
    path_count: int
    time_steps: int
    thread_count: int
    confidence_level: Decimal
    quantization_scale: Decimal
    correlation: Decimal
    cbb: Money
    facility_commitment: Money
    outstanding_exposure: Money
    base_margin_call: Money
    available_liquidity: Money
    price_volatility: Decimal
    margin_volatility: Decimal
    scenarios: tuple[ScenarioDefinition, ...]
    irc_policy: IrcPolicy
    hedge_effectiveness: Decimal = Decimal("0")
    seed_derivation: str = "snapshot-scenario-v1"
    distribution_assumption: str = "standard_normal"
    regime_mixture: tuple[tuple[str, Decimal], ...] = (("base", Decimal("1")),)

    def __post_init__(self) -> None:
        if re.fullmatch(
            RESOURCE_ID_PATTERN, self.assessment_id
        ) is None or not self.assessment_id.startswith("scn_"):
            raise ScenarioCapacityError("scenario assessment ID must be an scn UUIDv7")
        if re.fullmatch(
            RESOURCE_ID_PATTERN, self.snapshot_id
        ) is None or not self.snapshot_id.startswith("snp_"):
            raise ScenarioCapacityError("snapshot ID must be an snp UUIDv7")
        if self.prng_family != "python-mt19937-v1":
            raise ScenarioCapacityError("M4A requires pinned python-mt19937-v1 PRNG")
        if not self.seed_derivation:
            raise ScenarioCapacityError("seed derivation identifier is required")
        if self.distribution_assumption != "standard_normal":
            raise ScenarioCapacityError("M4A supports only the pinned standard_normal distribution")
        if (
            not self.regime_mixture
            or len({name for name, _ in self.regime_mixture}) != len(self.regime_mixture)
            or any(
                not name or not weight.is_finite() or weight <= 0
                for name, weight in self.regime_mixture
            )
            or sum((weight for _, weight in self.regime_mixture), Decimal(0)) != Decimal(1)
        ):
            raise ScenarioCapacityError(
                "regime mixture must have unique positive weights summing to one"
            )
        if self.path_count < 100 or self.time_steps < 1 or self.thread_count != 1:
            raise ScenarioCapacityError(
                "path count >= 100, positive steps, and one pinned thread are required"
            )
        if not Decimal("0") < self.confidence_level < Decimal("1"):
            raise ScenarioCapacityError("confidence level must be between zero and one")
        if self.quantization_scale <= 0 or not self.quantization_scale.is_finite():
            raise ScenarioCapacityError("quantization scale must be finite and positive")
        if not self.correlation.is_finite() or abs(self.correlation) > 1:
            raise ScenarioCapacityError("correlation must be between -1 and 1")
        if not self.price_volatility.is_finite() or not self.margin_volatility.is_finite():
            raise ScenarioCapacityError("volatilities must be finite")
        if self.price_volatility < 0 or self.margin_volatility < 0:
            raise ScenarioCapacityError("volatilities cannot be negative")
        if (
            not self.hedge_effectiveness.is_finite()
            or self.hedge_effectiveness < 0
            or self.hedge_effectiveness > 1
        ):
            raise ScenarioCapacityError("hedge effectiveness must be between zero and one")
        if not self.scenarios or len({item.scenario_id for item in self.scenarios}) != len(
            self.scenarios
        ):
            raise ScenarioCapacityError("at least one uniquely identified scenario is required")
        if not all(digest.startswith("sha256:") for digest in self.digests()):
            raise ScenarioCapacityError("all lineage references must be SHA-256 digests")
        amounts = (
            self.cbb,
            self.facility_commitment,
            self.outstanding_exposure,
            self.base_margin_call,
            self.available_liquidity,
        )
        if len({item.currency for item in amounts}) != 1 or any(
            item.amount < 0 for item in amounts
        ):
            raise ScenarioCapacityError("M4A amounts must share a currency and be non-negative")

    def digests(self) -> tuple[str, ...]:
        return (
            self.cbb_output_digest,
            self.hedge_liquidity_output_digest,
            self.market_bundle_digest,
            self.policy_bundle_digest,
            self.computation_bundle_digest,
        )

    def to_input_canonical_dict(self) -> dict[str, Any]:
        return {
            "scenario_version": self.scenario_version,
            "prng_family": self.prng_family,
            "seed_derivation": self.seed_derivation,
            "distribution_assumption": self.distribution_assumption,
            "regime_mixture": [
                {"name": name, "weight": _decimal(weight)} for name, weight in self.regime_mixture
            ],
            "seed": self.seed,
            "path_count": self.path_count,
            "time_steps": self.time_steps,
            "thread_count": self.thread_count,
            "confidence_level": _decimal(self.confidence_level),
            "quantization_scale": _decimal(self.quantization_scale),
            "correlation": _decimal(self.correlation),
            "correlation_matrix": [
                ["1", _decimal(self.correlation)],
                [_decimal(self.correlation), "1"],
            ],
            "price_volatility": _decimal(self.price_volatility),
            "margin_volatility": _decimal(self.margin_volatility),
            "scenarios": [item.to_canonical_dict() for item in self.scenarios],
            "irc_policy": self.irc_policy.to_canonical_dict(),
        }

    def market_bundle_payload(self) -> dict[str, str | list[list[str]]]:
        return {
            "price_volatility": _decimal(self.price_volatility),
            "margin_volatility": _decimal(self.margin_volatility),
            "correlation_matrix": [
                ["1", _decimal(self.correlation)],
                [_decimal(self.correlation), "1"],
            ],
        }

    def policy_bundle_payload(self) -> dict[str, Any]:
        return {
            "scenario_version": self.scenario_version,
            "scenarios": [item.to_canonical_dict() for item in self.scenarios],
            "irc_policy": self.irc_policy.to_canonical_dict(),
        }

    def computation_bundle_payload(self) -> dict[str, Any]:
        return {
            "prng_family": self.prng_family,
            "seed_derivation": self.seed_derivation,
            "path_count": self.path_count,
            "time_steps": self.time_steps,
            "thread_count": self.thread_count,
            "distribution_assumption": self.distribution_assumption,
            "regime_mixture": [
                {"name": name, "weight": _decimal(weight)} for name, weight in self.regime_mixture
            ],
            "quantization_scale": _decimal(self.quantization_scale),
        }

    @property
    def input_digest(self) -> str:
        return domain_digest(
            "scenario_capacity_input", 1, canonical_json_bytes(self.to_input_canonical_dict())
        )


@dataclass(frozen=True)
class ScenarioCapacityAssessment:
    assessment_id: str
    snapshot_id: str
    result: dict[str, Any]
    reason_codes: tuple[str, ...]
    output_digest: str

    def to_canonical_dict(self) -> dict[str, Any]:
        return {
            "assessment_id": self.assessment_id,
            "snapshot_id": self.snapshot_id,
            "result": self.result,
            "reason_codes": list(self.reason_codes),
            "output_digest": self.output_digest,
        }


@dataclass(frozen=True)
class CompiledShock:
    """Scenario shock after policy ordering and decimal quantization are fixed."""

    scenario_id: str
    family: str
    collateral_loss: Decimal
    margin_multiplier: Decimal


@dataclass(frozen=True)
class _MonteCarloPath:
    loss: Decimal
    collateral_loss: Decimal
    liquidity_shortfall: Decimal
    deficiency: Decimal
    hedge_effectiveness: Decimal


def evaluate_scenario_capacity(value: ScenarioCapacityInput) -> ScenarioCapacityAssessment:
    """Compute deterministic scenarios, pinned Monte Carlo metrics, and separate IRC."""
    quantum = value.quantization_scale
    deterministic = [
        _deterministic_scenario(value, scenario, quantum) for scenario in value.scenarios
    ]
    paths = _monte_carlo(value, quantum)
    paths.sort(key=lambda path: path.loss)
    var_index = _quantile_index(value.confidence_level, len(paths))
    var = paths[var_index].loss
    tail = paths[var_index:]
    expected_shortfall = _q(
        sum((path.loss for path in tail), Decimal(0)) / Decimal(len(tail)), quantum
    )
    expected_liquidity_shortfall = _q(
        sum((path.liquidity_shortfall for path in paths), Decimal(0)) / Decimal(len(paths)),
        quantum,
    )
    threshold_stability = _threshold_stability(paths, value.confidence_level, quantum)
    tail_collateral_loss = sum((path.collateral_loss for path in tail), Decimal(0))
    tail_liquidity_shortfall = sum((path.liquidity_shortfall for path in tail), Decimal(0))
    tail_total_loss = sum((path.loss for path in tail), Decimal(0))
    risk_buffer = _q(
        expected_shortfall * value.irc_policy.tail_loss_multiplier
        + expected_liquidity_shortfall * value.irc_policy.liquidity_multiplier
        + value.irc_policy.counterparty_buffer
        + value.irc_policy.climate_evidence_buffer,
        quantum,
    )
    uncapped_irc = _q(max(Decimal(0), value.cbb.amount - risk_buffer), quantum)
    irc = _q(min(value.cbb.amount, value.facility_commitment.amount, uncapped_irc), quantum)
    result: dict[str, Any] = {
        "currency": value.cbb.currency,
        "scenario_version": value.scenario_version,
        "monte_carlo": {
            "prng_family": value.prng_family,
            "seed_derivation": value.seed_derivation,
            "distribution_assumption": value.distribution_assumption,
            "regime_mixture": [
                {"name": name, "weight": _decimal(weight)} for name, weight in value.regime_mixture
            ],
            "seed": value.seed,
            "path_count": value.path_count,
            "time_steps": value.time_steps,
            "thread_count": value.thread_count,
            "confidence_level": _decimal(value.confidence_level),
            "correlation": _decimal(value.correlation),
            "correlation_matrix": [
                ["1", _decimal(value.correlation)],
                [_decimal(value.correlation), "1"],
            ],
            "value_at_risk": _money(var),
            "expected_shortfall": _money(expected_shortfall),
            "cbb_deficiency_probability": _probability(
                [path.deficiency for path in paths], value.path_count
            ),
            "margin_liquidity_shortfall_probability": _probability(
                sum(1 for path in paths if path.liquidity_shortfall > 0), value.path_count
            ),
            "expected_collateral_shortfall": _money(
                sum((path.deficiency for path in paths), Decimal(0)) / Decimal(value.path_count)
            ),
            "expected_margin_liquidity_shortfall": _money(expected_liquidity_shortfall),
            "threshold_stability": threshold_stability,
            "tail_contribution_by_factor": {
                "collateral_price": _ratio(tail_collateral_loss, tail_total_loss),
                "margin_liquidity": _ratio(tail_liquidity_shortfall, tail_total_loss),
            },
            "hedge_effectiveness_distribution": _distribution(
                [path.hedge_effectiveness for path in paths]
            ),
        },
        "deterministic_scenarios": deterministic,
        "worst_scenario_families": _worst_scenario_families(deterministic),
        "internal_risk_capacity": {
            "risk_buffer": _money(risk_buffer),
            "tail_loss_buffer": _money(
                _q(expected_shortfall * value.irc_policy.tail_loss_multiplier, quantum)
            ),
            "liquidity_buffer": _money(
                _q(expected_liquidity_shortfall * value.irc_policy.liquidity_multiplier, quantum)
            ),
            "counterparty_buffer": _money(value.irc_policy.counterparty_buffer),
            "climate_evidence_buffer": _money(value.irc_policy.climate_evidence_buffer),
            "uncapped_irc": _money(uncapped_irc),
            "irc": _money(irc),
            "cbb": _money(value.cbb.amount),
            "facility_commitment": _money(value.facility_commitment.amount),
        },
    }
    reasons = (
        "IRC_SEPARATE_FROM_CBB",
        "MONTE_CARLO_PINNED",
        *(
            "MARGIN_LIQUIDITY_SHORTFALL"
            for item in deterministic
            if item["margin_liquidity_shortfall"] != _money(Decimal(0))
        ),
    )
    draft = {
        "assessment_id": value.assessment_id,
        "snapshot_id": value.snapshot_id,
        "result": result,
        "reason_codes": list(reasons),
    }
    return ScenarioCapacityAssessment(
        value.assessment_id,
        value.snapshot_id,
        result,
        reasons,
        domain_digest("scenario_capacity_assessment", 1, canonical_json_bytes(draft)),
    )


def compile_shocks(value: ScenarioCapacityInput, scenario: ScenarioDefinition) -> CompiledShock:
    """Compile ordered price, haircut, and reserve shocks before revaluation."""
    collateral_loss = (
        max(Decimal(0), -scenario.price_shock) * value.cbb.amount
        + value.cbb.amount * scenario.cbb_haircut
        + scenario.added_reserve
    )
    return CompiledShock(
        scenario_id=scenario.scenario_id,
        family=scenario.family,
        collateral_loss=_q(collateral_loss, value.quantization_scale),
        margin_multiplier=scenario.margin_multiplier,
    )


def _deterministic_scenario(
    value: ScenarioCapacityInput, scenario: ScenarioDefinition, quantum: Decimal
) -> dict[str, str]:
    shock = compile_shocks(value, scenario)
    stressed_cbb = _q(max(Decimal(0), value.cbb.amount - shock.collateral_loss), quantum)
    margin_call = _q(value.base_margin_call.amount * shock.margin_multiplier, quantum)
    liquidity_shortfall = _q(
        max(Decimal(0), margin_call - value.available_liquidity.amount), quantum
    )
    return {
        "scenario_id": scenario.scenario_id,
        "family": scenario.family,
        "stressed_cbb": _money(stressed_cbb),
        "cbb_deficiency": _money(max(Decimal(0), value.outstanding_exposure.amount - stressed_cbb)),
        "margin_liquidity_shortfall": _money(liquidity_shortfall),
        "loss": _money(_q(value.cbb.amount - stressed_cbb + liquidity_shortfall, quantum)),
    }


def _monte_carlo(value: ScenarioCapacityInput, quantum: Decimal) -> list[_MonteCarloPath]:
    rng = random.Random(value.seed)
    paths: list[_MonteCarloPath] = []
    orthogonal = (Decimal(1) - value.correlation * value.correlation).sqrt()
    for _ in range(value.path_count):
        price_z = Decimal(str(rng.gauss(0, 1)))
        independent_z = Decimal(str(rng.gauss(0, 1)))
        margin_z = value.correlation * price_z + orthogonal * independent_z
        price_loss = (
            max(Decimal(0), price_z * value.price_volatility)
            * value.cbb.amount
            * (Decimal(1) - value.hedge_effectiveness)
        )
        stressed_cbb = max(Decimal(0), value.cbb.amount - price_loss)
        deficiency = max(Decimal(0), value.outstanding_exposure.amount - stressed_cbb)
        stressed_margin = max(
            Decimal(0),
            value.base_margin_call.amount * (Decimal(1) + margin_z * value.margin_volatility),
        )
        shortfall = max(Decimal(0), stressed_margin - value.available_liquidity.amount)
        paths.append(
            _MonteCarloPath(
                loss=_q(value.cbb.amount - stressed_cbb + shortfall, quantum),
                collateral_loss=_q(price_loss, quantum),
                liquidity_shortfall=_q(shortfall, quantum),
                deficiency=_q(deficiency, quantum),
                hedge_effectiveness=value.hedge_effectiveness,
            )
        )
    return paths


def _q(value: Decimal, quantum: Decimal) -> Decimal:
    return value.quantize(quantum, rounding=ROUND_HALF_EVEN)


def _decimal(value: Decimal) -> str:
    return format(value, "f")


def _money(value: Decimal) -> str:
    return f"{value:.2f}"


def _probability(values: int | list[Decimal], path_count: int) -> str:
    count = values if isinstance(values, int) else sum(1 for item in values if item > 0)
    probability = (Decimal(count) / Decimal(path_count)).quantize(
        Decimal("0.000001"), rounding=ROUND_HALF_EVEN
    )
    return f"{probability:.6f}"


def _quantile_index(confidence_level: Decimal, item_count: int) -> int:
    return max(0, math.ceil(float(confidence_level) * item_count) - 1)


def _threshold_stability(
    paths: list[_MonteCarloPath], confidence_level: Decimal, quantum: Decimal
) -> dict[str, str]:
    step = Decimal(1) / Decimal(len(paths))
    lower_level = max(Decimal(0), confidence_level - step)
    upper_level = min(Decimal(1), confidence_level + step)
    lower = paths[_quantile_index(lower_level, len(paths))].loss
    upper = paths[_quantile_index(upper_level, len(paths))].loss
    return {
        "lower_confidence_level": _decimal(lower_level),
        "upper_confidence_level": _decimal(upper_level),
        "lower_value_at_risk": _money(lower),
        "upper_value_at_risk": _money(upper),
        "band_width": _money(_q(upper - lower, quantum)),
    }


def _ratio(numerator: Decimal, denominator: Decimal) -> str:
    if denominator == 0:
        return "0.000000"
    return (
        f"{(numerator / denominator).quantize(Decimal('0.000001'), rounding=ROUND_HALF_EVEN):.6f}"
    )


def _distribution(values: list[Decimal]) -> dict[str, str]:
    ordered = sorted(values)
    return {
        "minimum": _decimal(ordered[0]),
        "median": _decimal(ordered[_quantile_index(Decimal("0.5"), len(ordered))]),
        "p95": _decimal(ordered[_quantile_index(Decimal("0.95"), len(ordered))]),
        "maximum": _decimal(ordered[-1]),
    }


def _worst_scenario_families(scenarios: list[dict[str, str]]) -> list[dict[str, str]]:
    totals: dict[str, Decimal] = {}
    for scenario in scenarios:
        totals[scenario["family"]] = totals.get(scenario["family"], Decimal(0)) + Decimal(
            scenario["loss"]
        )
    return [
        {"family": family, "loss": _money(loss)}
        for family, loss in sorted(totals.items(), key=lambda item: (-item[1], item[0]))
    ]
