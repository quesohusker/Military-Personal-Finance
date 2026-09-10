"""
State of legal residence: the decision that follows you for a career.

Under SCRA section 511 a service member does not acquire or lose domicile
merely by being present in a state under military orders. Military pay is
taxable ONLY by the state of legal residence, regardless of where you are
stationed. That is not a loophole -- it is the statute, and it exists because
you do not choose where you live.

What it means practically: a member who legitimately establishes domicile in a
no-income-tax state, typically at a genuine PCS to it, keeps that domicile for
the rest of a career and often into retirement. Over twenty years of active duty
plus thirty years of retired pay, the difference between a 5% state and a 0%
state is routinely six figures.

TWO THINGS THIS MODULE WILL NOT DO.

You cannot simply pick a state. Domicile requires intent plus objective acts --
DD Form 2058, driver's licence, voter registration, vehicle registration,
property, a will. States audit this, and a claimed domicile with no connection
to it is tax fraud, not planning. The model prices the difference; it does not
tell anyone they are entitled to it.

And it does not model the spouse's residency election as automatic. The Veterans
Auto and Education Improvement Act of 2022 lets a couple elect, for each tax
year, the member's residence, the spouse's own residence, or the duty station.
That is a genuine annual choice, and it is one most tax software handles badly.
"""

from __future__ import annotations
from dataclasses import dataclass, field

from engine.tax.state import STATE_RULES, StateRule, get_rule, STATE_NAMES

NO_TAX_STATES = ["Alaska", "Florida", "Nevada", "New Hampshire", "South Dakota",
                 "Tennessee", "Texas", "Washington", "Wyoming"]

# States that exempt ACTIVE DUTY pay for residents, in whole or in part, on top
# of whatever they do with retired pay. Several exempt it only when the member
# is stationed outside the state.
ACTIVE_DUTY_PAY_EXEMPT = {
    "Arkansas": 1.0, "Connecticut": 1.0, "Illinois": 1.0, "Indiana": 1.0,
    "Iowa": 1.0, "Kansas": 1.0, "Massachusetts": 0.0, "Michigan": 1.0,
    "Minnesota": 1.0, "Missouri": 1.0, "Montana": 1.0, "New Jersey": 1.0,
    "New York": 1.0, "Ohio": 1.0, "Oklahoma": 1.0, "Pennsylvania": 1.0,
    "Vermont": 0.0, "Virginia": 0.0, "West Virginia": 1.0, "Wisconsin": 0.0,
}

DOMICILE_ACTS = [
    "DD Form 2058, filed with your finance office",
    "Driver's licence issued by the state",
    "Voter registration, and actually voting",
    "Vehicle registration and titling",
    "Owning or renting property there",
    "A will or estate documents naming the state",
    "Bank accounts and professional licences held there",
    "Where you intend to return when you leave service",
]


@dataclass
class StateProfile:
    name: str = ""
    rate: float = 0.0
    taxes_active_duty_pay: bool = True
    active_duty_exempt_share: float = 0.0
    taxes_retired_pay: bool = True
    retired_pay_exempt_share: float = 0.0
    taxes_va_compensation: bool = False      # never, anywhere
    note: str = ""


def profile(state: str) -> StateProfile:
    """How one state treats a service member's income."""
    rule: StateRule = get_rule(state)
    ad_exempt = ACTIVE_DUTY_PAY_EXEMPT.get(state, 0.0)
    if rule.rate <= 0:
        ad_exempt = 1.0

    return StateProfile(
        name=state, rate=rule.rate,
        taxes_active_duty_pay=(rule.rate > 0 and ad_exempt < 1.0),
        active_duty_exempt_share=ad_exempt,
        taxes_retired_pay=(rule.rate > 0 and rule.military_pension_exempt < 1.0),
        retired_pay_exempt_share=rule.military_pension_exempt,
        taxes_va_compensation=False,
        note=rule.note,
    )


