"""
Chapter 61: disability retirement against disability severance.

The Integrated Disability Evaluation System produces a DoD disability rating,
and that number decides between two outcomes that are not remotely comparable:

    DoD rating 30% or more (any length of service), OR 20+ years with any
    rating  ->  DISABILITY RETIREMENT. Monthly retired pay for life, TRICARE,
                commissary and exchange, SBP eligibility.

    DoD rating under 30% AND under 20 years  ->  DISABILITY SEPARATION with a
                one-time severance payment, and none of the above.

Between a 20% and a 30% DoD rating sits the difference between a lump sum of
perhaps $60,000 and a lifetime inflation-indexed annuity plus healthcare. It is
the steepest cliff in the entire military compensation system and it turns on a
percentage assigned by a board.

TWO THINGS PEOPLE ARE ROUTINELY SURPRISED BY.

Severance is RECOUPED. VA withholds your disability compensation until the
severance has been recovered in full. You do not keep both. The exception is
severance for a combat-related disability, which is generally not recouped --
and severance for an injury incurred in a combat zone is also not taxed.

DoD and VA rate INDEPENDENTLY, and they routinely differ. DoD rates only the
conditions that make you unfit for duty; VA rates everything service-connected.
A member can leave with a 10% DoD rating and a 70% VA rating. The DoD number
decides retirement versus severance; the VA number decides your compensation.
"""

from __future__ import annotations
from dataclasses import dataclass, field

from engine.networth.balance_sheet import annuity_present_value

RETIREMENT_RATING_THRESHOLD = 30
RETIREMENT_YEARS_THRESHOLD = 20.0

SEVERANCE_MULTIPLIER = 2.0
SEVERANCE_MIN_YEARS = 3.0
SEVERANCE_MIN_YEARS_COMBAT = 6.0
SEVERANCE_MAX_YEARS = 19.0

MAX_RETIRED_PAY_MULTIPLIER = 0.75

OUTCOME_RETIREMENT = "Disability retirement (Chapter 61)"
OUTCOME_SEVERANCE = "Disability separation with severance"
OUTCOME_TDRL = "Temporary Disability Retired List"


@dataclass
class DisabilityOutcome:
    outcome: str = ""
    dod_rating: int = 0
    years_of_service: float = 0.0

    # Retirement path
    retired_pay_monthly: float = 0.0
    retired_pay_annual: float = 0.0
    multiplier_used: float = 0.0
    multiplier_basis: str = ""
    lifetime_present_value: float = 0.0
    keeps_tricare: bool = False

    # Severance path
    severance_gross: float = 0.0
    severance_after_tax: float = 0.0
    severance_years_credited: float = 0.0
    severance_recouped: bool = True
    months_of_va_withheld: float = 0.0

    notes: list = field(default_factory=list)


