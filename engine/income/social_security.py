"""
Social Security for a military household: what the benefit is, and when to
claim it.

THE STATEMENT IS THE ANSWER. The one figure that matters -- the monthly benefit
at full retirement age, which Social Security calls the Primary Insurance
Amount (PIA) -- is printed on the ssa.gov statement, computed from the actual
earnings record. Nothing this module estimates is as good as that number, so
the primary path is: type in the statement figure, and the module does the
claiming arithmetic around it. The fallback, for a member who has not pulled
the statement yet, reconstructs a career of covered earnings from the basic pay
table and the default promotion timeline. It is a rough number and the page
says so.

What a civilian tool gets wrong about a military record, stated once here and
repeated to the user on the page:

  * Military earnings have been fully covered by Social Security since 1957.
    Basic pay carries FICA; BAH and BAS do not. So covered earnings are BASIC
    PAY ONLY -- a quarter to a third below what a member lives on -- and the
    fallback models exactly that.
  * Military retired pay does NOT trigger the Windfall Elimination Provision
    or the Government Pension Offset. Those applied to pensions earned in work
    NOT covered by Social Security; military service is covered. Both were
    repealed for everyone by the Social Security Fairness Act signed in January
    2025, so the question is moot even for a later civil-service pension.
  * Neither retired pay nor VA compensation reduces a Social Security benefit,
    and Social Security reduces neither of them.
  * Active duty between 1957 and 2001 earned "special extra earnings credits":
    $300 a quarter for 1957-1977, and $100 per $300 of basic pay up to $1,200 a
    year for 1978-2001, added to the record when the benefit is computed.
    Nothing since 2002.
  * A combat zone exempts pay from income tax, NOT from FICA, so a tax-free
    deployment year still builds the record in full.

PARAMETERS. The bend points, the taxable maximum and the earnings-test exempt
amounts are the 2026 figures. They came from secondary sources because this
machine cannot reach ssa.gov -- VERIFY them against
https://www.ssa.gov/oact/cola/bendpoints.html and
https://www.ssa.gov/oact/cola/cbb.html before relying on the fallback. The
taxation thresholds ($25,000 / $32,000 and $34,000 / $44,000) are statutory and
unindexed since 1984 and 1993, so they need no annual update -- that is the
whole problem with them.

Everything is in today's dollars. Social Security is indexed to CPI, so a real
benefit is a level benefit: the claim-age comparison needs no inflation growth,
and the only rate that enters it is the household's real discount rate.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date
import math

from engine import mortality as MORT
from engine.tax import tables as T
from engine.tax.federal import taxable_social_security
from engine.pay import basepay as BP, grades as G
from engine.career import timeline as TL
from engine.networth.balance_sheet import annuity_present_value


# ==========================================================================
# Parameters. VERIFY the 2026 figures against ssa.gov.
# ==========================================================================

PARAMETER_YEAR = 2026

# PIA formula bend points for a worker first eligible (turning 62) in 2026.
# 90% of AIME to the first, 32% to the second, 15% above it.
BEND_POINT_1 = 1_286.0
BEND_POINT_2 = 7_749.0
PIA_RATES = (0.90, 0.32, 0.15)

# Maximum earnings subject to Social Security tax, 2026.
TAXABLE_MAXIMUM = 184_500.0

# Retirement earnings test, 2026: $1 withheld per $2 over the exempt amount
# before the year you reach FRA; $1 per $3 over the higher amount in that year.
EARNINGS_TEST_EXEMPT = 24_480.0
EARNINGS_TEST_EXEMPT_FRA_YEAR = 65_160.0
EARNINGS_TEST_WITHHOLDING = 0.5

PARAMETER_NOTE = (
    f"Bend points (${BEND_POINT_1:,.0f} and ${BEND_POINT_2:,.0f}), "
    f"the ${TAXABLE_MAXIMUM:,.0f} taxable maximum and the "
    f"${EARNINGS_TEST_EXEMPT:,.0f} earnings-test exempt amount are the "
    f"{PARAMETER_YEAR} figures, taken from secondary sources because this "
    f"machine cannot reach ssa.gov. Verify them at ssa.gov/oact/cola before "
    f"relying on the estimate."
)

COMPUTATION_YEARS = 35             # highest 35 years of indexed earnings
MIN_CLAIM_AGE = 62
MAX_CLAIM_AGE = 70
SURVIVOR_MIN_CLAIM_AGE = 60

# Worker's own benefit relative to PIA.
EARLY_REDUCTION_FIRST_36 = 5.0 / 9.0 / 100.0    # per month, first 36 months
EARLY_REDUCTION_BEYOND_36 = 5.0 / 12.0 / 100.0  # per month beyond 36
DELAYED_CREDIT_PER_MONTH = 0.08 / 12.0          # 8% a year, to age 70

# Spousal benefit: up to half the worker's PIA, reduced on a steeper schedule
# than the worker's own benefit, and never increased by delayed credits.
SPOUSAL_SHARE = 0.50
SPOUSAL_REDUCTION_FIRST_36 = 25.0 / 36.0 / 100.0
SPOUSAL_REDUCTION_BEYOND_36 = 5.0 / 12.0 / 100.0

# Survivor benefit: 100% of what the deceased was receiving, including delayed
# credits. If the deceased had claimed early, the survivor gets at least 82.5%
# of the PIA (the "RIB-LIM" floor). A survivor claiming at 60 gets 71.5%.
SURVIVOR_FLOOR_SHARE = 0.825
SURVIVOR_SHARE_AT_60 = 0.715

# Special extra earnings credits for active duty, 1978-2001. (1957-1977 was
# $300 a quarter, which also caps at $1,200 a year; the same rule is applied.)
EXTRA_CREDIT_LAST_YEAR = 2001
EXTRA_CREDIT_PER_300_OF_PAY = 100.0
EXTRA_CREDIT_ANNUAL_CAP = 1_200.0

# Taxation of benefits: provisional income = other AGI + tax-exempt interest
# + half the benefit. Statutory, unindexed.
PROVISIONAL_TIER1 = dict(T.SS_PROVISIONAL_TIER1)   # $25,000 single / $32,000 joint
PROVISIONAL_TIER2 = dict(T.SS_PROVISIONAL_TIER2)   # $34,000 single / $44,000 joint
MAX_TAXABLE_SHARE = T.SS_MAX_TAXABLE_SHARE          # 85%

SOURCE_STATEMENT = "Your ssa.gov statement"
SOURCE_ESTIMATE = "Estimated from a modelled career"
SOURCE_NONE = "No basis yet"

MILITARY_FACTS = [
    ("Military earnings are fully covered. Basic pay has carried Social "
     "Security tax since 1957 — but only basic pay. BAH and BAS are not "
     "wages for FICA, so your covered earnings are a quarter to a third "
     "below what you live on, and your statement reflects that."),
    ("WEP and GPO do not apply to military retired pay. The Windfall "
     "Elimination Provision and Government Pension Offset reduced benefits "
     "for pensions earned in work NOT covered by Social Security; military "
     "service is covered. Both were repealed outright by the Social Security "
     "Fairness Act signed in January 2025, so they no longer apply to a "
     "later civil-service pension either."),
    ("VA compensation and retired pay do not reduce Social Security, and "
     "Social Security does not reduce them. The three stack in full. The only "
     "interaction is tax: retired pay counts toward the provisional income "
     "that decides how much of your benefit is taxed; VA compensation does "
     "not."),
    ("Service before 2002 earned extra credits. Active duty from 1957 to 2001 "
     "added special extra earnings to your record — $100 for every $300 of "
     "basic pay, up to $1,200 a year, for 1978–2001. They are applied when "
     "your benefit is computed, not shown on the statement. Nothing accrues "
     "for service since 2002."),
    ("A combat zone exempts pay from income tax, not from Social Security "
     "tax. A tax-free deployment year still builds your record in full."),
    ("SSDI converts to a retirement benefit at full retirement age at the same "
     "amount. A spouse on SSDI is already receiving their full PIA; there is "
     "no early-claiming reduction to worry about and no claim-age decision to "
     "make for them."),
]


# ==========================================================================
# Full retirement age, and the claim-age arithmetic
# ==========================================================================

def full_retirement_age_months(birth_year: int) -> int:
    """
    FRA in whole months. 65 for 1937 and earlier, rising two months a year to
    66 for 1943–1954, then two months a year again to 67 for 1960 and later.
    (Social Security treats a 1 January birthday as the prior year; the app
    only knows the year, so it cannot.)
    """
    if birth_year <= 1937:
        return 65 * 12
    if birth_year <= 1942:
        return 65 * 12 + 2 * (birth_year - 1937)
    if birth_year <= 1954:
        return 66 * 12
    if birth_year <= 1959:
        return 66 * 12 + 2 * (birth_year - 1954)
    return 67 * 12


def full_retirement_age(birth_year: int) -> tuple[int, int]:
    """(years, months)."""
    return divmod(full_retirement_age_months(birth_year), 12)


def fra_years(birth_year: int) -> float:
    return full_retirement_age_months(birth_year) / 12.0


def fra_label(birth_year: int) -> str:
    y, mo = full_retirement_age(birth_year)
    if mo == 0:
        return f"{y}"
    return f"{y} and {mo} month{'s' if mo != 1 else ''}"


def _months(age_years: float) -> int:
    return int(round(float(age_years) * 12.0))


def _clamp_claim_months(claim_age: float) -> int:
    return min(max(_months(claim_age), MIN_CLAIM_AGE * 12), MAX_CLAIM_AGE * 12)


def claim_factor(birth_year: int, claim_age: float) -> float:
    """
    The worker's own benefit as a multiple of PIA, by claim age.

    Early: 5/9 of 1% a month for the first 36 months before FRA, 5/12 of 1% a
    month beyond that. Late: 8% a year (2/3 of 1% a month) to 70, nothing
    after. With FRA 67 that is 70% at 62 and 124% at 70. Claim ages outside
    62–70 are clamped, because nothing happens outside that window.
    """
    claim_m = _clamp_claim_months(claim_age)
    fra_m = full_retirement_age_months(birth_year)
    if claim_m < fra_m:
        early = fra_m - claim_m
        reduction = (min(early, 36) * EARLY_REDUCTION_FIRST_36
                     + max(0, early - 36) * EARLY_REDUCTION_BEYOND_36)
        return max(0.0, 1.0 - reduction)
    return 1.0 + (claim_m - fra_m) * DELAYED_CREDIT_PER_MONTH


def benefit_at(pia: float, birth_year: int, claim_age: float) -> float:
    return max(0.0, pia) * claim_factor(birth_year, claim_age)


def spousal_factor(birth_year: int, claim_age: float) -> float:
    """
    Spousal benefit relative to its full amount. 25/36 of 1% a month for the
    first 36 months early, 5/12 of 1% beyond; 65% of the full amount at 62
    with FRA 67. No delayed credits — a spousal benefit peaks at FRA.
    """
    claim_m = _clamp_claim_months(claim_age)
    fra_m = full_retirement_age_months(birth_year)
    if claim_m >= fra_m:
        return 1.0
    early = fra_m - claim_m
    reduction = (min(early, 36) * SPOUSAL_REDUCTION_FIRST_36
                 + max(0, early - 36) * SPOUSAL_REDUCTION_BEYOND_36)
    return max(0.0, 1.0 - reduction)


# ==========================================================================
# Cumulative benefits and breakeven
# ==========================================================================

def cumulative_benefit(monthly: float, claim_age: float, through_age: float) -> float:
    """Real dollars received from claim age to `through_age`. No growth: COLA'd."""
    return max(0.0, float(through_age) - float(claim_age)) * 12.0 * monthly


