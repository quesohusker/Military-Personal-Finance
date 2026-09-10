"""
The Survivor Benefit Plan, and whether term insurance beats it.

SBP pays a surviving spouse 55% of an elected base amount, for life, indexed to
inflation. It costs 6.5% of that base amount, deducted from retired pay BEFORE
tax -- so the effective cost is lower than 6.5% by your marginal rate.

Three features decide the analysis, and two of them are routinely missed:

  1. IT IS PAID UP at 360 months of premiums AND age 70 -- both conditions.
     After that, coverage continues with COLA and costs nothing. This bounds
     the lifetime cost, which is what makes "buy term instead" a much weaker
     argument than it first appears.

  2. THE SBP-DIC OFFSET WAS REPEALED, fully effective 1 January 2023. A survivor
     now receives SBP AND DIC in full. An enormous amount of published advice
     -- and a good deal of retiree folklore -- predates this and concluded SBP
     was not worth it precisely because of an offset that no longer exists.

  3. THE DECISION IS IRREVOCABLE, except in a narrow window between the second
     and third anniversary of retirement, and declining or reducing it requires
     notarised spousal concurrence. You get one chance, before you retire.

What SBP actually sells is risk transfer: an inflation-indexed lifetime income
with no underwriting and no sequence risk. Term insurance sells a lump sum that
must then be invested and drawn down, carrying both. They are not the same
product and a pure cost comparison flatters term.
"""

from __future__ import annotations
from dataclasses import dataclass, field

from engine.networth.balance_sheet import annuity_present_value

SBP_PREMIUM_RATE = 0.065
SBP_ANNUITY_RATE = 0.55
PAID_UP_MONTHS = 360
PAID_UP_AGE = 70

# 2026 base rate for a surviving spouse, tax-free.
DIC_MONTHLY_2026 = 1_699.36
DIC_EIGHT_YEAR_SUPPLEMENT = 360.85


@dataclass
class SBPAnalysis:
    base_amount_monthly: float = 0.0
    premium_monthly: float = 0.0
    premium_after_tax_monthly: float = 0.0
    annuity_monthly: float = 0.0

    years_paying: float = 0.0
    total_premiums: float = 0.0
    total_premiums_after_tax: float = 0.0
    # Premiums are paid over decades, so comparing their undiscounted sum
    # against a discounted benefit understates SBP. Both sides are valued at
    # the same date.
    premiums_present_value: float = 0.0
    paid_up_age: int = PAID_UP_AGE

    annuity_present_value: float = 0.0
    equivalent_term_face: float = 0.0

    dic_monthly: float = 0.0
    survivor_total_monthly: float = 0.0

    notes: list = field(default_factory=list)


def analyse(retired_pay_monthly: float, retirement_age: int,
            base_amount_monthly: float = 0.0,
            member_life_expectancy: int = 82,
            survivor_life_expectancy: int = 88,
            survivor_age_at_retirement: int | None = None,
            marginal_tax_rate: float = 0.22,
            survivor_marginal_rate: float = 0.12,
            real_discount_rate: float = 0.03,
            dic_applies: bool = False) -> SBPAnalysis:
    """
    Cost and benefit of electing SBP, with the paid-up rule applied.
    """
    base = base_amount_monthly if base_amount_monthly > 0 else retired_pay_monthly
    a = SBPAnalysis(base_amount_monthly=base,
                    premium_monthly=base * SBP_PREMIUM_RATE,
                    annuity_monthly=base * SBP_ANNUITY_RATE)

    # Premiums are excluded from gross income, so the real cost is net of tax.
    a.premium_after_tax_monthly = a.premium_monthly * (1.0 - marginal_tax_rate)

    # Paid up at 30 years of premiums AND age 70, whichever comes later.
    years_to_seventy = max(0.0, PAID_UP_AGE - retirement_age)
    years_paying = max(years_to_seventy, PAID_UP_MONTHS / 12.0)
    # But you stop paying at death regardless.
    years_paying = min(years_paying, max(0.0, member_life_expectancy - retirement_age))
    a.years_paying = years_paying

    a.total_premiums = a.premium_monthly * 12.0 * years_paying
    a.total_premiums_after_tax = a.premium_after_tax_monthly * 12.0 * years_paying
    # Present value at retirement, so cost and benefit are measured at the same
    # date. A stream paid over thirty years is worth materially less than its
    # nominal sum.
    a.premiums_present_value = annuity_present_value(
        a.premium_after_tax_monthly * 12.0, years_paying, real_discount_rate)

    # What the survivor receives, and for how long.
    survivor_age_at_death = (
        (survivor_age_at_retirement or retirement_age)
        + (member_life_expectancy - retirement_age))
    survivor_years = max(0.0, survivor_life_expectancy - survivor_age_at_death)

    annuity_annual = a.annuity_monthly * 12.0
    a.annuity_present_value = annuity_present_value(
        annuity_annual, survivor_years, real_discount_rate,
        deferral_years=max(0.0, member_life_expectancy - retirement_age))

    # An after-tax-equivalent term policy would have to fund the same
    # after-tax income for the same period.
    after_tax_annuity = annuity_annual * (1.0 - survivor_marginal_rate)
    a.equivalent_term_face = annuity_present_value(
        after_tax_annuity, survivor_years, real_discount_rate)

    if dic_applies:
        a.dic_monthly = DIC_MONTHLY_2026
    a.survivor_total_monthly = a.annuity_monthly + a.dic_monthly

    a.notes = _build_notes(a, retirement_age, survivor_years, dic_applies,
                           marginal_tax_rate, survivor_marginal_rate)
    return a


def _money(x: float) -> str:
    return f"${x:,.0f}"


