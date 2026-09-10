"""
Federal tax computation for one household-year, plus the policy layer that
implements future tax-rate scenarios.

The projection runs in REAL (2026) dollars. That has two consequences the code
handles explicitly:

  * Brackets and the standard deduction are indexed to inflation, so in real
    terms they are constant. They stay put unless the user asks for erosion.
  * Social Security provisional-income thresholds and the NIIT threshold are
    NOT indexed. In real terms they shrink every year. The engine deflates them
    by cumulative inflation, which is why a retiree's Social Security becomes
    more taxable over time even with a flat real income.
"""

from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Sequence

from engine.tax import tables as T


# ==========================================================================
# Policy layer -- future tax scenarios
# ==========================================================================

SCENARIO_CURRENT = "Current law holds"
SCENARIO_PRE_TCJA = "Pre-TCJA rates return"
SCENARIO_SURCHARGE = "Across-the-board rate increase"
SCENARIO_CUSTOM = "Custom bracket table"

SCENARIOS = [SCENARIO_CURRENT, SCENARIO_PRE_TCJA, SCENARIO_SURCHARGE, SCENARIO_CUSTOM]


@dataclass
class TaxPolicy:
    """Everything the user can say about future federal tax law."""

    scenario: str = SCENARIO_CURRENT

    # Year the change takes effect (ignored for "current law holds")
    change_year: int = 2034

    # Percentage points added to every marginal rate under the surcharge
    # scenario. 3.0 means the 22% bracket becomes 25%.
    surcharge_points: float = 3.0

    # Multiplier applied to bracket WIDTHS after the change year. 0.9 narrows
    # every band by 10%, pushing income into higher rates without changing any
    # headline rate. This is how tax increases usually arrive in practice.
    bracket_width_factor: float = 1.0

    # Real erosion of bracket boundaries per year, expressed as a decimal.
    # Chained-CPI indexing runs below true cost growth, so brackets creep down
    # in real terms. 0.003 is a commonly cited drag. Zero disables it.
    real_bracket_drag: float = 0.0

    # OBBBA senior deduction
    senior_deduction_enabled: bool = True
    senior_deduction_expiry_year: int = T.SENIOR_DEDUCTION_EXPIRY_YEAR

    # Are the Social Security provisional-income thresholds ever indexed?
    # False (the status quo since 1993) means they erode in real terms.
    index_ss_thresholds: bool = False

    # Same question for the NIIT threshold.
    index_niit_threshold: bool = False

    # Custom bracket tables, used only when scenario == SCENARIO_CUSTOM.
    # Format matches taxtables: list of (upper_bound, rate).
    custom_brackets: dict = field(default_factory=dict)
    custom_standard_deduction: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "TaxPolicy":
        known = {f for f in TaxPolicy.__dataclass_fields__}
        return TaxPolicy(**{k: v for k, v in d.items() if k in known})


def _scale_brackets(brackets: Sequence[tuple], width_factor: float,
                    drag_factor: float) -> list[tuple]:
    """Rescale bracket boundaries. Rates are untouched."""
    if width_factor == 1.0 and drag_factor == 1.0:
        return list(brackets)
    f = width_factor * drag_factor
    out = []
    for bound, rate in brackets:
        out.append((bound if bound == float("inf") else bound * f, rate))
    return out


def _add_points(brackets: Sequence[tuple], points: float) -> list[tuple]:
    """Add percentage points to every marginal rate."""
    p = points / 100.0
    return [(b, min(0.99, r + p)) for b, r in brackets]


@dataclass
class Regime:
    """The resolved tax law for a single projection year."""
    ordinary_brackets: list
    ltcg_brackets: list
    standard_deduction: float
    additional_65: float
    personal_exemption: float
    senior_deduction_available: bool


