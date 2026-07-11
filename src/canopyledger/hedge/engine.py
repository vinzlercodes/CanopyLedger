"""Authoritative M3 hedge exposure, option valuation, and liquidity calculations."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from enum import StrEnum
from typing import Any

from canopyledger.domain.money import Money
from canopyledger.domain.units import Quantity, UnitConversionTable, normalize_quantity
from canopyledger.integrity.canonical import canonical_json_bytes, domain_digest
from canopyledger.integrity.snapshot import RESOURCE_ID_PATTERN


class HedgeLiquidityError(ValueError):
    """Raised when hedge and liquidity inputs violate the M3 contract."""


class ExerciseStyle(StrEnum):
    AMERICAN = "american"
    EUROPEAN = "european"


class OptionType(StrEnum):
    CALL = "call"
    PUT = "put"


@dataclass(frozen=True)
class ExchangeContractSpecification:
    """Versioned exchange data; KC and AC are intentionally separate products."""

    exchange: str
    product_code: str
    contract_symbol: str
    contract_size: Decimal
    contract_size_unit: str
    price_unit: str
    price_unit_factor: Decimal
    tick_size: Decimal
    currency: str
    exercise_style: ExerciseStyle
    settlement_rule: str
    calendar_version: str
    delivery_months: tuple[str, ...]
    effective_from: str
    effective_to: str
    source_document_digest: str

    def __post_init__(self) -> None:
        if not all(
            (
                self.exchange,
                self.product_code,
                self.contract_symbol,
                self.contract_size_unit,
                self.price_unit,
                self.settlement_rule,
                self.calendar_version,
                self.effective_from,
                self.effective_to,
                self.source_document_digest,
            )
        ):
            raise HedgeLiquidityError("exchange contract specification metadata is required")
        if not self.contract_size.is_finite() or self.contract_size <= 0:
            raise HedgeLiquidityError("contract size must be finite and positive")
        if not self.price_unit_factor.is_finite() or self.price_unit_factor <= 0:
            raise HedgeLiquidityError("price unit factor must be finite and positive")
        if not self.tick_size.is_finite() or self.tick_size <= 0:
            raise HedgeLiquidityError("tick size must be finite and positive")
        if len(self.currency) != 3 or not self.currency.isupper():
            raise HedgeLiquidityError("contract currency must be a three-letter uppercase code")
        if self.settlement_rule not in {"futures_delivery", "cash_settlement"}:
            raise HedgeLiquidityError("exchange contract settlement rule is unsupported")
        if not self.delivery_months or len(set(self.delivery_months)) != len(self.delivery_months):
            raise HedgeLiquidityError("delivery months must be non-empty and unique")
        if re.fullmatch(r"sha256:[0-9a-f]{64}", self.source_document_digest) is None:
            raise HedgeLiquidityError("exchange specification source digest must be SHA-256")

    def to_canonical_dict(
        self, *, exposure_unit: str, unit_table: UnitConversionTable
    ) -> dict[str, str | list[str]]:
        normalized_size = normalize_quantity(
            Quantity(self.contract_size, self.contract_size_unit),
            output_unit=exposure_unit,
            table=unit_table,
        )
        return {
            "exchange": self.exchange,
            "product_code": self.product_code,
            "contract_symbol": self.contract_symbol,
            "contract_size": _decimal(self.contract_size),
            "contract_size_unit": self.contract_size_unit,
            "contract_size_in_exposure_unit": _decimal(normalized_size.output_value),
            "exposure_unit": exposure_unit,
            "price_unit": self.price_unit,
            "price_unit_factor": _decimal(self.price_unit_factor),
            "tick_size": _decimal(self.tick_size),
            "currency": self.currency,
            "exercise_style": self.exercise_style.value,
            "settlement_rule": self.settlement_rule,
            "calendar_version": self.calendar_version,
            "delivery_months": list(self.delivery_months),
            "effective_from": self.effective_from,
            "effective_to": self.effective_to,
            "source_document_digest": self.source_document_digest,
        }


@dataclass(frozen=True)
class PhysicalExposure:
    product_code: str
    delivery_month: str
    quantity: Decimal
    quantity_unit: str

    def __post_init__(self) -> None:
        if not all((self.product_code, self.delivery_month, self.quantity_unit)):
            raise HedgeLiquidityError("physical exposure metadata is required")
        if not self.quantity.is_finite() or self.quantity < 0:
            raise HedgeLiquidityError("physical exposure quantity must be finite and non-negative")


@dataclass(frozen=True)
class FuturesPosition:
    contract_specification: ExchangeContractSpecification
    contracts: Decimal
    delivery_month: str
    entry_futures_price: Decimal
    current_futures_price: Decimal

    def __post_init__(self) -> None:
        if not self.delivery_month:
            raise HedgeLiquidityError("futures delivery month is required")
        for value in (self.contracts, self.entry_futures_price, self.current_futures_price):
            if not value.is_finite():
                raise HedgeLiquidityError("futures values must be finite")


@dataclass(frozen=True)
class OptionPosition:
    contract_specification: ExchangeContractSpecification
    contracts: Decimal
    delivery_month: str
    option_type: OptionType
    strike: Decimal
    futures_price: Decimal
    volatility: Decimal
    risk_free_rate: Decimal
    time_to_expiry: Decimal
    lattice_steps: int = 200
    entry_option_price: Decimal | None = None

    def __post_init__(self) -> None:
        if not self.delivery_month:
            raise HedgeLiquidityError("option delivery month is required")
        if self.lattice_steps < 2:
            raise HedgeLiquidityError("option lattice requires at least two steps")
        for value in (
            self.contracts,
            self.strike,
            self.futures_price,
            self.volatility,
            self.risk_free_rate,
            self.time_to_expiry,
        ):
            if not value.is_finite():
                raise HedgeLiquidityError("option values must be finite")
        if self.strike <= 0 or self.futures_price < 0:
            raise HedgeLiquidityError("strike must be positive and futures price non-negative")
        if self.volatility < 0 or self.time_to_expiry < 0:
            raise HedgeLiquidityError("volatility and time to expiry cannot be negative")
        if self.entry_option_price is not None and not self.entry_option_price.is_finite():
            raise HedgeLiquidityError("entry option price must be finite")


@dataclass(frozen=True)
class OptionGreeks:
    price: Decimal
    delta: Decimal
    gamma: Decimal
    vega: Decimal
    theta: Decimal
    rho: Decimal


@dataclass(frozen=True)
class HedgeLiquidityInput:
    assessment_id: str
    snapshot_id: str
    as_of: date
    cbb_output_digest: str
    market_bundle_digest: str
    policy_bundle_digest: str
    computation_bundle_digest: str
    exposure_unit: str
    unit_conversion_table: UnitConversionTable
    physical_exposure: tuple[PhysicalExposure, ...]
    purchase_commitments: tuple[PhysicalExposure, ...]
    sales_commitments: tuple[PhysicalExposure, ...]
    futures_positions: tuple[FuturesPosition, ...]
    option_positions: tuple[OptionPosition, ...]
    fx_exposure: Money
    basis_exposure: Decimal
    available_cash: Money
    undrawn_contractual_availability: Money
    one_day_futures_moves: Mapping[str, Decimal]
    multi_day_futures_moves: Mapping[str, Decimal]
    fx_rates_to_facility: Mapping[str, Decimal] = field(default_factory=dict)
    required_liquidity_coverage_ratio: Decimal = Decimal("1")

    def __post_init__(self) -> None:
        if re.fullmatch(
            RESOURCE_ID_PATTERN, self.assessment_id
        ) is None or not self.assessment_id.startswith("hdl_"):
            raise HedgeLiquidityError("hedge liquidity assessment ID must be an hdl UUIDv7")
        if re.fullmatch(
            RESOURCE_ID_PATTERN, self.snapshot_id
        ) is None or not self.snapshot_id.startswith("snp_"):
            raise HedgeLiquidityError("snapshot ID must be an snp UUIDv7")
        if not all(
            (
                self.assessment_id,
                self.snapshot_id,
                self.cbb_output_digest,
                self.market_bundle_digest,
                self.policy_bundle_digest,
                self.computation_bundle_digest,
                self.exposure_unit,
            )
        ):
            raise HedgeLiquidityError("assessment IDs, digests, and exposure unit are required")
        if not all(
            digest.startswith("sha256:")
            for digest in (
                self.cbb_output_digest,
                self.market_bundle_digest,
                self.policy_bundle_digest,
                self.computation_bundle_digest,
            )
        ):
            raise HedgeLiquidityError("all lineage references must be SHA-256 digests")
        currencies = {
            self.available_cash.currency,
            self.undrawn_contractual_availability.currency,
        }
        if len(currencies) != 1:
            raise HedgeLiquidityError("liquidity amounts must use one facility currency")
        if self.available_cash.amount < 0 or self.undrawn_contractual_availability.amount < 0:
            raise HedgeLiquidityError("available liquidity cannot be negative")
        if not self.basis_exposure.is_finite():
            raise HedgeLiquidityError("basis exposure must be finite")
        if (
            not self.required_liquidity_coverage_ratio.is_finite()
            or self.required_liquidity_coverage_ratio <= 0
        ):
            raise HedgeLiquidityError(
                "required liquidity coverage ratio must be finite and positive"
            )
        for move in (*self.one_day_futures_moves.values(), *self.multi_day_futures_moves.values()):
            if not move.is_finite():
                raise HedgeLiquidityError("futures stress moves must be finite")
        for pair, rate in self.fx_rates_to_facility.items():
            if not pair or not rate.is_finite() or rate <= 0:
                raise HedgeLiquidityError(
                    "FX rates to facility currency must be finite and positive"
                )

    @property
    def input_digest(self) -> str:
        return domain_digest(
            "hedge_liquidity_input",
            1,
            canonical_json_bytes(self.to_input_canonical_dict()),
        )

    def to_input_canonical_dict(self) -> dict[str, Any]:
        """Canonical frozen business inputs, excluding snapshot/bundle publication context."""
        return {
            "as_of": self.as_of.isoformat(),
            "exposure_unit": self.exposure_unit,
            "unit_conversion_table": {
                "version": self.unit_conversion_table.version,
                "factors": [
                    {
                        "input_unit": input_unit,
                        "output_unit": output_unit,
                        "factor": _raw_decimal(factor),
                    }
                    for (input_unit, output_unit), factor in sorted(
                        self.unit_conversion_table.factors.items()
                    )
                ],
            },
            "physical_exposure": [_physical_input_dict(item) for item in self.physical_exposure],
            "purchase_commitments": [
                _physical_input_dict(item) for item in self.purchase_commitments
            ],
            "sales_commitments": [_physical_input_dict(item) for item in self.sales_commitments],
            "futures_positions": [_futures_input_dict(item) for item in self.futures_positions],
            "option_positions": [_option_input_dict(item) for item in self.option_positions],
            "fx_exposure": _money_input_dict(self.fx_exposure),
            "basis_exposure": _raw_decimal(self.basis_exposure),
            "available_cash": _money_input_dict(self.available_cash),
            "one_day_futures_moves": {
                product: _raw_decimal(move)
                for product, move in sorted(self.one_day_futures_moves.items())
            },
            "multi_day_futures_moves": {
                product: _raw_decimal(move)
                for product, move in sorted(self.multi_day_futures_moves.items())
            },
            "fx_rates_to_facility": {
                pair: _raw_decimal(rate) for pair, rate in sorted(self.fx_rates_to_facility.items())
            },
            "required_liquidity_coverage_ratio": _raw_decimal(
                self.required_liquidity_coverage_ratio
            ),
        }

    def market_bundle_payload(self) -> dict[str, Any]:
        """Pinned market-data projection required by the M3 calculation."""
        specifications = _specifications(self)
        return {
            "contract_specifications": [
                _specification_input_dict(item)
                for item in sorted(specifications.values(), key=lambda item: item.product_code)
            ],
            "futures_marks": [
                {
                    "product_code": item.contract_specification.product_code,
                    "delivery_month": item.delivery_month,
                    "current_futures_price": _raw_decimal(item.current_futures_price),
                }
                for item in self.futures_positions
            ],
            "option_market_inputs": [
                {
                    "product_code": item.contract_specification.product_code,
                    "delivery_month": item.delivery_month,
                    "futures_price": _raw_decimal(item.futures_price),
                    "volatility": _raw_decimal(item.volatility),
                    "risk_free_rate": _raw_decimal(item.risk_free_rate),
                }
                for item in self.option_positions
            ],
            "fx_rates_to_facility": {
                pair: _raw_decimal(rate) for pair, rate in sorted(self.fx_rates_to_facility.items())
            },
            "basis_exposure": _raw_decimal(self.basis_exposure),
        }

    def policy_bundle_payload(self) -> dict[str, Any]:
        """Pinned policy parameters required by S5."""
        return {
            "one_day_futures_moves": {
                product: _raw_decimal(move)
                for product, move in sorted(self.one_day_futures_moves.items())
            },
            "multi_day_futures_moves": {
                product: _raw_decimal(move)
                for product, move in sorted(self.multi_day_futures_moves.items())
            },
            "required_liquidity_coverage_ratio": _raw_decimal(
                self.required_liquidity_coverage_ratio
            ),
        }

    def computation_bundle_payload(self) -> dict[str, Any]:
        """Pinned deterministic-engine and unit-table parameters required by S5."""
        return {
            "engine_version": "1.0.0",
            "unit_conversion_table": {
                "version": self.unit_conversion_table.version,
                "factors": [
                    {
                        "input_unit": input_unit,
                        "output_unit": output_unit,
                        "factor": _raw_decimal(factor),
                    }
                    for (input_unit, output_unit), factor in sorted(
                        self.unit_conversion_table.factors.items()
                    )
                ],
            },
        }

    @classmethod
    def from_frozen_input(
        cls,
        payload: dict[str, Any],
        *,
        assessment_id: str,
        snapshot_id: str,
        cbb_output_digest: str,
        market_bundle_digest: str,
        policy_bundle_digest: str,
        computation_bundle_digest: str,
        undrawn_contractual_availability: Money,
    ) -> HedgeLiquidityInput:
        """Reconstruct stored inputs and inject the authoritative published CBB availability."""
        try:
            factors = {
                (item["input_unit"], item["output_unit"]): Decimal(item["factor"])
                for item in payload["unit_conversion_table"]["factors"]
            }
            return cls(
                assessment_id=assessment_id,
                snapshot_id=snapshot_id,
                as_of=date.fromisoformat(payload["as_of"]),
                cbb_output_digest=cbb_output_digest,
                market_bundle_digest=market_bundle_digest,
                policy_bundle_digest=policy_bundle_digest,
                computation_bundle_digest=computation_bundle_digest,
                exposure_unit=payload["exposure_unit"],
                unit_conversion_table=UnitConversionTable(
                    version=payload["unit_conversion_table"]["version"],
                    factors=factors,
                ),
                physical_exposure=tuple(
                    _physical_from_input(item) for item in payload["physical_exposure"]
                ),
                purchase_commitments=tuple(
                    _physical_from_input(item) for item in payload["purchase_commitments"]
                ),
                sales_commitments=tuple(
                    _physical_from_input(item) for item in payload["sales_commitments"]
                ),
                futures_positions=tuple(
                    _futures_from_input(item) for item in payload["futures_positions"]
                ),
                option_positions=tuple(
                    _option_from_input(item) for item in payload["option_positions"]
                ),
                fx_exposure=_money_from_input(payload["fx_exposure"]),
                basis_exposure=Decimal(payload["basis_exposure"]),
                available_cash=_money_from_input(payload["available_cash"]),
                undrawn_contractual_availability=undrawn_contractual_availability,
                one_day_futures_moves={
                    product: Decimal(move)
                    for product, move in payload["one_day_futures_moves"].items()
                },
                multi_day_futures_moves={
                    product: Decimal(move)
                    for product, move in payload["multi_day_futures_moves"].items()
                },
                fx_rates_to_facility={
                    pair: Decimal(rate) for pair, rate in payload["fx_rates_to_facility"].items()
                },
                required_liquidity_coverage_ratio=Decimal(
                    payload["required_liquidity_coverage_ratio"]
                ),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise HedgeLiquidityError("frozen hedge liquidity input payload is invalid") from exc


@dataclass(frozen=True)
class HedgeLiquidityAssessment:
    assessment_id: str
    snapshot_id: str
    input_digests: tuple[str, ...]
    market_bundle_digest: str
    policy_bundle_digest: str
    computation_bundle_digest: str
    result: dict[str, Any]
    warnings: tuple[str, ...]
    reason_codes: tuple[str, ...]
    output_digest: str

    def to_canonical_dict(self) -> dict[str, Any]:
        return {
            "assessment_id": self.assessment_id,
            "snapshot_id": self.snapshot_id,
            "stage": "hedge_liquidity",
            "stage_version": "1.0.0",
            "input_digests": list(self.input_digests),
            "market_bundle_digest": self.market_bundle_digest,
            "policy_bundle_digest": self.policy_bundle_digest,
            "computation_bundle_digest": self.computation_bundle_digest,
            "result": self.result,
            "warnings": list(self.warnings),
            "reason_codes": list(self.reason_codes),
            "output_digest": self.output_digest,
        }


def black76_price_and_greeks(
    *,
    option_type: OptionType,
    futures_price: Decimal,
    strike: Decimal,
    volatility: Decimal,
    risk_free_rate: Decimal,
    time_to_expiry: Decimal,
) -> OptionGreeks:
    """Calculate the Black-76 European reference with decimal arithmetic."""
    _validate_option_parameters(futures_price, strike, volatility, risk_free_rate, time_to_expiry)
    with localcontext() as context:
        context.prec = 50
        discount = (-risk_free_rate * time_to_expiry).exp()
        if futures_price == 0:
            price = Decimal(0) if option_type is OptionType.CALL else discount * strike
            delta = Decimal(0) if option_type is OptionType.CALL else -discount
            return OptionGreeks(
                price,
                delta,
                Decimal(0),
                Decimal(0),
                risk_free_rate * price,
                -time_to_expiry * price,
            )
        if time_to_expiry == 0 or volatility == 0:
            intrinsic = _intrinsic(option_type, futures_price, strike)
            price = intrinsic if time_to_expiry == 0 else discount * intrinsic
            if futures_price == strike:
                delta = Decimal("0.5") if option_type is OptionType.CALL else Decimal("-0.5")
            elif option_type is OptionType.CALL:
                delta = discount if futures_price > strike else Decimal(0)
            else:
                delta = -discount if futures_price < strike else Decimal(0)
            return OptionGreeks(
                price,
                delta,
                Decimal(0),
                Decimal(0),
                risk_free_rate * price,
                -time_to_expiry * price,
            )

        root_time = time_to_expiry.sqrt()
        sigma_root_time = volatility * root_time
        d1 = (
            (futures_price / strike).ln() + (volatility * volatility / 2) * time_to_expiry
        ) / sigma_root_time
        d2 = d1 - sigma_root_time
        normal_d1 = _normal_cdf(d1)
        normal_d2 = _normal_cdf(d2)
        density_d1 = _normal_density(d1)
        if option_type is OptionType.CALL:
            price = discount * (futures_price * normal_d1 - strike * normal_d2)
            delta = discount * normal_d1
        else:
            price = discount * (strike * _normal_cdf(-d2) - futures_price * _normal_cdf(-d1))
            delta = discount * (normal_d1 - 1)
        gamma = discount * density_d1 / (futures_price * sigma_root_time)
        vega = discount * futures_price * density_d1 * root_time
        theta = risk_free_rate * price - discount * futures_price * density_d1 * volatility / (
            2 * root_time
        )
        rho = -time_to_expiry * price
        return OptionGreeks(price, delta, gamma, vega, theta, rho)


def crr_american_price(
    *,
    option_type: OptionType,
    futures_price: Decimal,
    strike: Decimal,
    volatility: Decimal,
    risk_free_rate: Decimal,
    time_to_expiry: Decimal,
    steps: int,
) -> Decimal:
    """Value an American futures option with a recombining CRR lattice."""
    _validate_option_parameters(futures_price, strike, volatility, risk_free_rate, time_to_expiry)
    if steps < 2:
        raise HedgeLiquidityError("option lattice requires at least two steps")
    if futures_price == 0 or time_to_expiry == 0 or volatility == 0:
        return _intrinsic(option_type, futures_price, strike)
    with localcontext() as context:
        context.prec = 50
        dt = time_to_expiry / Decimal(steps)
        up = (volatility * dt.sqrt()).exp()
        down = Decimal(1) / up
        probability = (Decimal(1) - down) / (up - down)
        if probability < 0 or probability > 1:
            raise HedgeLiquidityError("CRR risk-neutral probability is outside [0, 1]")
        discount = (-risk_free_rate * dt).exp()
        values = [
            _intrinsic(
                option_type, futures_price * (up**up_moves) * (down ** (steps - up_moves)), strike
            )
            for up_moves in range(steps + 1)
        ]
        for level in range(steps - 1, -1, -1):
            values = [
                discount
                * (probability * values[index + 1] + (Decimal(1) - probability) * values[index])
                for index in range(level + 1)
            ]
            for up_moves in range(level + 1):
                node_futures = futures_price * (up**up_moves) * (down ** (level - up_moves))
                values[up_moves] = max(
                    values[up_moves], _intrinsic(option_type, node_futures, strike)
                )
        return values[0]


def evaluate_hedge_and_liquidity(value: HedgeLiquidityInput) -> HedgeLiquidityAssessment:
    """Produce immutable S5 hedge/liquidity output from pinned calculation inputs."""
    specifications = _specifications(value)
    facility_currency = value.available_cash.currency
    for specification in specifications.values():
        _validate_contract_effectiveness(specification, value.as_of)
        _require_fx_rate(specification.currency, facility_currency, value.fx_rates_to_facility)
    product_sizes = {
        product: _contract_size_in_exposure_unit(
            specification, value.exposure_unit, value.unit_conversion_table
        )
        for product, specification in specifications.items()
    }
    for physical_input in (
        *value.physical_exposure,
        *value.purchase_commitments,
        *value.sales_commitments,
    ):
        if physical_input.product_code not in specifications:
            raise HedgeLiquidityError(
                "physical exposure product has no exchange contract specification"
            )
    for product in (*value.one_day_futures_moves.keys(), *value.multi_day_futures_moves.keys()):
        if product not in specifications:
            raise HedgeLiquidityError("unknown futures move product")

    physical = _normalized_exposures(
        value.physical_exposure, value.exposure_unit, value.unit_conversion_table
    )
    purchases = _normalized_exposures(
        value.purchase_commitments, value.exposure_unit, value.unit_conversion_table
    )
    sales = _normalized_exposures(
        value.sales_commitments, value.exposure_unit, value.unit_conversion_table
    )
    gross_physical = sum((item[2] for item in physical), Decimal(0))
    net_physical = (
        gross_physical
        + sum((item[2] for item in purchases), Decimal(0))
        - sum((item[2] for item in sales), Decimal(0))
    )

    futures_exposure = Decimal(0)
    futures_pnl = Decimal(0)
    futures_result: list[dict[str, str]] = []
    month_hedge: dict[str, Decimal] = {}
    for futures_position in value.futures_positions:
        _validate_delivery_and_tick(
            futures_position.contract_specification,
            futures_position.delivery_month,
            futures_position.entry_futures_price,
            futures_position.current_futures_price,
        )
        size = product_sizes[futures_position.contract_specification.product_code]
        futures_delta = futures_position.contracts * size
        pnl_contract_currency = (
            futures_position.contracts
            * futures_position.contract_specification.contract_size
            * (futures_position.current_futures_price - futures_position.entry_futures_price)
            * futures_position.contract_specification.price_unit_factor
        )
        pnl = _to_facility_currency(
            pnl_contract_currency,
            futures_position.contract_specification.currency,
            facility_currency,
            value.fx_rates_to_facility,
        )
        futures_exposure += futures_delta
        futures_pnl += pnl
        month_hedge[futures_position.delivery_month] = (
            month_hedge.get(futures_position.delivery_month, Decimal(0)) + futures_delta
        )
        futures_result.append(
            {
                "product_code": futures_position.contract_specification.product_code,
                "delivery_month": futures_position.delivery_month,
                "contracts": _decimal(futures_position.contracts),
                "delta_exposure": _decimal(futures_delta),
                "pnl": _money(pnl),
            }
        )

    option_exposure = Decimal(0)
    option_value = Decimal(0)
    option_pnl = Decimal(0)
    aggregate_greeks = {name: Decimal(0) for name in ("delta", "gamma", "vega", "theta", "rho")}
    option_result: list[dict[str, str]] = []
    for option_position in value.option_positions:
        _validate_delivery_and_tick(
            option_position.contract_specification,
            option_position.delivery_month,
            option_position.futures_price,
            option_position.strike,
        )
        black = black76_price_and_greeks(
            option_type=option_position.option_type,
            futures_price=option_position.futures_price,
            strike=option_position.strike,
            volatility=option_position.volatility,
            risk_free_rate=option_position.risk_free_rate,
            time_to_expiry=option_position.time_to_expiry,
        )
        authoritative_price = (
            crr_american_price(
                option_type=option_position.option_type,
                futures_price=option_position.futures_price,
                strike=option_position.strike,
                volatility=option_position.volatility,
                risk_free_rate=option_position.risk_free_rate,
                time_to_expiry=option_position.time_to_expiry,
                steps=option_position.lattice_steps,
            )
            if option_position.contract_specification.exercise_style is ExerciseStyle.AMERICAN
            else black.price
        )
        multiplier = (
            option_position.contracts * option_position.contract_specification.contract_size
        )
        price_factor = option_position.contract_specification.price_unit_factor
        size = product_sizes[option_position.contract_specification.product_code]
        delta_exposure = option_position.contracts * size * black.delta
        position_value = _to_facility_currency(
            multiplier * price_factor * authoritative_price,
            option_position.contract_specification.currency,
            facility_currency,
            value.fx_rates_to_facility,
        )
        position_pnl = _to_facility_currency(
            Decimal(0)
            if option_position.entry_option_price is None
            else multiplier
            * price_factor
            * (authoritative_price - option_position.entry_option_price),
            option_position.contract_specification.currency,
            facility_currency,
            value.fx_rates_to_facility,
        )
        option_exposure += delta_exposure
        option_value += position_value
        option_pnl += position_pnl
        month_hedge[option_position.delivery_month] = (
            month_hedge.get(option_position.delivery_month, Decimal(0)) + delta_exposure
        )
        for name, greek in (
            ("delta", black.delta),
            ("gamma", black.gamma),
            ("vega", black.vega),
            ("theta", black.theta),
            ("rho", black.rho),
        ):
            aggregate_greeks[name] += multiplier * greek
        option_result.append(
            {
                "product_code": option_position.contract_specification.product_code,
                "delivery_month": option_position.delivery_month,
                "option_type": option_position.option_type.value,
                "contracts": _decimal(option_position.contracts),
                "black76_reference_price": _decimal(black.price),
                "authoritative_price": _decimal(authoritative_price),
                "delta_exposure": _decimal(delta_exposure),
                "value": _money(position_value),
                "pnl": _money(position_pnl),
                "delta": _decimal(black.delta),
                "gamma": _decimal(black.gamma),
                "vega": _decimal(black.vega),
                "theta": _decimal(black.theta),
                "rho": _decimal(black.rho),
            }
        )

    net_price_exposure = net_physical + futures_exposure + option_exposure
    hedge_delta = futures_exposure + option_exposure
    hedge_ratio = abs(hedge_delta) / gross_physical if gross_physical else None
    monthly_physical = _monthly_net_physical(physical, purchases, sales)
    month_rows = [
        {
            "delivery_month": month,
            "physical_exposure": _decimal(monthly_physical.get(month, Decimal(0))),
            "hedge_delta_exposure": _decimal(month_hedge.get(month, Decimal(0))),
            "net_price_exposure": _decimal(
                monthly_physical.get(month, Decimal(0)) + month_hedge.get(month, Decimal(0))
            ),
        }
        for month in sorted(set(monthly_physical) | set(month_hedge))
    ]
    liquidity = _liquidity_result(value)
    reason_codes = _reason_codes(gross_physical, hedge_delta, net_price_exposure, liquidity)
    total_physical_by_month = sum((abs(amount) for amount in monthly_physical.values()), Decimal(0))
    concentration_by_month = [
        {
            "delivery_month": month,
            "physical_concentration": _decimal(
                Decimal(0)
                if total_physical_by_month == 0
                else abs(monthly_physical.get(month, Decimal(0))) / total_physical_by_month
            ),
        }
        for month in sorted(monthly_physical)
    ]
    fx_exposure = _to_facility_currency(
        value.fx_exposure.amount,
        value.fx_exposure.currency,
        facility_currency,
        value.fx_rates_to_facility,
    )
    result = {
        "contract_specifications": [
            specification.to_canonical_dict(
                exposure_unit=value.exposure_unit,
                unit_table=value.unit_conversion_table,
            )
            for specification in sorted(specifications.values(), key=lambda item: item.product_code)
        ],
        "futures_positions": futures_result,
        "option_positions": option_result,
        "exposure": {
            "exposure_unit": value.exposure_unit,
            "gross_physical_exposure": _decimal(gross_physical),
            "purchase_commitment_exposure": _decimal(
                sum((item[2] for item in purchases), Decimal(0))
            ),
            "sales_commitment_exposure": _decimal(sum((item[2] for item in sales), Decimal(0))),
            "net_physical_exposure": _decimal(net_physical),
            "futures_exposure": _decimal(futures_exposure),
            "option_delta_equivalent": _decimal(option_exposure),
            "net_price_exposure": _decimal(net_price_exposure),
            "hedge_ratio": None if hedge_ratio is None else _decimal(hedge_ratio),
            "under_hedge_amount": _decimal(max(net_price_exposure, Decimal(0))),
            "over_hedge_amount": _decimal(max(-net_price_exposure, Decimal(0))),
            "fx_exposure": _money(fx_exposure),
            "fx_exposure_currency": facility_currency,
            "fx_exposure_source_amount": _money(value.fx_exposure.amount),
            "fx_exposure_source_currency": value.fx_exposure.currency,
            "basis_exposure": _decimal(value.basis_exposure),
            "delivery_month_mismatch": month_rows,
            "concentration_by_month": concentration_by_month,
        },
        "valuation": {
            "futures_pnl": _money(futures_pnl),
            "option_value": _money(option_value),
            "option_pnl": _money(option_pnl),
            "currency": value.available_cash.currency,
            "aggregate_greeks": {
                name: _decimal(amount) for name, amount in aggregate_greeks.items()
            },
        },
        "liquidity": liquidity,
    }
    draft = {
        "assessment_id": value.assessment_id,
        "snapshot_id": value.snapshot_id,
        "stage": "hedge_liquidity",
        "stage_version": "1.0.0",
        "input_digests": [value.cbb_output_digest, value.market_bundle_digest],
        "market_bundle_digest": value.market_bundle_digest,
        "policy_bundle_digest": value.policy_bundle_digest,
        "computation_bundle_digest": value.computation_bundle_digest,
        "result": result,
        "warnings": [],
        "reason_codes": list(reason_codes),
    }
    return HedgeLiquidityAssessment(
        assessment_id=value.assessment_id,
        snapshot_id=value.snapshot_id,
        input_digests=(value.cbb_output_digest, value.market_bundle_digest),
        market_bundle_digest=value.market_bundle_digest,
        policy_bundle_digest=value.policy_bundle_digest,
        computation_bundle_digest=value.computation_bundle_digest,
        result=result,
        warnings=(),
        reason_codes=reason_codes,
        output_digest=domain_digest("hedge_liquidity_assessment", 1, canonical_json_bytes(draft)),
    )


def _liquidity_result(value: HedgeLiquidityInput) -> dict[str, str | None]:
    positions = value.futures_positions
    facility_currency = value.available_cash.currency
    one_day = _margin_stress(
        positions,
        value.one_day_futures_moves,
        facility_currency,
        value.fx_rates_to_facility,
    )
    multi_day = _margin_stress(
        positions,
        value.multi_day_futures_moves,
        facility_currency,
        value.fx_rates_to_facility,
    )
    available_liquidity = (
        value.available_cash.amount + value.undrawn_contractual_availability.amount
    )
    shortfall = max(multi_day - available_liquidity, Decimal(0))
    required_reserve = multi_day * value.required_liquidity_coverage_ratio
    coverage = None if required_reserve == 0 else available_liquidity / required_reserve
    return {
        "currency": value.available_cash.currency,
        "available_cash": _money(value.available_cash.amount),
        "undrawn_contractual_availability": _money(value.undrawn_contractual_availability.amount),
        "total_liquidity_available": _money(available_liquidity),
        "one_day_margin_stress": _money(one_day),
        "multi_day_margin_stress": _money(multi_day),
        "timing_mismatch": _money(max(multi_day - value.available_cash.amount, Decimal(0))),
        "margin_call_shortfall": _money(shortfall),
        "liquidity_coverage_ratio": None if coverage is None else _decimal(coverage),
        "required_liquidity_reserve": _money(required_reserve),
        "required_liquidity_coverage_ratio": _decimal(value.required_liquidity_coverage_ratio),
    }


def _margin_stress(
    positions: tuple[FuturesPosition, ...],
    moves: Mapping[str, Decimal],
    facility_currency: str,
    fx_rates_to_facility: Mapping[str, Decimal],
) -> Decimal:
    return sum(
        (
            _to_facility_currency(
                abs(position.contracts)
                * position.contract_specification.contract_size
                * abs(moves.get(position.contract_specification.product_code, Decimal(0)))
                * position.contract_specification.price_unit_factor,
                position.contract_specification.currency,
                facility_currency,
                fx_rates_to_facility,
            )
            for position in positions
        ),
        Decimal(0),
    )


def _reason_codes(
    gross_physical: Decimal,
    hedge_delta: Decimal,
    net_price_exposure: Decimal,
    liquidity: Mapping[str, str | None],
) -> tuple[str, ...]:
    codes: list[str] = []
    if gross_physical and hedge_delta:
        codes.append(
            "HEDGE_REDUCES_PRICE_EXPOSURE"
            if abs(net_price_exposure) < gross_physical
            else "HEDGE_INCREASES_PRICE_EXPOSURE"
        )
    if Decimal(str(liquidity["margin_call_shortfall"])) > 0:
        codes.append("MARGIN_LIQUIDITY_SHORTFALL")
    if net_price_exposure < 0:
        codes.append("OVER_HEDGED")
    return tuple(codes)


def _specifications(value: HedgeLiquidityInput) -> dict[str, ExchangeContractSpecification]:
    specifications: dict[str, ExchangeContractSpecification] = {}
    for futures_position in value.futures_positions:
        specification = futures_position.contract_specification
        current = specifications.get(specification.product_code)
        if current is not None and current != specification:
            raise HedgeLiquidityError(
                "one product cannot use multiple exchange contract specifications"
            )
        specifications[specification.product_code] = specification
    for option_position in value.option_positions:
        specification = option_position.contract_specification
        current = specifications.get(specification.product_code)
        if current is not None and current != specification:
            raise HedgeLiquidityError(
                "one product cannot use multiple exchange contract specifications"
            )
        specifications[specification.product_code] = specification
    if not specifications:
        raise HedgeLiquidityError("at least one futures or option position is required")
    return specifications


def _normalized_exposures(
    exposures: tuple[PhysicalExposure, ...], output_unit: str, table: UnitConversionTable
) -> list[tuple[str, str, Decimal]]:
    return [
        (
            exposure.product_code,
            exposure.delivery_month,
            normalize_quantity(
                Quantity(exposure.quantity, exposure.quantity_unit),
                output_unit=output_unit,
                table=table,
            ).output_value,
        )
        for exposure in exposures
    ]


def _monthly_net_physical(
    physical: list[tuple[str, str, Decimal]],
    purchases: list[tuple[str, str, Decimal]],
    sales: list[tuple[str, str, Decimal]],
) -> dict[str, Decimal]:
    amounts: dict[str, Decimal] = {}
    for _, month, amount in physical:
        amounts[month] = amounts.get(month, Decimal(0)) + amount
    for _, month, amount in purchases:
        amounts[month] = amounts.get(month, Decimal(0)) + amount
    for _, month, amount in sales:
        amounts[month] = amounts.get(month, Decimal(0)) - amount
    return amounts


def _contract_size_in_exposure_unit(
    specification: ExchangeContractSpecification,
    exposure_unit: str,
    table: UnitConversionTable,
) -> Decimal:
    return normalize_quantity(
        Quantity(specification.contract_size, specification.contract_size_unit),
        output_unit=exposure_unit,
        table=table,
    ).output_value


def _validate_contract_effectiveness(
    specification: ExchangeContractSpecification,
    as_of: date,
) -> None:
    try:
        effective_from = date.fromisoformat(specification.effective_from)
        effective_to = date.fromisoformat(specification.effective_to)
    except ValueError as exc:
        raise HedgeLiquidityError("contract effective dates must use ISO calendar dates") from exc
    if effective_from > effective_to:
        raise HedgeLiquidityError("contract effective date range is invalid")
    if not effective_from <= as_of <= effective_to:
        raise HedgeLiquidityError(
            "exchange contract specification is not effective at snapshot as-of"
        )


def _validate_delivery_and_tick(
    specification: ExchangeContractSpecification,
    delivery_month: str,
    *prices: Decimal,
) -> None:
    if delivery_month not in specification.delivery_months:
        raise HedgeLiquidityError("delivery month is not valid for exchange contract specification")
    for price in prices:
        if price.remainder_near(specification.tick_size) != 0:
            raise HedgeLiquidityError(
                "market price does not conform to exchange contract tick size"
            )


def _require_fx_rate(
    source_currency: str,
    facility_currency: str,
    fx_rates_to_facility: Mapping[str, Decimal],
) -> None:
    if source_currency == facility_currency:
        return
    pair = f"{source_currency}/{facility_currency}"
    if pair not in fx_rates_to_facility:
        raise HedgeLiquidityError("contract currency requires a pinned FX conversion")


def _to_facility_currency(
    amount: Decimal,
    source_currency: str,
    facility_currency: str,
    fx_rates_to_facility: Mapping[str, Decimal],
) -> Decimal:
    _require_fx_rate(source_currency, facility_currency, fx_rates_to_facility)
    return (
        amount
        if source_currency == facility_currency
        else amount * fx_rates_to_facility[f"{source_currency}/{facility_currency}"]
    )


def _validate_option_parameters(
    futures_price: Decimal,
    strike: Decimal,
    volatility: Decimal,
    risk_free_rate: Decimal,
    time_to_expiry: Decimal,
) -> None:
    if not all(
        item.is_finite()
        for item in (futures_price, strike, volatility, risk_free_rate, time_to_expiry)
    ):
        raise HedgeLiquidityError("option values must be finite")
    if futures_price < 0 or strike <= 0:
        raise HedgeLiquidityError("futures price must be non-negative and strike positive")
    if volatility < 0 or time_to_expiry < 0:
        raise HedgeLiquidityError("volatility and time to expiry cannot be negative")


def _intrinsic(option_type: OptionType, futures_price: Decimal, strike: Decimal) -> Decimal:
    return (
        max(futures_price - strike, Decimal(0))
        if option_type is OptionType.CALL
        else max(strike - futures_price, Decimal(0))
    )


def _normal_density(value: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = 50
        return (-(value * value) / 2).exp() / Decimal(
            "2.5066282746310005024157652848110452530069867406099"
        )


def _normal_cdf(value: Decimal) -> Decimal:
    """Decimal normal CDF; the series is accurate at the pricing-relevant centre."""
    if value < 0:
        return Decimal(1) - _normal_cdf(-value)
    with localcontext() as context:
        context.prec = 50
        if value > Decimal("8"):
            return Decimal(1)
        if value > Decimal("3"):
            # Abramowitz-Stegun tail approximation is sufficient far from the strike.
            t = Decimal(1) / (Decimal(1) + Decimal("0.2316419") * value)
            polynomial = (
                Decimal("0.319381530") * t
                + Decimal("-0.356563782") * (t**2)
                + Decimal("1.781477937") * (t**3)
                + Decimal("-1.821255978") * (t**4)
                + Decimal("1.330274429") * (t**5)
            )
            return Decimal(1) - _normal_density(value) * polynomial
        z = value / Decimal("1.4142135623730950488016887242096980785696718753769")
        term = z
        series = term
        index = 0
        while abs(term) > Decimal("1e-45"):
            index += 1
            term *= -(z * z) * Decimal(2 * index - 1) / (Decimal(index) * Decimal(2 * index + 1))
            series += term
            if index > 500:
                raise HedgeLiquidityError("normal CDF did not converge")
        erf = Decimal(2) * series / Decimal("1.7724538509055160272981674833411451827975494561224")
        return (Decimal(1) + erf) / 2


def _decimal(value: Decimal) -> str:
    quantum = Decimal("0.00000001")
    rounded = value.quantize(quantum, rounding=ROUND_HALF_EVEN)
    return format(abs(rounded) if rounded.is_zero() else rounded, ".8f")


def _money(value: Decimal) -> str:
    rounded = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
    return format(abs(rounded) if rounded.is_zero() else rounded, ".2f")


def _raw_decimal(value: Decimal) -> str:
    return format(value, "f")


def _money_input_dict(value: Money) -> dict[str, str]:
    return {"amount": _raw_decimal(value.amount), "currency": value.currency}


def _specification_input_dict(value: ExchangeContractSpecification) -> dict[str, Any]:
    return {
        "exchange": value.exchange,
        "product_code": value.product_code,
        "contract_symbol": value.contract_symbol,
        "contract_size": _raw_decimal(value.contract_size),
        "contract_size_unit": value.contract_size_unit,
        "price_unit": value.price_unit,
        "price_unit_factor": _raw_decimal(value.price_unit_factor),
        "tick_size": _raw_decimal(value.tick_size),
        "currency": value.currency,
        "exercise_style": value.exercise_style.value,
        "settlement_rule": value.settlement_rule,
        "calendar_version": value.calendar_version,
        "delivery_months": list(value.delivery_months),
        "effective_from": value.effective_from,
        "effective_to": value.effective_to,
        "source_document_digest": value.source_document_digest,
    }


def _physical_input_dict(value: PhysicalExposure) -> dict[str, str]:
    return {
        "product_code": value.product_code,
        "delivery_month": value.delivery_month,
        "quantity": _raw_decimal(value.quantity),
        "quantity_unit": value.quantity_unit,
    }


def _futures_input_dict(value: FuturesPosition) -> dict[str, Any]:
    return {
        "contract_specification": _specification_input_dict(value.contract_specification),
        "contracts": _raw_decimal(value.contracts),
        "delivery_month": value.delivery_month,
        "entry_futures_price": _raw_decimal(value.entry_futures_price),
        "current_futures_price": _raw_decimal(value.current_futures_price),
    }


def _option_input_dict(value: OptionPosition) -> dict[str, Any]:
    return {
        "contract_specification": _specification_input_dict(value.contract_specification),
        "contracts": _raw_decimal(value.contracts),
        "delivery_month": value.delivery_month,
        "option_type": value.option_type.value,
        "strike": _raw_decimal(value.strike),
        "futures_price": _raw_decimal(value.futures_price),
        "volatility": _raw_decimal(value.volatility),
        "risk_free_rate": _raw_decimal(value.risk_free_rate),
        "time_to_expiry": _raw_decimal(value.time_to_expiry),
        "lattice_steps": value.lattice_steps,
        "entry_option_price": (
            None if value.entry_option_price is None else _raw_decimal(value.entry_option_price)
        ),
    }


def _money_from_input(value: dict[str, Any]) -> Money:
    return Money(Decimal(value["amount"]), value["currency"])


def _specification_from_input(value: dict[str, Any]) -> ExchangeContractSpecification:
    return ExchangeContractSpecification(
        exchange=value["exchange"],
        product_code=value["product_code"],
        contract_symbol=value["contract_symbol"],
        contract_size=Decimal(value["contract_size"]),
        contract_size_unit=value["contract_size_unit"],
        price_unit=value["price_unit"],
        price_unit_factor=Decimal(value["price_unit_factor"]),
        tick_size=Decimal(value["tick_size"]),
        currency=value["currency"],
        exercise_style=ExerciseStyle(value["exercise_style"]),
        settlement_rule=value["settlement_rule"],
        calendar_version=value["calendar_version"],
        delivery_months=tuple(value["delivery_months"]),
        effective_from=value["effective_from"],
        effective_to=value["effective_to"],
        source_document_digest=value["source_document_digest"],
    )


def _physical_from_input(value: dict[str, Any]) -> PhysicalExposure:
    return PhysicalExposure(
        product_code=value["product_code"],
        delivery_month=value["delivery_month"],
        quantity=Decimal(value["quantity"]),
        quantity_unit=value["quantity_unit"],
    )


def _futures_from_input(value: dict[str, Any]) -> FuturesPosition:
    return FuturesPosition(
        contract_specification=_specification_from_input(value["contract_specification"]),
        contracts=Decimal(value["contracts"]),
        delivery_month=value["delivery_month"],
        entry_futures_price=Decimal(value["entry_futures_price"]),
        current_futures_price=Decimal(value["current_futures_price"]),
    )


def _option_from_input(value: dict[str, Any]) -> OptionPosition:
    entry_option_price = value["entry_option_price"]
    return OptionPosition(
        contract_specification=_specification_from_input(value["contract_specification"]),
        contracts=Decimal(value["contracts"]),
        delivery_month=value["delivery_month"],
        option_type=OptionType(value["option_type"]),
        strike=Decimal(value["strike"]),
        futures_price=Decimal(value["futures_price"]),
        volatility=Decimal(value["volatility"]),
        risk_free_rate=Decimal(value["risk_free_rate"]),
        time_to_expiry=Decimal(value["time_to_expiry"]),
        lattice_steps=int(value["lattice_steps"]),
        entry_option_price=None if entry_option_price is None else Decimal(entry_option_price),
    )
