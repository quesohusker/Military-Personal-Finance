"""
Post-9/11 GI Bill: what it is worth, and whether to transfer it.

The benefit is 36 months of entitlement covering three things:

    Tuition and fees   In-state public: the full in-state rate, uncapped.
                       Private or foreign: capped at a national maximum.
    Housing (MHA)      The E-5 WITH DEPENDENTS BAH rate at the SCHOOL's ZIP
                       code -- not the member's, and not their own pay grade.
                       Half the national average for online-only study.
                       NOTHING while the service member is on active duty.
    Books              $1,000 a year.

Because the housing allowance is tied to the school's location, the same
benefit is worth dramatically more at a university in an expensive city than at
one in a cheap one. That is usually the largest single variable and it is
almost never considered when choosing a school.

TRANSFERRING IT IS A PURCHASE, NOT A GIFT. It requires six years of service and
an agreement to serve four more -- ten total. That obligation is a real cost and
must be weighed against the value being transferred. It also must be requested
WHILE STILL SERVING; it cannot be initiated after separation, and that deadline
is missed regularly.
"""

from __future__ import annotations
from dataclasses import dataclass, field

# Academic year 2025-26 national maximum for private and foreign schools.
PRIVATE_SCHOOL_CAP_ANNUAL = 28_937.09
BOOKS_STIPEND_ANNUAL = 1_000.0
MONTHS_OF_ENTITLEMENT = 36
MONTHS_PER_ACADEMIC_YEAR = 9

TRANSFER_SERVICE_REQUIRED = 6
TRANSFER_OBLIGATION_YEARS = 4
CHILD_USE_AFTER_YEARS = 10
CHILD_MUST_USE_BY_AGE = 26

SCHOOL_PUBLIC_IN_STATE = "Public, in-state"
SCHOOL_PUBLIC_OUT_STATE = "Public, out-of-state"
SCHOOL_PRIVATE = "Private"
SCHOOL_ONLINE = "Online only"
SCHOOL_TYPES = [SCHOOL_PUBLIC_IN_STATE, SCHOOL_PUBLIC_OUT_STATE, SCHOOL_PRIVATE,
                SCHOOL_ONLINE]


@dataclass
class BenefitValue:
    school_type: str = ""
    months_used: int = MONTHS_OF_ENTITLEMENT
    academic_years: float = 0.0

    tuition_covered: float = 0.0
    tuition_shortfall: float = 0.0
    housing: float = 0.0
    books: float = 0.0
    total: float = 0.0

    monthly_housing: float = 0.0
    yellow_ribbon_needed: bool = False
    notes: list = field(default_factory=list)


def value_benefit(school_type: str, annual_tuition: float,
                  school_zip_e5_bah: float = 0.0,
                  months_used: int = MONTHS_OF_ENTITLEMENT,
                  on_active_duty: bool = False,
                  national_average_bah: float = 2_100.0) -> BenefitValue:
    """
    What 36 months of entitlement is worth at a given school.

    `school_zip_e5_bah` is the E-5-with-dependents BAH at the school's ZIP.
    Look it up on the Pay page -- it is the single biggest variable here.
    """
    v = BenefitValue(school_type=school_type, months_used=months_used,
                     academic_years=months_used / MONTHS_PER_ACADEMIC_YEAR)

    # Tuition
    if school_type in (SCHOOL_PUBLIC_IN_STATE, SCHOOL_ONLINE):
        v.tuition_covered = annual_tuition * v.academic_years
    else:
        capped = min(annual_tuition, PRIVATE_SCHOOL_CAP_ANNUAL)
        v.tuition_covered = capped * v.academic_years
        v.tuition_shortfall = max(0.0, annual_tuition - capped) * v.academic_years
        v.yellow_ribbon_needed = v.tuition_shortfall > 0

    # Housing
    if on_active_duty:
        v.monthly_housing = 0.0
        v.notes.append(
            "**No housing allowance while the service member is on active "
            "duty.** If you use it yourself before separating you receive "
            "tuition and books only — which is a large part of why using it in "
            "service is often the wrong call.")
    elif school_type == SCHOOL_ONLINE:
        v.monthly_housing = national_average_bah / 2.0
        v.notes.append(
            f"Online-only study pays half the national average BAH — about "
            f"${v.monthly_housing:,.0f} a month — regardless of where you live. "
            f"A single in-person class each term changes that to the full rate "
            f"for the school's location, which is often worth more than the "
            f"class costs.")
    else:
        v.monthly_housing = school_zip_e5_bah
        if school_zip_e5_bah > 0:
            v.notes.append(
                f"Housing pays the E-5-with-dependents BAH rate at the SCHOOL's "
                f"ZIP code — ${school_zip_e5_bah:,.0f} a month — not your own "
                f"pay grade and not where you live. The same benefit is worth "
                f"thousands more a year at a university in an expensive city. "
                f"It is the largest variable in this calculation and it is "
                f"almost never considered when choosing a school.")

    v.housing = v.monthly_housing * months_used
    v.books = BOOKS_STIPEND_ANNUAL * v.academic_years
    v.total = v.tuition_covered + v.housing + v.books

    if v.yellow_ribbon_needed:
        v.notes.append(
            f"Tuition exceeds the national cap by "
            f"${v.tuition_shortfall / v.academic_years:,.0f} a year. The Yellow "
            f"Ribbon Program can close that gap — the school contributes and VA "
            f"matches dollar for dollar — but participation and the number of "
            f"places are set by the school. Confirm before enrolling, not after.")

    return v


