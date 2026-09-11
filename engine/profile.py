"""
The service member / household profile.

The DIEMS date is the most consequential single field in the whole app: it
determines which retirement system applies, which determines whether there is a
TSP match at all, which reorders the entire financial priority waterfall. Get
it wrong and every downstream recommendation is wrong.
"""

from __future__ import annotations
from dataclasses import dataclass, field, asdict, fields, is_dataclass
from datetime import date
from typing import Any, get_type_hints
import json

from engine.debt.payoff import Debt
from engine.income.spouse import SpouseIncome

# --------------------------------------------------------------------------
# Component
# --------------------------------------------------------------------------
ACTIVE = "Active Duty"
GUARD = "National Guard"
RESERVE = "Reserve"
RETIRED = "Military Retiree"
VETERAN = "Veteran (not retired)"
CIVILIAN = "Civilian"
COMPONENTS = [ACTIVE, GUARD, RESERVE, RETIRED, VETERAN, CIVILIAN]

SERVING = (ACTIVE, GUARD, RESERVE)

# --------------------------------------------------------------------------
# Retirement systems, resolved from DIEMS
# --------------------------------------------------------------------------
SYS_FINAL_PAY = "Final Pay"
SYS_HIGH3 = "High-3"
SYS_REDUX = "CSB/REDUX"
SYS_BRS = "Blended Retirement System"
SYS_NONE = "Not retirement-eligible"
RETIREMENT_SYSTEMS = [SYS_HIGH3, SYS_BRS, SYS_REDUX, SYS_FINAL_PAY, SYS_NONE]

# Statutory DIEMS boundaries.
DIEMS_FINAL_PAY_END = date(1980, 9, 7)
DIEMS_REDUX_START = date(1986, 8, 1)
DIEMS_BRS_START = date(2018, 1, 1)


def retirement_system_for_diems(diems: date | None, took_csb: bool = False,
                                opted_into_brs: bool = False) -> str:
    """
    Resolve the retirement system from the DIEMS date.

    CSB/REDUX is not a DIEMS outcome on its own -- it is an election a member in
    the eligible DIEMS window made at 15 years in exchange for a $30,000 bonus.
    No new elections have been possible since 31 Dec 2017, so for anyone still
    serving this is a historical fact to record, not a decision to model.
    """
    if diems is None:
        return SYS_NONE
    if diems >= DIEMS_BRS_START:
        return SYS_BRS
    if opted_into_brs:
        return SYS_BRS                      # 2018 opt-in window
    if diems <= DIEMS_FINAL_PAY_END:
        return SYS_FINAL_PAY
    if took_csb and diems >= DIEMS_REDUX_START:
        return SYS_REDUX
    return SYS_HIGH3


def has_tsp_match(system: str) -> bool:
    """Only BRS carries service automatic and matching contributions."""
    return system == SYS_BRS


# --------------------------------------------------------------------------
# 2026 statutory limits. Update annually.
# --------------------------------------------------------------------------
@dataclass
class Limits:
    year: int = 2026
    tsp_elective_deferral: float = 24_500.0       # IRC 402(g)
    tsp_catchup_50: float = 8_000.0
    tsp_catchup_60_63: float = 11_250.0           # SECURE 2.0 sec. 109
    tsp_annual_addition: float = 72_000.0         # IRC 415(c)
    ira_contribution: float = 7_500.0
    ira_catchup_50: float = 1_100.0
    sdp_cap: float = 10_000.0
    sdp_apr: float = 0.10
    roth_catchup_wage_threshold: float = 150_000.0  # prior-year wages -> Roth-only catch-up
    czte_officer_monthly_cap: float = 11_391.90


# --------------------------------------------------------------------------
# People
# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
# Plan-wide sub-objects. Each is owned by one page and read by several; they
# live here so a plan file carries them and an older file still loads.
# --------------------------------------------------------------------------
@dataclass
class Assumptions:
    """Every rate the projections use, in one place. Real terms throughout."""
    inflation_pct: float = 2.5
    real_return_pct: float = 4.0            # portfolio return above inflation
    real_discount_rate_pct: float = 3.0     # for valuing guaranteed income
    pay_raise_real_pct: float = 0.0         # military raises track ECI ~ CPI
    cola_full: bool = True                  # REDUX members get CPI minus 1
    tax_scenario: str = "Current law"       # Current law | TCJA sunset | Higher
    planning_margin_years: int = 5          # plan past the median lifespan


@dataclass
class SocialSecurity:
    """From the ssa.gov statement. Military earnings count in full."""
    estimated_monthly_at_fra: float = 0.0
    claim_age: int = 67
    spouse_estimated_monthly_at_fra: float = 0.0
    spouse_claim_age: int = 67
    spouse_on_ssdi: bool = False
    spouse_ssdi_monthly: float = 0.0


@dataclass
class Healthcare:
    tricare_plan: str = "Prime"             # Prime | Select | Reserve Select | For Life
    fedvip_dental_monthly: float = 0.0
    ltc_premium_monthly: float = 0.0
    part_b_when_eligible: bool = True       # TRICARE For Life requires it
    out_of_pocket_annual: float = 0.0