def present_value_of_benefit(monthly: float, claim_age: float, through_age: float,
                             real_rate: float, valued_at: float = MIN_CLAIM_AGE) -> float:
    """The same stream discounted at the household's real rate, valued at 62."""
    years = max(0.0, float(through_age) - float(claim_age))
    return annuity_present_value(monthly * 12.0, years, real_rate,
                                 deferral_years=max(0.0, float(claim_age) - valued_at))


def breakeven_age(monthly_early: float, early_age: float,
                  monthly_late: float, late_age: float,
                  real_rate: float = 0.0) -> float | None:
    """
    The age at which the later, larger benefit has paid out as much in total
    as the earlier, smaller one. Undiscounted it is closed-form; with a real
    discount rate it is found by scanning month by month. None if the later
    claim never catches up.
    """
    if monthly_late <= monthly_early or late_age <= early_age:
        return None
    if abs(real_rate) < 1e-9:
        return ((monthly_late * late_age - monthly_early * early_age)
                / (monthly_late - monthly_early))
    for m in range(int(round(late_age * 12)), 120 * 12 + 1):
        age = m / 12.0
        late = present_value_of_benefit(monthly_late, late_age, age, real_rate)
        early = present_value_of_benefit(monthly_early, early_age, age, real_rate)
        if late >= early - 1e-6:
            return age
    return None


# ==========================================================================
# Spousal and survivor benefits
# ==========================================================================

@dataclass
class SpousalResult:
    worker_pia: float = 0.0
    spouse_own_pia: float = 0.0
    spouse_claim_age: float = 67.0
    spouse_fra_label: str = ""
    own_benefit: float = 0.0            # own PIA adjusted for the spouse's claim age
    spousal_excess_full: float = 0.0    # half the worker's PIA less the spouse's own PIA
    spousal_excess_paid: float = 0.0    # after the early-claiming reduction
    total: float = 0.0
    share_of_worker_pia: float = 0.0
    note: str = ""


