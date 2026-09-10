"""
The bridge from the app's Household to the Roth conversion engine's Profile.

The conversion engine (engine/roth_profile.py, engine/retirement/projection.py)
predates the household model and has its own, much larger, input object. This
module maps what the Household knows onto it. Everything the engine needs that
the Household does not hold becomes a field of RothInputs -- a page-level input
with a defensible default -- rather than a new profile field.

Two traps this file exists to contain:

  * The two Assumptions classes disagree on units. engine/profile.Assumptions
    carries percentages (inflation_pct = 2.5); engine/roth_profile.Assumptions
    carries decimals (inflation = 0.025). Every rate crosses that boundary
    here and nowhere else.
  * The two sides name things differently. The app's "High-3" is the engine's
    "High-3 (Legacy)"; the plan-wide tax_scenario ("Current law" | "TCJA
    sunset" | "Higher") has to become a federal.TaxPolicy; and the engine's
    state table silently treats a name it does not recognise as a no-tax
    state, so free-text residence is resolved before it gets there.

The tax scenarios are NOT redefined here. engine/assumptions.py owns that
vocabulary and owns the mapping onto a TaxPolicy, and the Assumptions page
shows the user the resulting bracket table; a second copy of the names or of
the surcharge size would let this page model a different future from the one
the rest of the app describes.
"""

from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import date

from engine.profile import (Household, RETIRED,
                            SYS_HIGH3 as APP_HIGH3, SYS_REDUX as APP_REDUX,
                            SYS_BRS as APP_BRS, SYS_FINAL_PAY as APP_FINAL_PAY,
                            SYS_NONE as APP_NONE)
from engine import assumptions as A
from engine import roth_profile as RP
from engine.roth_profile import Profile, Person, ConversionPlan
from engine.tax import tables as T
from engine.tax import state as ST
from engine.tax.federal import TaxPolicy, SCENARIO_CURRENT
from engine import mortality as MORT
from engine.pay import taxable as TP
from engine.retirement import tsp as TSP


# --------------------------------------------------------------------------
# Vocabulary shared with the page
# --------------------------------------------------------------------------

# The plan-wide Household.assumptions.tax_scenario values, re-exported so the
# page has one import. engine/assumptions.py is the definition.
TAX_CURRENT = A.TAX_CURRENT
TAX_SUNSET = A.TAX_SUNSET
TAX_HIGHER = A.TAX_HIGHER
TAX_SCENARIOS = list(A.TAX_SCENARIOS)

TAX_SCENARIO_HELP = {
    TAX_CURRENT: ("The 2026 rate schedule holds for the whole projection. The "
                  "One Big Beautiful Bill Act made the TCJA rates permanent, "
                  "so this is the statutory baseline."),
    TAX_SUNSET: ("The pre-2018 schedule returns in the change year: rates of "
                 "10/15/25/28/33/35/39.6%, a standard deduction about half of "
                 "today's, and personal exemptions back."),
    TAX_HIGHER: (f"Every marginal rate rises by {A.HIGHER_POINTS:g} points in "
                 f"the change year — the stress test the Assumptions page "
                 f"describes. The simplest way to ask 'what if taxes go up'."),
}

SYSTEM_MAP = {
    APP_HIGH3: RP.SYS_HIGH3,
    APP_REDUX: RP.SYS_REDUX,
    APP_BRS: RP.SYS_BRS,
    APP_FINAL_PAY: RP.SYS_FINAL_PAY,
    APP_NONE: RP.SYS_NONE,
}

STRATEGIES = [
    ConversionPlan.STRATEGY_BRACKET,
    ConversionPlan.STRATEGY_FIXED,
    ConversionPlan.STRATEGY_IRMAA,
    ConversionPlan.STRATEGY_PERCENT,
    ConversionPlan.STRATEGY_TARGET,
]

DEFAULT_CHANGE_YEAR = TaxPolicy().change_year   # the engine's own default
DEFAULT_SURCHARGE_POINTS = A.HIGHER_POINTS      # what "Higher" means app-wide
DEFAULT_MC_PATHS = 300
MAX_MC_PATHS = 500                # a projection is a few ms; 500 paired paths
                                  # is several seconds, which is the ceiling
                                  # for a page that has to stay responsive
