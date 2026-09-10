"""
Military retirement systems, the 20-year cliff, and the BRS lump-sum election.

Four systems, chosen for you by your DIEMS date rather than by preference:

    Final Pay   2.5% x years x FINAL basic pay,  full CPI
    High-3      2.5% x years x high-36 average,  full CPI
    CSB/REDUX   reduced multiplier + CPI minus 1%, recomputed at 62
    BRS         2.0% x years x high-36 average,  full CPI, plus a TSP match

Two decisions live here and both are large.

THE 20-YEAR CLIFF. Under the legacy systems, separating at 19 years and 11
months produces exactly nothing -- no pension, no retiree TRICARE, no
commissary. At 20 years it produces an inflation-indexed lifetime annuity
typically worth seven figures in present value. There is no other point in a
career where twelve months is worth that much, and the app should be able to
put a number on it.

THE BRS LUMP SUM. At retirement a BRS retiree may take 25% or 50% of the
discounted present value of their retired pay up to Social Security full
retirement age, as cash, in exchange for a reduced annuity until that age. The
discount rate DoD uses -- 6.46% for 2026 -- is applied to what is functionally a
COLA-indexed, government-backed, longevity-hedged income stream. You would only
accept that trade if you were confident of clearing 6.46% AFTER TAX, on a lump
sum that arrives fully taxable in a single year, while absorbing the sequence
risk the annuity does not carry. This module computes the break-even rather than
asserting a verdict.
"""

from __future__ import annotations
from dataclasses import dataclass, field

from engine.networth.balance_sheet import annuity_present_value

SYS_FINAL_PAY = "Final Pay"
SYS_HIGH3 = "High-3"
SYS_REDUX = "CSB/REDUX"
SYS_BRS = "Blended Retirement System"

MULTIPLIER_LEGACY = 0.025
MULTIPLIER_BRS = 0.020
REDUX_PENALTY_PER_YEAR_UNDER_30 = 0.01
REDUX_COLA_PENALTY = 0.01
REDUX_RECOMPUTE_AGE = 62
MAX_MULTIPLIER = 0.75
CSB_BONUS = 30_000.0

# DoD-published discount rate for the BRS lump-sum calculation, CY2026.
BRS_LUMP_SUM_DISCOUNT_2026 = 0.0646
SSA_FULL_RETIREMENT_AGE = 67


def multiplier(system: str, years_of_service: float) -> float:
    """Retired pay multiplier, capped at 75%."""
    y = max(0.0, years_of_service)
    if system == SYS_BRS:
        m = MULTIPLIER_BRS * y
    elif system == SYS_REDUX:
        m = MULTIPLIER_LEGACY * y - REDUX_PENALTY_PER_YEAR_UNDER_30 * max(0.0, 30.0 - y)
    else:
        m = MULTIPLIER_LEGACY * y
    return max(0.0, min(MAX_MULTIPLIER, m))


@dataclass
class RetiredPay:
    system: str = ""
    years_of_service: float = 0.0
    multiplier: float = 0.0
    base_pay: float = 0.0          # high-3 average, or final pay
    monthly: float = 0.0
    annual: float = 0.0
    real_cola_drift: float = 0.0   # 0 for full CPI, negative for REDUX
    note: str = ""


def retired_pay(system: str, years_of_service: float,
                high_three_monthly: float) -> RetiredPay:
    """Monthly retired pay at the moment of retirement."""
    mult = multiplier(system, years_of_service)
    monthly = high_three_monthly * mult

    note = ""
    drift = 0.0
    if system == SYS_REDUX:
        drift = -REDUX_COLA_PENALTY
        note = (f"REDUX pays CPI minus one percent, so the pension loses about "
                f"1% of its purchasing power every year until the recomputation "
                f"at {REDUX_RECOMPUTE_AGE}, which restores it to what High-3 "
                f"would have paid. The reduced COLA then resumes.")
    elif system == SYS_BRS:
        note = ("BRS pays a smaller pension than the legacy systems, and makes "
                "up the difference with a TSP match you receive from your third "
                "year of service. Judge it on the two together, never on the "
                "multiplier alone.")
    elif system == SYS_FINAL_PAY:
        note = "Final Pay uses your last month of basic pay, not a three-year average."

    if years_of_service < 20 and system != SYS_BRS:
        note = (f"At {years_of_service:g} years there is no pension at all under "
                f"{system}. The 20-year cliff is absolute.")
        monthly = 0.0
        mult = 0.0

    return RetiredPay(system=system, years_of_service=years_of_service,
                      multiplier=mult, base_pay=high_three_monthly,
                      monthly=monthly, annual=monthly * 12.0,
                      real_cola_drift=drift, note=note)


# --------------------------------------------------------------------------
# The 20-year cliff
# --------------------------------------------------------------------------

