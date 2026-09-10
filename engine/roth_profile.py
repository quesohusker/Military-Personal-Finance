"""
The complete input set for the model.

Design rule: the engine reads NOTHING that is not in this file. Every rate,
age, threshold and behavioural assumption is a named field with a default the
user can see and change in the app. If you find yourself wanting a magic number
in projection.py, put it here instead.

The whole structure serialises to plain JSON for local save/load.
"""

from __future__ import annotations
from dataclasses import dataclass, field, asdict, fields, is_dataclass
from typing import Any, get_type_hints
import json

from engine.tax import tables as T
from engine.tax.federal import TaxPolicy, SCENARIO_CURRENT


# --------------------------------------------------------------------------
# Retirement systems -- affects COLA treatment
# --------------------------------------------------------------------------
SYS_HIGH3 = "High-3 (Legacy)"
SYS_REDUX = "REDUX / CSB"
SYS_BRS = "Blended Retirement System"
SYS_FINAL_PAY = "Final Pay"
SYS_NONE = "No military retired pay"
RETIREMENT_SYSTEMS = [SYS_HIGH3, SYS_REDUX, SYS_BRS, SYS_FINAL_PAY, SYS_NONE]


@dataclass
class Person:
    name: str = ""
    birth_year: int = 1975
    birth_month: int = 1

    # Employment
    annual_wages: float = 0.0
    work_through_year: int = 2027          # last year of wage income
    wage_real_growth: float = 0.0          # real growth per year while working

    # Social Security -- PIA is the monthly benefit at Full Retirement Age,
    # in today's dollars. Get it from ssa.gov.
    ss_pia_monthly: float = 0.0
    ss_claim_age: int = 67
    receives_ssdi: bool = False
    ssdi_monthly: float = 0.0

    # Longevity. The projection runs to the later of the two death ages.
    death_age: int = 90

    # Retirement accounts, in today's dollars
    traditional_balance: float = 0.0       # TSP / 401k / traditional IRA
    roth_balance: float = 0.0
    traditional_basis: float = 0.0         # after-tax (non-deductible) basis

    # Ongoing contributions while working, per year
    traditional_contribution: float = 0.0
    roth_contribution: float = 0.0

    # Is this person more than 10 years younger than the account owner?
    # Affects the RMD divisor table. Left as an explicit override.
    rmd_age_override: int = 0              # 0 = use SECURE 2.0 default


@dataclass
class MilitaryRetirement:
    system: str = SYS_HIGH3
    years_of_service: float = 20.0
    retired_pay_monthly: float = 0.0       # gross, today's dollars
    retirement_year: int = 2020

    # COLA. The projection is in real dollars, so a full-CPI COLA means 0.0
    # real drift. REDUX pays CPI minus 1% until the age-62 recomputation, which
    # is a REAL loss of about 1% per year.
    cola_real_drift: float = 0.0
    redux_recompute_age: int = 62
    redux_catchup_applies: bool = True     # one-time restoral at 62

    # VA disability -- tax-free at both federal and state level
    va_disability_monthly: float = 0.0
    va_rating: int = 0
    va_permanent_and_total: bool = False

    # Concurrent receipt. With 20+ years and a rating of 50% or more, CRDP
    # restores retired pay that would otherwise be offset by VA compensation.
    crdp_applies: bool = True
    crsc_monthly: float = 0.0              # tax-free, alternative to CRDP

    # Survivor Benefit Plan
    sbp_elected: bool = True
    sbp_base_amount_monthly: float = 0.0   # 0 means full retired pay
    sbp_premium_rate: float = 0.065        # 6.5% of base amount
    sbp_paid_up: bool = False              # 30 years / age 70

    # Healthcare
    has_tricare: bool = True
    tricare_annual_cost: float = 720.0     # TRICARE Select/Prime enrollment fees
    medicare_part_b_age: int = 65          # required for TRICARE For Life


@dataclass
class OtherIncome:
    """Income streams that are neither wages, military pay, nor Social Security."""
    civilian_pension_monthly: float = 0.0
    civilian_pension_start_age: int = 65
    civilian_pension_cola_real: float = -0.02   # most private pensions are nominal
    civilian_pension_survivor_pct: float = 0.5
    civilian_pension_state_exempt: bool = False

    rental_net_annual: float = 0.0
    other_taxable_annual: float = 0.0
    other_taxfree_annual: float = 0.0


