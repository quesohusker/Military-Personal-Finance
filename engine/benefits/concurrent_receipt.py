"""
CRDP against CRSC: the annual choice where DFAS compares the wrong number.

By default, military retired pay is reduced dollar for dollar by VA disability
compensation -- the "VA waiver". Because VA compensation is tax-free and retired
pay is not, taking the waiver alone is still usually beneficial. Two programs
restore some or all of the waived pay:

    CRDP  Concurrent Retirement and Disability Pay.
          Needs 20+ years of service AND a VA rating of 50% or more.
          Automatic -- no application. Restores retired pay in full.
          TAXABLE, because it IS restored retired pay.

    CRSC  Combat-Related Special Compensation.
          Needs disabilities the SERVICE determines to be combat-related.
          Available at ANY length of service, including Chapter 61 medical
          retirees with under 20 years. Requires an application to your branch.
          TAX-FREE, paid as a separate entitlement.

You cannot receive both. DFAS computes both for dual-eligibles, pays whichever
is HIGHER, and runs an annual open season to switch.

THE PROBLEM THIS MODULE EXISTS FOR: DFAS compares them on GROSS. Because CRSC
is tax-free and CRDP is taxable, the higher gross is not always the better
after-tax outcome. A retiree in the 24% bracket can be defaulted onto the
larger cheque and end up with less money. The comparison below is after tax.
"""

from __future__ import annotations
from dataclasses import dataclass, field

CRDP = "CRDP"
CRSC = "CRSC"

CRDP_MIN_YEARS = 20.0
CRDP_MIN_RATING = 50


@dataclass
class Eligibility:
    crdp: bool = False
    crsc: bool = False
    crdp_reason: str = ""
    crsc_reason: str = ""


def eligibility(years_of_service: float, va_rating: int,
                has_combat_related_disability: bool,
                is_chapter_61: bool = False) -> Eligibility:
    """Who qualifies for which programme."""
    e = Eligibility()

    if years_of_service >= CRDP_MIN_YEARS and va_rating >= CRDP_MIN_RATING:
        e.crdp = True
        e.crdp_reason = (f"{years_of_service:g} years of service and a "
                         f"{va_rating}% rating meet both CRDP conditions. It is "
                         f"automatic — no application is required.")
    elif years_of_service < CRDP_MIN_YEARS:
        e.crdp_reason = (f"CRDP requires {CRDP_MIN_YEARS:.0f} years of service. "
                         f"At {years_of_service:g} you do not qualify"
                         + (" — but a Chapter 61 medical retiree can still "
                            "receive CRSC at any length of service."
                            if is_chapter_61 else "."))
    else:
        e.crdp_reason = (f"CRDP requires a VA rating of {CRDP_MIN_RATING}% or "
                         f"more. Yours is {va_rating}%.")

    if has_combat_related_disability:
        e.crsc = True
        e.crsc_reason = ("You have disabilities your service may determine to be "
                         "combat-related. CRSC is NOT automatic — you must apply "
                         "to your branch of service, not to the VA and not to "
                         "DFAS.")
    else:
        e.crsc_reason = ("CRSC requires disabilities the service determines to be "
                         "combat-related: armed conflict, hazardous service, an "
                         "instrumentality of war, or training simulating war. "
                         "If any of yours might qualify, apply — the "
                         "determination is theirs to make, not yours.")
    return e


@dataclass
class Comparison:
    crdp_gross_annual: float = 0.0
    crdp_after_tax: float = 0.0
    crsc_gross_annual: float = 0.0
    crsc_after_tax: float = 0.0
    marginal_rate: float = 0.0
    better_by_gross: str = ""
    better_by_after_tax: str = ""
    after_tax_difference: float = 0.0
    dfas_would_pay: str = ""
    mismatch: bool = False
    notes: list = field(default_factory=list)