def spousal_benefit(worker_pia: float, spouse_own_pia: float,
                    spouse_birth_year: int, spouse_claim_age: float,
                    own_is_fixed: bool = False) -> SpousalResult:
    """
    What a spouse receives once both have filed: their own benefit, topped up
    to half the worker's PIA if their own is smaller. The top-up is reduced if
    the spouse claims before their own FRA and never grows past FRA, so a
    spouse with no record of their own peaks at exactly 50% of the worker's
    PIA. `own_is_fixed` is for a spouse on SSDI, whose own benefit is already
    their full PIA regardless of age.
    """
    r = SpousalResult(worker_pia=max(0.0, worker_pia),
                      spouse_own_pia=max(0.0, spouse_own_pia),
                      spouse_claim_age=spouse_claim_age,
                      spouse_fra_label=fra_label(spouse_birth_year))
    if own_is_fixed:
        r.own_benefit = r.spouse_own_pia
    else:
        r.own_benefit = benefit_at(r.spouse_own_pia, spouse_birth_year, spouse_claim_age)
    r.spousal_excess_full = max(0.0, SPOUSAL_SHARE * r.worker_pia - r.spouse_own_pia)
    r.spousal_excess_paid = (r.spousal_excess_full
                             * spousal_factor(spouse_birth_year, spouse_claim_age))
    r.total = r.own_benefit + r.spousal_excess_paid
    r.share_of_worker_pia = (r.total / r.worker_pia) if r.worker_pia > 0 else 0.0

    if r.worker_pia <= 0:
        r.note = "No worker benefit to draw a spousal benefit from."
    elif r.spousal_excess_full <= 0:
        r.note = ("Their own benefit is already at least half of yours, so the "
                  "spousal benefit adds nothing. They claim on their own record.")
    elif spousal_factor(spouse_birth_year, spouse_claim_age) < 1.0:
        r.note = (f"Claiming at {spouse_claim_age:g}, before their full retirement "
                  f"age of {r.spouse_fra_label}, cuts the spousal top-up to "
                  f"{spousal_factor(spouse_birth_year, spouse_claim_age) * 100:.0f}% "
                  f"of its full amount. Unlike your own benefit it never grows "
                  f"past FRA, so there is no reason for them to wait beyond it "
                  f"for this part.")
    else:
        r.note = ("The spousal top-up peaks at full retirement age — there are "
                  "no delayed credits on it. Waiting past FRA raises only their "
                  "own benefit, not this one.")
    return r


@dataclass
class SurvivorResult:
    deceased_pia: float = 0.0
    deceased_claim_age: float = 67.0
    deceased_benefit: float = 0.0
    survivor_own_benefit: float = 0.0
    survivor_benefit: float = 0.0       # entitlement on the deceased's record
    survivor_receives: float = 0.0      # the larger of own and survivor
    household_before: float = 0.0
    household_after: float = 0.0
    monthly_drop: float = 0.0
    floor_applied: bool = False
    note: str = ""


def survivor_benefit(deceased_pia: float, deceased_birth_year: int,
                     deceased_claim_age: float, survivor_own_benefit: float) -> SurvivorResult:
    """
    A widow or widower at or past their own FRA receives 100% of what the
    deceased was receiving — delayed credits included — or their own benefit,
    whichever is larger; not both. If the deceased had claimed early the
    survivor is floored at 82.5% of the PIA. This is why the higher earner's
    claim age is a decision about the survivor's income, not just their own.
    """
    r = SurvivorResult(deceased_pia=max(0.0, deceased_pia),
                       deceased_claim_age=deceased_claim_age,
                       survivor_own_benefit=max(0.0, survivor_own_benefit))
    r.deceased_benefit = benefit_at(r.deceased_pia, deceased_birth_year, deceased_claim_age)
    r.survivor_benefit = r.deceased_benefit
    if _clamp_claim_months(deceased_claim_age) < full_retirement_age_months(deceased_birth_year):
        floor = SURVIVOR_FLOOR_SHARE * r.deceased_pia
        if floor > r.survivor_benefit:
            r.survivor_benefit = floor
            r.floor_applied = True
    r.survivor_receives = max(r.survivor_own_benefit, r.survivor_benefit)
    r.household_before = r.survivor_own_benefit + r.deceased_benefit
    r.household_after = r.survivor_receives
    r.monthly_drop = max(0.0, r.household_before - r.household_after)

    if r.deceased_pia <= 0:
        r.note = "No benefit on this record for a survivor to inherit."
    elif r.survivor_own_benefit >= r.survivor_benefit:
        r.note = ("The survivor's own benefit is the larger one, so they keep "
                  "it and the deceased's benefit simply stops.")
    elif r.floor_applied:
        r.note = (f"Because the benefit was claimed before full retirement age, "
                  f"the survivor is floored at {SURVIVOR_FLOOR_SHARE * 100:.1f}% of "
                  f"the PIA rather than inheriting the reduced amount.")
    else:
        r.note = ("The survivor inherits the full benefit, delayed credits "
                  "included, for life. Their own benefit stops — a household "
                  "goes from two checks to the larger one.")
    return r


# ==========================================================================
# Taxation of benefits
# ==========================================================================

@dataclass
class TaxationResult:
    ss_annual: float = 0.0
    other_income: float = 0.0
    married: bool = False
    status: str = ""
    provisional_income: float = 0.0
    tier1: float = 0.0
    tier2: float = 0.0
    taxable_amount: float = 0.0
    taxable_share: float = 0.0
    tax_exempt_interest: float = 0.0
    note: str = ""


ROTH_NOTE = (
    "A Roth CONVERSION is ordinary income in the year you do it, so it raises "
    "provisional income and can drag more of that year's benefit into tax — "
    "which is one reason to finish converting before benefits start. A Roth "
    "WITHDRAWAL is the reverse: it is not in provisional income at all, so "
    "spending from Roth in retirement keeps the benefit's taxable share down "
    "in a way a traditional TSP withdrawal cannot."
)