def _build_notes(a: SBPAnalysis, retirement_age: int, survivor_years: float,
                 dic_applies: bool, marginal: float,
                 survivor_marginal: float) -> list[str]:
    notes = [
        (f"The premium is {SBP_PREMIUM_RATE * 100:.1f}% of the base amount — "
         f"{_money(a.premium_monthly)} a month — but it comes out of retired pay "
         f"BEFORE tax, so at a {marginal * 100:.0f}% marginal rate the real cost "
         f"is about {_money(a.premium_after_tax_monthly)} a month."),
        (f"You stop paying at {PAID_UP_AGE}, after {PAID_UP_MONTHS // 12} years "
         f"of premiums — both conditions, whichever comes later. Retiring at "
         f"{retirement_age} means about {a.years_paying:.0f} years of premiums "
         f"totalling {_money(a.total_premiums_after_tax)} after tax — "
         f"{_money(a.premiums_present_value)} in present value. Coverage "
         f"then continues for life, with COLA, at no further cost. That cap is "
         f"the single most overlooked feature of SBP, and it is what makes the "
         f"'buy term instead' argument much weaker than it sounds."),
        (f"The annuity is {SBP_ANNUITY_RATE * 100:.0f}% of the base amount — "
         f"{_money(a.annuity_monthly)} a month, indexed to inflation, for the "
         f"survivor's life. It is taxable to them."),
    ]

    if a.equivalent_term_face > 0:
        notes.append(
            f"To replace it with insurance you would need roughly "
            f"{_money(a.equivalent_term_face)} of death benefit, invested and "
            f"drawn down over about {survivor_years:.0f} years. And it would "
            f"have to be permanent coverage, not term — term expires, and it "
            f"expires precisely when the risk is highest.")

    notes.append(
        "The honest comparison is not cost against cost. SBP transfers three "
        "risks you otherwise keep: longevity (the survivor cannot outlive it), "
        "inflation (it is indexed), and sequence (a bad decade cannot reduce "
        "it). A lump sum carries all three. Term is cheaper in nominal dollars "
        "and does less.")

    if dic_applies:
        notes.append(
            f"**The SBP-DIC offset was fully repealed effective 1 January 2023.** "
            f"Your survivor would receive SBP AND DIC — currently "
            f"{_money(DIC_MONTHLY_2026)} a month, tax-free — for a combined "
            f"{_money(a.survivor_total_monthly)} a month. A great deal of "
            f"published advice concluding 'SBP is not worth it because of DIC' "
            f"predates the repeal and is now simply wrong.")
    else:
        notes.append(
            "If you are rated totally disabled and remain so for the qualifying "
            "period, or die of a service-connected cause, your survivor may also "
            "receive DIC. Since the offset repeal in 2023 they would receive "
            "both SBP and DIC in full — the DIC portion tax-free.")

    notes.append(
        "This election is effectively irrevocable. There is a narrow window "
        "between the second and third anniversary of retirement to withdraw, "
        "with spousal concurrence and no refund of premiums. Declining or "
        "reducing coverage at retirement requires your spouse's notarised "
        "consent. You get one chance and you get it before you retire.")

    return notes


def findings(a: SBPAnalysis, elected: bool, has_spouse: bool,
             ) -> list[tuple[str, str, str]]:
    """(severity, headline, detail)."""
    out = []

    if not has_spouse:
        out.append(("info", "SBP is a spouse and dependent benefit.",
                    "With no spouse or dependent children there is generally "
                    "nothing to elect. A child-only election, or an "
                    "insurable-interest election, may still apply in specific "
                    "family circumstances."))
        return out

    # Both sides valued at retirement. Comparing a discounted benefit against
    # an undiscounted premium sum would understate SBP by roughly a third.
    ratio = (a.annuity_present_value / a.premiums_present_value
             if a.premiums_present_value else 0.0)

    if elected:
        out.append(("good", "You have elected SBP.",
                    f"Your survivor would receive "
                    f"{_money(a.survivor_total_monthly)} a month, indexed to "
                    f"inflation, for life. You will pay about "
                    f"{_money(a.total_premiums_after_tax)} after tax over "
                    f"{a.years_paying:.0f} years, and then nothing."))
    else:
        out.append(("warn", "You have not elected SBP.",
                    "That may be the right call — but make it deliberately "
                    "rather than by default, and make it before you retire. "
                    "Declining requires your spouse's notarised concurrence, "
                    "and the decision cannot be revisited except in a narrow "
                    "window two to three years after retirement."))

    if ratio > 1.5:
        out.append(("good",
                    f"The expected value is roughly {ratio:.1f} times what you "
                    f"would pay for it.",
                    f"{_money(a.annuity_present_value)} of present value against "
                    f"{_money(a.premiums_present_value)} of after-tax premiums, "
                    f"both measured at retirement, on the life expectancies "
                    f"entered. That ratio is "
                    f"sensitive to those assumptions — a survivor who is younger "
                    f"and outlives you by longer makes it larger, and the "
                    f"reverse makes it smaller. Move them and see."))
    elif ratio > 0:
        out.append(("info",
                    f"The expected value is about {ratio:.1f} times the premiums.",
                    "On these life expectancies it is closer than usual. That "
                    "usually means the survivor is not much younger than the "
                    "member, or the discount rate is high. Try a longer survivor "
                    "life expectancy — SBP's value is concentrated in the case "
                    "where they live a long time, which is exactly the case "
                    "insurance is for."))

    out.append(("info", "What SBP is actually buying.",
                "Not a rate of return. An inflation-indexed lifetime income for "
                "your survivor, with no underwriting, that cannot be outlived "
                "and cannot be damaged by a bad decade in markets. Price term "
                "insurance against that honestly: to match it you need "
                "permanent coverage, not a 20-year level term that expires at "
                "the age your survivor is most likely to need it."))

    return out