def evaluate(dod_rating: int, years_of_service: float,
             high_three_monthly: float, is_brs: bool = False,
             combat_related: bool = False,
             incurred_in_combat_zone: bool = False,
             va_monthly_compensation: float = 0.0,
             age_at_separation: int = 30,
             life_expectancy: int = 85,
             real_discount_rate: float = 0.03,
             marginal_tax_rate: float = 0.12,
             on_tdrl: bool = False) -> DisabilityOutcome:
    """Which path applies, and what each is worth."""
    o = DisabilityOutcome(dod_rating=dod_rating, years_of_service=years_of_service)

    qualifies = (dod_rating >= RETIREMENT_RATING_THRESHOLD
                 or years_of_service >= RETIREMENT_YEARS_THRESHOLD)

    if on_tdrl:
        o.outcome = OUTCOME_TDRL
        o.notes.append(
            "You are on the Temporary Disability Retired List. You draw retired "
            "pay now, but the rating is re-evaluated periodically for up to "
            "three years, after which you are either moved to the permanent "
            "list, separated with severance, or found fit. Plan for the "
            "possibility of any of the three — a TDRL outcome is not settled "
            "income.")

    if qualifies or on_tdrl:
        o.outcome = o.outcome or OUTCOME_RETIREMENT
        o.keeps_tricare = True

        length_mult = (0.020 if is_brs else 0.025) * years_of_service
        rating_mult = dod_rating / 100.0
        if rating_mult >= length_mult:
            o.multiplier_used = min(rating_mult, MAX_RETIRED_PAY_MULTIPLIER)
            o.multiplier_basis = (f"your {dod_rating}% DoD disability rating, "
                                 f"which exceeds the "
                                 f"{length_mult * 100:.1f}% your length of "
                                 f"service would produce")
        else:
            o.multiplier_used = min(length_mult, MAX_RETIRED_PAY_MULTIPLIER)
            o.multiplier_basis = (f"your {years_of_service:g} years of service, "
                                 f"which exceeds the {dod_rating}% your rating "
                                 f"would produce")

        o.retired_pay_monthly = high_three_monthly * o.multiplier_used
        o.retired_pay_annual = o.retired_pay_monthly * 12.0
        o.lifetime_present_value = annuity_present_value(
            o.retired_pay_annual, max(0.0, life_expectancy - age_at_separation),
            real_discount_rate)

        o.notes.append(
            f"Your retired pay uses the greater of the two multipliers — here, "
            f"{o.multiplier_basis}. The result is capped at "
            f"{MAX_RETIRED_PAY_MULTIPLIER * 100:.0f}%.")
        o.notes.append(
            "Disability retirement carries the full retiree package: TRICARE "
            "for you and your family, commissary and exchange access, and SBP "
            "eligibility. That healthcare alone is worth thousands a year and "
            "is usually left out when people compare the two paths.")
        if dod_rating >= RETIREMENT_RATING_THRESHOLD and years_of_service < 20:
            o.notes.append(
                f"Note how narrow this was. At {years_of_service:g} years, a DoD "
                f"rating of {RETIREMENT_RATING_THRESHOLD - 10}% instead of "
                f"{dod_rating}% would have produced a one-time severance "
                f"payment and nothing else — no pension, no TRICARE. Ten "
                f"percentage points is the whole difference.")
        return o

    # Severance path
    o.outcome = OUTCOME_SEVERANCE
    credited = max(SEVERANCE_MIN_YEARS_COMBAT if combat_related
                   else SEVERANCE_MIN_YEARS, years_of_service)
    credited = min(credited, SEVERANCE_MAX_YEARS)
    o.severance_years_credited = credited

    o.severance_gross = SEVERANCE_MULTIPLIER * high_three_monthly * credited
    taxable = not incurred_in_combat_zone
    o.severance_after_tax = (o.severance_gross * (1.0 - marginal_tax_rate)
                             if taxable else o.severance_gross)

    o.severance_recouped = not combat_related
    if o.severance_recouped and va_monthly_compensation > 0:
        o.months_of_va_withheld = o.severance_gross / va_monthly_compensation

    o.notes.append(
        f"Severance is {SEVERANCE_MULTIPLIER:.0f} times monthly basic pay times "
        f"years of service, with a floor of "
        f"{SEVERANCE_MIN_YEARS_COMBAT if combat_related else SEVERANCE_MIN_YEARS:.0f} "
        f"years credited and a ceiling of {SEVERANCE_MAX_YEARS:.0f}. Yours "
        f"credits {credited:g} years.")

    if not taxable:
        o.notes.append(
            "Because the injury was incurred in a combat zone, the severance is "
            "not taxable. Claim it as excluded — it is commonly withheld at "
            "source and then has to be recovered by amending the return.")
    else:
        o.notes.append(
            f"Severance is taxable and is withheld at supplemental rates, so the "
            f"cheque will be smaller than the gross figure. At a "
            f"{marginal_tax_rate * 100:.0f}% marginal rate you keep about "
            f"${o.severance_after_tax:,.0f}.")

    if o.severance_recouped:
        msg = ("**VA will recoup this severance.** Your disability compensation "
               "is withheld until the full gross amount has been recovered")
        if o.months_of_va_withheld > 0:
            msg += (f" — about {o.months_of_va_withheld:.0f} months at "
                    f"${va_monthly_compensation:,.0f} a month")
        msg += (". You do not keep both. People plan around the severance as "
                "though it is additional money and are then surprised when VA "
                "payments do not start.")
        o.notes.append(msg)
    else:
        o.notes.append(
            "Because the disability is combat-related, the severance is "
            "generally NOT recouped from your VA compensation. That exception "
            "is worth the entire severance amount, so make sure the "
            "combat-related determination is made and documented.")

    o.notes.append(
        f"You do not receive retiree TRICARE, commissary or exchange access, or "
        f"SBP eligibility. Health coverage ends, with an 18 to 36 month CHCBP "
        f"bridge available at your own expense.")

    return o