@dataclass
class CliffAnalysis:
    current_years: float = 0.0
    years_remaining: float = 0.0
    pension_if_you_stay: float = 0.0        # annual
    present_value: float = 0.0
    value_per_remaining_year: float = 0.0
    tsp_kept_if_you_leave: float = 0.0
    system: str = ""
    note: str = ""


def value_of_reaching_twenty(system: str, current_years: float,
                             high_three_monthly: float, retirement_age: int,
                             life_expectancy: int = 90,
                             real_discount_rate: float = 0.03,
                             tsp_balance: float = 0.0) -> CliffAnalysis:
    """
    What the remaining years to 20 are worth.

    For a legacy-system member near the cliff this is the single largest number
    in their financial life, and it is invisible on a pay stub.
    """
    remaining = max(0.0, 20.0 - current_years)
    pay = retired_pay(system, 20.0, high_three_monthly)
    years_drawing = max(0.0, life_expectancy - (retirement_age + remaining))
    pv = annuity_present_value(pay.annual, years_drawing, real_discount_rate)

    out = CliffAnalysis(
        current_years=current_years, years_remaining=remaining,
        pension_if_you_stay=pay.annual, present_value=pv, system=system,
        value_per_remaining_year=(pv / remaining) if remaining > 0 else 0.0,
        tsp_kept_if_you_leave=tsp_balance if system == SYS_BRS else tsp_balance,
    )

    if remaining <= 0:
        out.note = ("You are already retirement-eligible. The pension is earned; "
                    "each additional year adds to the multiplier but the cliff "
                    "is behind you.")
    elif system == SYS_BRS:
        out.note = (f"Under BRS the cliff is real but far less brutal: if you "
                    f"separate before 20 you keep your TSP balance, including "
                    f"the vested match. That is the whole design of BRS, and it "
                    f"is why the roughly 85% of members who never reach 20 are "
                    f"better off under it. Reaching 20 is still worth about "
                    f"${pv:,.0f} in present value.")
    else:
        out.note = (f"Under {system} there is no partial credit. Separating at "
                    f"19 years and 11 months produces no pension, no retiree "
                    f"TRICARE and no commissary access. The remaining "
                    f"{remaining:g} year(s) are worth roughly ${pv:,.0f} in "
                    f"present value — about ${out.value_per_remaining_year:,.0f} "
                    f"per year served. There is no other point in a career where "
                    f"twelve months is worth that much.")
    return out


# --------------------------------------------------------------------------
# The BRS lump-sum election
# --------------------------------------------------------------------------

@dataclass
class LumpSumAnalysis:
    share: float = 0.0                    # 0.25 or 0.50
    lump_sum_gross: float = 0.0
    lump_sum_after_tax: float = 0.0
    annuity_reduction_monthly: float = 0.0
    years_reduced: float = 0.0
    total_annuity_given_up: float = 0.0
    discount_rate: float = 0.0
    breakeven_real_return: float = 0.0
    marginal_tax_rate: float = 0.0
    verdict: str = ""
    reasoning: list = field(default_factory=list)


