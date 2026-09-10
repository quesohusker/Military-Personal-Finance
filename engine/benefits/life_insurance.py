"""
SGLI, VGLI, and why VGLI is usually the wrong answer.

SGLI covers up to $500,000 at a flat rate regardless of age -- $25 a month plus
$1 for the traumatic injury rider since the July 2025 premium reduction. For a
45-year-old that is extraordinarily cheap; for a 22-year-old it is merely cheap.

At separation you may convert SGLI to VGLI. The conversion has a hard deadline
and a soft one:

    Within 240 days   Guaranteed acceptance. No health questions at all.
    241 to 485 days   Still eligible, but you must prove good health.
    After 485 days    Gone.

VGLI premiums are age-banded in five-year steps and escalate steeply -- modest
under 30, several hundred a month by 60, over a thousand a month in the
seventies. That escalation arrives exactly when a fixed retirement income is
least able to absorb it.

THE CONCLUSION THIS MODULE ARGUES FOR: VGLI is the right answer for someone who
cannot get commercial coverage. For a healthy separating member, level term is
usually a fraction of the cost with a premium locked for twenty or thirty years.

AND THE TIMING TRAP: apply for commercial term and be APPROVED before you
separate, while the 240-day guaranteed-acceptance window is still open. Then
VGLI is your fallback if underwriting goes badly. Do it the other way round and
a declined application leaves you with nothing but an expiring window.
"""

from __future__ import annotations
from dataclasses import dataclass, field

SGLI_MAX = 500_000.0
SGLI_RATE_PER_1000 = 0.05          # monthly, since 1 July 2025
TSGLI_MONTHLY = 1.00
SGLI_FREE_DAYS_AFTER_SEPARATION = 120

VGLI_MAX = 500_000.0
VGLI_GUARANTEED_DAYS = 240
VGLI_FINAL_DEADLINE_DAYS = 485

FSGLI_SPOUSE_MAX = 100_000.0
FSGLI_CHILD_COVERAGE = 10_000.0    # free

# VGLI monthly premium per $10,000 of coverage, by age band. Estimates for
# planning; confirm current rates at va.gov before relying on them.
VGLI_RATE_PER_10K = {
    29: 0.70, 34: 0.90, 39: 1.20, 44: 1.60, 49: 2.10, 54: 3.30,
    59: 6.00, 64: 10.00, 69: 13.30, 74: 22.50, 79: 46.00, 999: 66.00,
}

# Illustrative level-term rates per $10,000 monthly, for a healthy non-smoker
# at issue age, 20-year level term. Real quotes vary by carrier and health.
TERM_RATE_PER_10K_20YR = {
    29: 0.22, 34: 0.26, 39: 0.36, 44: 0.58, 49: 0.95, 54: 1.55,
    59: 2.70, 64: 4.60, 999: 8.00,
}


def _band(age: int, table: dict) -> float:
    for ceiling in sorted(table):
        if age <= ceiling:
            return table[ceiling]
    return table[max(table)]


def sgli_monthly(coverage: float = SGLI_MAX, include_tsgli: bool = True) -> float:
    """SGLI is a flat rate at every age."""
    c = min(max(0.0, coverage), SGLI_MAX)
    return c / 1_000.0 * SGLI_RATE_PER_1000 + (TSGLI_MONTHLY if include_tsgli else 0.0)


def vgli_monthly(age: int, coverage: float) -> float:
    return min(max(0.0, coverage), VGLI_MAX) / 10_000.0 * _band(age, VGLI_RATE_PER_10K)


def term_monthly(issue_age: int, coverage: float) -> float:
    """Illustrative level-term premium, fixed for the term at the issue age."""
    return max(0.0, coverage) / 10_000.0 * _band(issue_age, TERM_RATE_PER_10K_20YR)


@dataclass
class InsuranceComparison:
    coverage: float = 0.0
    separation_age: int = 0
    compare_to_age: int = 0

    sgli_monthly: float = 0.0
    vgli_first_monthly: float = 0.0
    vgli_final_monthly: float = 0.0
    vgli_total: float = 0.0

    term_monthly: float = 0.0
    term_total: float = 0.0
    term_expires_at_age: int = 0

    saving: float = 0.0
    recommendation: str = ""
    reasoning: list = field(default_factory=list)