def taxation(ss_annual: float, other_income: float, married: bool,
             tax_exempt_interest: float = 0.0) -> TaxationResult:
    """
    How much of an annual benefit is subject to federal income tax, at
    today's thresholds. Up to 50% between the tiers, up to 85% above the
    second. The thresholds are not indexed, so in real terms they fall every
    year; the retirement projection deflates them, this snapshot does not.
    """
    status = T.MFJ if married else T.SINGLE
    r = TaxationResult(ss_annual=max(0.0, ss_annual), other_income=max(0.0, other_income),
                       married=married, status=status,
                       tier1=float(PROVISIONAL_TIER1[status]),
                       tier2=float(PROVISIONAL_TIER2[status]),
                       tax_exempt_interest=max(0.0, tax_exempt_interest))
    r.provisional_income = r.other_income + r.tax_exempt_interest + 0.5 * r.ss_annual
    r.taxable_amount = taxable_social_security(r.ss_annual, r.other_income,
                                               r.tax_exempt_interest, status)
    r.taxable_share = (r.taxable_amount / r.ss_annual) if r.ss_annual > 0 else 0.0

    if r.ss_annual <= 0:
        r.note = "No benefit yet, so nothing to tax."
    elif r.provisional_income <= r.tier1:
        r.note = (f"Provisional income of ${r.provisional_income:,.0f} is under the "
                  f"${r.tier1:,.0f} threshold, so none of the benefit is taxed. "
                  f"Every dollar of other income above that starts pulling it in.")
    elif r.provisional_income <= r.tier2:
        r.note = (f"Provisional income of ${r.provisional_income:,.0f} sits between "
                  f"${r.tier1:,.0f} and ${r.tier2:,.0f}, so "
                  f"{r.taxable_share * 100:.0f}% of the benefit is taxed. In this "
                  f"band each extra dollar of other income makes 50 cents more of "
                  f"the benefit taxable — a 12% bracket behaves like 18%.")
    else:
        r.note = (f"Provisional income of ${r.provisional_income:,.0f} is above the "
                  f"${r.tier2:,.0f} threshold, so {r.taxable_share * 100:.0f}% of "
                  f"the benefit is taxed"
                  + (". That is the 85% ceiling — once there, extra income no "
                     "longer changes the share, only the rate on it."
                     if r.taxable_share >= MAX_TAXABLE_SHARE - 1e-6 else
                     ". Until the 85% ceiling, each extra dollar of other income "
                     "makes 85 cents more of the benefit taxable — a 22% bracket "
                     "behaves like 40.7%."))
    return r


def taxation_ramp(ss_annual: float, married: bool,
                  other_income_steps=(0, 20_000, 40_000, 60_000, 80_000, 100_000)):
    """Taxable share at a range of other-income levels, for a small table."""
    return [(o, taxation(ss_annual, o, married)) for o in other_income_steps]


# ==========================================================================
# Fallback: a career of covered earnings -> AIME -> PIA
# ==========================================================================

@dataclass
class EarningsYear:
    calendar_year: int = 0
    age: int = 0
    years_of_service: float = 0.0
    grade: str = ""
    source: str = ""                  # "Military" | "Civilian"
    earnings: float = 0.0             # basic pay, or civilian wages
    extra_credit: float = 0.0         # pre-2002 special extra earnings
    covered: float = 0.0              # what counts, after the taxable maximum


@dataclass
class EarningsEstimate:
    found: bool = False
    years: list = field(default_factory=list)
    n_military_years: int = 0
    n_civilian_years: int = 0
    n_years_counted: int = 0          # non-zero years among the top 35
    top_years_total: float = 0.0
    aime: float = 0.0
    pia_at_current_bend_points: float = 0.0
    pia: float = 0.0
    bend_points_year: int = PARAMETER_YEAR
    bend_points: tuple = (BEND_POINT_1, BEND_POINT_2)
    real_wage_growth_pct: float = 0.0
    wage_growth_factor: float = 1.0
    separation_yos: float = 0.0
    note: str = ""
    assumptions: list = field(default_factory=list)


def extra_earnings_credit(calendar_year: int, basic_pay_annual: float) -> float:
    """Special extra earnings for active duty through 2001."""
    if calendar_year > EXTRA_CREDIT_LAST_YEAR or basic_pay_annual <= 0:
        return 0.0
    return min(EXTRA_CREDIT_ANNUAL_CAP,
               math.floor(basic_pay_annual / 300.0) * EXTRA_CREDIT_PER_300_OF_PAY)


def aime_from_earnings(covered_earnings) -> float:
    """
    Average Indexed Monthly Earnings: the highest 35 years, zeros filling any
    shortfall, divided by 420 months, rounded down to the dollar.
    """
    top = sorted((max(0.0, float(x)) for x in covered_earnings), reverse=True)[:COMPUTATION_YEARS]
    return float(math.floor(sum(top) / (COMPUTATION_YEARS * 12.0)))


def pia_from_aime(aime: float, bend1: float = BEND_POINT_1,
                  bend2: float = BEND_POINT_2) -> float:
    """The bend-point formula, rounded down to the dime as Social Security does."""
    a = max(0.0, aime)
    r1, r2, r3 = PIA_RATES
    pia = (r1 * min(a, bend1)
           + r2 * max(0.0, min(a, bend2) - bend1)
           + r3 * max(0.0, a - bend2))
    return math.floor(pia * 10.0 + 1e-9) / 10.0


def _canonical_ladder(category: str) -> list[tuple[str, float]]:
    """The default promotion ladder for a category: (grade, yos promoted to it)."""
    def ordered(table):
        return sorted(table.items(), key=lambda kv: kv[1])
    if category == G.ENLISTED:
        return [("E-1", 0.0)] + ordered(TL.ENLISTED_DEFAULTS)
    if category == G.WARRANT:
        return [("W-1", 0.0)] + ordered(TL.WARRANT_DEFAULTS)
    if category == G.OFFICER_PRIOR_ENLISTED:
        ladder = [("O-1E", 0.0), ("O-2E", TL.OFFICER_DEFAULTS["O-2"]),
                  ("O-3E", TL.OFFICER_DEFAULTS["O-3"])]
        ladder += [(g, y) for g, y in ordered(TL.OFFICER_DEFAULTS)
                   if G.get(g).sort > G.get("O-3").sort]
        return ladder
    return [("O-1", 0.0)] + ordered(TL.OFFICER_DEFAULTS)


def grade_history(grade: str, years_of_service: float, time_in_grade_years: float,
                  serving: bool = True) -> list[tuple[float, str]]:
    """
    (years of service at which it began, grade) across the whole career.

    The past is the default ladder shifted so that promotion into the current
    grade lands where time-in-grade says it did; the future is the timeline
    module's default promotions. Warrant officers and prior-enlisted officers
    get enlisted years in front of their ladder.
    """
    g = G.get(grade)
    ladder = _canonical_ladder(g.category)
    labels = [lab for lab, _ in ladder]
    idx = labels.index(g.label) if g.label in labels else 0

    promoted_at = max(0.0, float(years_of_service) - max(0.0, float(time_in_grade_years)))
    offset = promoted_at - ladder[idx][1]

    past = [(max(0.0, y + offset), lab) for lab, y in ladder[:idx]]
    past.append((promoted_at, g.label))

    if offset > 0 and g.category in (G.WARRANT, G.OFFICER_PRIOR_ENLISTED):
        enlisted = [(y, lab) for lab, y in _canonical_ladder(G.ENLISTED) if y < offset]
        past = enlisted + past

    future = []
    if serving:
        future = [(p.at_years_of_service, p.to_grade)
                  for p in TL.default_promotions(g.label, years_of_service)]

    steps = past + future
    steps.sort(key=lambda s: s[0])
    return steps