def compare(crdp_monthly: float, crsc_monthly: float,
            marginal_tax_rate: float = 0.22,
            state_tax_rate: float = 0.0) -> Comparison:
    """
    Compare the two after tax.

    CRDP is taxable at both federal and state level. CRSC is tax-free at both.
    """
    c = Comparison(crdp_gross_annual=crdp_monthly * 12.0,
                   crsc_gross_annual=crsc_monthly * 12.0,
                   marginal_rate=marginal_tax_rate + state_tax_rate)

    c.crdp_after_tax = c.crdp_gross_annual * (1.0 - c.marginal_rate)
    c.crsc_after_tax = c.crsc_gross_annual          # tax-free

    c.better_by_gross = CRDP if c.crdp_gross_annual > c.crsc_gross_annual else CRSC
    c.better_by_after_tax = CRDP if c.crdp_after_tax > c.crsc_after_tax else CRSC
    c.after_tax_difference = abs(c.crdp_after_tax - c.crsc_after_tax)
    c.dfas_would_pay = c.better_by_gross
    c.mismatch = c.better_by_gross != c.better_by_after_tax

    if c.mismatch:
        c.notes.append(
            f"**DFAS would default you to {c.better_by_gross}, and that is the "
            f"worse choice for you.** {c.better_by_gross} is larger on paper, "
            f"but {c.better_by_after_tax} leaves you "
            f"${c.after_tax_difference:,.0f} a year better off after tax. DFAS "
            f"compares gross amounts; it does not know your bracket. Use the "
            f"annual open season to elect {c.better_by_after_tax}.")
    else:
        c.notes.append(
            f"{c.better_by_after_tax} is better on both gross and after-tax, so "
            f"the DFAS default is correct here. Worth re-checking whenever your "
            f"rating changes or your income moves you between brackets.")

    if c.crsc_gross_annual > 0:
        breakeven = c.crsc_gross_annual / (1.0 - c.marginal_rate) / 12.0
        c.notes.append(
            f"Your break-even: CRDP would need to exceed "
            f"${breakeven:,.0f} a month gross to beat your CRSC after tax, "
            f"because CRSC arrives untaxed. At a "
            f"{c.marginal_rate * 100:.0f}% combined rate every tax-free dollar "
            f"is worth about ${1 / (1 - c.marginal_rate):.2f} of taxable pay.")

    c.notes.append(
        "You may switch during the annual open season, and you should re-run "
        "this whenever your VA rating changes, when a second-career salary "
        "starts or stops, or when you move to a state that taxes retired pay "
        "differently. It is a recurring decision, not a one-time one.")

    return c


def findings(elig: Eligibility, comp: Comparison | None,
             va_rating: int, years_of_service: float,
             is_chapter_61: bool = False) -> list[tuple[str, str, str]]:
    """(severity, headline, detail)."""
    out = []

    if elig.crdp and not elig.crsc:
        out.append(("good", "You qualify for CRDP, and it is automatic.",
                    elig.crdp_reason + " Your retired pay is restored in full "
                    "and you receive it alongside your VA compensation. It is "
                    "taxable, because it is retired pay."))
        out.append(("info", "It is still worth asking about CRSC.",
                    elig.crsc_reason + " CRSC is tax-free, so even a smaller "
                    "CRSC amount can beat a larger CRDP one after tax. The only "
                    "way to find out is to apply and let your branch make the "
                    "determination."))

    elif elig.crsc and not elig.crdp:
        out.append(("good", "You may qualify for CRSC.", elig.crsc_reason))
        out.append(("warn", "CRDP is not available to you.", elig.crdp_reason))
        if is_chapter_61:
            out.append(("info", "Chapter 61 retirees are exactly who CRSC is for.",
                        "A medical retirement under Chapter 61 with fewer than "
                        "20 years locks you out of CRDP entirely. CRSC has no "
                        "length-of-service requirement, which makes it the only "
                        "route back to some of your waived retired pay."))

    elif elig.crdp and elig.crsc:
        out.append(("good", "You may qualify for both.",
                    "DFAS will compute both and pay the higher amount, with an "
                    "annual open season to switch. But it compares them on "
                    "GROSS — see below, because that is not always the right "
                    "answer for you."))

    else:
        out.append(("info", "Neither programme applies as entered.",
                    elig.crdp_reason + " " + elig.crsc_reason))

    if comp is not None and comp.crsc_gross_annual > 0 and comp.crdp_gross_annual > 0:
        sev = "bad" if comp.mismatch else "good"
        head = ("The DFAS default would cost you money."
                if comp.mismatch else "The DFAS default is right for you.")
        out.append((sev, head, comp.notes[0]))

    if va_rating >= CRDP_MIN_RATING and years_of_service >= CRDP_MIN_YEARS:
        out.append(("info", "A rating increase changes this calculation.",
                    "VA retroactive payments can also trigger a DFAS recoupment "
                    "of retired pay already paid, which arrives as an alarming "
                    "letter and a suspended payment. It is usually correct and "
                    "usually temporary — but budget for it rather than being "
                    "surprised by it."))

    return out