@dataclass
class Housing:
    owns_home: bool = False
    mortgage_rate_pct: float = 0.0
    mortgage_years_left: float = 0.0
    is_va_loan: bool = False
    used_va_entitlement_before: bool = False
    annual_property_tax: float = 0.0
    monthly_rent: float = 0.0
    years_at_this_station: float = 3.0


@dataclass
class Estate:
    has_will: bool = False
    tsp_beneficiary_current: bool = False
    sgli_beneficiary_current: bool = False
    ira_beneficiary_current: bool = False
    n_children: int = 0
    annual_gift_per_child: float = 0.0
    target_legacy_per_child: float = 0.0
    gifting_start_year: int = 2026


@dataclass
class Investments:
    """TSP allocation in percent; the five funds plus one lifecycle fund."""
    tsp_g_pct: float = 0.0
    tsp_f_pct: float = 0.0
    tsp_c_pct: float = 0.0
    tsp_s_pct: float = 0.0
    tsp_i_pct: float = 0.0
    tsp_lifecycle_fund: str = ""            # e.g. "L 2055"; blank = none
    tsp_lifecycle_pct: float = 100.0
    target_equity_pct: float = 80.0
    taxable_equity_pct: float = 0.0


@dataclass
class ServiceMember:
    name: str = ""
    birth_year: int = 1995
    # Only used to pick a mortality table. Life expectancy differs by about
    # three years between the two, which is enough to move the value of a
    # pension or an SBP election by a five-figure sum.
    sex: str = ""
    component: str = ACTIVE
    branch: str = "Army"

    grade: str = "E-5"
    years_of_service: float = 6.0

    # Time in grade, asked two ways. A Date of Rank is a fact off the LES or
    # the ORB that does not change until the next promotion; a number of years
    # is right on the day it is typed and quietly wrong on every later day the
    # plan is opened. So DOR wins when it is set, and the typed number stays
    # for anyone who does not know theirs. Read them through time_in_grade().
    date_of_rank: str = ""                    # ISO text, like diems_date
    time_in_grade_years: float = 2.0          # fallback when there is no DOR

    # DIEMS drives the retirement system. Stored as ISO text so the profile
    # stays JSON-native.
    diems_date: str = "2020-01-01"
    took_csb_redux: bool = False
    opted_into_brs: bool = False

    # Duty location and dependency status drive BAH.
    duty_zip: str = ""
    has_dependents: bool = False
    lives_in_government_housing: bool = False

    # Pay overrides. The LES is authoritative; the tables are a convenience.
    basic_pay_monthly_override: float = 0.0
    bah_monthly_override: float = 0.0
    bas_monthly_override: float = 0.0
    special_pay_monthly: float = 0.0
    special_pay_taxable: bool = True
    # Enlistment, re-enlistment, retention and career-field bonuses, as a
    # lump sum for the year. Taxable unless paid in a combat zone.
    bonus_annual_taxable: float = 0.0

    # Deployment
    is_deployed: bool = False
    months_deployed_this_year: int = 0
    in_combat_zone: bool = False              # drives CZTE
    drawing_hostile_fire_pay: bool = False    # gates SDP eligibility

    # TSP
    tsp_contribution_pct: float = 0.05        # of basic pay
    tsp_roth_share: float = 1.0               # 1.0 = all Roth
    tsp_traditional_balance: float = 0.0
    tsp_roth_balance: float = 0.0
    tsp_has_loan: bool = False

    # IRA
    ira_roth_balance: float = 0.0
    ira_traditional_balance: float = 0.0
    ira_contributed_this_year: float = 0.0

    # SDP
    sdp_balance: float = 0.0

    # Insurance
    sgli_coverage: float = 500_000.0

    # Retiree fields
    retired_pay_monthly: float = 0.0
    va_disability_monthly: float = 0.0
    va_rating: int = 0
    va_rating_permanent_total: bool = False
    crdp_applies: bool = False
    crsc_monthly: float = 0.0
    sbp_elected: bool = False

    # Civilian income (spouse, or a retiree's second career)
    civilian_wages_annual: float = 0.0

    # Leaving the service (non-medical)
    leave_balance_days: float = 0.0
    planned_separation_date: str = ""       # ISO date; blank = not planned

    # Guard and Reserve
    retirement_points: int = 0

    # Student loans
    student_loan_balance: float = 0.0
    student_loan_apr_pct: float = 0.0
    student_loan_federal: bool = True
    student_loan_incurred_before_service: bool = False

    @property
    def diems(self) -> date | None:
        try:
            return date.fromisoformat(self.diems_date)
        except (ValueError, TypeError):
            return None

    @property
    def dor(self) -> date | None:
        """Date of Rank, or None if it was never entered or does not parse."""
        try:
            return date.fromisoformat(self.date_of_rank)
        except (ValueError, TypeError):
            return None

    def time_in_grade(self, as_of: date | None = None) -> float:
        """
        Years in the current grade, from the Date of Rank when there is one.

        A DOR in the future is a typo, not a promotion that has not happened
        yet, so it falls back rather than returning a negative. Everything
        downstream -- the Social Security earnings history in particular --
        reads this rather than the stored number.
        """
        d = self.dor
        if d is None:
            return max(0.0, float(self.time_in_grade_years))
        today = as_of or date.today()
        years = (today - d).days / 365.25
        if years < 0:
            return max(0.0, float(self.time_in_grade_years))
        return years

    @property
    def retirement_system(self) -> str:
        if self.component in (RETIRED,):
            return retirement_system_for_diems(self.diems, self.took_csb_redux,
                                               self.opted_into_brs)
        if self.component not in SERVING:
            return SYS_NONE
        return retirement_system_for_diems(self.diems, self.took_csb_redux,
                                           self.opted_into_brs)

    @property
    def is_serving(self) -> bool:
        return self.component in SERVING

    def age(self, in_year: int | None = None) -> int:
        return (in_year or date.today().year) - self.birth_year