def grade_at(steps: list[tuple[float, str]], yos: float) -> str:
    grade = steps[0][1] if steps else ""
    for start, lab in steps:
        if start <= yos + 1e-9:
            grade = lab
    return grade


def estimate_pia_from_career(member, separation_yos: float | None = None,
                             civilian_years: int | None = None,
                             civilian_wages_annual: float | None = None,
                             table: BP.BasePayTable | None = None,
                             current_year: int | None = None,
                             real_wage_growth_pct: float = 0.0) -> EarningsEstimate:
    """
    A PIA from a modelled career, for a member without a statement.

    Covered earnings are BASIC PAY ONLY, read off the current pay table at each
    year's grade and longevity, plus the pre-2002 extra credits, plus
    `civilian_years` of `civilian_wages_annual` after service. Every year is
    valued off the current table and the current bend points: that is the
    same as assuming basic pay and the national average wage index move
    together, which is the today's-dollars convention the ssa.gov statement
    itself uses. `real_wage_growth_pct` above zero scales the result up for
    wage growth beyond inflation between now and age 60.
    """
    year = current_year or date.today().year
    table = table if table is not None else BP.load()
    est = EarningsEstimate(real_wage_growth_pct=real_wage_growth_pct)
    if table is None:
        est.note = BP.MISSING_DATA_NOTE
        return est

    serving = bool(getattr(member, "is_serving", True))
    yos_now = max(0.0, float(member.years_of_service))
    if separation_yos is None:
        separation_yos = max(20.0, yos_now) if serving else yos_now
    if not serving:
        separation_yos = yos_now
    separation_yos = max(0.0, float(separation_yos))
    est.separation_yos = separation_yos

    diems = getattr(member, "diems", None)
    if serving or diems is None:
        start_year = year - int(math.floor(yos_now))
    else:
        start_year = diems.year

    wages = (float(member.civilian_wages_annual) if civilian_wages_annual is None
             else float(civilian_wages_annual))
    age_at_separation = (start_year + separation_yos) - member.birth_year
    if civilian_years is None:
        civilian_years = int(max(0.0, MIN_CLAIM_AGE - age_at_separation))
    civilian_years = max(0, int(civilian_years))

    steps = grade_history(member.grade, yos_now, member.time_in_grade_years, serving)
    override = float(getattr(member, "basic_pay_monthly_override", 0.0) or 0.0)

    n_mil = int(math.ceil(separation_yos - 1e-9))
    for i in range(n_mil):
        fraction = min(1.0, separation_yos - i)
        mid = i + 0.5 * fraction
        grade = grade_at(steps, mid)
        cal = start_year + i
        use_override = (serving and override > 0 and i == int(math.floor(yos_now)))
        bp = BP.lookup(grade, mid, table, override_monthly=override if use_override else 0.0)
        pay = (bp.monthly if bp.found else 0.0) * 12.0 * fraction
        credit = extra_earnings_credit(cal, pay)
        est.years.append(EarningsYear(
            calendar_year=cal, age=cal - member.birth_year, years_of_service=float(i),
            grade=grade, source="Military", earnings=pay, extra_credit=credit,
            covered=min(TAXABLE_MAXIMUM, pay + credit)))
    est.n_military_years = n_mil

    for j in range(civilian_years):
        cal = start_year + n_mil + j
        est.years.append(EarningsYear(
            calendar_year=cal, age=cal - member.birth_year, years_of_service=0.0,
            grade="", source="Civilian", earnings=wages,
            covered=min(TAXABLE_MAXIMUM, max(0.0, wages))))
    est.n_civilian_years = civilian_years

    covered = [y.covered for y in est.years]
    top = sorted(covered, reverse=True)[:COMPUTATION_YEARS]
    est.top_years_total = sum(top)
    est.n_years_counted = sum(1 for x in top if x > 0)
    est.aime = aime_from_earnings(covered)
    est.pia_at_current_bend_points = pia_from_aime(est.aime)

    years_to_60 = max(0, (member.birth_year + 60) - year)
    g = max(0.0, real_wage_growth_pct) / 100.0
    est.wage_growth_factor = (1.0 + g) ** years_to_60 if g > 0 else 1.0
    est.pia = math.floor(est.pia_at_current_bend_points * est.wage_growth_factor * 10.0) / 10.0
    est.found = True

    zero_years = max(0, COMPUTATION_YEARS - est.n_years_counted)
    est.assumptions = [
        (f"Covered earnings are basic pay only, from the {table.year} table at "
         f"each year's grade and longevity — BAH, BAS and special pays carry no "
         f"Social Security tax."),
        (f"{n_mil} years of service, with promotions on the default timeline "
         f"(adjust it on the Career page — it is the biggest lever here), then "
         f"{civilian_years} civilian year{'s' if civilian_years != 1 else ''} at "
         f"${wages:,.0f}."),
        (f"The highest 35 years count. {est.n_years_counted} of them have "
         f"earnings"
         + (f"; the other {zero_years} are zeros, which is what pulls a short "
            f"career's benefit down." if zero_years else ".")),
        ("Every year is valued off today's pay table and today's bend points — "
         "the same today's-dollars convention the ssa.gov statement uses. It "
         "assumes basic pay tracks the national average wage."
         + (f" Real wage growth of {real_wage_growth_pct:.1f}% a year to age 60 "
            f"scales the result by {est.wage_growth_factor:.2f}."
            if g > 0 else "")),
        PARAMETER_NOTE,
    ]
    if any(y.extra_credit > 0 for y in est.years):
        total_credit = sum(y.extra_credit for y in est.years)
        est.assumptions.append(
            f"Service before 2002 adds ${total_credit:,.0f} of special extra "
            f"earnings credits across "
            f"{sum(1 for y in est.years if y.extra_credit > 0)} years.")
    est.note = (f"Estimated PIA ${est.pia:,.0f} a month at full retirement age, "
                f"from an AIME of ${est.aime:,.0f} and the {est.bend_points_year} "
                f"bend points.")
    return est


# ==========================================================================
# The household analysis
# ==========================================================================

@dataclass
class ClaimRow:
    age: int = 62
    factor: float = 1.0
    monthly: float = 0.0
    annual: float = 0.0
    total_by_life_expectancy: float = 0.0
    pv_by_life_expectancy: float = 0.0
    total_by_planning_age: float = 0.0
    breakeven_vs_62: float | None = None


