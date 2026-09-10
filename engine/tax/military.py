"""
Military-specific federal tax rules.

Two things here that no civilian tax model contains, and that between them
explain most of what makes military financial planning different:

  1. THE UNTAXED ALLOWANCE SPLIT. BAH and BAS never enter gross income. An E-6
     with $70,000 of total compensation may show roughly $48,000 of taxable
     wages, so their marginal bracket sits well below their standard of living.
     That is the whole basis for defaulting to Roth.

  2. THE COMBAT ZONE TAX EXCLUSION. For enlisted members and warrant officers,
     ALL military pay earned in a qualifying month is excluded, with no cap.
     Commissioned officers are capped at the highest enlisted basic pay plus
     hostile fire pay. Any part of a month in the zone counts as a whole month.

CZTE turns a deployment into the cheapest tax year of a career, and that is
what makes it the single best moment to fill Roth accounts and convert old
traditional balances -- years before anyone would normally call it "retirement
planning".
"""

from __future__ import annotations
from dataclasses import dataclass, field

from engine.pay import grades as G

# 2026 cap for commissioned officers: highest enlisted basic pay (the Senior
# Enlisted Advisor to the Chairman rate) plus hostile fire / imminent danger pay.
CZTE_OFFICER_MONTHLY_CAP_2026 = 11_391.90
HOSTILE_FIRE_PAY_MONTHLY = 225.00


@dataclass
class CompensationSplit:
    """One year of pay, divided the way the tax code divides it."""
    basic_pay: float = 0.0
    special_pay_taxable: float = 0.0
    bah: float = 0.0
    bas: float = 0.0
    other_nontaxable: float = 0.0

    # Filled in by apply_czte()
    czte_excluded: float = 0.0
    czte_months: int = 0

    @property
    def gross(self) -> float:
        return (self.basic_pay + self.special_pay_taxable + self.bah + self.bas
                + self.other_nontaxable)

    @property
    def allowances(self) -> float:
        return self.bah + self.bas + self.other_nontaxable

    @property
    def taxable_before_czte(self) -> float:
        return self.basic_pay + self.special_pay_taxable

    @property
    def federal_taxable(self) -> float:
        """What actually lands on the W-2 as taxable wages."""
        return max(0.0, self.taxable_before_czte - self.czte_excluded)

    @property
    def nontaxable(self) -> float:
        return self.gross - self.federal_taxable

    @property
    def nontaxable_share(self) -> float:
        return (self.nontaxable / self.gross) if self.gross else 0.0

    @property
    def fica_wages(self) -> float:
        """
        Social Security and Medicare still apply to CZTE pay.

        Excluded combat pay is exempt from income tax but NOT from FICA, so a
        fully tax-free deployment year still builds the Social Security earnings
        record. Allowances are outside FICA entirely.
        """
        return self.taxable_before_czte


def czte_monthly_exclusion(grade: str, basic_pay_monthly: float,
                           special_pay_monthly: float = 0.0,
                           officer_cap: float = CZTE_OFFICER_MONTHLY_CAP_2026,
                           ) -> tuple[float, str]:
    """
    Military pay excluded for one qualifying month, and why.

    Enlisted members and warrant officers -- including commissioned warrant
    officers -- exclude everything. Only commissioned officers are capped.
    """
    eligible = basic_pay_monthly + special_pay_monthly
    try:
        g = G.get(grade)
    except KeyError:
        return 0.0, f"Unknown pay grade {grade!r}."

    if g.category in (G.ENLISTED, G.WARRANT):
        return eligible, ("Enlisted members and warrant officers exclude ALL "
                          "military pay earned in a qualifying month. There is "
                          "no cap.")

    excluded = min(eligible, officer_cap)
    if excluded < eligible:
        return excluded, (
            f"Commissioned officers are capped at ${officer_cap:,.2f} a month — "
            f"the highest enlisted basic pay plus hostile fire pay. "
            f"${eligible - excluded:,.2f} a month remains taxable.")
    return excluded, (f"Below the ${officer_cap:,.2f} monthly officer cap, so "
                      f"all of it is excluded.")


