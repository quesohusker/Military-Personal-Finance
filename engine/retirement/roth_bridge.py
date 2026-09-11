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

from engine.profile import (Household, RETIRED, ACTIVE,
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
from engine.pay import bah as BAH
from engine.pay import basepay as BP
from engine.career import timeline as TL
from engine.retirement import tsp as TSP
from engine.retirement import systems as SYS


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
MIN_BIRTH_YEAR, MAX_BIRTH_YEAR = 1930, 2010   # matches the Profile page
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
    wages_this_year: float = 0.0     # 0 = same as wages_annual; see _member_wages
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
    Taxable wages in a NORMAL year: military basic pay and taxable special pays
    for someone still serving (BAH and BAS are not wages), plus any civilian
    job. This is the figure carried forward for every projected year.

    It is deliberately before the Combat Zone Tax Exclusion. A deployment ends;
    growing a reduced wage forward for thirty years would understate a career.
    The current year is handled by _member_wages_this_year().
    """
    return float(TP.compute(m).annual + (m.civilian_wages_annual or 0.0))


def _member_wages_this_year(m) -> float:
    """
    Taxable wages for the first projected year, with the CZTE applied.

    Pay excluded in a combat zone never reaches a return. Modelling a deployed
    member at their full nominal wage overstates income in the one year it
    matters most: the low-tax year right after -- or during -- a deployment is
    the cheapest conversion window most members will ever get, and overstating
    the wage hides it.

    Returns 0.0 when this year is ordinary, meaning "use the normal wage".
    """
    if not m.is_serving or TP.czte_months(m) == 0:
        return 0.0
    return float(TP.annual_after_czte(m) + (m.civilian_wages_annual or 0.0))


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


# --------------------------------------------------------------------------
# The serving years (docs/ARCHITECTURE.md §7 step 4)
# --------------------------------------------------------------------------
#
# `Profile` now has a place to describe being in uniform, and this is what
# fills it. Nothing here models pay: `engine/career/timeline.py` walks the
# career -- promotions, longevity steps, PCS moves, BAH by ZIP --
# `engine/pay/taxable.py` says what of it is taxable, `engine/retirement/tsp.py`
# computes the BRS match and the deferral limit, and `engine/retirement/
# systems.py` prices the pension. This file only asks them, in order, and
# writes down the answer.

#: Guard and Reserve pay is drill pay and a retirement-points record, and the
#: pension starts at 60 rather than at separation. None of that is the
#: active-duty tables, so the schedule refuses rather than running a reservist
#: through them (§8).
RESERVE_NOT_MODELLED = (
    "Guard and Reserve service is not modelled year by year yet. The pay is "
    "drill pay rather than the active-duty table, retirement credit is counted "
    "in points, and the pension starts at 60 instead of at separation. Running "
    "it through the active-duty tables would produce a confident wrong number."
)

NO_PAY_TABLE_NOT_MODELLED = (
    "No basic pay table is installed, so the serving years cannot be priced. "
    "Run `python scripts/refresh_basepay.py` to install one."
)

#: The published tables, loaded once. A BAH file is 41,000 ZIP codes and the
#: bridge is called on every page render, so it is read once per process. Both
#: are static reference data for a given year.
_TABLES: dict = {}


def _pay_tables():
    if "loaded" not in _TABLES:
        try:
            _TABLES["bah"] = BAH.load()
        except Exception:                                    # pragma: no cover
            _TABLES["bah"] = None
        try:
            _TABLES["basepay"] = BP.load()
        except Exception:                                    # pragma: no cover
            _TABLES["basepay"] = None
        _TABLES["loaded"] = True
    return _TABLES["bah"], _TABLES["basepay"]


def _timeline_for(h: Household, timeline=None) -> TL.CareerTimeline:
    """
    The member's own timeline, with the separation point made runnable.

    A separation point already behind the member -- a plan left alone for two
    years, or a timeline that was never opened -- would produce a schedule with
    no years in it, so it is pulled forward to this year rather than dropped.
    `timeline` is the seam for a course of action (§7 step 6): the same
    household, scheduled against a different career.
    """
    t = timeline if timeline is not None else h.career
    if t is None:
        t = TL.CareerTimeline()
    yos = float(h.member.years_of_service or 0.0)
    if float(t.separation_at_years_of_service) < yos:
        t = TL.CareerTimeline(promotions=list(t.promotions), moves=list(t.moves),
                              separation_at_years_of_service=yos,
                              entered=t.entered)
    return t


def _service_assumptions(m, t: TL.CareerTimeline, bah_data, rows) -> list:
    """What the schedule had to stand in for, in the member's own terms."""
    out = []
    if not t.entered:
        out.append(
            "Nobody has answered the Career page for this plan, so it is "
            f"modelled as {t.separation_at_years_of_service:g} years of service "
            f"with no further promotions. Both are answers the member has to "
            f"give; neither is a forecast.")
    elif not t.promotions:
        out.append(f"No further promotions: the pay is {m.grade} pay for the "
                   f"rest of the career, stepping only at longevity boundaries.")
    if bah_data is None:
        out.append("No BAH table is installed, so the housing allowance is "
                   "missing from the pay in every serving year.")
    elif rows and rows[0].bah_monthly <= 0 and not m.lives_in_government_housing:
        out.append("No BAH rate was found for this duty ZIP, so the housing "
                   "allowance is missing from the pay.")
    if not t.moves:
        out.append("No PCS moves are on the timeline, so BAH is held at the "
                   "current duty station's rate for the whole career. A move "
                   "can change it by thousands a month.")
    return out


def build_service(h: Household, inputs: "RothInputs | None" = None, *,
                  start_year: int | None = None,
                  timeline=None) -> RP.MilitaryService:
    """
    The resolved serving years for this household.

    Returns an empty, `serving=False` block for anyone not in uniform -- which
    is what leaves the retiree path exactly as it was.
    """
    m = h.member
    sy = int(start_year or (inputs.start_year if inputs else date.today().year))

    if m is None or not m.is_serving:
        return RP.MilitaryService()
    if m.component != ACTIVE:
        return RP.MilitaryService(serving=False, component=m.component,
                                  grade_now=m.grade,
                                  years_of_service_now=float(m.years_of_service),
                                  not_modelled=RESERVE_NOT_MODELLED)

    bah_data, pay_table = _pay_tables()
    if pay_table is None:                                    # pragma: no cover
        return RP.MilitaryService(serving=False, component=m.component,
                                  grade_now=m.grade,
                                  years_of_service_now=float(m.years_of_service),
                                  not_modelled=NO_PAY_TABLE_NOT_MODELLED)

    t = _timeline_for(h, timeline)
    raise_real = float(getattr(h.assumptions, "pay_raise_real_pct", 0.0)) / 100.0

    def _refuse(reason: str) -> RP.MilitaryService:
        return RP.MilitaryService(serving=False, component=m.component,
                                  grade_now=m.grade,
                                  years_of_service_now=float(m.years_of_service),
                                  not_modelled=reason)

    try:
        rows = TL.project(m, t, sy, bah_data=bah_data, basepay_table=pay_table,
                          annual_raise=raise_real)
    except Exception as exc:
        # A grade the tables do not carry is the case this catches, and it
        # raises from inside the timeline. A projection that cannot price the
        # pay must say so, not run on zeroes.
        return _refuse(f"The serving years could not be priced: {exc}")
    if not rows:                                             # pragma: no cover
        return _refuse("The career timeline produced no years to project.")
    if rows[0].basic_pay_monthly <= 0:
        return _refuse(
            f"No basic pay could be looked up for {m.grade or 'that grade'} at "
            f"{float(m.years_of_service):g} years of service, so there is no "
            f"pay to project. Enter it from your LES on the Income page.")

    is_brs = (m.retirement_system == APP_BRS)
    pct = max(0.0, float(m.tsp_contribution_pct))
    roth_share = min(1.0, max(0.0, float(m.tsp_roth_share)))
    special_taxable = bool(m.special_pay_taxable)

    # The first year is the only one that can be atypical. A deployment is a
    # this-year event: `RothInputs.wages_this_year` carries the Combat Zone Tax
    # Exclusion already applied (see `_member_wages_this_year`), and setting it
    # to 0 means "this year is like every other". The civilian half of that
    # input is not military pay, so it comes back out.
    civilian = float(m.civilian_wages_annual or 0.0)
    first_taxable = None
    if inputs is not None and float(inputs.wages_this_year) > 0:
        first_taxable = max(0.0, float(inputs.wages_this_year) - civilian)

    years = []
    for idx, r in enumerate(rows):
        first = (idx == 0)
        basic_annual = r.basic_pay_monthly * 12.0
        special_annual = r.special_pay_monthly * 12.0
        bonus = float(m.bonus_annual_taxable or 0.0) if first else 0.0

        # Everything the member is paid, and then the part of it a return sees.
        total = (basic_annual + special_annual
                 + (r.bah_monthly + r.bas_monthly) * 12.0 + bonus)
        taxable = basic_annual + (special_annual if special_taxable else 0.0) + bonus
        if first and first_taxable is not None:
            taxable = min(first_taxable, total)
        taxable = max(0.0, min(taxable, total))

        # TSP. The member's own money is a percentage of BASIC pay -- not of
        # total compensation, which is the mistake tsp.py exists to correct --
        # and is bounded by the elective deferral limit for their age. The
        # service's automatic and matching contributions are computed on the
        # uncapped election, because the match follows the percentage rather
        # than the dollars, and they always land in the traditional balance.
        age = r.year - int(m.birth_year)
        own = min(basic_annual * pct, TSP.elective_limit(age))
        own_roth = own * roth_share
        match = TSP.service_match(basic_annual, pct, is_brs,
                                  float(r.years_of_service))

        years.append(RP.ServiceYear(
            year=int(r.year), years_of_service=float(r.years_of_service),
            grade=r.grade, promoted=bool(r.promoted_this_year),
            duty_zip=r.duty_zip or "", duty_label=r.duty_label or "",
            basic_pay_monthly=float(r.basic_pay_monthly),
            taxable_pay=float(taxable), nontaxable_pay=float(total - taxable),
            tsp_member_traditional=float(own - own_roth),
            tsp_member_roth=float(own_roth),
            tsp_service=float(match.total_service)))

    last = rows[-1]
    sv = RP.MilitaryService(
        serving=True, component=m.component, grade_now=m.grade,
        years_of_service_now=float(m.years_of_service),
        separation_year=int(last.year),
        separation_years_of_service=float(last.years_of_service),
        separation_grade=last.grade,
        high_three_monthly=_high_three(rows),
        civilian_wages_annual=civilian,
        civilian_wages_entered=civilian > 0,
        tricare_annual_cost=0.0,          # active duty pays nothing for it
        years=years,
        assumptions=_service_assumptions(m, t, bah_data, rows))

    if not sv.civilian_wages_entered:
        sv.assumptions.append(
            "Nothing in the plan says what you expect to earn after you take "
            "the uniform off, so the projection carries your current taxable "
            "pay forward as a civilian wage from the year after you separate. "
            "That is an assumption, not an answer.")

    # THE ASSUMPTION THAT MOVES THE ENDING BALANCE MORE THAN ANY OTHER, and it
    # was the one nobody had written down.
    #
    # Spending is one figure -- "what do you spend in a month" -- held flat in
    # REAL terms for the whole plan, while military pay steps at every
    # longevity boundary and jumps at every promotion. Everything not spent is
    # reinvested. For a retiree that is close to true: they are at their
    # terminal standard of living and the income is fixed. For someone at six
    # years it implies a savings rate they have not agreed to and would
    # probably not recognise, compounded for forty years, and it is what
    # produces a seven-figure taxable account out of an E-5.
    #
    # The arithmetic is the plan's own and is not second-guessed here: a member
    # who really does bank two thirds of their pay should see that future. But
    # a figure this consequential cannot be silent, so the rate is stated as a
    # number the member can check against their own bank statement. §8: a
    # number with no visible derivation is worse than no number.
    annual_spend = float(h.monthly_expenses or 0.0) * 12.0
    if sv.years and annual_spend > 0:
        first_pay = float(sv.years[0].taxable_pay + sv.years[0].nontaxable_pay)
        if first_pay > annual_spend:
            rate = 1.0 - annual_spend / first_pay
            # Two money figures in one string, so NO dollar signs: Streamlit
            # reads the span between a pair of them as LaTeX and eats both.
            # "in today's dollars" carries the unit instead.
            sv.assumptions.append(
                f"Your spending is held at {annual_spend:,.0f} a year in "
                f"today's dollars for the whole plan, while your pay steps with "
                f"longevity and promotion. Against {first_pay:,.0f} of military "
                f"pay this year that is a saving rate of {rate * 100:.0f}%, and "
                f"everything not spent is invested in a taxable account and "
                f"compounds. If you would not recognise that rate, raise your "
                f"monthly spending figure — it drives the ending balance more "
                f"than any return assumption does.")
    return sv


def _high_three(rows) -> float:
    """
    The high-36 average, off the basic pay the timeline actually produced.

    Fewer than three years on the schedule means a member who is already
    nearly out; averaging the years there are is the closest thing to the
    truth and is what the pension is then priced from.
    """
    if not rows:
        return 0.0
    tail = rows[-3:]
    return sum(r.basic_pay_monthly for r in tail) / len(tail)


def pension_at_separation(m, sv: RP.MilitaryService) -> tuple[float, str]:
    """
    Monthly retired pay the day after separation, in today's dollars, and the
    sentence that says where it came from.

    THE TWENTY-YEAR CLIFF IS APPLIED HERE, FOR EVERY SYSTEM.
    `engine/retirement/systems.py::retired_pay()` zeroes a pension short of
    twenty years for the legacy systems but not for BRS, so a BRS member
    leaving at twelve comes back from it with a pension they will never be
    paid. BRS is gentler than the legacy systems because the member keeps the
    TSP and the vested match -- not because it pays an annuity at twelve years.
    """
    if not sv.serving:
        return 0.0, ""
    system = m.retirement_system
    years = float(sv.separation_years_of_service)
    if system not in (SYS.SYS_FINAL_PAY, SYS.SYS_HIGH3, SYS.SYS_REDUX, SYS.SYS_BRS):
        return 0.0, ("No retirement system could be resolved from the DIEMS "
                     "date, so no pension is modelled.")
    if years < 20.0:
        return 0.0, (f"Separating at {years:g} years is short of twenty, so "
                     f"there is no pension under {system} and none is modelled. "
                     + ("Under BRS the TSP balance and the vested match are "
                        "still yours." if system == SYS.SYS_BRS else
                        "There is no partial credit."))

    # Final Pay is the one system that is not an average: it uses the last
    # month of basic pay.
    base = (sv.years[-1].basic_pay_monthly if (system == SYS.SYS_FINAL_PAY and sv.years)
            else sv.high_three_monthly)
    pay = SYS.retired_pay(system, years, base)
    return float(pay.monthly), (
        f"{pay.multiplier * 100:.0f}% of a ${base:,.0f} "
        f"{'final month of basic pay' if system == SYS.SYS_FINAL_PAY else 'high-3 average'}"
        f" at {years:g} years under {system}.")


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
        wages_this_year=_member_wages_this_year(m),
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
                    start_year: int | None = None,
                    timeline=None) -> Profile:
    """
    Build the engine's Profile from the Household plus the page inputs.

    With `inputs` omitted the defaults are used, which is enough for a valid
    engine profile from any Household -- including an active-duty member with
    no retired pay and nothing to convert.

    `timeline` schedules the serving years against a career other than the one
    on the plan. It is how a course of action gets priced (§7 step 6): stay to
    twenty and leave at twelve are the same household with two timelines, and
    two Profiles the projection can be run over side by side.
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
        wages_first_year=float(i.wages_this_year),
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

    # The serving years, and what they end in. For anyone not in uniform this
    # is an empty block and every line below falls back to what the Household
    # already holds, which is why the retiree path is untouched.
    p.service = build_service(h, i, start_year=sy, timeline=timeline)
    sv = p.service

    system = SYSTEM_MAP.get(m.retirement_system, RP.SYS_NONE)
    has_tricare, tricare_fee, part_b_age = _tricare(h)
    retired_monthly = float(m.retired_pay_monthly)
    retirement_year = _retirement_year(m, sy)
    years_served = float(m.years_of_service)
    if sv.serving:
        retired_monthly, _ = pension_at_separation(m, sv)
        retirement_year = sv.separation_year
        years_served = sv.separation_years_of_service
        # Retiree TRICARE costs what a retiree pays, but only from the year the
        # member becomes one, and only if they reach twenty. Before that it is
        # free, which `service.tricare_annual_cost` carries.
        plan_name = (h.healthcare.tricare_plan or "").strip()
        tricare_fee = (RP.MilitaryRetirement().tricare_annual_cost
                       if (retired_monthly > 0 and plan_name in ("Prime", "Select"))
                       else 0.0)
        if retired_monthly <= 0:
            sv.assumptions.append(
                "Leaving before twenty years means no retiree TRICARE either. "
                "What health cover costs you after that is not modelled.")

    p.military = RP.MilitaryRetirement(
        system=system,
        years_of_service=years_served,
        retired_pay_monthly=retired_monthly,
        retirement_year=retirement_year,
        pension_start_year=sv.pension_start_year,
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
    sv = p.service
    trad = p.primary.traditional_balance + (p.spouse.traditional_balance if p.has_spouse else 0.0)
    roth = p.primary.roth_balance + (p.spouse.roth_balance if p.has_spouse else 0.0)
    state_note = "" if state_is_known(p.state) else " (not in the state table; modelled as no income tax)"
    rule = ST.get_rule(p.state)

    # The serving years, when the plan has any. A pension that has not started
    # has to say when it does, or the figure reads as money arriving now.
    serving_rows = []
    if sv.serving and sv.years:
        first = sv.years[0]
        serving_rows.append((
            "Your years in uniform",
            f"{len(sv.years)} years modelled, {first.year}–{sv.separation_year}: "
            f"{sv.grade_now} at {sv.years_of_service_now:g} years now, "
            f"{sv.separation_grade} at {sv.separation_years_of_service:g} when you "
            f"separate. {money(first.total_pay)} this year, "
            f"{pct(first.nontaxable_share, 0)} of it untaxed."))
        serving_rows.append((
            "High-3 at separation",
            f"{money(sv.high_three_monthly)}/mo, averaged over the last 36 months "
            f"of basic pay the timeline produces"))
    elif sv.not_modelled:
        serving_rows.append(("Your years in uniform", sv.not_modelled))

    pension_when = (f" · from {mil.pension_start_year}"
                    if mil.pension_start_year and mil.retired_pay_monthly > 0 else "")

    if sv.serving and sv.years:
        first = sv.years[0]
        wages_text = (
            f"{money(first.total_pay)} of military pay in {first.year}, "
            f"{money(first.taxable_pay)} of it taxable, stepping with longevity "
            f"and promotion to {sv.separation_year}; then "
            f"{money(p.primary.annual_wages)} a year to "
            f"{p.primary.work_through_year}"
            + ("" if sv.civilian_wages_entered else " (assumed, not entered)"))
    else:
        wages_text = (
            (f"{money(p.primary.wages_first_year)} this year "
             f"(combat-zone pay excluded), then "
             if p.primary.wages_first_year > 0 else "")
            + f"{money(p.primary.annual_wages)} through {p.primary.work_through_year}")
    if p.has_spouse:
        wages_text += (f"; spouse {money(p.spouse.annual_wages)} through "
                       f"{p.spouse.work_through_year}")

    rows = [
        ("Filing status", p.filing_status),
        ("State of legal residence",
         f"{p.state or 'not set'}{state_note} — {pct(rule.rate, 2)} on ordinary income, "
         f"military retired pay {'exempt' if rule.military_pension_exempt >= 1 else 'taxed'}"),
        ("Retirement system", mil.system),
        *serving_rows,
        ("Retired pay, gross", f"{money(mil.retired_pay_monthly * 12)}/yr"
                               + pension_when
                               + (" · SBP elected" if mil.sbp_elected else "")
                               + (" · CRDP" if mil.crdp_applies and mil.va_disability_monthly > 0 else "")),
        ("VA compensation (tax-free)", f"{money(mil.va_disability_monthly * 12)}/yr"
                                       + (f" · {mil.va_rating}%" if mil.va_rating else "")),
        ("Wages this year", wages_text),
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

    # THE ASSUMPTIONS, SURFACED. `build_service()` writes down every place the
    # schedule had to assume something rather than read it, and until now
    # nothing rendered them: five carefully worded lines recorded on the
    # Profile and shown to nobody. That is the §8 failure in its purest form --
    # a projection whose largest inputs are invisible - and `describe()` is the
    # one thing a page actually reads, so they belong here.
    #
    # Numbered, because "Assumption" repeated five times reads as one row in a
    # table and the reader cannot tell there are five.
    for n, note in enumerate(sv.assumptions, 1):
        rows.append((f"Assumption {n} of {len(sv.assumptions)}", note))
    if sv.not_modelled:
        rows.append(("Not modelled", sv.not_modelled))
    return rows