@dataclass
class TransferAnalysis:
    eligible_to_transfer: bool = False
    years_of_service: float = 0.0
    obligation_years: int = TRANSFER_OBLIGATION_YEARS
    total_service_required: float = 0.0

    member_value: float = 0.0
    dependent_value: float = 0.0
    difference: float = 0.0

    recommendation: str = ""
    reasoning: list = field(default_factory=list)


def analyse_transfer(years_of_service: float, member_value: BenefitValue,
                     dependent_value: BenefitValue,
                     already_has_degree: bool = False,
                     still_serving: bool = True,
                     child_age: int | None = None,
                     ) -> TransferAnalysis:
    """
    Use it yourself, or transfer it.

    The obligation is the real cost and the model refuses to treat it as free.
    """
    a = TransferAnalysis(years_of_service=years_of_service,
                         member_value=member_value.total,
                         dependent_value=dependent_value.total)
    a.total_service_required = years_of_service + TRANSFER_OBLIGATION_YEARS
    a.difference = a.dependent_value - a.member_value

    if not still_serving:
        a.recommendation = "Too late to transfer"
        a.reasoning = [
            "**Transfer must be requested while still serving.** It cannot be "
            "initiated after separation, at any point, for any reason. This "
            "deadline is missed regularly and there is no appeal. If you are "
            "still in and think you might ever want to transfer, submit the "
            "request now — you can adjust the allocation later, and an unused "
            "transfer costs you nothing beyond the obligation you already "
            "served."]
        return a

    if years_of_service < TRANSFER_SERVICE_REQUIRED:
        a.recommendation = "Not yet eligible"
        a.reasoning = [
            f"Transfer requires {TRANSFER_SERVICE_REQUIRED} years of service. "
            f"You are at {years_of_service:g}. Revisit at "
            f"{TRANSFER_SERVICE_REQUIRED}."]
        return a

    a.eligible_to_transfer = True
    a.reasoning = [
        (f"Transferring commits you to {TRANSFER_OBLIGATION_YEARS} more years — "
         f"{a.total_service_required:g} total. That obligation is the price, and "
         f"it is not free: it removes your option to separate for four years. "
         f"If you were staying anyway it costs nothing. If you were not, it is "
         f"a real constraint on your life."),
        (f"Used by you: about ${a.member_value:,.0f}. "
         f"Transferred: about ${a.dependent_value:,.0f}."),
    ]

    if child_age is not None:
        years_until_26 = CHILD_MUST_USE_BY_AGE - child_age
        a.reasoning.append(
            f"A child may only begin using it after you complete "
            f"{CHILD_USE_AFTER_YEARS} years of service, must have a high school "
            f"diploma or be 18, and **must use it before turning "
            f"{CHILD_MUST_USE_BY_AGE}** — about {years_until_26} years from now "
            f"for this child. A spouse has no such deadline and may use it "
            f"immediately once transferred.")

    if already_has_degree and a.dependent_value > 0:
        a.recommendation = "Transfer"
        a.reasoning.append(
            "You already have the degree you need. The benefit has little value "
            "to you and substantial value to a dependent, so the only real "
            "question is whether the four-year obligation fits your plans.")
    elif a.difference > 25_000:
        a.recommendation = "Transfer is worth more"
        a.reasoning.append(
            f"Transferring is worth about ${a.difference:,.0f} more, largely "
            f"because a dependent studying full time off active duty collects "
            f"the housing allowance and you would not.")
    elif a.difference < -25_000:
        a.recommendation = "Using it yourself is worth more"
        a.reasoning.append(
            f"Using it yourself is worth about ${-a.difference:,.0f} more on "
            f"these assumptions — but check whether you would actually be "
            f"drawing the housing allowance, because you cannot while serving.")
    else:
        a.recommendation = "Close — decide on the obligation"
        a.reasoning.append(
            "The dollar values are close enough that the four-year obligation "
            "should decide it, not the arithmetic.")

    a.reasoning.append(
        "Treat this as a capital allocation decision, not an education one. A "
        f"transferred benefit worth ${a.dependent_value:,.0f} usually beats "
        f"years of 529 contributions, and it should be counted as an education "
        f"asset on your balance sheet rather than forgotten until the child "
        f"applies to university.")

    return a