@dataclass
class TaxableAccount:
    """Joint brokerage / cash."""
    balance: float = 0.0
    cost_basis: float = 0.0
    cash_balance: float = 0.0              # emergency fund, not invested
    dividend_yield: float = 0.018          # of balance, paid out annually
    qualified_dividend_share: float = 0.90
    turnover_rate: float = 0.05            # share of gains realised annually
    annual_contribution: float = 0.0


@dataclass
class Assumptions:
    """Returns, inflation and the mechanical rules of the projection."""

    inflation: float = 0.025               # nominal CPI, used only to deflate
                                           # unindexed tax thresholds

    real_return_traditional: float = 0.045
    real_return_roth: float = 0.050
    real_return_taxable: float = 0.045
    real_return_cash: float = 0.005

    # Withdrawal order once portfolio income is needed
    withdrawal_order: tuple = ("cash", "taxable", "traditional", "roth")

    start_year: int = 2026
    rmd_age_override: int = 0              # 0 = SECURE 2.0 by birth year

    # Discounting for the lifetime-total comparison. 0 shows undiscounted real
    # dollars; a positive rate values near-term taxes more heavily.
    discount_rate: float = 0.0

    # Spending, in today's dollars
    annual_spending: float = 0.0
    spending_start_year: int = 2027
    spending_real_drift: float = -0.005    # retirees typically spend less in
                                           # real terms as they age
    survivor_spending_factor: float = 0.75 # spending after one spouse dies
    late_life_care_annual: float = 0.0
    late_life_care_start_age: int = 85


@dataclass
class ConversionPlan:
    """How the 'with conversions' future is executed."""

    enabled: bool = True

    STRATEGY_BRACKET = "Fill to top of a tax bracket"
    STRATEGY_IRMAA = "Fill to an IRMAA tier ceiling"
    STRATEGY_FIXED = "Fixed dollar amount per year"
    STRATEGY_PERCENT = "Fixed percent of traditional balance"
    STRATEGY_TARGET = "Drain traditional to a target by RMD age"

    strategy: str = STRATEGY_BRACKET

    start_year: int = 2027
    end_year: int = 2040

    target_bracket: float = 0.22           # for STRATEGY_BRACKET
    irmaa_tier_index: int = 0              # for STRATEGY_IRMAA (0 = first ceiling)
    fixed_amount: float = 50_000.0         # for STRATEGY_FIXED
    percent_of_balance: float = 0.06       # for STRATEGY_PERCENT
    target_remaining_balance: float = 0.0  # for STRATEGY_TARGET

    # Paying the tax from outside the IRA is what makes conversions work. If
    # False, the tax comes out of the converted amount and lands in the Roth
    # net of tax -- and triggers a 10% penalty before 59.5.
    pay_tax_from_taxable: bool = True

    # Hard ceiling regardless of strategy
    annual_cap: float = 0.0                # 0 = no cap

    # Stop converting once the traditional balance falls below this
    floor_balance: float = 0.0

    # Skip conversions in years the household is still drawing wages
    skip_while_working: bool = False

    early_withdrawal_penalty: float = 0.10
    penalty_free_age: float = 59.5


@dataclass
class Heirs:
    """What happens to what is left over."""
    n_beneficiaries: int = 2
    heir_marginal_rate: float = 0.24       # their bracket during the 10-year drain
    heir_state_rate: float = 0.05
    drain_years: int = 10                  # SECURE Act non-eligible beneficiary
    heir_real_return: float = 0.05
    # Roth inherits tax-free but must also empty in 10 years. Model the value
    # of that extra decade of tax-free growth.
    value_roth_tax_free_growth: bool = True


@dataclass
class Survivorship:
    """Which spouse dies first, and when. Drives the widow's-penalty analysis."""
    model_survivor: bool = True
    first_death: str = "Primary"           # "Primary", "Spouse", or "None"
    first_death_year: int = 0              # 0 = use the person's death_age

    # DIC: tax-free survivor benefit when the veteran was rated totally
    # disabled for the qualifying period, or died of a service-connected cause.
    dic_applies: bool = False
    dic_monthly: float = T.DIC_BASE_MONTHLY_2026

    # Since 2023 SBP is no longer offset by DIC.
    sbp_dic_offset: bool = False


@dataclass
class MonteCarlo:
    enabled: bool = False
    n_paths: int = 1_000
    return_stdev: float = 0.14             # annual stdev of real equity returns
    inflation_stdev: float = 0.012
    correlation_across_accounts: float = 0.95
    random_seed: int = 12345
    mortality_variability: bool = False
    mortality_stdev_years: float = 6.0