DEFAULT_RETURN_STDEV = 0.14
DEFAULT_INFLATION_STDEV = 0.012
DEFAULT_SEED = 12345
DEFAULT_HEIR_RATE = 0.24
WAGES_STOP_AGE = 65
REDUX_REAL_DRIFT = -0.01

# The page's numeric questions are bounded, and Streamlit REFUSES a value
# outside a widget's range rather than clamping it -- a plan with an old
# member and a generous planning margin used to hand st.number_input a death
# age of 114 and take the whole page down. So the bounds live here, next to
# the defaults that have to satisfy them, and the page imports them.
MIN_BIRTH_YEAR, MAX_BIRTH_YEAR = 1930, 2010   # matches the Who I am page
MAX_PLANNING_AGE = 110
MAX_HORIZON_YEARS = 60            # how far past the start year a year input goes
MAX_BENEFICIARIES = 20

STATE_ABBREVIATIONS = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana",
    "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan",
    "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
    "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey",
    "NM": "New Mexico", "NY": "New York", "NC": "North Carolina",
    "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}


# --------------------------------------------------------------------------
# What the Household does not hold
# --------------------------------------------------------------------------

@dataclass
class RothInputs:
    """
    Everything the engine needs that the Household lacks, fully resolved.

    default_inputs() fills each field from the plan where it can (mortality
    for the death ages, the pay table for a serving member's wages, the RMD
    age for the end of the conversion window) so the page can offer a
    defensible number rather than a blank.
    """
    start_year: int = 2026

    # Work and life
    wages_annual: float = 0.0
    work_through_year: int = 2026
    death_age: int = 90
    spouse_birth_year: int = 1975
    spouse_wages_annual: float = 0.0
    spouse_work_through_year: int = 2026
    spouse_death_age: int = 90

    # Balances the household file does not carry on its own
    spouse_traditional_balance: float = 0.0
    spouse_roth_balance: float = 0.0
    taxable_cost_basis: float = 0.0

    # The conversion being tested
    strategy: str = ConversionPlan.STRATEGY_BRACKET
    target_bracket: float = 0.22
    fixed_amount: float = 50_000.0
    irmaa_tier_index: int = 0
    percent_of_balance: float = 0.06
    target_remaining_balance: float = 0.0
    conversion_start_year: int = 2026
    conversion_end_year: int = 2049
    pay_tax_from_taxable: bool = True
    annual_cap: float = 0.0
    skip_while_working: bool = False

    # Heirs and the survivor
    n_beneficiaries: int = 2
    heir_marginal_rate: float = DEFAULT_HEIR_RATE
    dic_applies: bool = False

    # Future tax law (the scenario itself is plan-wide: h.assumptions)
    tax_change_year: int = DEFAULT_CHANGE_YEAR
    surcharge_points: float = DEFAULT_SURCHARGE_POINTS

    # Monte Carlo
    mc_paths: int = DEFAULT_MC_PATHS
    return_stdev: float = DEFAULT_RETURN_STDEV
    inflation_stdev: float = DEFAULT_INFLATION_STDEV
    random_seed: int = DEFAULT_SEED

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------
# Small resolvers
# --------------------------------------------------------------------------

def resolve_state(text: str) -> str:
    """
    Turn free-text residence into a key of the state table.

    The Household stores the state as typed. The engine's get_rule() answers
    a no-income-tax rule for anything it does not recognise, which would turn
    a typo into a tax-free conversion, so match exactly, then by postal
    abbreviation, then case-insensitively. Unrecognised text is returned as
    is so the page can say so.
    """
    raw = (text or "").strip()
    if not raw:
        return ""
    if raw in ST.STATE_RULES:
        return raw
    up = raw.upper()
    if up in STATE_ABBREVIATIONS:
        return STATE_ABBREVIATIONS[up]
    low = raw.lower()
    for name in ST.STATE_NAMES:
        if name.lower() == low:
            return name
    return raw


def state_is_known(name: str) -> bool:
    return name in ST.STATE_RULES


def _clamp(value, low, high):
    """Keep a plan-derived default inside the range its widget will accept."""
    return max(low, min(high, value))