@dataclass
class Household:
    profile_name: str = "Untitled plan"
    member: ServiceMember = field(default_factory=ServiceMember)
    spouse: ServiceMember | None = None
    has_spouse: bool = False
    n_dependents: int = 0

    # Spouse earnings are modelled separately from the service member's, because
    # a military spouse's career is interrupted by every PCS rather than
    # continuous. See engine/income/spouse.py.
    spouse_income: SpouseIncome = field(default_factory=SpouseIncome)

    state_of_legal_residence: str = "Texas"
    current_state: str = "Texas"

    # Cash position
    cash_savings: float = 0.0
    monthly_expenses: float = 0.0
    # What could not be cut if the income stopped -- housing, food, utilities,
    # insurance, healthcare, transport, minimum debt payments. 0.0 means the
    # question has not been answered, NOT that nothing is essential, so read it
    # through engine.funnel.essential_monthly(), which falls back to a share of
    # monthly_expenses. The income-floor component of the scorecard compares
    # guaranteed inflation-linked income against THIS, not against the total.
    essential_monthly_expenses: float = 0.0

    # The age the plan is built around. 0 means not chosen; the scorecard's job
    # is to say whether a target holds, not to invent one.
    target_retirement_age: int = 0

    # Which of the three intake funnels this plan is in: one of
    # engine.funnel.FUNNELS, or "" for never asked. Deliberately NOT a second
    # status field -- engine.funnel.set_funnel() keeps member.component
    # consistent with it, so the app's existing status gates keep working
    # unchanged. Read it through engine.funnel.funnel_of(), which falls back to
    # inference for a plan saved before the question existed.
    funnel: str = ""

    # Balance sheet beyond retirement accounts
    taxable_brokerage: float = 0.0
    home_value: float = 0.0
    mortgage_balance: float = 0.0
    vehicles_value: float = 0.0
    other_assets: float = 0.0

    debts: list = field(default_factory=list)

    assumptions: Assumptions = field(default_factory=Assumptions)
    social_security: SocialSecurity = field(default_factory=SocialSecurity)
    healthcare: Healthcare = field(default_factory=Healthcare)
    housing: Housing = field(default_factory=Housing)
    estate: Estate = field(default_factory=Estate)
    investments: Investments = field(default_factory=Investments)

    limits: Limits = field(default_factory=Limits)
    schema_version: int = 1

    # ----------------------------------------------------------------
    def people(self) -> list[ServiceMember]:
        return [self.member] + ([self.spouse] if (self.has_spouse and self.spouse) else [])

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=_json_default)

    @staticmethod
    def from_dict(data: dict) -> "Household":
        return _build(Household, data)

    @staticmethod
    def from_json(text: str) -> "Household":
        return Household.from_dict(json.loads(text))


def _json_default(o: Any):
    if isinstance(o, tuple):
        return list(o)
    if isinstance(o, date):
        return o.isoformat()
    raise TypeError(f"not serialisable: {type(o)}")


def _build(cls, data: Any):
    """Rebuild nested dataclasses, tolerating keys an older save did not have."""
    if not is_dataclass(cls) or not isinstance(data, dict):
        return data
    hints = get_type_hints(cls)
    kwargs = {}
    for f in fields(cls):
        if f.name not in data:
            continue
        value = data[f.name]
        ftype = hints.get(f.name, f.type)

        if f.name == "debts" and isinstance(value, list):
            kwargs[f.name] = [Debt(**{k: v for k, v in d.items()
                                      if k in {x.name for x in fields(Debt)}})
                              for d in value if isinstance(d, dict)]
            continue
        if f.name == "spouse":
            kwargs[f.name] = _build(ServiceMember, value) if isinstance(value, dict) else None
            continue
        if f.name == "spouse_income" and isinstance(value, dict):
            kwargs[f.name] = _build(SpouseIncome, value)
            continue
        if is_dataclass(ftype) and isinstance(value, dict):
            kwargs[f.name] = _build(ftype, value)
        else:
            kwargs[f.name] = value
    return cls(**kwargs)