@dataclass
class DomicileComparison:
    from_state: str = ""
    to_state: str = ""
    active_duty_years: float = 0.0
    retirement_years: float = 0.0

    from_active_tax: float = 0.0
    to_active_tax: float = 0.0
    from_retired_tax: float = 0.0
    to_retired_tax: float = 0.0

    active_saving: float = 0.0
    retired_saving: float = 0.0
    lifetime_saving: float = 0.0
    notes: list = field(default_factory=list)


def compare_states(from_state: str, to_state: str,
                   annual_taxable_military_pay: float,
                   annual_retired_pay: float,
                   active_duty_years: float,
                   retirement_years: float,
                   annual_va_compensation: float = 0.0) -> DomicileComparison:
    """
    What a domicile difference is worth over a career and into retirement.

    Only TAXABLE military pay is counted -- BAH and BAS are outside state income
    tax as well as federal, and VA compensation is tax-free in every state.
    """
    a, b = profile(from_state), profile(to_state)
    c = DomicileComparison(from_state=from_state, to_state=to_state,
                           active_duty_years=active_duty_years,
                           retirement_years=retirement_years)

    def active_tax(p: StateProfile) -> float:
        taxed = annual_taxable_military_pay * (1.0 - p.active_duty_exempt_share)
        return taxed * p.rate

    def retired_tax(p: StateProfile) -> float:
        taxed = annual_retired_pay * (1.0 - p.retired_pay_exempt_share)
        return taxed * p.rate

    c.from_active_tax = active_tax(a) * active_duty_years
    c.to_active_tax = active_tax(b) * active_duty_years
    c.from_retired_tax = retired_tax(a) * retirement_years
    c.to_retired_tax = retired_tax(b) * retirement_years

    c.active_saving = c.from_active_tax - c.to_active_tax
    c.retired_saving = c.from_retired_tax - c.to_retired_tax
    c.lifetime_saving = c.active_saving + c.retired_saving

    if annual_va_compensation > 0:
        c.notes.append(
            f"Your ${annual_va_compensation:,.0f} of VA compensation is tax-free "
            f"in every state, so it does not enter this comparison at all. "
            f"Neither do BAH or BAS.")

    if abs(c.lifetime_saving) < 1_000:
        c.notes.append(
            f"{from_state} and {to_state} treat your military income almost "
            f"identically. Domicile is not worth moving for on tax grounds here.")
    elif c.lifetime_saving > 0:
        c.notes.append(
            f"Over {active_duty_years:g} years of service and "
            f"{retirement_years:g} years of retirement, {to_state} would cost "
            f"${c.lifetime_saving:,.0f} less in state income tax than "
            f"{from_state}.")
    else:
        c.notes.append(
            f"{to_state} would cost ${-c.lifetime_saving:,.0f} MORE than "
            f"{from_state} over the same period.")

    if a.retired_pay_exempt_share >= 1.0 and b.retired_pay_exempt_share < 1.0:
        c.notes.append(
            f"Note the reversal in retirement: {from_state} exempts military "
            f"retired pay entirely and {to_state} does not. A state that is "
            f"good for you now may not be the one you want to retire to — and "
            f"once you separate, SCRA no longer protects your domicile. You "
            f"become a resident of wherever you actually live.")

    if a.rate <= 0 and b.rate > 0 and not b.taxes_retired_pay:
        c.notes.append(
            f"Careful: {to_state} exempts your military pay but is not a "
            f"no-income-tax state. Your spouse's salary, a second career, and "
            f"investment income would all be taxed at "
            f"{b.rate * 100:.2f}%, where {from_state} taxes none of it. On "
            f"military pay alone they look identical; for a household they are "
            f"not.")
    elif b.rate <= 0 and a.rate > 0 and not a.taxes_retired_pay:
        c.notes.append(
            f"Worth noting beyond military pay: {from_state} exempts your "
            f"military income but taxes everything else at "
            f"{a.rate * 100:.2f}% — a spouse's salary, a second career, "
            f"investment income. {to_state} taxes none of it. The saving above "
            f"counts only military pay and therefore understates the difference "
            f"for a household with other income.")

    c.notes.append(
        "Establishing domicile requires genuine connection, not preference. "
        "The practical route is to establish it at a real PCS to that state — "
        "licence, registration, voting, DD Form 2058 — not by declaring it from "
        "somewhere else. States audit this.")

    return c