def tax_policy_for(scenario: str, change_year: int = DEFAULT_CHANGE_YEAR,
                   surcharge_points: float = DEFAULT_SURCHARGE_POINTS) -> TaxPolicy:
    """
    The plan-wide tax_scenario, as the engine's TaxPolicy.

    The scenario -> TaxPolicy mapping belongs to engine/assumptions.py, which
    is also what the Assumptions page renders its bracket table from. Only the
    two page-level dials -- when the change lands, and how big the surcharge is
    -- are applied on top, and the surcharge only where it means anything.
    """
    sc = A.tax_scenarios.get(scenario, A.tax_scenarios[TAX_CURRENT])
    policy = sc.to_tax_policy(int(change_year))
    if sc.points_added:
        policy.surcharge_points = float(surcharge_points)
    return policy


def scenario_policies(change_year: int = DEFAULT_CHANGE_YEAR,
                      surcharge_points: float = DEFAULT_SURCHARGE_POINTS
                      ) -> list[tuple[str, TaxPolicy]]:
    """All three plan-wide scenarios, for sweep_tax_scenarios()."""
    return [(s, tax_policy_for(s, change_year, surcharge_points))
            for s in TAX_SCENARIOS]


def _planning_death_age(birth_year: int, sex: str, start_year: int,
                        margin: int) -> int:
    """
    Life expectancy plus the plan's margin: never in the past, never past
    MAX_PLANNING_AGE.

    The margin is a plan-wide assumption the Assumptions page lets run to
    thirty years, which on top of an older member's life expectancy produces
    an age no widget -- and no useful projection -- will take.
    """
    age_now = max(0, int(start_year) - int(birth_year))
    planned = max(age_now + 1, MORT.planning_age(age_now, sex or "", margin=margin))
    return min(MAX_PLANNING_AGE, planned)


def _member_wages(m) -> float:
    """
    Taxable wages this year: military basic pay and taxable special pays for
    someone still serving (BAH and BAS are not wages), plus any civilian job.
    """
    return float(TP.compute(m).annual + (m.civilian_wages_annual or 0.0))


def _member_contributions(m) -> tuple[float, float]:
    """(traditional, roth) added per year while working, from the TSP election."""
    if not m.is_serving:
        return 0.0, 0.0
    basic = TP.compute(m).basic_monthly * 12.0
    if basic <= 0:
        return 0.0, 0.0
    own = basic * float(m.tsp_contribution_pct)
    roth = own * float(m.tsp_roth_share)
    trad = own - roth
    # Service contributions always land in the traditional balance.
    match = TSP.service_match(basic, float(m.tsp_contribution_pct),
                              m.retirement_system == APP_BRS,
                              float(m.years_of_service))
    return trad + match.total_service, roth


def _retirement_year(m, start_year: int) -> int:
    """Only matters for the REDUX COLA drift. Derived from DIEMS + service."""
    if m.component == RETIRED and m.diems is not None:
        return min(int(start_year), m.diems.year + int(m.years_of_service))
    return int(start_year)


def _healthcare_extras(h: Household) -> float:
    hc = h.healthcare
    return (12.0 * (float(hc.fedvip_dental_monthly) + float(hc.ltc_premium_monthly))
            + float(hc.out_of_pocket_annual))


def _tricare(h: Household) -> tuple[bool, float, int]:
    """(has_tricare, enrollment fee per year, Medicare Part B age)."""
    m = h.member
    hc = h.healthcare
    plan = (hc.tricare_plan or "").strip()
    has = bool(plan) and (m.component == RETIRED or m.is_serving)
    fee = 0.0
    if has and m.component == RETIRED and plan in ("Prime", "Select"):
        fee = RP.MilitaryRetirement().tricare_annual_cost
    # Declining Part B means TRICARE For Life does not work, and no IRMAA.
    part_b_age = RP.MilitaryRetirement().medicare_part_b_age if hc.part_b_when_eligible else 200
    return has, fee, part_b_age


def _first_rmd_year(birth_year: int) -> int:
    return int(birth_year) + T.rmd_age_for_birth_year(int(birth_year))


# --------------------------------------------------------------------------
# Defaults, then the mapping
# --------------------------------------------------------------------------