@dataclass
class Profile:
    """Everything, in one object."""
    profile_name: str = "Untitled plan"
    filing_status: str = T.MFJ
    state: str = "Texas"
    state_rate_override: float = -1.0      # <0 means use the table
    state_military_exempt_override: int = -1   # -1 = table, 0 = taxed, 1 = exempt

    primary: Person = field(default_factory=Person)
    spouse: Person = field(default_factory=Person)
    has_spouse: bool = True

    military: MilitaryRetirement = field(default_factory=MilitaryRetirement)
    other_income: OtherIncome = field(default_factory=OtherIncome)
    taxable: TaxableAccount = field(default_factory=TaxableAccount)
    assumptions: Assumptions = field(default_factory=Assumptions)
    conversion: ConversionPlan = field(default_factory=ConversionPlan)
    heirs: Heirs = field(default_factory=Heirs)
    survivorship: Survivorship = field(default_factory=Survivorship)
    tax_policy: TaxPolicy = field(default_factory=TaxPolicy)
    monte_carlo: MonteCarlo = field(default_factory=MonteCarlo)

    schema_version: int = 1

    # ----------------------------------------------------------------
    # Serialisation
    # ----------------------------------------------------------------
    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=_json_default)

    @staticmethod
    def from_dict(data: dict) -> "Profile":
        return _build(Profile, data)

    @staticmethod
    def from_json(text: str) -> "Profile":
        return Profile.from_dict(json.loads(text))

    # ----------------------------------------------------------------
    # Derived helpers
    # ----------------------------------------------------------------
    def people(self) -> list[Person]:
        return [self.primary, self.spouse] if self.has_spouse else [self.primary]

    def final_year(self) -> int:
        return max(
            p.birth_year + p.death_age for p in self.people()
        )

    def rmd_age(self, person: Person) -> int:
        if person.rmd_age_override:
            return person.rmd_age_override
        if self.assumptions.rmd_age_override:
            return self.assumptions.rmd_age_override
        return T.rmd_age_for_birth_year(person.birth_year)


def _json_default(o: Any):
    if isinstance(o, tuple):
        return list(o)
    raise TypeError(f"not serialisable: {type(o)}")


def _build(cls, data: Any):
    """
    Reconstruct nested dataclasses from a plain dict, ignoring stale keys so an
    older saved file still loads after the schema grows.

    `from __future__ import annotations` makes every field type a string, so
    resolve them through get_type_hints rather than reading f.type directly.
    """
    if not is_dataclass(cls) or not isinstance(data, dict):
        return data

    hints = get_type_hints(cls)
    kwargs = {}
    for f in fields(cls):
        if f.name not in data:
            continue
        value = data[f.name]
        ftype = hints.get(f.name, f.type)
        if is_dataclass(ftype) and isinstance(value, dict):
            kwargs[f.name] = _build(ftype, value)
        elif ftype is tuple and isinstance(value, list):
            kwargs[f.name] = tuple(value)
        else:
            kwargs[f.name] = value
    return cls(**kwargs)


def validate(p: Profile) -> list[str]:
    """Return a list of human-readable problems. Empty means the plan is sane."""
    issues = []

    for label, person in (("You", p.primary), ("Spouse", p.spouse)):
        if not p.has_spouse and label == "Spouse":
            continue
        if person.birth_year < 1930 or person.birth_year > 2015:
            issues.append(f"{label}: birth year {person.birth_year} looks wrong.")
        if not (T.SS_MIN_CLAIM_AGE <= person.ss_claim_age <= T.SS_MAX_CLAIM_AGE):
            issues.append(
                f"{label}: Social Security claim age must be between "
                f"{T.SS_MIN_CLAIM_AGE} and {T.SS_MAX_CLAIM_AGE}.")
        if person.death_age <= (p.assumptions.start_year - person.birth_year):
            issues.append(f"{label}: assumed death age is in the past.")

    if p.conversion.enabled and p.conversion.end_year < p.conversion.start_year:
        issues.append("Conversion window ends before it starts.")

    total_traditional = sum(x.traditional_balance for x in p.people())
    if p.conversion.enabled and total_traditional <= 0:
        issues.append(
            "No traditional balance to convert -- the two futures will be identical.")

    if p.assumptions.annual_spending <= 0:
        issues.append(
            "Annual spending is zero. The model will never draw on the portfolio, "
            "which will overstate both futures.")

    if p.conversion.pay_tax_from_taxable and p.taxable.balance + p.taxable.cash_balance <= 0:
        issues.append(
            "You chose to pay conversion tax from a taxable account, but the "
            "taxable balance is zero. Tax will come out of the conversion instead.")

    return issues