def regime_for_year(policy: TaxPolicy, year: int, status: str,
                    n_people_65plus: int, n_people: int) -> Regime:
    """Resolve the bracket table and deductions in effect for `year`."""

    years_elapsed = max(0, year - T.TAX_YEAR_BASIS)
    drag = (1.0 - policy.real_bracket_drag) ** years_elapsed

    changed = policy.scenario != SCENARIO_CURRENT and year >= policy.change_year

    if policy.scenario == SCENARIO_CUSTOM and policy.custom_brackets:
        base_ord = policy.custom_brackets.get(status, T.FEDERAL_BRACKETS_2026[status])
        base_std = policy.custom_standard_deduction.get(
            status, T.STANDARD_DEDUCTION_2026[status])
        if not changed:
            base_ord = T.FEDERAL_BRACKETS_2026[status]
            base_std = T.STANDARD_DEDUCTION_2026[status]
        exemption = 0.0

    elif changed and policy.scenario == SCENARIO_PRE_TCJA:
        base_ord = T.PRE_TCJA_BRACKETS_2026[status]
        base_std = T.PRE_TCJA_STANDARD_DEDUCTION[status]
        exemption = T.PRE_TCJA_PERSONAL_EXEMPTION * n_people

    elif changed and policy.scenario == SCENARIO_SURCHARGE:
        base_ord = _add_points(T.FEDERAL_BRACKETS_2026[status],
                               policy.surcharge_points)
        base_std = T.STANDARD_DEDUCTION_2026[status]
        exemption = 0.0

    else:
        base_ord = T.FEDERAL_BRACKETS_2026[status]
        base_std = T.STANDARD_DEDUCTION_2026[status]
        exemption = 0.0

    width = policy.bracket_width_factor if changed else 1.0
    ordinary = _scale_brackets(base_ord, width, drag)
    ltcg = _scale_brackets(T.LTCG_BRACKETS_2026[status], width, drag)

    senior_ok = (
        policy.senior_deduction_enabled
        and year <= policy.senior_deduction_expiry_year
        and n_people_65plus > 0
    )

    return Regime(
        ordinary_brackets=ordinary,
        ltcg_brackets=ltcg,
        standard_deduction=base_std * drag,
        additional_65=T.ADDITIONAL_STD_DEDUCTION_65[status] * n_people_65plus,
        personal_exemption=exemption,
        senior_deduction_available=senior_ok,
    )


# ==========================================================================
# Core tax math
# ==========================================================================

def bracket_tax(taxable: float, brackets: Sequence[tuple]) -> float:
    """Progressive tax on `taxable` given (upper_bound, rate) bands."""
    if taxable <= 0:
        return 0.0
    tax = 0.0
    lower = 0.0
    for bound, rate in brackets:
        if taxable <= lower:
            break
        top = min(taxable, bound)
        tax += (top - lower) * rate
        lower = bound
    return tax


def marginal_rate(taxable: float, brackets: Sequence[tuple]) -> float:
    """Statutory marginal rate at a given taxable income."""
    lower = 0.0
    for bound, rate in brackets:
        if taxable <= bound:
            return rate
        lower = bound
    return brackets[-1][1]


def bracket_headroom(taxable: float, brackets: Sequence[tuple],
                     target_rate: float) -> float:
    """
    Dollars of additional ordinary income that fit before exceeding
    `target_rate`. Returns 0 if already above it.
    """
    ceiling = 0.0
    for bound, rate in brackets:
        if rate <= target_rate + 1e-9:
            ceiling = bound
    if ceiling == float("inf"):
        return float("inf")
    return max(0.0, ceiling - taxable)


def taxable_social_security(ss_benefit: float, other_income: float,
                            tax_exempt_interest: float, status: str,
                            deflator: float = 1.0) -> float:
    """
    Portion of Social Security subject to federal income tax.

    `other_income` is AGI excluding Social Security. `deflator` converts the
    unindexed nominal thresholds into the projection's real dollars: pass
    1 / (1 + inflation)^years.
    """
    if ss_benefit <= 0:
        return 0.0

    tier1 = T.SS_PROVISIONAL_TIER1[status] * deflator
    tier2 = T.SS_PROVISIONAL_TIER2[status] * deflator

    provisional = other_income + tax_exempt_interest + 0.5 * ss_benefit

    if provisional <= tier1:
        return 0.0

    if provisional <= tier2:
        return min(0.5 * (provisional - tier1), 0.5 * ss_benefit)

    lower_part = min(0.5 * (tier2 - tier1), 0.5 * ss_benefit)
    upper_part = 0.85 * (provisional - tier2)
    return min(lower_part + upper_part, T.SS_MAX_TAXABLE_SHARE * ss_benefit)


def capital_gains_tax(ordinary_taxable: float, gains: float,
                      brackets: Sequence[tuple]) -> float:
    """
    Preferential-rate tax on long-term gains and qualified dividends. Gains
    stack on top of ordinary income, so ordinary income determines which
    capital-gains band the gains fall into.
    """
    if gains <= 0:
        return 0.0
    tax = 0.0
    lower = max(0.0, ordinary_taxable)
    remaining = gains
    for bound, rate in brackets:
        if remaining <= 0:
            break
        if lower >= bound:
            continue
        chunk = min(remaining, bound - lower)
        tax += chunk * rate
        remaining -= chunk
        lower += chunk
    return tax


def niit_tax(magi: float, net_investment_income: float, status: str,
             deflator: float = 1.0, indexed: bool = False) -> float:
    """3.8% Net Investment Income Tax."""
    if net_investment_income <= 0:
        return 0.0
    threshold = T.NIIT_THRESHOLD[status] * (1.0 if indexed else deflator)
    excess = max(0.0, magi - threshold)
    return T.NIIT_RATE * min(net_investment_income, excess)