def apply_czte(split: CompensationSplit, grade: str, months_in_zone: int,
               officer_cap: float = CZTE_OFFICER_MONTHLY_CAP_2026
               ) -> CompensationSplit:
    """
    Apply the exclusion for a number of qualifying months.

    Remember that ANY part of a month in the zone counts as a full month, so a
    deployment spanning 1 January to 1 July is seven qualifying months, not six.
    """
    months = max(0, min(12, int(months_in_zone)))
    if months == 0:
        split.czte_excluded = 0.0
        split.czte_months = 0
        return split

    monthly_basic = split.basic_pay / 12.0
    monthly_special = split.special_pay_taxable / 12.0
    per_month, _ = czte_monthly_exclusion(grade, monthly_basic, monthly_special,
                                          officer_cap)
    split.czte_excluded = min(per_month * months, split.taxable_before_czte)
    split.czte_months = months
    return split


@dataclass
class CZTEAnalysis:
    months: int = 0
    excluded: float = 0.0
    taxable_without: float = 0.0
    taxable_with: float = 0.0
    is_capped: bool = False
    cap_note: str = ""
    opportunities: list = field(default_factory=list)


def analyse_czte(split: CompensationSplit, grade: str,
                 months_in_zone: int) -> CZTEAnalysis:
    """What the exclusion is worth, and what it unlocks."""
    before = split.taxable_before_czte
    applied = apply_czte(split, grade, months_in_zone)
    monthly_basic = split.basic_pay / 12.0
    _, note = czte_monthly_exclusion(grade, monthly_basic,
                                     split.special_pay_taxable / 12.0)

    out = CZTEAnalysis(months=applied.czte_months, excluded=applied.czte_excluded,
                       taxable_without=before, taxable_with=applied.federal_taxable,
                       is_capped="remains taxable" in note, cap_note=note)

    if applied.czte_months == 0:
        return out

    out.opportunities = [
        ("Fund the Savings Deposit Program first",
         "A guaranteed 10% on up to $10,000, compounded monthly, with interest "
         "continuing 90 days after you redeploy. It outranks everything else "
         "here, including the TSP match. Deposits start on day 31 and come out "
         "of unallotted pay, so a short deployment cannot reach the cap without "
         "planning it from the start."),
        ("Put everything into Roth, not traditional",
         "Traditional contributions save you tax you are not paying this year. "
         "Contributing tax-free pay to a Roth account means those dollars are "
         "never taxed — not going in, not growing, not coming out. This is the "
         "single best contribution you will ever make."),
        ("Convert old traditional balances at close to zero cost",
         "A conversion is taxed as ordinary income. In a year where your taxable "
         "income is near zero, so is the tax on converting. If you have a "
         "traditional IRA or traditional TSP balance from earlier years, this is "
         "the cheapest chance you will get to move it, and it will not come "
         "again until you retire."),
        ("Realise capital gains at 0%",
         "The 0% long-term capital gains bracket is generous, and with almost no "
         "ordinary income you have the whole of it. Selling appreciated holdings "
         "and immediately rebuying resets your basis higher at no tax cost."),
        ("Execute a reenlistment in the zone if one is due",
         "A bonus received while in a combat zone, for a reenlistment executed "
         "there, is excluded too. On a large selective reenlistment bonus that "
         "is a five-figure difference for signing in one place rather than "
         "another."),
    ]
    return out


def effective_tax_rate_note(split: CompensationSplit) -> str:
    """Plain-language framing of the untaxed share."""
    if split.gross <= 0:
        return ""
    share = split.nontaxable_share
    return (
        f"{share * 100:.0f}% of your compensation never appears in taxable "
        f"income. A civilian earning ${split.gross:,.0f} pays federal tax on all "
        f"of it; you pay on ${split.federal_taxable:,.0f}. Two consequences: "
        f"your marginal bracket is lower than your standard of living suggests, "
        f"which makes Roth the default rather than a close call — and a lender "
        f"will happily qualify you on gross pay that includes allowances you "
        f"lose the moment you move into quarters or PCS somewhere cheaper."
    )