def default_inputs(h: Household, start_year: int | None = None) -> RothInputs:
    m = h.member
    sy = int(start_year or date.today().year)
    a = h.assumptions
    margin = int(getattr(a, "planning_margin_years", MORT.LONGEVITY_MARGIN_YEARS))

    sp = h.spouse if (h.has_spouse and h.spouse) else None
    # No spouse record: the spouse is modelled as the member's contemporary,
    # which is what the household's own spouse questions assume elsewhere.
    spouse_birth = _clamp(int(sp.birth_year) if sp else int(m.birth_year),
                          MIN_BIRTH_YEAR, MAX_BIRTH_YEAR)
    si = h.spouse_income
    spouse_wages = float(si.annual_income) if (h.has_spouse and si.employed) else 0.0

    liquid = float(h.taxable_brokerage) + float(h.cash_savings)
    n_heirs = (int(h.estate.n_children) or int(h.n_dependents)
               or RP.Heirs().n_beneficiaries)
    last_year = sy + MAX_HORIZON_YEARS

    return RothInputs(
        start_year=sy,
        wages_annual=_member_wages(m),
        work_through_year=_clamp(int(m.birth_year) + WAGES_STOP_AGE, sy, last_year),
        death_age=_planning_death_age(m.birth_year, m.sex, sy, margin),
        spouse_birth_year=spouse_birth,
        spouse_wages_annual=spouse_wages,
        spouse_work_through_year=_clamp(spouse_birth + WAGES_STOP_AGE, sy, last_year),
        spouse_death_age=_planning_death_age(spouse_birth, sp.sex if sp else "",
                                             sy, margin),
        spouse_traditional_balance=(float(sp.tsp_traditional_balance)
                                    + float(sp.ira_traditional_balance)) if sp else 0.0,
        spouse_roth_balance=(float(sp.tsp_roth_balance)
                             + float(sp.ira_roth_balance)) if sp else 0.0,
        # The engine reads a zero basis as "no embedded gain", which is the
        # same thing as basis == balance. Show the user the balance.
        taxable_cost_basis=float(h.taxable_brokerage),
        strategy=ConversionPlan.STRATEGY_BRACKET,
        target_bracket=0.22,
        fixed_amount=50_000.0,
        irmaa_tier_index=0,
        percent_of_balance=0.06,
        target_remaining_balance=0.0,
        conversion_start_year=sy,
        conversion_end_year=_clamp(_first_rmd_year(m.birth_year) - 1, sy, last_year),
        pay_tax_from_taxable=liquid > 0,
        annual_cap=0.0,
        skip_while_working=False,
        n_beneficiaries=_clamp(n_heirs, 1, MAX_BENEFICIARIES),
        heir_marginal_rate=DEFAULT_HEIR_RATE,
        dic_applies=bool(m.va_rating_permanent_total and int(m.va_rating) >= 100),
        tax_change_year=_clamp(max(DEFAULT_CHANGE_YEAR, sy + 1), sy, last_year),
        surcharge_points=DEFAULT_SURCHARGE_POINTS,
        mc_paths=DEFAULT_MC_PATHS,
        return_stdev=DEFAULT_RETURN_STDEV,
        inflation_stdev=DEFAULT_INFLATION_STDEV,
        random_seed=DEFAULT_SEED,
    )