@dataclass
class SocialSecurityAnalysis:
    pia: float = 0.0
    pia_source: str = SOURCE_NONE
    estimate: EarningsEstimate | None = None

    birth_year: int = 0
    age_now: int = 0
    fra_years: float = 67.0
    fra_label: str = "67"
    claim_age: int = 67
    claim_factor: float = 1.0
    benefit_at_claim: float = 0.0
    benefit_at_62: float = 0.0
    benefit_at_fra: float = 0.0
    benefit_at_70: float = 0.0

    conditioning_age: int = 62
    life_expectancy: int = 0
    planning_age: int = 0
    real_discount_rate: float = 0.03

    rows: list = field(default_factory=list)
    best_age_by_life_expectancy: int = 0
    best_age_by_planning_age: int = 0
    breakeven_62_vs_70: float | None = None
    breakeven_62_vs_70_discounted: float | None = None
    breakeven_62_vs_fra: float | None = None
    edge_70_over_62_at_life_expectancy: float = 0.0
    edge_70_over_62_pv: float = 0.0
    edge_70_over_62_at_planning_age: float = 0.0

    has_spouse: bool = False
    spouse_pia: float = 0.0
    spouse_claim_age: int = 67
    spouse_on_ssdi: bool = False
    spouse_benefit_at_claim: float = 0.0
    higher_earner: str = "you"
    spousal_for_spouse: SpousalResult | None = None
    spousal_for_you: SpousalResult | None = None
    survivor: SurvivorResult | None = None
    survivor_if_higher_claims_62: float = 0.0
    survivor_if_higher_claims_fra: float = 0.0
    survivor_if_higher_claims_70: float = 0.0

    earnings_test_exposed: bool = False
    earnings_test_withheld_annual: float = 0.0

    household_ss_annual: float = 0.0
    taxation: TaxationResult | None = None
    ramp: list = field(default_factory=list)

    facts: list = field(default_factory=lambda: list(MILITARY_FACTS))
    findings: list = field(default_factory=list)
    life_expectancy_note: str = ""


def _money(x: float) -> str:
    return f"${abs(x):,.0f}"


def analyse(h, separation_yos: float | None = None, civilian_years: int | None = None,
            other_income_annual: float = 0.0, current_year: int | None = None,
            table: BP.BasePayTable | None = None) -> SocialSecurityAnalysis:
    """
    The whole picture for one household: the PIA (statement first, estimate
    second), the 62–70 table with breakevens, spousal and survivor benefits,
    taxation at today's thresholds, and the findings.
    """
    m = h.member
    ss = h.social_security
    year = current_year or date.today().year

    a = SocialSecurityAnalysis(birth_year=m.birth_year, age_now=m.age(year))
    a.fra_years = fra_years(m.birth_year)
    a.fra_label = fra_label(m.birth_year)
    a.claim_age = int(min(MAX_CLAIM_AGE, max(MIN_CLAIM_AGE, int(ss.claim_age))))
    a.real_discount_rate = max(0.0, float(h.assumptions.real_discount_rate_pct)) / 100.0

    # ---- the PIA ----------------------------------------------------------
    a.estimate = estimate_pia_from_career(m, separation_yos, civilian_years,
                                          table=table, current_year=year)
    if ss.estimated_monthly_at_fra > 0:
        a.pia = float(ss.estimated_monthly_at_fra)
        a.pia_source = SOURCE_STATEMENT
    elif a.estimate.found and a.estimate.pia > 0:
        a.pia = a.estimate.pia
        a.pia_source = SOURCE_ESTIMATE
    else:
        a.pia = 0.0
        a.pia_source = SOURCE_NONE

    a.claim_factor = claim_factor(m.birth_year, a.claim_age)
    a.benefit_at_claim = a.pia * a.claim_factor
    a.benefit_at_62 = benefit_at(a.pia, m.birth_year, MIN_CLAIM_AGE)
    a.benefit_at_fra = a.pia
    a.benefit_at_70 = benefit_at(a.pia, m.birth_year, MAX_CLAIM_AGE)

    # ---- longevity, conditional on reaching the decision ------------------
    # The claiming question only arises if you reach 62, so the relevant life
    # expectancy is the one for someone who has. For a 27-year-old that is
    # about five years longer than the figure from birth.
    a.conditioning_age = max(a.age_now, MIN_CLAIM_AGE)
    a.life_expectancy = MORT.life_expectancy(a.conditioning_age, m.sex)
    a.planning_age = MORT.planning_age(a.conditioning_age, m.sex)
    a.life_expectancy_note = (
        f"Life expectancy here is for someone who has reached "
        f"{a.conditioning_age}: about {a.life_expectancy}. Roughly half of "
        f"people outlive it, which is why the table also shows {a.planning_age}. "
        + ("" if MORT.is_authoritative() else
           "The mortality table is a built-in approximation of the SSA period "
           "life table, not the published file."))

    # ---- the 62-70 table --------------------------------------------------
    r = a.real_discount_rate
    for age in range(MIN_CLAIM_AGE, MAX_CLAIM_AGE + 1):
        f = claim_factor(m.birth_year, age)
        monthly = a.pia * f
        row = ClaimRow(age=age, factor=f, monthly=monthly, annual=monthly * 12.0,
                       total_by_life_expectancy=cumulative_benefit(monthly, age, a.life_expectancy),
                       pv_by_life_expectancy=present_value_of_benefit(monthly, age, a.life_expectancy, r),
                       total_by_planning_age=cumulative_benefit(monthly, age, a.planning_age),
                       breakeven_vs_62=(breakeven_age(a.benefit_at_62, MIN_CLAIM_AGE, monthly, age)
                                        if age > MIN_CLAIM_AGE else None))
        a.rows.append(row)

    if a.rows:
        a.best_age_by_life_expectancy = max(a.rows, key=lambda x: (round(x.total_by_life_expectancy), -x.age)).age
        a.best_age_by_planning_age = max(a.rows, key=lambda x: (round(x.total_by_planning_age), -x.age)).age
    a.breakeven_62_vs_70 = breakeven_age(a.benefit_at_62, MIN_CLAIM_AGE, a.benefit_at_70, MAX_CLAIM_AGE)
    a.breakeven_62_vs_70_discounted = breakeven_age(a.benefit_at_62, MIN_CLAIM_AGE,
                                                    a.benefit_at_70, MAX_CLAIM_AGE, r)
    a.breakeven_62_vs_fra = breakeven_age(a.benefit_at_62, MIN_CLAIM_AGE, a.benefit_at_fra, a.fra_years)
    a.edge_70_over_62_at_life_expectancy = (
        cumulative_benefit(a.benefit_at_70, MAX_CLAIM_AGE, a.life_expectancy)
        - cumulative_benefit(a.benefit_at_62, MIN_CLAIM_AGE, a.life_expectancy))
    a.edge_70_over_62_pv = (
        present_value_of_benefit(a.benefit_at_70, MAX_CLAIM_AGE, a.life_expectancy, r)
        - present_value_of_benefit(a.benefit_at_62, MIN_CLAIM_AGE, a.life_expectancy, r))
    a.edge_70_over_62_at_planning_age = (
        cumulative_benefit(a.benefit_at_70, MAX_CLAIM_AGE, a.planning_age)
        - cumulative_benefit(a.benefit_at_62, MIN_CLAIM_AGE, a.planning_age))

    # ---- spouse -----------------------------------------------------------
    a.has_spouse = bool(h.has_spouse)
    if a.has_spouse:
        spouse_by = h.spouse.birth_year if getattr(h, "spouse", None) else m.birth_year
        a.spouse_on_ssdi = bool(ss.spouse_on_ssdi)
        a.spouse_claim_age = int(min(MAX_CLAIM_AGE, max(MIN_CLAIM_AGE, int(ss.spouse_claim_age))))
        a.spouse_pia = float(ss.spouse_ssdi_monthly if a.spouse_on_ssdi
                             else ss.spouse_estimated_monthly_at_fra)
        a.spouse_pia = max(0.0, a.spouse_pia)

        a.spousal_for_spouse = spousal_benefit(a.pia, a.spouse_pia, spouse_by,
                                               a.spouse_claim_age, own_is_fixed=a.spouse_on_ssdi)
        a.spousal_for_you = spousal_benefit(a.spouse_pia, a.pia, m.birth_year, a.claim_age)
        a.spouse_benefit_at_claim = a.spousal_for_spouse.total
        # Your own benefit may also be topped up if your spouse out-earns you.
        your_total = a.spousal_for_you.total
        a.higher_earner = "you" if a.pia >= a.spouse_pia else "your spouse"

        if a.higher_earner == "you":
            hi_pia, hi_by, hi_claim = a.pia, m.birth_year, a.claim_age
            lo_own = a.spouse_benefit_at_claim
        else:
            hi_pia, hi_by, hi_claim = a.spouse_pia, spouse_by, a.spouse_claim_age
            lo_own = your_total
        a.survivor = survivor_benefit(hi_pia, hi_by, hi_claim, lo_own)
        a.survivor_if_higher_claims_62 = survivor_benefit(hi_pia, hi_by, MIN_CLAIM_AGE, lo_own).survivor_receives
        a.survivor_if_higher_claims_fra = survivor_benefit(hi_pia, hi_by, fra_years(hi_by), lo_own).survivor_receives
        a.survivor_if_higher_claims_70 = survivor_benefit(hi_pia, hi_by, MAX_CLAIM_AGE, lo_own).survivor_receives
        a.household_ss_annual = (your_total + a.spouse_benefit_at_claim) * 12.0
    else:
        a.household_ss_annual = a.benefit_at_claim * 12.0

    # ---- earnings test ----------------------------------------------------
    wages = float(m.civilian_wages_annual or 0.0)
    if a.estimate is not None and a.estimate.found:
        age_at_sep = a.age_now + (a.estimate.separation_yos - float(m.years_of_service))
        working_until = age_at_sep + a.estimate.n_civilian_years
    else:
        working_until = a.age_now
    if (a.claim_age < a.fra_years and wages > EARNINGS_TEST_EXEMPT
            and working_until > a.claim_age):
        a.earnings_test_exposed = True
        a.earnings_test_withheld_annual = min(a.benefit_at_claim * 12.0,
                                              (wages - EARNINGS_TEST_EXEMPT) * EARNINGS_TEST_WITHHOLDING)

    # ---- taxation ---------------------------------------------------------
    a.taxation = taxation(a.household_ss_annual, other_income_annual, a.has_spouse)
    a.ramp = taxation_ramp(a.household_ss_annual, a.has_spouse)

    a.findings = _findings(a, m, ss, other_income_annual)
    return a