def senior_deduction(magi: float, status: str, n_people_65plus: int,
                     amount: float = T.SENIOR_DEDUCTION_AMOUNT) -> float:
    """OBBBA per-person deduction for taxpayers 65+, with its MAGI phase-out."""
    if n_people_65plus <= 0:
        return 0.0
    gross = amount * n_people_65plus
    start = T.SENIOR_DEDUCTION_PHASEOUT_START[status]
    if magi <= start:
        return gross
    reduction = (magi - start) * T.SENIOR_DEDUCTION_PHASEOUT_RATE
    return max(0.0, gross - reduction)


def irmaa_annual(magi_lookback: float, status: str,
                 n_enrolled: int, tiers=None,
                 standard_premium: float = T.IRMAA_PART_B_STANDARD,
                 count_base_premium: bool = True) -> float:
    """
    Annual Medicare Part B + Part D cost, per household.

    `magi_lookback` is MAGI from IRMAA_LOOKBACK_YEARS earlier. `n_enrolled` is
    how many people in the household are on Medicare -- surcharges are per
    person.

    If `count_base_premium` is False, only the IRMAA surcharge above the
    standard premium is counted, which isolates the marginal cost a conversion
    creates.
    """
    if n_enrolled <= 0:
        return 0.0
    tiers = tiers or T.IRMAA_TIERS_2026[status]
    part_b, part_d = tiers[-1][1], tiers[-1][2]
    for bound, b, d in tiers:
        if magi_lookback <= bound:
            part_b, part_d = b, d
            break
    if not count_base_premium:
        part_b = max(0.0, part_b - standard_premium)
    return (part_b + part_d) * 12.0 * n_enrolled


def irmaa_tier_ceilings(status: str, tiers=None) -> list[float]:
    """The MAGI ceilings that trigger each IRMAA step, for cliff-aware filling."""
    tiers = tiers or T.IRMAA_TIERS_2026[status]
    return [b for b, _, _ in tiers if b != float("inf")]


# ==========================================================================
# Household-year assembly
# ==========================================================================

@dataclass
class TaxResult:
    agi: float
    magi: float
    taxable_income: float
    ordinary_taxable: float
    taxable_ss: float
    federal_ordinary_tax: float
    federal_cap_gains_tax: float
    niit: float
    federal_total: float
    state_total: float
    irmaa: float
    total_tax: float
    marginal_rate: float
    deductions: float


def compute_year_tax(
    *,
    regime: Regime,
    status: str,
    wages: float,
    military_pension: float,
    other_pension: float,
    taxable_withdrawals: float,
    conversion: float,
    social_security: float,
    interest_and_nonqual_div: float,
    qualified_dividends: float,
    capital_gains: float,
    tax_exempt_interest: float,
    n_people_65plus: int,
    ss_deflator: float,
    niit_deflator: float,
    index_niit: bool,
    state_tax_amount: float,
    irmaa_amount: float,
) -> TaxResult:
    """Compute one year of federal tax for the household."""

    ordinary_non_ss = (
        wages + military_pension + other_pension + taxable_withdrawals
        + conversion + interest_and_nonqual_div
    )
    preferential = qualified_dividends + capital_gains

    taxable_ss = taxable_social_security(
        social_security,
        ordinary_non_ss + preferential,
        tax_exempt_interest,
        status,
        ss_deflator,
    )

    agi = ordinary_non_ss + preferential + taxable_ss
    magi = agi + tax_exempt_interest

    deductions = regime.standard_deduction + regime.additional_65 + regime.personal_exemption
    if regime.senior_deduction_available:
        deductions += senior_deduction(magi, status, n_people_65plus)

    taxable_income = max(0.0, agi - deductions)
    ordinary_taxable = max(0.0, taxable_income - preferential)

    fed_ordinary = bracket_tax(ordinary_taxable, regime.ordinary_brackets)
    fed_gains = capital_gains_tax(ordinary_taxable, min(preferential, taxable_income),
                                  regime.ltcg_brackets)

    nii = interest_and_nonqual_div + qualified_dividends + capital_gains
    nii_tax = niit_tax(magi, nii, status, niit_deflator, index_niit)

    federal_total = fed_ordinary + fed_gains + nii_tax

    return TaxResult(
        agi=agi,
        magi=magi,
        taxable_income=taxable_income,
        ordinary_taxable=ordinary_taxable,
        taxable_ss=taxable_ss,
        federal_ordinary_tax=fed_ordinary,
        federal_cap_gains_tax=fed_gains,
        niit=nii_tax,
        federal_total=federal_total,
        state_total=state_tax_amount,
        irmaa=irmaa_amount,
        total_tax=federal_total + state_tax_amount + irmaa_amount,
        marginal_rate=marginal_rate(ordinary_taxable, regime.ordinary_brackets),
        deductions=deductions,
    )