def compare_paths(dod_rating: int, years_of_service: float,
                  high_three_monthly: float, **kw) -> dict:
    """
    The severance outcome against what one more rating band would have produced.

    This exists to size the cliff, not to suggest anyone can choose their side
    of it.
    """
    actual = evaluate(dod_rating, years_of_service, high_three_monthly, **kw)
    if actual.outcome != OUTCOME_SEVERANCE:
        return {"actual": actual, "alternative": None, "gap": 0.0}

    alternative = evaluate(RETIREMENT_RATING_THRESHOLD, years_of_service,
                           high_three_monthly, **kw)
    return {
        "actual": actual,
        "alternative": alternative,
        "gap": alternative.lifetime_present_value - actual.severance_after_tax,
    }


def findings(o: DisabilityOutcome, comparison: dict | None = None
             ) -> list[tuple[str, str, str]]:
    """(severity, headline, detail)."""
    out = []

    if o.outcome == OUTCOME_RETIREMENT:
        out.append(("good", "You qualify for disability retirement.",
                    f"Monthly retired pay of ${o.retired_pay_monthly:,.0f} for "
                    f"life, indexed to inflation, plus TRICARE and the full "
                    f"retiree package. Replacing that income would cost roughly "
                    f"${o.lifetime_present_value:,.0f}."))
    elif o.outcome == OUTCOME_TDRL:
        out.append(("warn", "You are on the temporary list, not the permanent one.",
                    "Retired pay is being paid now, but the rating is "
                    "re-evaluated for up to three years and the outcome can "
                    "change to permanent retirement, severance, or a finding of "
                    "fit for duty. Do not plan as though this income is settled."))
    else:
        out.append(("bad", "You are on the severance path, not the retirement one.",
                    f"A one-time payment of ${o.severance_gross:,.0f} gross, and "
                    f"no pension, no retiree TRICARE, no commissary. The DoD "
                    f"rating threshold for retirement is "
                    f"{RETIREMENT_RATING_THRESHOLD}%."))

    if comparison and comparison.get("gap", 0) > 0:
        out.append(("bad",
                    f"The gap between the two paths is about "
                    f"${comparison['gap']:,.0f}.",
                    f"A DoD rating of {RETIREMENT_RATING_THRESHOLD}% rather than "
                    f"{o.dod_rating}% would have produced a lifetime annuity "
                    f"worth roughly "
                    f"${comparison['alternative'].lifetime_present_value:,.0f} "
                    f"instead of a severance worth "
                    f"${o.severance_after_tax:,.0f} after tax. This is the "
                    f"steepest cliff in military compensation and it turns on a "
                    f"board's percentage. If you believe the rating "
                    f"understates conditions that make you unfit, that is what "
                    f"the appeal process is for — and it is worth taking "
                    f"seriously at these stakes."))

    if o.outcome == OUTCOME_SEVERANCE and o.severance_recouped:
        out.append(("warn", "Your VA compensation will be withheld until the "
                            "severance is recovered.",
                    "Budget for a gap between separating and receiving VA "
                    "payments. Many people do not, because the severance feels "
                    "like additional money rather than an advance against "
                    "compensation they were going to receive anyway."))

    out.append(("info", "DoD and VA rate independently, and often differently.",
                "DoD rates only the conditions that make you unfit for duty. VA "
                "rates everything service-connected. Leaving with a 10% DoD "
                "rating and a 70% VA rating is entirely normal — the DoD number "
                "decides retirement against severance, the VA number decides "
                "your monthly compensation. Do not assume one predicts the "
                "other."))

    return out