def _findings(a: SocialSecurityAnalysis, m, ss, other_income_annual: float) -> list:
    out = []

    # ---- where the number comes from --------------------------------------
    if a.pia_source == SOURCE_STATEMENT:
        detail = (f"Your statement's {_money(a.pia)} a month at {a.fra_label} is "
                  f"computed from your actual earnings record, which no estimate "
                  f"can match. It assumes you keep earning about what you earn "
                  f"now until you claim, and it is in today's dollars. Check it "
                  f"once a year at ssa.gov/myaccount — a missing year of "
                  f"earnings is far easier to fix now than at 62.")
        if a.estimate is not None and a.estimate.found and a.estimate.pia > 0:
            gap = a.estimate.pia - a.pia
            detail += (f" For comparison, a career modelled from the pay table "
                       f"gives {_money(a.estimate.pia)} — "
                       f"{_money(gap)} {'more' if gap > 0 else 'less'} — which is "
                       f"only a check on the order of magnitude.")
        out.append(("good", "Your estimate comes from your statement.", detail))
    elif a.pia_source == SOURCE_ESTIMATE:
        out.append(("warn", "No statement figure — this is a modelled estimate. "
                            "Get the real one.",
                    f"Create an account at ssa.gov/myaccount and read the benefit "
                    f"at full retirement age off your statement; it takes ten "
                    f"minutes and replaces everything modelled here. Until then "
                    f"the app estimates {_money(a.pia)} a month at {a.fra_label} "
                    f"from a career of basic pay on the default promotion timeline "
                    f"— {a.estimate.n_military_years} military years, then "
                    f"{a.estimate.n_civilian_years} civilian. Basic pay only: BAH "
                    f"and BAS are not covered wages. The bend points are the "
                    f"{a.estimate.bend_points_year} figures and have not been "
                    f"verified against ssa.gov from this machine."))
    else:
        out.append(("bad", "There is nothing to work from yet.",
                    "Enter the benefit at full retirement age from your ssa.gov "
                    "statement. Without it, and without a basic pay table to "
                    "model a career from, the page cannot estimate anything."))
        return out

    # ---- the claim-age framing -------------------------------------------
    le = a.life_expectancy
    edge = a.edge_70_over_62_at_life_expectancy
    be = a.breakeven_62_vs_70
    be_txt = f"age {be:.0f}" if be else "never"
    bed = a.breakeven_62_vs_70_discounted
    bed_txt = f"about {bed:.0f}" if bed else "never"
    if edge >= 0:
        head = (f"At your life expectancy of {le}, claiming at 70 beats 62 by "
                f"{_money(edge)}.")
        sev = "good"
    else:
        head = (f"At your life expectancy of {le}, claiming at 62 beats 70 by "
                f"{_money(edge)}.")
        sev = "info"
    detail = (f"Claiming at 62 pays {_money(a.benefit_at_62)} a month; at 70, "
              f"{_money(a.benefit_at_70)} — {a.benefit_at_70 / a.benefit_at_62 * 100 - 100:.0f}% "
              f"more, for life, indexed to inflation. The later claim catches up "
              f"at {be_txt} in total dollars, and at {bed_txt} once the money is "
              f"discounted at your {a.real_discount_rate * 100:.1f}% real rate. "
              f"By {a.planning_age}, which is what you should plan to, the gap is "
              f"{_money(a.edge_70_over_62_at_planning_age)} in favour of "
              f"{'70' if a.edge_70_over_62_at_planning_age >= 0 else '62'}. "
              f"The larger point: delaying is the cheapest inflation-indexed "
              f"lifetime annuity you can buy, and it insures the outcome where "
              f"you live a long time — the one that actually needs insuring."
              if a.benefit_at_62 > 0 else "")
    out.append((sev, head, detail))

    if a.claim_age < a.fra_years and a.pia > 0:
        out.append(("warn",
                    f"Claiming at {a.claim_age} locks in a "
                    f"{(1 - a.claim_factor) * 100:.0f}% cut for life.",
                    f"{_money(a.benefit_at_claim)} a month instead of "
                    f"{_money(a.pia)} at {a.fra_label}. The reduction is "
                    f"permanent, and it carries into the survivor benefit if you "
                    f"are the higher earner. It is the right call if you need the "
                    f"income, your health is poor, or the alternative is drawing "
                    f"down investments in a bad market — it is a poor default."))
    elif a.claim_age > a.fra_years and a.pia > 0 and a.claim_age < MAX_CLAIM_AGE:
        out.append(("info",
                    f"Delayed credits stop at 70; {a.claim_age} leaves some on the table.",
                    f"Each month past {a.fra_label} adds two-thirds of a percent. "
                    f"Waiting to 70 would pay {_money(a.benefit_at_70)} a month "
                    f"against {_money(a.benefit_at_claim)} at {a.claim_age}. "
                    f"Past 70 there is nothing to gain by waiting."))

    if a.earnings_test_exposed:
        out.append(("warn",
                    "You would be working past your claim age — the earnings "
                    "test bites.",
                    f"Before full retirement age, Social Security withholds $1 of "
                    f"benefit for every $2 you earn above "
                    f"${EARNINGS_TEST_EXEMPT:,.0f} a year ({PARAMETER_YEAR} figure). "
                    f"At {_money(float(m.civilian_wages_annual))} of wages that "
                    f"is about {_money(a.earnings_test_withheld_annual)} a year "
                    f"withheld. It is not lost — your benefit is recomputed at "
                    f"FRA to give it back — but it makes claiming while working "
                    f"pointless. Military retired pay and VA compensation are not "
                    f"earnings for this test; only wages and self-employment are."))

    # ---- spouse -----------------------------------------------------------
    if a.has_spouse:
        sv = a.survivor
        if sv is not None and a.pia > 0:
            who = "your" if a.higher_earner == "you" else "your spouse's"
            hi_claim = a.claim_age if a.higher_earner == "you" else a.spouse_claim_age
            out.append(("warn" if hi_claim < a.fra_years else "info",
                        f"The higher earner's claim age is survivor insurance: "
                        f"{_money(a.survivor_if_higher_claims_70)} a month at 70 "
                        f"versus {_money(a.survivor_if_higher_claims_62)} at 62.",
                        f"When the first of you dies, the household keeps the "
                        f"larger benefit and loses the smaller — two checks become "
                        f"one. The survivor inherits 100% of {who} benefit, "
                        f"delayed credits included, for life. So delaying the "
                        f"higher earner's claim raises the survivor's income for "
                        f"as long as either of you lives, and the survivor is "
                        f"usually the one who lives longest. As planned, the "
                        f"household drops from {_money(sv.household_before)} to "
                        f"{_money(sv.household_after)} a month at the first death. "
                        f"{sv.note}"))

        if a.spouse_on_ssdi:
            out.append(("info", "Your spouse's SSDI simply becomes their retirement "
                                "benefit at full retirement age.",
                        f"Same amount — {_money(a.spouse_pia)} a month — no "
                        f"application, no early-claiming reduction. Their PIA is "
                        f"what they receive now, so it is also the base for any "
                        f"spousal or survivor benefit."
                        + (f" Half of your PIA is {_money(SPOUSAL_SHARE * a.pia)}, "
                           f"which is more than their SSDI, so once you file they "
                           f"can be topped up by about "
                           f"{_money(a.spousal_for_spouse.spousal_excess_paid)} a month."
                           if a.spousal_for_spouse and a.spousal_for_spouse.spousal_excess_paid > 0
                           else "")))
        elif a.spouse_pia <= 0 and a.pia > 0:
            out.append(("info", f"Your spouse can draw up to {_money(SPOUSAL_SHARE * a.pia)} "
                                f"a month on your record.",
                        f"Half of your PIA, at their full retirement age, whether "
                        f"or not they ever paid in — a military spouse whose "
                        f"career was interrupted by every PCS often has a thin "
                        f"record of their own, and this is the floor under it. "
                        f"It is reduced if they claim early and does not grow "
                        f"past FRA, and you must have filed for them to claim it. "
                        f"Enter their own statement figure to compare."))
        elif a.spousal_for_spouse and a.spousal_for_spouse.spousal_excess_paid > 0:
            out.append(("info", f"Your spouse's benefit is topped up by "
                                f"{_money(a.spousal_for_spouse.spousal_excess_paid)} "
                                f"a month on your record.",
                        f"Their own benefit is below half of your PIA, so once you "
                        f"file they receive their own plus the difference — "
                        f"{_money(a.spousal_for_spouse.total)} in all. "
                        f"{a.spousal_for_spouse.note}"))
        elif a.spousal_for_you and a.spousal_for_you.spousal_excess_paid > 0:
            out.append(("info", f"Your benefit is topped up by "
                                f"{_money(a.spousal_for_you.spousal_excess_paid)} a "
                                f"month on your spouse's record.",
                        f"Your own benefit is below half of their PIA. "
                        f"{a.spousal_for_you.note}"))

    # ---- taxation ---------------------------------------------------------
    tx = a.taxation
    if tx is not None and tx.ss_annual > 0:
        sev = "warn" if tx.taxable_share >= MAX_TAXABLE_SHARE - 1e-6 else "info"
        out.append((sev,
                    f"With {_money(tx.other_income)} of other income, "
                    f"{tx.taxable_share * 100:.0f}% of your household benefit is "
                    f"taxable.",
                    f"{tx.note} The thresholds — "
                    f"${PROVISIONAL_TIER1[T.SINGLE]:,.0f} and "
                    f"${PROVISIONAL_TIER2[T.SINGLE]:,.0f} single, "
                    f"${PROVISIONAL_TIER1[T.MFJ]:,.0f} and "
                    f"${PROVISIONAL_TIER2[T.MFJ]:,.0f} joint — have not moved since "
                    f"1993 and are not indexed, so every year of inflation pulls "
                    f"more retirees across them. Retired pay counts toward "
                    f"provisional income; VA compensation does not. {ROTH_NOTE}"))

    out.append(("good", "Nothing about your service reduces this benefit.",
                "Military earnings are fully covered, WEP and GPO do not apply "
                "to military retired pay (and were repealed in January 2025 in "
                "any case), and neither retired pay nor VA compensation offsets "
                "Social Security. If you served before 2002, special extra "
                "earnings credits are added to your record automatically when "
                "the benefit is computed."))
    return out