def to_roth_profile(h: Household, inputs: RothInputs | None = None, *,
                    start_year: int | None = None) -> Profile:
    """
    Build the engine's Profile from the Household plus the page inputs.

    With `inputs` omitted the defaults are used, which is enough for a valid
    engine profile from any Household -- including an active-duty member with
    no retired pay and nothing to convert.
    """
    m = h.member
    i = inputs or default_inputs(h, start_year)
    sy = int(i.start_year)
    a = h.assumptions
    ss = h.social_security
    sp = h.spouse if (h.has_spouse and h.spouse) else None

    state = resolve_state(h.state_of_legal_residence)
    rule = ST.get_rule(state)

    p = Profile(profile_name=h.profile_name,
                filing_status=T.MFJ if h.has_spouse else T.SINGLE,
                state=state, has_spouse=bool(h.has_spouse))

    trad_c, roth_c = _member_contributions(m)
    p.primary = Person(
        name=m.name or "",
        birth_year=int(m.birth_year),
        annual_wages=float(i.wages_annual),
        work_through_year=int(i.work_through_year),
        wage_real_growth=(float(a.pay_raise_real_pct) / 100.0 if m.is_serving else 0.0),
        ss_pia_monthly=float(ss.estimated_monthly_at_fra),
        ss_claim_age=int(ss.claim_age),
        death_age=int(i.death_age),
        traditional_balance=float(m.tsp_traditional_balance) + float(m.ira_traditional_balance),
        roth_balance=float(m.tsp_roth_balance) + float(m.ira_roth_balance),
        traditional_contribution=trad_c,
        roth_contribution=roth_c,
    )

    si = h.spouse_income
    sp_contrib = 0.0
    if h.has_spouse and si.employed:
        sp_contrib = float(si.annual_income) * (float(si.retirement_contribution_pct)
                                                + float(si.employer_match_pct))
    p.spouse = Person(
        name=(sp.name if sp else "") or "",
        birth_year=int(i.spouse_birth_year),
        annual_wages=float(i.spouse_wages_annual),
        work_through_year=int(i.spouse_work_through_year),
        ss_pia_monthly=float(ss.spouse_estimated_monthly_at_fra),
        ss_claim_age=int(ss.spouse_claim_age),
        receives_ssdi=bool(ss.spouse_on_ssdi),
        ssdi_monthly=float(ss.spouse_ssdi_monthly),
        death_age=int(i.spouse_death_age),
        traditional_balance=float(i.spouse_traditional_balance),
        roth_balance=float(i.spouse_roth_balance),
        traditional_contribution=sp_contrib,
    )

    system = SYSTEM_MAP.get(m.retirement_system, RP.SYS_NONE)
    has_tricare, tricare_fee, part_b_age = _tricare(h)
    p.military = RP.MilitaryRetirement(
        system=system,
        years_of_service=float(m.years_of_service),
        retired_pay_monthly=float(m.retired_pay_monthly),
        retirement_year=_retirement_year(m, sy),
        cola_real_drift=(REDUX_REAL_DRIFT
                         if (system == RP.SYS_REDUX or not a.cola_full) else 0.0),
        va_disability_monthly=float(m.va_disability_monthly),
        va_rating=int(m.va_rating),
        va_permanent_and_total=bool(m.va_rating_permanent_total),
        crdp_applies=bool(m.crdp_applies),
        crsc_monthly=float(m.crsc_monthly),
        sbp_elected=bool(m.sbp_elected),
        has_tricare=has_tricare,
        tricare_annual_cost=tricare_fee,
        medicare_part_b_age=part_b_age,
    )

    p.taxable = RP.TaxableAccount(
        balance=float(h.taxable_brokerage),
        cost_basis=float(i.taxable_cost_basis),
        cash_balance=float(h.cash_savings),
    )

    r = float(a.real_return_pct) / 100.0
    p.assumptions = RP.Assumptions(
        inflation=float(a.inflation_pct) / 100.0,
        real_return_traditional=r,
        real_return_roth=r,
        real_return_taxable=r,
        start_year=sy,
        discount_rate=float(a.real_discount_rate_pct) / 100.0,
        annual_spending=float(h.monthly_expenses) * 12.0 + _healthcare_extras(h),
        spending_start_year=sy,
    )

    c_start = int(i.conversion_start_year)
    p.conversion = ConversionPlan(
        enabled=True,
        strategy=i.strategy if i.strategy in STRATEGIES else ConversionPlan.STRATEGY_BRACKET,
        start_year=c_start,
        end_year=max(c_start, int(i.conversion_end_year)),
        target_bracket=float(i.target_bracket),
        irmaa_tier_index=int(i.irmaa_tier_index),
        fixed_amount=float(i.fixed_amount),
        percent_of_balance=float(i.percent_of_balance),
        target_remaining_balance=float(i.target_remaining_balance),
        pay_tax_from_taxable=bool(i.pay_tax_from_taxable),
        annual_cap=float(i.annual_cap),
        skip_while_working=bool(i.skip_while_working),
    )

    p.heirs = RP.Heirs(
        n_beneficiaries=max(1, int(i.n_beneficiaries)),
        heir_marginal_rate=float(i.heir_marginal_rate),
        heir_state_rate=float(rule.rate),
    )

    primary_death = int(m.birth_year) + int(i.death_age)
    spouse_death = int(i.spouse_birth_year) + int(i.spouse_death_age)
    p.survivorship = RP.Survivorship(
        model_survivor=True,
        first_death="Primary" if (not h.has_spouse or primary_death <= spouse_death) else "Spouse",
        dic_applies=bool(h.has_spouse and i.dic_applies),
        dic_monthly=T.DIC_BASE_MONTHLY_2026,
        sbp_dic_offset=False,
    )

    p.tax_policy = tax_policy_for(a.tax_scenario, i.tax_change_year, i.surcharge_points)

    p.monte_carlo = RP.MonteCarlo(
        enabled=True,
        n_paths=int(min(max(1, int(i.mc_paths)), MAX_MC_PATHS)),
        return_stdev=float(i.return_stdev),
        inflation_stdev=float(i.inflation_stdev),
        random_seed=int(i.random_seed),
    )
    return p