def brs_lump_sum(annual_retired_pay: float, retirement_age: int,
                 share: float = 0.50,
                 discount_rate: float = BRS_LUMP_SUM_DISCOUNT_2026,
                 ssa_fra: int = SSA_FULL_RETIREMENT_AGE,
                 marginal_tax_rate: float = 0.32,
                 real_discount_for_comparison: float = 0.03) -> LumpSumAnalysis:
    """
    Price the lump-sum election honestly.

    The output is a break-even return, not a verdict. There are narrow cases
    where taking it is defensible -- a genuinely short life expectancy, or
    extinguishing debt at a rate above the break-even -- and the analysis should
    let those show rather than moralising.
    """
    years_to_fra = max(0.0, ssa_fra - retirement_age)
    out = LumpSumAnalysis(share=share, discount_rate=discount_rate,
                          years_reduced=years_to_fra,
                          marginal_tax_rate=marginal_tax_rate)

    if years_to_fra <= 0 or annual_retired_pay <= 0:
        out.verdict = "Not applicable"
        out.reasoning = ["The election applies only before Social Security full "
                         "retirement age."]
        return out

    # DoD discounts the stream to FRA at its published rate.
    pv_to_fra = annuity_present_value(annual_retired_pay, years_to_fra,
                                      discount_rate)
    out.lump_sum_gross = pv_to_fra * share

    # It arrives fully taxable in a single year, usually stacked on a first-year
    # civilian salary.
    out.lump_sum_after_tax = out.lump_sum_gross * (1.0 - marginal_tax_rate)

    out.annuity_reduction_monthly = (annual_retired_pay * share) / 12.0
    out.total_annuity_given_up = annual_retired_pay * share * years_to_fra

    # What the after-tax lump sum must earn, in real terms, to replace the
    # payments it is buying out.
    out.breakeven_real_return = _solve_breakeven(
        out.lump_sum_after_tax, annual_retired_pay * share, years_to_fra)

    out.reasoning = [
        (f"You would receive ${out.lump_sum_gross:,.0f} before tax — "
         f"${out.lump_sum_after_tax:,.0f} after tax at a "
         f"{marginal_tax_rate * 100:.0f}% marginal rate. It lands entirely in "
         f"one tax year, usually stacked on top of a first-year civilian "
         f"salary, which is what pushes the rate that high in the first place."),
        (f"In exchange your retired pay falls by "
         f"${out.annuity_reduction_monthly:,.0f} a month for "
         f"{years_to_fra:.0f} years — ${out.total_annuity_given_up:,.0f} of "
         f"payments given up — and is then restored in full at "
         f"{ssa_fra}."),
        (f"For that to be worth doing, the after-tax lump sum must earn about "
         f"**{out.breakeven_real_return * 100:.1f}% real, every year, with "
         f"certainty**, just to break even."),
        (f"DoD discounts your pension at {discount_rate * 100:.2f}% to compute "
         f"the offer. That rate is applied to an inflation-indexed, "
         f"government-backed, lifetime income stream — the safest cash flow in "
         f"anyone's financial life. You are being asked to sell the safest asset "
         f"you own at a rate you would normally demand from equities."),
        ("The annuity also carries no sequence risk and no longevity risk. A "
         "lump sum invested carries both. A bad first five years cannot reduce "
         "your pension; it can permanently impair a portfolio."),
    ]

    if out.breakeven_real_return > 0.05:
        out.verdict = "Almost certainly a bad trade"
        out.reasoning.append(
            f"A {out.breakeven_real_return * 100:.1f}% guaranteed real return "
            f"does not exist. Long-run real equity returns are in that "
            f"neighbourhood but carry the risk of decades of underperformance, "
            f"and you would need to clear it after tax, every year, without a "
            f"bad sequence.")
    elif out.breakeven_real_return > 0.03:
        out.verdict = "Probably a bad trade"
    else:
        out.verdict = "Worth modelling carefully"

    out.reasoning.append(
        "Narrow cases where it can still be right: a genuinely shortened life "
        "expectancy, extinguishing debt at a rate above the break-even, or a "
        "specific business use with a return you can actually defend. "
        "'I will invest it' is not one of those cases unless you can name the "
        "investment and its risk.")

    return out


def _solve_breakeven(lump_after_tax: float, annual_payment_forgone: float,
                     years: float, lo: float = -0.5, hi: float = 1.0) -> float:
    """
    The real return at which the after-tax lump sum exactly funds the payments
    it replaces. Bisection, because the annuity factor has no clean inverse.
    """
    if lump_after_tax <= 0 or annual_payment_forgone <= 0 or years <= 0:
        return 0.0

    def shortfall(rate: float) -> float:
        return annuity_present_value(annual_payment_forgone, years, rate) - lump_after_tax

    if shortfall(hi) > 0:
        return hi
    for _ in range(80):
        mid = (lo + hi) / 2.0
        if shortfall(mid) > 0:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


# --------------------------------------------------------------------------
# Comparing systems
# --------------------------------------------------------------------------

def compare_systems(years_of_service: float, high_three_monthly: float,
                    retirement_age: int, life_expectancy: int = 90,
                    real_discount_rate: float = 0.03,
                    tsp_balance_brs: float = 0.0) -> list[dict]:
    """
    All four systems side by side. Only one applies to any given member -- this
    exists to explain what theirs is worth relative to the others, not to offer
    a choice they do not have.
    """
    years_drawing = max(0.0, life_expectancy - retirement_age)
    out = []
    for system in (SYS_FINAL_PAY, SYS_HIGH3, SYS_REDUX, SYS_BRS):
        pay = retired_pay(system, years_of_service, high_three_monthly)
        # REDUX's reduced COLA is a real loss, so discount it harder.
        rate = real_discount_rate - pay.real_cola_drift
        pv = annuity_present_value(pay.annual, years_drawing, rate)
        row = {"System": system, "Multiplier": pay.multiplier,
               "Monthly": pay.monthly, "Annual": pay.annual,
               "Pension present value": pv,
               "TSP from match": tsp_balance_brs if system == SYS_BRS else 0.0,
               "Total": pv + (tsp_balance_brs if system == SYS_BRS else 0.0),
               "Note": pay.note}
        if system == SYS_REDUX:
            row["Total"] += CSB_BONUS
            row["CSB bonus"] = CSB_BONUS
        out.append(row)
    return out