def rank_states(annual_taxable_military_pay: float, annual_retired_pay: float,
                active_duty_years: float, retirement_years: float,
                spouse_income: float = 0.0, spouse_years: float = 0.0,
                limit: int = 0) -> list[dict]:
    """
    Every state ranked by state income tax on the household's income.

    TWENTY-FOUR STATES COST A MILITARY MEMBER NOTHING on military income --
    the nine with no income tax, plus fifteen more that exempt both active duty
    pay and military retired pay outright. On military pay alone they are
    identical.

    They are NOT identical for a household. A state with no income tax at all
    also collects nothing from a spouse's salary, a second career, or investment
    income. A state that merely exempts military pay taxes all of that at its
    normal rate. Since a military spouse's earnings are often the household's
    second-largest income, that distinction is worth real money and it is
    invisible if you rank on military pay alone -- so the ranking breaks ties in
    favour of genuinely no-tax states and reports why.
    """
    out = []
    for name in STATE_NAMES:
        p = profile(name)
        active = (annual_taxable_military_pay * (1.0 - p.active_duty_exempt_share)
                  * p.rate * active_duty_years)
        retired = (annual_retired_pay * (1.0 - p.retired_pay_exempt_share)
                   * p.rate * retirement_years)
        spouse = spouse_income * p.rate * spouse_years
        no_income_tax = p.rate <= 0

        out.append({
            "State": name, "Rate": p.rate,
            "No income tax at all": no_income_tax,
            "Active duty pay": "No income tax" if no_income_tax
                               else ("Exempt" if p.active_duty_exempt_share >= 1.0
                                     else "Taxed"),
            "Retired pay": "No income tax" if no_income_tax
                           else ("Exempt" if p.retired_pay_exempt_share >= 1.0
                                 else "Taxed"),
            "Tax while serving": active,
            "Tax in retirement": retired,
            "Tax on spouse income": spouse,
            "Military income tax": active + retired,
            "Lifetime": active + retired + spouse,
        })

    # Sort on total household tax, then break ties toward states that tax
    # nothing at all -- because a spouse's income and a second career are taxed
    # in a state that only exempts military pay.
    out.sort(key=lambda r: (round(r["Lifetime"], 2),
                            not r["No income tax at all"], r["State"]))
    return out[:limit] if limit else out


def exempt_but_taxing_states() -> list[str]:
    """
    States that cost a member nothing on military income but DO tax everything
    else -- a spouse's salary, a second career, investment income.
    """
    return [s for s in STATE_NAMES
            if profile(s).rate > 0
            and not profile(s).taxes_active_duty_pay
            and not profile(s).taxes_retired_pay]


def spouse_residency_note(member_slr: str, spouse_state: str,
                          duty_state: str) -> str:
    """The VAEIA annual election, which most tax software handles badly."""
    options = {member_slr, spouse_state, duty_state}
    return (
        f"**Your spouse has a genuine annual choice.** The Veterans Auto and "
        f"Education Improvement Act of 2022 lets a married couple elect, for "
        f"each tax year independently, to use the service member's state of "
        f"legal residence, the spouse's own residence, or the duty station. "
        f"Your options here are {', '.join(sorted(options))}.\n\n"
        f"This is not the old Military Spouses Residency Relief Act rule, which "
        f"only let a spouse retain a pre-marriage domicile. The 2022 Act is "
        f"broader and it is re-electable every year — so the right answer can "
        f"change when your spouse's income changes or when you PCS. Most tax "
        f"software does not surface it, and many preparers are not aware of it."
    )