# --------------------------------------------------------------------------
# What the engine was given, for the page to show
# --------------------------------------------------------------------------

def describe(p: Profile) -> list[tuple[str, str]]:
    """(item, value) pairs, plain text with dollar signs -- escape for markdown."""
    def money(x: float) -> str:
        sign = "-" if x < 0 else ""
        return f"{sign}${abs(x):,.0f}"

    def pct(x: float, dp: int = 1) -> str:
        return f"{x * 100:.{dp}f}%"

    mil = p.military
    a = p.assumptions
    trad = p.primary.traditional_balance + (p.spouse.traditional_balance if p.has_spouse else 0.0)
    roth = p.primary.roth_balance + (p.spouse.roth_balance if p.has_spouse else 0.0)
    state_note = "" if state_is_known(p.state) else " (not in the state table; modelled as no income tax)"
    rule = ST.get_rule(p.state)

    rows = [
        ("Filing status", p.filing_status),
        ("State of legal residence",
         f"{p.state or 'not set'}{state_note} — {pct(rule.rate, 2)} on ordinary income, "
         f"military retired pay {'exempt' if rule.military_pension_exempt >= 1 else 'taxed'}"),
        ("Retirement system", mil.system),
        ("Retired pay, gross", f"{money(mil.retired_pay_monthly * 12)}/yr"
                               + (" · SBP elected" if mil.sbp_elected else "")
                               + (" · CRDP" if mil.crdp_applies and mil.va_disability_monthly > 0 else "")),
        ("VA compensation (tax-free)", f"{money(mil.va_disability_monthly * 12)}/yr"
                                       + (f" · {mil.va_rating}%" if mil.va_rating else "")),
        ("Wages this year", f"{money(p.primary.annual_wages)} through {p.primary.work_through_year}"
                            + (f"; spouse {money(p.spouse.annual_wages)} through "
                               f"{p.spouse.work_through_year}" if p.has_spouse else "")),
        ("Social Security at full retirement age",
         f"{money(p.primary.ss_pia_monthly)}/mo, claimed at {p.primary.ss_claim_age}"
         + (f"; spouse {money(p.spouse.ss_pia_monthly)}/mo at {p.spouse.ss_claim_age}"
            if p.has_spouse else "")),
        ("Traditional (TSP + IRA)", money(trad)),
        ("Roth (TSP + IRA)", money(roth)),
        ("Brokerage and cash", f"{money(p.taxable.balance)} (basis {money(p.taxable.cost_basis)})"
                               f" + {money(p.taxable.cash_balance)} cash"),
        ("Spending", f"{money(a.annual_spending)}/yr, in today's dollars"),
        ("Returns", f"{pct(a.real_return_traditional)} real · inflation {pct(a.inflation)}"
                    f" · discount rate {pct(a.discount_rate)}"),
        ("Planning horizon",
         f"you to {p.primary.death_age}" + (f", spouse to {p.spouse.death_age}" if p.has_spouse else "")
         + " (life expectancy plus the plan's margin)"),
        ("Future federal tax law", p.tax_policy.scenario
         + (f", from {p.tax_policy.change_year}" if p.tax_policy.scenario != SCENARIO_CURRENT else "")),
    ]
    return rows
