"""
What healthcare costs a military family over a lifetime, in today's dollars.

Civilian retirement planning treats healthcare as the largest and least
predictable line in the budget: a six-figure estimate for a couple at 65, and
before that a gap between the employer plan and Medicare that keeps people
working. A military family's picture differs in three specific ways, and this
module models each of them rather than borrowing the civilian number:

  1. THE PRE-65 GAP DOES NOT EXIST. A retiree's family is on TRICARE Prime or
     Select from the day retired pay starts, for an enrollment fee of a few
     hundred dollars a year and a catastrophic cap of a few thousand. The ACA
     subsidy cliff that caps a civilian early retiree's Roth conversions is
     not a constraint here.

  2. AT 65 THE COST IS MEDICARE PART B, NOT TRICARE. TRICARE For Life has no
     enrollment fee -- but it is a wraparound to Medicare and it REQUIRES
     Part B. Decline Part B and TFL does not exist; neither does Medigap or
     Medicare Advantage, which also require it. So a military retiree's real
     healthcare cost from 65 on is the Part B premium, per person, for life,
     plus IRMAA if income is high.

  3. IRMAA IS WHERE ROTH CONVERSIONS MEET HEALTHCARE. Medicare premiums are
     set by MAGI from two years earlier, in steps, and every step is a cliff:
     one dollar over a bracket costs the whole step for the whole year. A
     conversion at 63 sets the Part B premium at 65. `probe_conversion()`
     exists to make that visible before the conversion is made.

The phases, by component:

    Active duty      TRICARE Prime, ~$0 for the member and the family
    Guard / Reserve  TRICARE Reserve Select, a monthly premium
    Gray area        A Reserve retiree under 60: TRICARE Retired Reserve,
                     which is priced at full cost and is the expensive stretch
    Retiree under 65 Prime or Select enrollment fee, Group A or Group B by
                     DIEMS date (before / on or after 1 January 2018)
    65 and over      Medicare Part B premium + IRMAA; TFL pays second, free

PROVENANCE. Every dollar figure lives in FIGURES below, with the year it
applies to, and every one carries a VERIFY note in VERIFY. This machine cannot
reach tricare.mil, cms.gov or ssa.gov, so the figures are from memory of the
published 2026 notices and the retiree-COLA indexing rule, not from the
documents themselves. Correct them in one place and every page follows.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date
import math

from engine import mortality as MORT
from engine.profile import ACTIVE, GUARD, RESERVE, RETIRED, VETERAN, CIVILIAN
from engine.pay import taxable as PAY
from engine.tax import military as MIL
from engine.tax import tables as T

# ==========================================================================
# 2026 figures. ONE place. Every entry has a VERIFY note below.
# ==========================================================================
FIGURES = {
    "year": 2026,

    # ---- Medicare Part B, per person, monthly --------------------------
    "part_b_standard_monthly": 202.90,
    "part_b_deductible_annual": 283.00,

    # ---- IRMAA. MAGI ceilings are INCLUSIVE ("$218,000 or less" is the
    #      standard premium; $218,001 is the first surcharge tier). MAGI is
    #      from the return filed two years earlier. Per person, monthly.
    "irmaa_ceilings_single": [109_000.0, 137_000.0, 171_000.0, 205_000.0, 500_000.0],
    "irmaa_ceilings_joint": [218_000.0, 274_000.0, 342_000.0, 410_000.0, 750_000.0],
    # CHECKED against ssa.gov Medicare Premiums (browser save, 2026-09-10).
    # Published as the standard premium plus a surcharge of 81.20, 202.90,
    # 324.60, 446.30, 487.00. Three tiers were a dime high when derived
    # from the statutory cost shares instead.
    "irmaa_part_b_monthly": [202.90, 284.10, 405.80, 527.50, 649.20, 689.90],
    "irmaa_part_d_monthly": [0.00, 14.50, 37.50, 60.40, 83.30, 91.00],
    "irmaa_lookback_years": 2,
    "part_b_late_penalty_per_year": 0.10,

    # ---- What the IRMAA tiers are DERIVED from. Holding these here lets a
    #      test re-derive every premium above and catch a typed digit.
    "irmaa_share_of_cost": [0.25, 0.35, 0.50, 0.65, 0.80, 0.85],
    "part_d_base_beneficiary_monthly": 38.99,

    # ---- TRICARE Reserve Select / TRICARE Retired Reserve, monthly -----
    "trs_member_monthly": 63.02,
    "trs_family_monthly": 301.03,
    "trr_member_monthly": 683.55,
    "trr_family_monthly": 1_641.78,

    # ---- Retiree enrollment fees, annual, by TRICARE group -------------
    "prime_fee_group_a": {"individual": 382.0, "family": 764.0},
    "prime_fee_group_b": {"individual": 464.0, "family": 928.0},
    "select_fee_group_a": {"individual": 188.0, "family": 376.0},
    "select_fee_group_b": {"individual": 199.0, "family": 398.0},

    # ---- Catastrophic caps, annual, per family -------------------------
    "cat_cap_retiree_group_a": 3_000.0,
    "cat_cap_retiree_group_b": 4_635.0,
    "cat_cap_adfm_group_a": 1_000.0,
    "cat_cap_adfm_group_b": 1_324.0,

    # ---- Dental, monthly (TRICARE Dental Program, active duty family) --
    "tdp_adfm_single_monthly": 12.28,
    "tdp_adfm_family_monthly": 31.93,

    # ---- Civilian comparison, annual. ESTIMATES, not tariffs. ----------
    "civilian_family_plan_total_annual": 25_000.0,
    "civilian_family_worker_share_annual": 6_500.0,
    "civilian_single_plan_total_annual": 9_000.0,
    "civilian_single_worker_share_annual": 1_400.0,
}

# What each figure is, where to check it, and how far to trust it. Shown on
# the page, so the person reading the number knows its standing.
VERIFY = {
    "part_b_standard_monthly":
        "VERIFY at cms.gov: 2026 Medicare Part B standard premium (CMS notice, "
        "November 2025). Confidence HIGH; matches engine/tax/tables.py.",
    "part_b_deductible_annual":
        "VERIFY at cms.gov: 2026 Part B annual deductible. Confidence HIGH.",
    "irmaa_ceilings_single":
        "CHECKED 2026-09-10 against ssa.gov. 2026 IRMAA MAGI brackets, single, "
        "based on the 2024 return. Confidence HIGH; matches engine/tax/tables.py.",
    "irmaa_ceilings_joint":
        "CHECKED 2026-09-10 against ssa.gov. IRMAA MAGI brackets, married filing "
        "jointly. Confidence HIGH; matches engine/tax/tables.py.",
    "irmaa_part_b_monthly":
        "CHECKED 2026-09-10 against ssa.gov. 2026 Part B total premium by "
        "Confidence HIGH; matches engine/tax/tables.py, and each tier is the "
        "statutory share of the $811.60 total cost implied by the standard "
        "premium (25/35/50/65/80/85 percent), which all six figures satisfy.",
    "irmaa_part_d_monthly":
        "CHECKED 2026-09-10 against ssa.gov, exact. 2026 Part D "
        "Confidence MEDIUM-HIGH. Each tier is (share - 25.5%) / 25.5% times "
        "the national base beneficiary premium, and all five reproduce to the "
        "cent from a 2026 base of $38.99 -- so they are right if that base is. "
        "engine/tax/tables.py still carries 13.70/35.30/57.00/78.60/85.80, "
        "which reproduce from the 2025 base of $36.78: those are last year's "
        "amounts and that file needs the update, not this one.",
    "irmaa_lookback_years":
        "Statutory: IRMAA uses MAGI from the return two years earlier. "
        "Confidence HIGH.",
    "irmaa_share_of_cost":
        "Statutory (42 U.S.C. 1395r(i)): the share of the total Part B cost "
        "each tier pays. The standard premium is 25%; the surcharge tiers are "
        "35, 50, 65, 80 and 85%. Confidence HIGH -- these are in law and do "
        "not change with the year.",
    "part_d_base_beneficiary_monthly":
        "VERIFY at cms.gov: the 2026 Part D national base beneficiary premium, "
        "which every Part D IRMAA amount above is computed from. Confidence "
        "MEDIUM (2025 was 36.78).",
    "part_b_late_penalty_per_year":
        "Statutory: 10% of the standard premium for each full 12-month period "
        "without Part B after eligibility, for life. Confidence HIGH.",
    "trs_member_monthly":
        "VERIFY at tricare.mil/costs: 2026 TRICARE Reserve Select member-only "
        "premium. Confidence LOW-MEDIUM (2025 was 54.35; 2026 rose sharply).",
    "trs_family_monthly":
        "VERIFY at tricare.mil/costs: 2026 TRS member-and-family premium. "
        "Confidence LOW-MEDIUM (2025 was 261.99).",
    "trr_member_monthly":
        "VERIFY at tricare.mil/costs: 2026 TRICARE Retired Reserve member-only "
        "premium. Confidence LOW-MEDIUM (2025 was 585.14).",
    "trr_family_monthly":
        "VERIFY at tricare.mil/costs: 2026 TRR member-and-family premium. "
        "Confidence LOW-MEDIUM (2025 was 1,406.22).",
    "prime_fee_group_a":
        "VERIFY at tricare.mil/costs: 2026 Prime enrollment fee, Group A "
        "retirees (DIEMS before 1 Jan 2018). Derived from the 2024 fee of "
        "363/726 indexed by the 2.5% and 2.8% retiree COLAs. Confidence LOW.",
    "prime_fee_group_b":
        "VERIFY at tricare.mil/costs: 2026 Prime enrollment fee, Group B "
        "retirees (DIEMS on or after 1 Jan 2018). Derived from the 2018 fee of "
        "350/700 indexed by retiree COLA (2025: 451/902). Confidence LOW.",
    "select_fee_group_a":
        "VERIFY at tricare.mil/costs: 2026 Select enrollment fee, Group A "
        "retirees. Began at 150/300 in 2021, indexed since. Confidence LOW.",
    "select_fee_group_b":
        "VERIFY at tricare.mil/costs: 2026 Select enrollment fee, Group B "
        "retirees. Began at 150/300 in 2018, indexed since. Confidence LOW.",
    "cat_cap_retiree_group_a":
        "Statutory: Group A retiree catastrophic cap is 3,000 and is NOT "
        "indexed. Confidence HIGH.",
    "cat_cap_retiree_group_b":
        "VERIFY at tricare.mil/costs: Group B retiree catastrophic cap, 3,500 "
        "in 2018 indexed by retiree COLA (2025: 4,509). Confidence LOW-MEDIUM.",
    "cat_cap_adfm_group_a":
        "Statutory: Group A active duty family catastrophic cap, 1,000, not "
        "indexed. Confidence HIGH.",
    "cat_cap_adfm_group_b":
        "VERIFY at tricare.mil/costs: Group B active duty family cap, 1,000 in "
        "2018 indexed by retiree COLA. Confidence LOW.",
    "tdp_adfm_single_monthly":
        "VERIFY at tricare.mil/dental: TRICARE Dental Program, active duty "
        "family, one member. Confidence LOW (approximately 12).",
    "tdp_adfm_family_monthly":
        "VERIFY at tricare.mil/dental: TRICARE Dental Program, active duty "
        "family, two or more members. Confidence LOW (approximately 32).",
    "civilian_family_plan_total_annual":
        "ESTIMATE from the KFF Employer Health Benefits Survey: total family "
        "premium (employer plus worker) was roughly 25,000-27,000 in 2024-25. "
        "Not a tariff; labelled as an estimate wherever it appears.",
    "civilian_family_worker_share_annual":
        "ESTIMATE from KFF: the worker's share of a family premium, roughly "
        "6,300-6,900 in 2024-25.",
    "civilian_single_plan_total_annual":
        "ESTIMATE from KFF: total single-coverage premium, roughly 9,000-9,300.",
    "civilian_single_worker_share_annual":
        "ESTIMATE from KFF: worker's share of single coverage, roughly 1,400.",
}

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------
GROUP_A = "Group A"
GROUP_B = "Group B"
# Same date as the BRS boundary, but a separate rule (FY17 NDAA sec. 701).
GROUP_B_DIEMS_START = date(2018, 1, 1)

MEDICARE_AGE = 65
RESERVE_RETIRED_PAY_AGE = 60   # and the age Reserve retiree TRICARE begins
CONVERSION_WINDOW_CLOSES_AT = MEDICARE_AGE - FIGURES["irmaa_lookback_years"]

PLAN_PRIME = "Prime"
PLAN_SELECT = "Select"
PLAN_TRS = "Reserve Select"
PLAN_TFL = "For Life"
PLANS = [PLAN_PRIME, PLAN_SELECT, PLAN_TRS, PLAN_TFL]

# Phases. The labels are what the chart legend shows.
PH_ACTIVE = "Active duty — TRICARE Prime"
PH_TRS = "Guard/Reserve — TRICARE Reserve Select"
PH_GRAY = "Gray area — TRICARE Retired Reserve"
PH_RETIREE_PRIME = "Retiree under 65 — TRICARE Prime"
PH_RETIREE_SELECT = "Retiree under 65 — TRICARE Select"
PH_TFL = "65 and over — Medicare Part B with TRICARE For Life"
PH_NO_TFL = "65 and over — Part B declined, no TRICARE For Life"
PH_CIVILIAN = "Civilian coverage"
PH_MEDICARE = "65 and over — Medicare without TRICARE"
PHASE_ORDER = [PH_ACTIVE, PH_TRS, PH_GRAY, PH_RETIREE_PRIME, PH_RETIREE_SELECT,
               PH_CIVILIAN, PH_TFL, PH_NO_TFL, PH_MEDICARE]
RETIREE_PHASES = (PH_RETIREE_PRIME, PH_RETIREE_SELECT)
MEDICARE_PHASES = (PH_TFL, PH_MEDICARE)


def _money(x: float) -> str:
    return f"${x:,.0f}"


# ==========================================================================
# IRMAA
# ==========================================================================

@dataclass(frozen=True)
class IRMAATier:
    """One row of the IRMAA table, for one filing status."""
    index: int                   # 0 = standard premium, no surcharge
    floor: float                 # exclusive: MAGI must exceed this
    ceiling: float               # inclusive; inf for the top tier
    part_b_monthly: float        # total Part B premium, per person
    part_d_surcharge_monthly: float
    filing_joint: bool

    @property
    def part_b_surcharge_monthly(self) -> float:
        return self.part_b_monthly - FIGURES["part_b_standard_monthly"]

    @property
    def surcharge_annual_per_person(self) -> float:
        """Part B + Part D surcharge above the standard premium, per year."""
        return (self.part_b_surcharge_monthly + self.part_d_surcharge_monthly) * 12.0

    @property
    def part_b_annual_per_person(self) -> float:
        return self.part_b_monthly * 12.0

    @property
    def label(self) -> str:
        return "Standard" if self.index == 0 else f"Tier {self.index}"

    @property
    def is_top(self) -> bool:
        return math.isinf(self.ceiling)

    def magi_range_text(self) -> str:
        if self.index == 0:
            return f"{_money(self.ceiling)} or less"
        if self.is_top:
            return f"over {_money(self.floor)}"
        return f"{_money(self.floor + 1)} to {_money(self.ceiling)}"


def irmaa_tiers(filing_joint: bool) -> list[IRMAATier]:
    key = "irmaa_ceilings_joint" if filing_joint else "irmaa_ceilings_single"
    ceilings = list(FIGURES[key]) + [math.inf]
    part_b = FIGURES["irmaa_part_b_monthly"]
    part_d = FIGURES["irmaa_part_d_monthly"]
    if not (len(ceilings) == len(part_b) == len(part_d)):
        raise ValueError("IRMAA figures are misaligned: one list per tier")
    out, floor = [], -math.inf
    for i, ceiling in enumerate(ceilings):
        out.append(IRMAATier(i, floor, ceiling, part_b[i], part_d[i], filing_joint))
        floor = ceiling
    return out


def irmaa_for_magi(magi: float, filing_joint: bool) -> IRMAATier:
    """
    The IRMAA tier a MAGI lands in. A step function: $218,000 is the standard
    premium and $218,001 is the first surcharge tier, for the whole year.
    """
    tiers = irmaa_tiers(filing_joint)
    for tier in tiers:
        if magi <= tier.ceiling:
            return tier
    return tiers[-1]


def irmaa_headroom(magi: float, filing_joint: bool) -> float:
    """Dollars of MAGI left before the next cliff. inf at the top tier."""
    tier = irmaa_for_magi(magi, filing_joint)
    return math.inf if tier.is_top else tier.ceiling - magi


def irmaa_cost_annual(magi: float, filing_joint: bool, n_enrolled: int = 1,
                      include_part_d: bool = True) -> float:
    """Part B + (optionally) Part D surcharge above standard, for a year."""
    if n_enrolled <= 0:
        return 0.0
    tier = irmaa_for_magi(magi, filing_joint)
    d = tier.part_d_surcharge_monthly if include_part_d else 0.0
    return (tier.part_b_surcharge_monthly + d) * 12.0 * n_enrolled


def conversion_irmaa_cost(baseline_magi: float, conversion_amount: float,
                          joint: bool, n_enrolled: int = 1,
                          include_part_d: bool = True) -> float:
    """
    The extra Part B (+ Part D) cost, for ONE year, that a Roth conversion
    triggers two years later.

    IRMAA is recomputed every year from that year's lookback return, so a
    single conversion year raises premiums for a single year. Cliff behaviour
    is inherited from irmaa_for_magi: a conversion that crosses a bracket by
    one dollar costs the entire step.
    """
    if conversion_amount <= 0 or n_enrolled <= 0:
        return 0.0
    before = irmaa_for_magi(baseline_magi, joint)
    after = irmaa_for_magi(baseline_magi + conversion_amount, joint)
    step_b = after.part_b_monthly - before.part_b_monthly
    step_d = ((after.part_d_surcharge_monthly - before.part_d_surcharge_monthly)
              if include_part_d else 0.0)
    return (step_b + step_d) * 12.0 * n_enrolled


@dataclass
class ConversionProbe:
    """Everything the page needs to say about one 'what if I convert $X'."""
    baseline_magi: float = 0.0
    conversion: float = 0.0
    magi_after: float = 0.0
    joint: bool = False
    n_enrolled: int = 1
    include_part_d: bool = True
    before: IRMAATier | None = None
    after: IRMAATier | None = None
    tiers_crossed: int = 0
    extra_annual_cost: float = 0.0     # for the household, for one year
    headroom_before: float = 0.0       # the conversion that would have fit
    overshoot: float = 0.0             # dollars past the last cliff crossed
    effective_rate: float = 0.0        # extra cost / conversion
    conversion_year: int = 0
    year_paid: int = 0
    applies: bool = True               # someone is on Medicare in year_paid


def probe_conversion(baseline_magi: float, conversion_amount: float, joint: bool,
                     n_enrolled: int = 1, include_part_d: bool = True,
                     conversion_year: int | None = None,
                     age_in_conversion_year: int | None = None) -> ConversionProbe:
    """
    A conversion this year, priced in Medicare premiums two years from now.

    `age_in_conversion_year` decides whether the surcharge ever lands: a
    conversion at 62 sets a premium for a year the member is not on Medicare,
    so nothing is paid. From 63 on, every conversion year has a price.
    """
    year = conversion_year or date.today().year
    p = ConversionProbe(baseline_magi=baseline_magi, conversion=max(0.0, conversion_amount),
                        magi_after=baseline_magi + max(0.0, conversion_amount),
                        joint=joint, n_enrolled=max(1, n_enrolled),
                        include_part_d=include_part_d, conversion_year=year,
                        year_paid=year + FIGURES["irmaa_lookback_years"])
    p.before = irmaa_for_magi(baseline_magi, joint)
    p.after = irmaa_for_magi(p.magi_after, joint)
    p.tiers_crossed = p.after.index - p.before.index
    p.headroom_before = irmaa_headroom(baseline_magi, joint)
    p.extra_annual_cost = conversion_irmaa_cost(baseline_magi, p.conversion, joint,
                                                p.n_enrolled, include_part_d)
    if p.tiers_crossed > 0:
        p.overshoot = p.magi_after - p.after.floor
    p.effective_rate = p.extra_annual_cost / p.conversion if p.conversion > 0 else 0.0
    if age_in_conversion_year is not None:
        p.applies = (age_in_conversion_year + FIGURES["irmaa_lookback_years"]) >= MEDICARE_AGE
    return p


# ==========================================================================
# TRICARE groups, fees, VA priority
# ==========================================================================

def tricare_group(diems: date | None) -> str:
    """
    Group A: DIEMS before 1 January 2018. Group B: on or after.

    Group B pays higher retiree enrollment fees and an indexed catastrophic
    cap; Group A's cap is fixed in law at $3,000. An unreadable DIEMS is
    treated as Group A, which is where nearly every current retiree sits.
    """
    if diems is None:
        return GROUP_A
    return GROUP_B if diems >= GROUP_B_DIEMS_START else GROUP_A


def _gkey(group: str) -> str:
    return "group_b" if group == GROUP_B else "group_a"


def enrollment_fee_annual(plan: str, group: str, family: bool) -> float:
    """Retiree enrollment fee for Prime or Select. TFL and active duty: none."""
    if plan == PLAN_SELECT:
        table = FIGURES[f"select_fee_{_gkey(group)}"]
    elif plan == PLAN_PRIME:
        table = FIGURES[f"prime_fee_{_gkey(group)}"]
    else:
        return 0.0
    return float(table["family" if family else "individual"])


def catastrophic_cap(group: str, retiree: bool) -> float:
    kind = "retiree" if retiree else "adfm"
    return float(FIGURES[f"cat_cap_{kind}_{_gkey(group)}"])


def trs_annual(family: bool) -> float:
    return 12.0 * FIGURES["trs_family_monthly" if family else "trs_member_monthly"]


def trs_eligible(component: str) -> bool:
    """
    TRICARE Reserve Select is sold to Selected Reserve members ONLY.

    It is not a plan an active-duty family, a retiree or a veteran can buy at
    any price. A retired reservist under 60 buys TRICARE Retired Reserve
    instead, which costs roughly ten times as much, and a retiree at 60 moves
    to Prime or Select like any other retiree.
    """
    return component in (GUARD, RESERVE)


def plans_for(component: str) -> list[str]:
    """
    The TRICARE plans this component can actually hold, for the page's menu.

    Offering a plan somebody cannot buy is how a page produces a confident
    wrong answer, so Reserve Select appears for the Selected Reserve and
    nowhere else, and For Life appears only where somebody is already retired.
    Veterans and civilians without a military retirement have no TRICARE at
    all; the menu still asks, because the question is what tells them so.
    """
    if trs_eligible(component):
        return [PLAN_TRS, PLAN_PRIME, PLAN_SELECT]
    if component == RETIRED:
        return [PLAN_PRIME, PLAN_SELECT, PLAN_TFL]
    return [PLAN_PRIME, PLAN_SELECT]


def trr_annual(family: bool) -> float:
    return 12.0 * FIGURES["trr_family_monthly" if family else "trr_member_monthly"]


def va_priority_group(rating: int, permanent_total: bool = False) -> tuple[int | None, str]:
    """
    VA healthcare Priority Group from a disability rating alone.

    The rating is the main driver but not the only one -- Purple Heart, POW
    status, income and enrollment date also place people. Only the rating is
    known here, so a 0% rating returns None with the range it could fall in.
    """
    if rating >= 50:
        why = ("no copays for any VA care, and the family may qualify for "
               "CHAMPVA if they are not TRICARE-eligible" if permanent_total
               else "no copays for any VA care")
        return 1, f"Priority Group 1 — {why}"
    if rating >= 30:
        return 2, "Priority Group 2 — no copays for service-connected care"
    if rating >= 10:
        return 3, "Priority Group 3 — no copays for service-connected care"
    return None, ("Priority Group 5 to 8, set by income and enrollment date; a "
                  "0% service-connected condition is Group 6 for that condition")


# ==========================================================================
# The lifetime model
# ==========================================================================

@dataclass
class YearCost:
    year: int
    age: int
    phase: str
    premiums: float = 0.0         # fees, TRS/TRR, Part B standard, civilian plan
    irmaa: float = 0.0            # Part B + Part D surcharges
    dental: float = 0.0
    ltc: float = 0.0
    out_of_pocket: float = 0.0
    n_part_b: int = 0             # people paying Part B this year
    covered: bool = True          # False when Part B is declined at 65+
    discount_factor: float = 1.0

    @property
    def total(self) -> float:
        return self.premiums + self.irmaa + self.dental + self.ltc + self.out_of_pocket

    @property
    def present_value(self) -> float:
        return self.total * self.discount_factor


@dataclass
class LifetimeCost:
    rows: list = field(default_factory=list)
    group: str = GROUP_A
    start_age: int = 0
    death_age: int = 0
    start_year: int = 0
    leave_service_age: int | None = None
    will_retire: bool = False
    first_part_b_age: int | None = None
    tfl_covered: bool = True
    retirement_magi: float = 0.0
    filing_joint: bool = False
    irmaa_tier: IRMAATier | None = None
    part_d_enrolled: bool = False
    total_today_dollars: float = 0.0
    present_value: float = 0.0
    by_phase: dict = field(default_factory=dict)              # present value
    by_phase_undiscounted: dict = field(default_factory=dict)
    phase_spans: list = field(default_factory=list)           # (phase, first, last)
    first_year_cost: float = 0.0
    assumptions: list = field(default_factory=list)

    def phase_of(self, age: int) -> str | None:
        for r in self.rows:
            if r.age == age:
                return r.phase
        return None

    def span_of(self, phase: str) -> tuple[int, int] | None:
        for p, a, b in self.phase_spans:
            if p == phase:
                return a, b
        return None


# The IRS Uniform Lifetime divisor used to size an RMD. 75 is chosen because
# it is a few years into the RMD years for everyone the app plans for, so the
# figure is representative of the years IRMAA is actually watching.
RMD_ESTIMATE_AGE = 75


def estimate_rmd_annual(h) -> float:
    """
    What today's traditional balances would force out as an RMD, per year.

    RMDs are why a military retiree's MAGI RISES in exactly the years IRMAA is
    watching. Retired pay and Social Security are known and flat; a seven-figure
    traditional TSP starts forcing withdrawals in the seventies whether they are
    wanted or not, and every dollar of them counts in MAGI. Leaving them out
    understates the cliff risk for the one person this page is written for.

    Today's balance is divided by the Uniform Lifetime divisor at
    RMD_ESTIMATE_AGE with NO growth added, so this is a floor rather than a
    forecast: a balance that keeps compounding throws off more.
    """
    m = h.member
    trad = float(m.tsp_traditional_balance) + float(m.ira_traditional_balance)
    sp = h.spouse if (h.has_spouse and h.spouse) else None
    if sp is not None:
        trad += float(sp.tsp_traditional_balance) + float(sp.ira_traditional_balance)
    if trad <= 0:
        return 0.0
    return trad / float(T.UNIFORM_LIFETIME_TABLE[RMD_ESTIMATE_AGE])


def estimate_retirement_magi(h, include_rmd: bool = True) -> float:
    """
    A starting point for MAGI at 65+: retired pay, the taxable share of Social
    Security, and the RMD today's traditional balances would throw off.

    VA compensation, CRSC and Roth withdrawals are NOT in MAGI. Wages are
    assumed to have stopped. It is a starting point and nothing more -- the
    page asks the user to confirm or replace it, because IRMAA turns on a
    single dollar and no estimate is good to a dollar.
    """
    m, ss = h.member, h.social_security
    ss_annual = ss.estimated_monthly_at_fra * 12.0
    if h.has_spouse:
        ss_annual += ss.spouse_estimated_monthly_at_fra * 12.0
    magi = m.retired_pay_monthly * 12.0 + 0.85 * ss_annual
    if include_rmd:
        magi += estimate_rmd_annual(h)
    return magi


def estimate_current_magi(h) -> float:
    """
    This year's MAGI before any conversion: military pay, retired pay, wages.

    Basic pay and taxable special pays count; BAH and BAS never do, and pay
    excluded under the Combat Zone Tax Exclusion does not either -- which is
    what makes a deployment year the cheapest year of a career to convert in.
    """
    m = h.member
    magi = m.retired_pay_monthly * 12.0 + m.civilian_wages_annual
    if h.has_spouse and getattr(h.spouse_income, "employed", False):
        magi += float(getattr(h.spouse_income, "annual_income", 0.0))
    if m.is_serving:
        pay = PAY.compute(m)          # basic + taxable special pays + bonuses
        excluded = 0.0
        if m.in_combat_zone and m.months_deployed_this_year > 0:
            per_month, _ = MIL.czte_monthly_exclusion(
                m.grade, pay.basic_monthly, pay.special_monthly_taxable)
            excluded = min(per_month * min(12, int(m.months_deployed_this_year)),
                           pay.annual)
        magi += max(0.0, pay.annual - excluded)
    return magi


def medicare_enrollees(h, year: int, spouse_birth_year: int | None = None) -> int:
    """How many of member and spouse are 65+ in `year` (spouse assumed same age)."""
    m = h.member
    n = 1 if (year - m.birth_year) >= MEDICARE_AGE else 0
    if h.has_spouse:
        sby = spouse_birth_year or (h.spouse.birth_year if h.spouse else m.birth_year)
        n += 1 if (year - sby) >= MEDICARE_AGE else 0
    return n


def default_leave_service_age(m, today_year: int | None = None) -> int:
    """Twenty years, or next year if already past it."""
    year0 = today_year or date.today().year
    age0 = year0 - m.birth_year
    remaining = max(0.0, 20.0 - m.years_of_service)
    return age0 + max(1, int(math.ceil(remaining)))


def _phase_at(component: str, age: int, leave_age: int, will_retire: bool,
              takes_part_b: bool, retiree_phase: str) -> str:
    over_65 = PH_TFL if takes_part_b else PH_NO_TFL
    if component == RETIRED:
        return retiree_phase if age < MEDICARE_AGE else over_65
    if component == ACTIVE:
        if age < leave_age:
            return PH_ACTIVE
        if not will_retire:
            return PH_CIVILIAN if age < MEDICARE_AGE else PH_MEDICARE
        return retiree_phase if age < MEDICARE_AGE else over_65
    if component in (GUARD, RESERVE):
        if age < leave_age:
            return PH_TRS
        if not will_retire:
            return PH_CIVILIAN if age < MEDICARE_AGE else PH_MEDICARE
        if age < RESERVE_RETIRED_PAY_AGE:
            return PH_GRAY
        return retiree_phase if age < MEDICARE_AGE else over_65
    # Veteran (not retired) and civilian: no TRICARE at any age.
    return PH_CIVILIAN if age < MEDICARE_AGE else PH_MEDICARE


def lifetime_cost(h, *, retirement_magi: float | None = None,
                  filing_joint: bool | None = None,
                  part_d_enrolled: bool = False,
                  leave_service_age: int | None = None,
                  civilian_plan_annual: float | None = None,
                  ltc_start_age: int | None = None,
                  today_year: int | None = None) -> LifetimeCost:
    """
    Year-by-year healthcare cost from now to life expectancy, in today's
    dollars, discounted at the household's real discount rate.

    Reads h.healthcare, h.member (component, birth year, sex, DIEMS, retired
    pay), h.has_spouse and h.assumptions. Everything else is a keyword with a
    sensible default, so a page can override one thing at a time.
    """
    m, hc = h.member, h.healthcare
    year0 = today_year or date.today().year
    age0 = year0 - m.birth_year
    death = max(MORT.life_expectancy(age0, m.sex), age0 + 1)
    r = h.assumptions.real_discount_rate_pct / 100.0

    lc = LifetimeCost(group=tricare_group(m.diems), start_age=age0, death_age=death,
                      start_year=year0, part_d_enrolled=part_d_enrolled)
    lc.filing_joint = bool(h.has_spouse) if filing_joint is None else bool(filing_joint)
    lc.retirement_magi = (estimate_retirement_magi(h) if retirement_magi is None
                          else float(retirement_magi))
    lc.irmaa_tier = irmaa_for_magi(lc.retirement_magi, lc.filing_joint)

    family = bool(h.has_spouse or h.n_dependents > 0)
    spouse_by = (h.spouse.birth_year if (h.has_spouse and h.spouse) else m.birth_year)
    takes_part_b = bool(hc.part_b_when_eligible)
    retiree_phase = PH_RETIREE_SELECT if hc.tricare_plan == PLAN_SELECT else PH_RETIREE_PRIME
    retiree_plan = PLAN_SELECT if retiree_phase == PH_RETIREE_SELECT else PLAN_PRIME

    if m.component in (ACTIVE, GUARD, RESERVE):
        leave = (default_leave_service_age(m, year0) if leave_service_age is None
                 else int(leave_service_age))
        leave = max(leave, age0)
        lc.leave_service_age = leave
        lc.will_retire = (m.years_of_service + (leave - age0)) >= 20.0
    else:
        leave = age0
        lc.will_retire = m.component == RETIRED

    civ = (float(civilian_plan_annual) if civilian_plan_annual is not None
           else float(FIGURES["civilian_family_worker_share_annual" if family
                              else "civilian_single_worker_share_annual"]))
    ltc_from = age0 if ltc_start_age is None else int(ltc_start_age)
    oop_in = max(0.0, float(hc.out_of_pocket_annual))
    dental_annual = max(0.0, float(hc.fedvip_dental_monthly)) * 12.0
    ltc_annual = max(0.0, float(hc.ltc_premium_monthly)) * 12.0
    part_b_std = FIGURES["part_b_standard_monthly"] * 12.0
    surcharge = (lc.irmaa_tier.part_b_surcharge_monthly
                 + (lc.irmaa_tier.part_d_surcharge_monthly if part_d_enrolled else 0.0)) * 12.0
    cap_ret = catastrophic_cap(lc.group, retiree=True)
    cap_adfm = catastrophic_cap(lc.group, retiree=False)

    for age in range(age0, death):
        year = year0 + (age - age0)
        t = age - age0
        phase = _phase_at(m.component, age, leave, lc.will_retire, takes_part_b, retiree_phase)
        row = YearCost(year=year, age=age, phase=phase,
                       discount_factor=1.0 / (1.0 + r) ** t)
        spouse_age = year - spouse_by
        spouse_on_medicare = h.has_spouse and spouse_age >= MEDICARE_AGE and takes_part_b

        if phase == PH_ACTIVE:
            row.out_of_pocket = min(oop_in, cap_adfm) if family else 0.0
        elif phase == PH_TRS:
            row.premiums = trs_annual(family)
            row.out_of_pocket = min(oop_in, cap_adfm)
        elif phase == PH_GRAY:
            row.premiums = trr_annual(family)
            row.out_of_pocket = min(oop_in, cap_ret)
        elif phase in RETIREE_PHASES:
            # A spouse already on Medicare has left the Prime/Select roll.
            fam_here = bool(h.n_dependents > 0 or (h.has_spouse and not spouse_on_medicare))
            row.premiums = enrollment_fee_annual(retiree_plan, lc.group, fam_here)
            if spouse_on_medicare:
                row.n_part_b = 1
                row.premiums += part_b_std
                row.irmaa = surcharge
            row.out_of_pocket = min(oop_in, cap_ret)
        elif phase == PH_TFL:
            n = 1 + (1 if spouse_on_medicare else 0)
            row.n_part_b = n
            row.premiums = part_b_std * n
            row.irmaa = surcharge * n
            if h.has_spouse and not spouse_on_medicare and takes_part_b:
                # Spouse still under 65: on Prime/Select at the individual fee.
                row.premiums += enrollment_fee_annual(retiree_plan, lc.group, False)
            row.out_of_pocket = min(oop_in, cap_ret)
        elif phase == PH_NO_TFL:
            # No Part B: no TFL, no Medigap, no Advantage. Nothing is capped.
            row.covered = False
            row.out_of_pocket = oop_in
        elif phase == PH_CIVILIAN:
            row.premiums = civ
            row.out_of_pocket = oop_in
        elif phase == PH_MEDICARE:
            # Medicare with no TRICARE behind it: the Part B deductible is
            # yours, where TFL would have paid it.
            n = 1 + (1 if spouse_on_medicare else 0)
            row.n_part_b = n
            row.premiums = part_b_std * n
            row.irmaa = surcharge * n
            row.out_of_pocket = oop_in + FIGURES["part_b_deductible_annual"] * n

        row.dental = dental_annual
        row.ltc = ltc_annual if age >= ltc_from else 0.0
        lc.rows.append(row)

    # ---- roll-ups -------------------------------------------------------
    lc.total_today_dollars = sum(x.total for x in lc.rows)
    lc.present_value = sum(x.present_value for x in lc.rows)
    lc.first_year_cost = lc.rows[0].total if lc.rows else 0.0
    for x in lc.rows:
        lc.by_phase[x.phase] = lc.by_phase.get(x.phase, 0.0) + x.present_value
        lc.by_phase_undiscounted[x.phase] = (lc.by_phase_undiscounted.get(x.phase, 0.0)
                                            + x.total)
    first_b = [x.age for x in lc.rows if x.n_part_b > 0 and x.phase in MEDICARE_PHASES]
    lc.first_part_b_age = min(first_b) if first_b else None
    lc.tfl_covered = not any(x.phase == PH_NO_TFL for x in lc.rows)

    spans, cur = [], None
    for x in lc.rows:
        if cur and cur[0] == x.phase:
            cur[2] = x.age
        else:
            cur = [x.phase, x.age, x.age]
            spans.append(cur)
    lc.phase_spans = [tuple(s) for s in spans]

    lc.assumptions = _assumptions(h, lc, spouse_by, retiree_plan, civ)
    return lc


def _assumptions(h, lc: LifetimeCost, spouse_by: int, retiree_plan: str,
                 civ: float) -> list[str]:
    m = h.member
    out = [f"Figures are {FIGURES['year']} amounts held constant in real terms; "
           f"present values use a {h.assumptions.real_discount_rate_pct:g}% real "
           f"discount rate.",
           f"Life expectancy {lc.death_age}, from {MORT.load().source.split(' (')[0]} "
           f"for a {lc.start_age}-year-old. Half of people outlive it."]
    if h.has_spouse and not h.spouse:
        out.append("Your spouse is assumed to be your age, so both of you start "
                   "Medicare Part B in the same year.")
    if m.component in (ACTIVE, GUARD, RESERVE) and lc.leave_service_age is not None:
        out.append(f"You leave the service at {lc.leave_service_age}"
                   + (", retirement-eligible." if lc.will_retire
                      else " without a retirement, so civilian coverage follows."))
    if m.component in (GUARD, RESERVE):
        out.append("Your drilling years are costed at TRICARE Reserve Select. "
                   "On active-duty orders of 30 days or more you get Prime at "
                   "no cost instead, so a mobilisation year costs less than "
                   "this shows.")
    if m.component in (GUARD, RESERVE) and lc.will_retire and (lc.leave_service_age or 0) < 60:
        out.append("Reserve retiree TRICARE starts at 60 even if an early "
                   "retirement moves retired pay earlier.")
    if lc.will_retire:
        out.append(f"Under 65 you use TRICARE {retiree_plan}. Change the plan on "
                   f"the left to compare.")
    if any(x.phase == PH_CIVILIAN for x in lc.rows):
        out.append(f"Civilian coverage is costed at {_money(civ)} a year — the "
                   f"worker's share of an employer plan, an estimate. Enter "
                   f"your own figure on the left.")
    out.append("Dependent children are assumed to have aged off your plan by "
               "the time you reach 65.")
    return out


# ==========================================================================
# Comparisons and findings
# ==========================================================================

def civilian_comparison(lc: LifetimeCost, family: bool) -> dict:
    """
    What TRICARE saves against an employer plan, per year, for the first
    TRICARE phase in the model. An estimate on both sides.
    """
    kind = "family" if family else "single"
    civ_total = FIGURES[f"civilian_{kind}_plan_total_annual"]
    civ_worker = FIGURES[f"civilian_{kind}_worker_share_annual"]
    tricare_rows = [x for x in lc.rows if x.phase in
                    (PH_ACTIVE, PH_TRS, *RETIREE_PHASES)]
    if not tricare_rows:
        return {}
    x = tricare_rows[0]
    yours = x.premiums + x.out_of_pocket
    return {"phase": x.phase, "yours": yours, "civilian_total": civ_total,
            "civilian_worker_share": civ_worker,
            "value_vs_total": civ_total - yours,
            "value_vs_worker_share": civ_worker - yours}


def findings(h, lc: LifetimeCost, probe: ConversionProbe | None = None
             ) -> list[tuple[str, str, str]]:
    """(severity, headline, detail) — severity in good / warn / bad / info."""
    m, hc = h.member, h.healthcare
    out: list[tuple[str, str, str]] = []
    yr = FIGURES["year"]
    std = FIGURES["part_b_standard_monthly"]
    n_medicare = 2 if h.has_spouse else 1
    tier = lc.irmaa_tier or irmaa_for_magi(lc.retirement_magi, lc.filing_joint)
    reaches_65 = lc.death_age > MEDICARE_AGE
    military = lc.will_retire or m.component in (ACTIVE, GUARD, RESERVE, RETIRED)

    # ---- TFL requires Part B ------------------------------------------
    if military and lc.will_retire and reaches_65:
        if not hc.part_b_when_eligible:
            out.append(("bad",
                        "Declining Medicare Part B forfeits TRICARE For Life.",
                        f"TFL is not a plan you enroll in — it is TRICARE paying "
                        f"second to Medicare, and it exists only for people "
                        f"enrolled in Part A AND Part B. Decline Part B and at 65 "
                        f"you have no TRICARE at all, and no Medigap or Medicare "
                        f"Advantage either, since both require Part B too. Enrol "
                        f"late and the premium carries a "
                        f"{FIGURES['part_b_late_penalty_per_year'] * 100:.0f}% "
                        f"penalty for every year you waited, for life. The Part B "
                        f"premium — {_money(std)} a month per person in {yr} — is "
                        f"the price of TFL. This model shows the 65-and-over "
                        f"years as uncovered because that is what they would be."))
        else:
            out.append(("good",
                        f"At 65 your healthcare cost becomes Medicare Part B — "
                        f"{_money(std)} a month per person — and TFL costs nothing "
                        f"on top.",
                        f"TRICARE For Life has no enrollment fee. Medicare pays "
                        f"first, TFL pays second, and for most care the "
                        f"out-of-pocket is zero. It includes the TRICARE pharmacy "
                        f"benefit, so a Part D plan is usually unnecessary. For a "
                        f"couple that is {_money(std * 12 * n_medicare)} a year at "
                        f"the standard premium, which is the number to carry in "
                        f"your retirement budget from {m.birth_year + MEDICARE_AGE}."))

    # ---- IRMAA cliff ---------------------------------------------------
    if reaches_65:
        tiers = irmaa_tiers(lc.filing_joint)
        status = "joint" if lc.filing_joint else "single"
        first = tiers[1]
        # The first cliff is the STANDARD tier's ceiling, which is the first
        # surcharge tier's floor -- not that tier's own ceiling, which is the
        # second cliff and roughly $56,000 further up.
        first_cliff = first.floor
        step_b = (first.part_b_monthly - std) * 12.0
        step_d = first.part_d_surcharge_monthly * 12.0
        if lc.retirement_magi <= 0:
            # Nothing has been entered to estimate from. Saying "$0 of MAGI,
            # $218,000 of headroom" would read as an answer rather than as the
            # absence of one.
            head = ("We have nothing to estimate your income at 65 from, so "
                    "this page cannot tell you whether IRMAA will reach you.")
            sev = "info"
        elif tier.index == 0:
            head = (f"Your expected retirement MAGI of {_money(lc.retirement_magi)} "
                    f"sits {_money(tier.ceiling - lc.retirement_magi)} below the "
                    f"first IRMAA cliff.")
            sev = "info"
        else:
            head = (f"Your expected retirement MAGI of {_money(lc.retirement_magi)} "
                    f"puts you in IRMAA {tier.label}: "
                    f"{_money(tier.part_b_surcharge_monthly * 12)} a year more per "
                    f"person for Part B.")
            sev = "warn"
        nxt = ("" if (tier.is_top or lc.retirement_magi <= 0) else
               f" Your next cliff is at {_money(tier.ceiling)}, "
               f"{_money(tier.ceiling - lc.retirement_magi)} away.")
        if lc.retirement_magi <= 0:
            nxt = (f" Enter what you expect to draw at 65 — retired pay, "
                   f"Social Security, RMDs from a traditional TSP — in the "
                   f"MAGI box on the left, and this page will price it.")
        out.append((sev, head,
                    f"IRMAA is a cliff, not a ramp. A {status} MAGI of "
                    f"{_money(first_cliff)} pays the standard premium; "
                    f"{_money(first_cliff + 1)} — one dollar more — pays "
                    f"{_money(first.part_b_monthly)} a month instead of "
                    f"{_money(std)}, which is {_money(step_b)} a year per person "
                    f"for Part B and another {_money(step_d)} if you hold a Part "
                    f"D plan. One dollar over costs the whole step, for the whole "
                    f"year, and it is set from your return two years earlier — "
                    f"income at {CONVERSION_WINDOW_CLOSES_AT} sets the premium at "
                    f"{MEDICARE_AGE}. VA compensation is not in MAGI; Roth "
                    f"conversions, RMDs and capital gains are.{nxt} If your "
                    f"income drops because you stopped working, file SSA-44 — "
                    f"retirement is a qualifying life-changing event and Social "
                    f"Security will use the current year instead."))

        if lc.start_age < CONVERSION_WINDOW_CLOSES_AT and lc.will_retire:
            yrs = CONVERSION_WINDOW_CLOSES_AT - lc.start_age
            out.append(("info",
                        f"You have {yrs} more year{'s' if yrs != 1 else ''} of "
                        f"Roth conversions that cannot touch your Medicare "
                        f"premium.",
                        f"IRMAA looks back two years, so MAGI through age "
                        f"{CONVERSION_WINDOW_CLOSES_AT - 1} sets premiums for "
                        f"years you are not yet on Medicare. From "
                        f"{CONVERSION_WINDOW_CLOSES_AT} on, every conversion "
                        f"year has a Part B price two years later. A military "
                        f"retiree with a pension and TRICARE has a wider window "
                        f"than a civilian, because there is no ACA subsidy to "
                        f"lose — use it before {CONVERSION_WINDOW_CLOSES_AT}."))

    # ---- The conversion probe ---------------------------------------------
    if probe is not None and probe.conversion > 0 and probe.after is not None:
        if probe.tiers_crossed > 0:
            trim = probe.headroom_before
            detail = (f"Converting {_money(probe.conversion)} takes MAGI from "
                      f"{_money(probe.baseline_magi)} to {_money(probe.magi_after)}, "
                      f"which is {_money(probe.overshoot)} past the "
                      f"{_money(probe.after.floor)} line. The Part B premium in "
                      f"{probe.year_paid} goes from "
                      f"{_money(probe.before.part_b_monthly)} to "
                      f"{_money(probe.after.part_b_monthly)} a month per person"
                      + (f", plus {_money(probe.after.part_d_surcharge_monthly)} "
                         f"of Part D surcharge" if probe.include_part_d and
                         probe.after.part_d_surcharge_monthly > 0 else "")
                      + f" — {_money(probe.extra_annual_cost)} for the household, "
                      f"an effective {probe.effective_rate * 100:.1f}% surcharge on "
                      f"the conversion, for one year. ")
            if trim > 0 and not math.isinf(trim):
                detail += (f"Convert {_money(trim)} instead and the surcharge is "
                           f"zero; the last {_money(probe.overshoot)} is what "
                           f"costs the whole step.")
            if not probe.applies:
                detail += (f" It does not land this time — nobody in the "
                           f"household is on Medicare in {probe.year_paid} — but "
                           f"the same conversion from age "
                           f"{CONVERSION_WINDOW_CLOSES_AT} on would.")
                sev = "info"
            else:
                sev = "warn"
            cliffs = (f"{probe.tiers_crossed} IRMAA cliff"
                      f"{'s' if probe.tiers_crossed > 1 else ''}")
            head = (f"Converting {_money(probe.conversion)} this year crosses "
                    f"{cliffs} and costs {_money(probe.extra_annual_cost)} in "
                    f"{probe.year_paid} Medicare premiums."
                    if probe.applies else
                    f"Converting {_money(probe.conversion)} this year crosses "
                    f"{cliffs} — but nobody is on Medicare in "
                    f"{probe.year_paid}, so it costs nothing.")
            out.append((sev, head, detail))
        else:
            room = irmaa_headroom(probe.magi_after, probe.joint)
            out.append(("good",
                        f"Converting {_money(probe.conversion)} this year stays in "
                        f"the same IRMAA tier.",
                        (f"MAGI of {_money(probe.magi_after)} after the conversion "
                         f"leaves {_money(room)} of headroom below the next cliff "
                         f"at {_money(probe.after.ceiling)}. "
                         if not math.isinf(room) else
                         f"You are already in the top tier, so there is no "
                         f"further IRMAA cost to a larger conversion. ")
                        + f"IRMAA is recomputed every year, so this is a "
                        f"one-year question you get to ask again next year."))

    # ---- TRICARE against a civilian plan ----------------------------------
    family = bool(h.has_spouse or h.n_dependents > 0)
    comp = civilian_comparison(lc, family)
    if comp:
        out.append(("good",
                    f"TRICARE is worth roughly {_money(comp['value_vs_total'])} a "
                    f"year against a civilian {'family' if family else 'single'} "
                    f"plan.",
                    f"An employer {'family' if family else 'single'} plan costs "
                    f"about {_money(comp['civilian_total'])} a year in total "
                    f"premiums — an estimate from the KFF employer survey, of "
                    f"which the worker typically pays "
                    f"{_money(comp['civilian_worker_share'])} — with a deductible "
                    f"and an out-of-pocket maximum on top. Your "
                    f"{comp['phase'].split(' — ')[-1]} costs "
                    f"{_money(comp['yours'])} a year with a catastrophic cap of "
                    f"{_money(catastrophic_cap(lc.group, retiree=True))}. For a "
                    f"retiree that gap is the part of retired pay nobody prices, "
                    f"and it is why a second-career salary without benefits is "
                    f"worth more to you than the same salary is to a civilian."))

    # ---- Group A / Group B --------------------------------------------------
    if lc.will_retire or m.component == RETIRED:
        if lc.group == GROUP_B:
            out.append(("info",
                        "Your DIEMS date puts you in TRICARE Group B.",
                        f"Entry on or after 1 January 2018 means higher retiree "
                        f"enrollment fees — "
                        f"{_money(enrollment_fee_annual(PLAN_PRIME, GROUP_B, True))} "
                        f"a year for family Prime against "
                        f"{_money(enrollment_fee_annual(PLAN_PRIME, GROUP_A, True))} "
                        f"for Group A — and a catastrophic cap of "
                        f"{_money(catastrophic_cap(GROUP_B, True))} that is indexed "
                        f"to the retiree COLA, where Group A's is fixed at "
                        f"{_money(catastrophic_cap(GROUP_A, True))}. Still a "
                        f"fraction of any civilian plan."))
        else:
            out.append(("info",
                        "Your DIEMS date puts you in TRICARE Group A.",
                        f"Entry before 1 January 2018: family Prime costs "
                        f"{_money(enrollment_fee_annual(PLAN_PRIME, GROUP_A, True))} "
                        f"a year, Select "
                        f"{_money(enrollment_fee_annual(PLAN_SELECT, GROUP_A, True))}, "
                        f"and the catastrophic cap is fixed in law at "
                        f"{_money(catastrophic_cap(GROUP_A, True))}. Prime is the "
                        f"HMO — a primary care manager and referrals, near-zero "
                        f"copays. Select is the PPO — any TRICARE-authorised "
                        f"provider, with copays. Prime requires living near a "
                        f"military treatment facility or a Prime service area."))

    # ---- Guard and Reserve --------------------------------------------------
    if m.component in (GUARD, RESERVE):
        out.append(("good",
                    f"TRICARE Reserve Select at "
                    f"{_money(FIGURES['trs_family_monthly' if family else 'trs_member_monthly'])} "
                    f"a month is the best-priced coverage most Guard and Reserve "
                    f"families can get.",
                    f"It is Select-style coverage — any TRICARE-authorised "
                    f"provider — for {_money(trs_annual(family))} a year. Compare "
                    f"that to the worker's share of an employer family plan at "
                    f"roughly {_money(FIGURES['civilian_family_worker_share_annual'])}. "
                    f"You cannot hold it while on active duty orders (you get "
                    f"Prime for free then) and, until the law changes, not while "
                    f"eligible for FEHB as a federal civilian employee."))
        if lc.will_retire and (lc.leave_service_age or 0) < RESERVE_RETIRED_PAY_AGE:
            out.append(("warn",
                        f"Between {lc.leave_service_age} and 60 you are in the gray "
                        f"area, and TRICARE Retired Reserve costs "
                        f"{_money(trr_annual(family))} a year.",
                        f"A Reserve retiree is not a TRICARE retiree until 60. "
                        f"TRR is priced at full cost — "
                        f"{_money(FIGURES['trr_family_monthly'])} a month for a "
                        f"family in {yr} — which is closer to a civilian plan "
                        f"than to anything else TRICARE sells. Plan for employer "
                        f"coverage through those years, or budget for TRR. An "
                        f"early retirement earned by deployments moves retired "
                        f"pay earlier but does not move TRICARE."))

    # ---- The VA as a parallel system -----------------------------------------
    if m.va_rating > 0:
        group, label = va_priority_group(m.va_rating, m.va_rating_permanent_total)
        out.append(("info",
                    f"Your {m.va_rating}% rating puts you in VA {label.split(' — ')[0]} "
                    f"— care for you, not your family.",
                    f"{label}. VA healthcare runs alongside TRICARE, not instead "
                    f"of it: use the VA for service-connected conditions at no "
                    f"cost, and TRICARE for everything else and for everyone "
                    f"else. Your spouse and children are not VA patients, so it "
                    f"is not a substitute for family coverage. (CHAMPVA covers "
                    f"dependents of 100% P&T veterans only when they are NOT "
                    f"TRICARE-eligible, which a retiree's family is.) At 65 the "
                    f"VA does not require Part B — but TFL does, and dropping "
                    f"TFL to save the premium leaves your family with nothing."))

    # ---- Part D ---------------------------------------------------------------
    if military and lc.will_retire and reaches_65 and hc.part_b_when_eligible:
        if lc.part_d_enrolled:
            out.append(("info",
                        "You probably do not need a Part D plan with TFL.",
                        "The TRICARE pharmacy benefit is creditable drug coverage, "
                        "so there is no late-enrollment penalty for skipping "
                        "Part D, and TFL beneficiaries who enroll pay a Part D "
                        "premium plus the Part D IRMAA on top of Part B. The usual "
                        "reason to enroll anyway is a drug TRICARE does not cover, "
                        "or Extra Help eligibility. Turn the Part D switch off to "
                        "see the cost without it."))
        elif tier.index > 0:
            out.append(("info",
                        "Part D IRMAA is only charged if you hold a Part D plan.",
                        f"TFL's pharmacy benefit is creditable coverage, so most "
                        f"TFL retirees never enroll in Part D and never pay its "
                        f"surcharge — {_money(tier.part_d_surcharge_monthly)} a "
                        f"month per person at your tier. The model leaves it out; "
                        f"the switch on the left adds it back."))

    # ---- Long-term care -------------------------------------------------------
    if hc.ltc_premium_monthly <= 0 and lc.start_age >= 50:
        out.append(("warn",
                    "Nothing on this page covers long-term care.",
                    "TRICARE, TRICARE For Life and Medicare all stop at custodial "
                    "care — help with daily living in a facility or at home — "
                    "which is the largest uninsured cost most families face after "
                    "80. The VA covers it only for higher-rated and low-income "
                    "veterans, and only for the veteran. The Federal Long Term "
                    "Care Insurance Program is open to service members and "
                    "retirees but has been closed to new applicants since "
                    "December 2022; check whether it has reopened before pricing "
                    "a private policy. Enter a premium on the left to see it in "
                    "the lifetime figure."))

    # ---- No TRICARE at all --------------------------------------------------
    if m.component in (VETERAN, CIVILIAN) or (m.component in (ACTIVE, GUARD, RESERVE)
                                               and not lc.will_retire):
        out.append(("warn",
                    "Without a military retirement there is no TRICARE, and the "
                    "model needs your real plan cost.",
                    f"Separating short of twenty years ends TRICARE — "
                    f"Transitional Assistance Management Program covers 180 days, "
                    f"then the Continued Health Care Benefit Program sells up to 36 "
                    f"months at full cost. The civilian years here are costed at "
                    f"the worker's share of an employer plan, an estimate. Enter "
                    f"what your plan actually costs. If you carry a VA rating, VA "
                    f"care covers you for service-connected conditions but not "
                    f"your family."))

    return out