def compare(coverage: float, separation_age: int, compare_to_age: int = 70,
            term_years: int = 20, insurable: bool = True
            ) -> InsuranceComparison:
    """
    VGLI against level term over the same period.

    `insurable` is the whole question. If a health condition makes commercial
    coverage unavailable, VGLI's guaranteed acceptance is worth its price and
    nothing else competes.
    """
    c = InsuranceComparison(coverage=min(coverage, VGLI_MAX),
                            separation_age=separation_age,
                            compare_to_age=compare_to_age,
                            term_expires_at_age=separation_age + term_years)
    c.sgli_monthly = sgli_monthly(c.coverage)
    c.vgli_first_monthly = vgli_monthly(separation_age, c.coverage)
    c.vgli_final_monthly = vgli_monthly(compare_to_age, c.coverage)

    # VGLI, year by year through the age bands.
    total = 0.0
    for age in range(separation_age, compare_to_age):
        total += vgli_monthly(age, c.coverage) * 12.0
    c.vgli_total = total

    c.term_monthly = term_monthly(separation_age, c.coverage)
    covered_years = min(term_years, max(0, compare_to_age - separation_age))
    c.term_total = c.term_monthly * 12.0 * covered_years
    c.saving = c.vgli_total - c.term_total

    if not insurable:
        c.recommendation = "Take VGLI"
        c.reasoning = [
            "**VGLI exists for exactly this case.** Within 240 days of "
            "separation it is issued with no health questions at all. If a "
            "condition makes commercial coverage unavailable or unaffordable, "
            "that guaranteed acceptance is worth the escalating premium and "
            "nothing else competes with it.",
            f"Budget for the escalation: ${c.vgli_first_monthly:,.0f} a month at "
            f"{separation_age} becomes ${c.vgli_final_monthly:,.0f} a month at "
            f"{compare_to_age}. Plan for the year it stops being affordable, "
            f"because for most people there is one.",
        ]
        return c

    c.recommendation = "Level term, with VGLI as the fallback"
    c.reasoning = [
        (f"Level term at {separation_age} costs about "
         f"${c.term_monthly:,.0f} a month, fixed for {term_years} years. VGLI "
         f"starts at ${c.vgli_first_monthly:,.0f} and rises with every "
         f"five-year age band, reaching ${c.vgli_final_monthly:,.0f} a month by "
         f"{compare_to_age}."),
        (f"Over the period to {compare_to_age} that is roughly "
         f"${c.vgli_total:,.0f} for VGLI against ${c.term_total:,.0f} for term "
         f"— a difference of about ${c.saving:,.0f}."),
        ("**Do this in the right order.** Apply for commercial term and be "
         "APPROVED before you separate, while the 240-day guaranteed-acceptance "
         "window for VGLI is still open. Then VGLI is your fallback if "
         "underwriting goes badly. Separate first and apply later, and a "
         "declined application leaves you with an expiring window and no "
         "coverage."),
        (f"Term expires at {c.term_expires_at_age}. That is a real limitation, "
         f"not a footnote — but by then a military retiree usually has a "
         f"pension, SBP, and possibly DIC standing behind their survivor, so "
         f"the amount of insurance actually needed is far smaller. Size the "
         f"coverage to the gap, not to a round number."),
    ]
    return c


@dataclass
class NeedsAnalysis:
    income_replacement: float = 0.0
    mortgage_payoff: float = 0.0
    education: float = 0.0
    final_expenses: float = 0.0
    gross_need: float = 0.0

    survivor_income_offset: float = 0.0
    existing_assets: float = 0.0
    net_need: float = 0.0
    current_coverage: float = 0.0
    gap: float = 0.0
    notes: list = field(default_factory=list)


def needs(annual_income_to_replace: float, years_to_replace: float,
          mortgage_balance: float = 0.0, education_cost: float = 0.0,
          final_expenses: float = 25_000.0,
          survivor_annual_income: float = 0.0,
          liquid_assets: float = 0.0,
          current_coverage: float = 0.0,
          real_discount_rate: float = 0.03) -> NeedsAnalysis:
    """
    How much cover is actually needed, after what a military survivor already
    receives.

    This is where military and civilian needs analysis diverge sharply. A
    retiree's survivor may already have SBP, DIC and Social Security survivor
    benefits. Sizing a policy without netting those off buys insurance against
    a loss that is already partly covered.
    """
    from engine.networth.balance_sheet import annuity_present_value

    n = NeedsAnalysis(
        income_replacement=annuity_present_value(annual_income_to_replace,
                                                 years_to_replace,
                                                 real_discount_rate),
        mortgage_payoff=mortgage_balance, education=education_cost,
        final_expenses=final_expenses, current_coverage=current_coverage,
        existing_assets=liquid_assets)

    n.survivor_income_offset = annuity_present_value(
        survivor_annual_income, years_to_replace, real_discount_rate)

    n.gross_need = (n.income_replacement + n.mortgage_payoff + n.education
                    + n.final_expenses)
    n.net_need = max(0.0, n.gross_need - n.survivor_income_offset
                     - n.existing_assets)
    n.gap = max(0.0, n.net_need - n.current_coverage)

    if n.survivor_income_offset > 0:
        n.notes.append(
            f"Your survivor's existing guaranteed income — SBP, DIC, Social "
            f"Security survivor benefits — is worth about "
            f"${n.survivor_income_offset:,.0f} against this need. Sizing a "
            f"policy without netting that off buys cover for a loss that is "
            f"already partly insured.")

    if n.gap <= 0:
        n.notes.append(
            f"Your existing ${current_coverage:,.0f} of coverage meets the need "
            f"as calculated. Re-check it when the mortgage changes, when a "
            f"child's education is funded, and at separation.")
    else:
        n.notes.append(
            f"A gap of about ${n.gap:,.0f}. Note that this need SHRINKS over "
            f"time as the mortgage amortises and children finish education — "
            f"which is exactly why level term, priced for a fixed period, fits "
            f"better than permanent coverage priced for life.")

    return n
