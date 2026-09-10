"""
Thrift Savings Plan: limits, the BRS match, and the combat zone overflow.

Four things this models that people routinely get wrong:

  1. THE MATCH EXISTS ONLY UNDER BRS, and is computed on BASIC PAY ONLY -- not
     BAH, not BAS, not special pays. "Contribute 5% of your income" is the wrong
     instruction and will under-contribute.

  2. SERVICE CONTRIBUTIONS ALWAYS LAND IN THE TRADITIONAL BALANCE, no matter how
     you designate your own. A member contributing 100% Roth still accumulates a
     traditional balance from the match, and will have RMDs on it.

  3. TWO SEPARATE LIMITS. Your own contributions are capped by the elective
     deferral limit. Total additions -- yours plus the service's plus any
     tax-exempt combat pay -- are capped by the much higher annual addition
     limit. In a combat zone the gap between the two is the opportunity.

  4. THE COMBAT ZONE OVERFLOW. Tax-exempt pay can be contributed up to the
     ANNUAL ADDITION limit, but Roth TSP is still capped at the ELECTIVE
     DEFERRAL limit. So the play is: fill Roth to the deferral limit first, then
     overflow tax-exempt pay into traditional. Those overflow dollars become a
     tax-exempt traditional balance -- never taxed again on withdrawal, though
     their earnings are.
"""

from __future__ import annotations
from dataclasses import dataclass, field

# --------------------------------------------------------------------------
# BRS match schedule
# --------------------------------------------------------------------------
AUTOMATIC_PCT = 0.01           # service contributes this regardless
MATCH_FULL_UPTO = 0.03         # 100% match on the first 3%
MATCH_HALF_UPTO = 0.05         # 50% match on the next 2%
MATCH_MAX_PCT = 0.04           # so the match itself tops out at 4%
FULL_MATCH_CONTRIBUTION = 0.05 # contribute 5% to get everything

AUTOMATIC_VESTING_YEARS = 2.0  # only the automatic 1% has a vesting cliff
MATCHING_BEGINS_YOS = 2.0      # matching starts at the 3rd year of service


@dataclass
class TSPLimits:
    year: int = 2026
    elective_deferral: float = 24_500.0
    catchup_50: float = 8_000.0
    catchup_60_63: float = 11_250.0
    annual_addition: float = 72_000.0
    roth_catchup_wage_threshold: float = 150_000.0


def elective_limit(age: int, limits: TSPLimits | None = None) -> float:
    """Your own contribution ceiling, including any catch-up you qualify for."""
    L = limits or TSPLimits()
    if 60 <= age <= 63:
        return L.elective_deferral + L.catchup_60_63
    if age >= 50:
        return L.elective_deferral + L.catchup_50
    return L.elective_deferral


def catchup_must_be_roth(prior_year_wages: float,
                         limits: TSPLimits | None = None) -> bool:
    """
    From 2026, a member whose prior-year wages exceeded the threshold must make
    catch-up contributions as Roth. Tax-exempt combat pay contributions must
    also be Roth.
    """
    L = limits or TSPLimits()
    return prior_year_wages > L.roth_catchup_wage_threshold


@dataclass
class MatchResult:
    eligible: bool = False
    automatic: float = 0.0
    matching: float = 0.0
    total_service: float = 0.0
    member_contribution: float = 0.0
    unclaimed: float = 0.0
    contribution_pct: float = 0.0
    note: str = ""
    vested_automatic: bool = True


def _append_vesting_note(r: "MatchResult") -> None:
    """
    Say what is and is not at risk before two years of service.

    This has to reach the member who is UNDER two years -- the only person for
    whom it matters -- so it is appended on every path out of service_match(),
    including the early return for members whose matching has not begun.
    People routinely believe the whole balance is forfeit if they separate
    early. Only the automatic 1% is.
    """
    if not r.vested_automatic:
        r.note += (f" The automatic 1% vests at {AUTOMATIC_VESTING_YEARS:.0f} "
                   f"years of service; your own contributions and the matching "
                   f"contributions are yours immediately, and you keep them "
                   f"whenever you separate.")


def service_match(basic_pay_annual: float, contribution_pct: float,
                  is_brs: bool, years_of_service: float = 10.0) -> MatchResult:
    """
    Service automatic and matching contributions for a year.

    Schedule: 1% automatic regardless of what you do, then 100% on the first 3%
    you contribute and 50% on the next 2%. Contribute 5% and the service adds
    5%. Contribute more and the service adds nothing further.
    """
    r = MatchResult(contribution_pct=contribution_pct,
                    member_contribution=basic_pay_annual * contribution_pct)

    if not is_brs:
        r.note = ("There is no TSP match under this retirement system. Only BRS "
                  "carries service automatic and matching contributions — a "
                  "legacy High-3 member contributing 5% 'for the match' is "
                  "getting nothing for it.")
        return r

    r.eligible = True
    r.automatic = basic_pay_annual * AUTOMATIC_PCT
    r.vested_automatic = years_of_service >= AUTOMATIC_VESTING_YEARS

    if years_of_service < MATCHING_BEGINS_YOS:
        r.total_service = r.automatic
        r.unclaimed = basic_pay_annual * MATCH_MAX_PCT
        r.note = (f"Matching begins at {MATCHING_BEGINS_YOS:.0f} years of "
                  f"service. Until then you receive the automatic 1% only. Keep "
                  f"contributing anyway — your own contributions are always "
                  f"yours, and the habit is what matters.")
        _append_vesting_note(r)
        return r

    pct = max(0.0, contribution_pct)
    full = min(pct, MATCH_FULL_UPTO)
    half = max(0.0, min(pct, MATCH_HALF_UPTO) - MATCH_FULL_UPTO)
    match_pct = full + half * 0.5

    r.matching = basic_pay_annual * match_pct
    r.total_service = r.automatic + r.matching
    r.unclaimed = basic_pay_annual * max(0.0, MATCH_MAX_PCT - match_pct)

    if pct >= FULL_MATCH_CONTRIBUTION:
        r.note = ("You are capturing the full match. Contributing above 5% earns "
                  "no additional service money, though it may still be right for "
                  "other reasons.")
    else:
        r.note = (f"Contribute {FULL_MATCH_CONTRIBUTION * 100:.0f}% of basic pay "
                  f"to capture everything. You are currently leaving "
                  f"${r.unclaimed:,.0f} a year on the table.")

    _append_vesting_note(r)
    return r


@dataclass
class ContributionPlan:
    age: int = 0
    elective_limit: float = 0.0
    annual_addition_limit: float = 0.0
    member_regular: float = 0.0
    service_contributions: float = 0.0
    roth_capacity: float = 0.0
    taxexempt_overflow_capacity: float = 0.0
    total_capacity: float = 0.0
    in_combat_zone: bool = False
    catchup_forced_roth: bool = False
    notes: list = field(default_factory=list)


def plan_contributions(basic_pay_annual: float, age: int, is_brs: bool,
                       contribution_pct: float, in_combat_zone: bool = False,
                       prior_year_wages: float = 0.0,
                       years_of_service: float = 10.0,
                       limits: TSPLimits | None = None) -> ContributionPlan:
    """
    Work out the ceilings that actually apply, and what the combat zone opens up.
    """
    L = limits or TSPLimits()
    p = ContributionPlan(age=age, in_combat_zone=in_combat_zone,
                         elective_limit=elective_limit(age, L),
                         annual_addition_limit=L.annual_addition)

    match = service_match(basic_pay_annual, contribution_pct, is_brs,
                          years_of_service)
    p.service_contributions = match.total_service
    p.member_regular = min(basic_pay_annual * contribution_pct, p.elective_limit)

    # Roth is always bounded by the elective deferral limit, combat zone or not.
    p.roth_capacity = p.elective_limit

    if in_combat_zone:
        headroom = max(0.0, p.annual_addition_limit - p.elective_limit
                       - p.service_contributions)
        p.taxexempt_overflow_capacity = headroom
        p.total_capacity = p.elective_limit + headroom
        p.notes.append(
            f"In a combat zone your total additions are bounded by the "
            f"${p.annual_addition_limit:,.0f} annual addition limit, not the "
            f"${p.elective_limit:,.0f} elective deferral limit. But Roth TSP is "
            f"still capped at ${p.elective_limit:,.0f}.")
        p.notes.append(
            f"So the order is: fill Roth TSP to ${p.elective_limit:,.0f} with "
            f"tax-free pay first, then overflow up to "
            f"${headroom:,.0f} more into TRADITIONAL TSP as tax-exempt "
            f"contributions.")
        p.notes.append(
            "Those overflow dollars become a tax-exempt traditional balance: "
            "contributed with pay that was never taxed, and never taxed again on "
            "withdrawal. Their earnings ARE taxable. Note that a tax-exempt "
            "traditional balance cannot be cleanly rolled to a traditional IRA, "
            "so it needs care at separation.")
    else:
        p.total_capacity = p.elective_limit

    p.catchup_forced_roth = age >= 50 and catchup_must_be_roth(prior_year_wages, L)
    if p.catchup_forced_roth:
        p.notes.append(
            f"Your prior-year wages exceeded ${L.roth_catchup_wage_threshold:,.0f}, "
            f"so from {L.year} your catch-up contributions must be Roth. This is "
            f"not optional.")

    if 60 <= age <= 63:
        p.notes.append(
            f"You are in the 60-63 window, where the catch-up is "
            f"${L.catchup_60_63:,.0f} rather than ${L.catchup_50:,.0f}. It drops "
            f"back at 64.")

    return p


def traditional_or_roth(marginal_rate_now: float, nontaxable_share: float,
                        in_combat_zone: bool = False,
                        expected_retirement_rate: float = 0.22) -> tuple[str, str]:
    """
    Which side of the TSP to contribute to. Returns (recommendation, reasoning).

    The military tilt toward Roth is structural rather than a matter of taste:
    untaxed allowances hold the marginal bracket down relative to real income,
    so the tax being saved by a traditional contribution is unusually cheap tax
    to pay instead.
    """
    if in_combat_zone:
        return ("Roth", 
                "You are in a combat zone, so your pay is not being taxed going "
                "in. A traditional contribution would save you tax you are not "
                "paying anyway, and then tax the money on the way out. Roth "
                "contributions of tax-free pay are never taxed at any point — "
                "going in, growing, or coming out. This is the single best "
                "contribution available to a service member.")

    if marginal_rate_now <= 0.12:
        return ("Roth",
                f"You are in the {marginal_rate_now * 100:.0f}% bracket. A "
                f"traditional contribution saves you {marginal_rate_now * 100:.0f} "
                f"cents on the dollar now, against a retirement in which your "
                f"pension is a taxable income floor that never goes away. Paying "
                f"tax at this rate is cheap.")

    if nontaxable_share > 0.25 and marginal_rate_now <= 0.22:
        return ("Roth",
                f"{nontaxable_share * 100:.0f}% of your compensation is untaxed, "
                f"which holds your marginal rate at "
                f"{marginal_rate_now * 100:.0f}% despite your actual standard of "
                f"living. That is a lower rate than most civilians at your total "
                f"compensation face, and lower than the rate a military retiree "
                f"typically faces later — a pension plus Social Security is a "
                f"taxable floor that RMDs then stack on top of.")

    if marginal_rate_now >= expected_retirement_rate + 0.05:
        return ("Traditional",
                f"At a {marginal_rate_now * 100:.0f}% marginal rate now against "
                f"an expected {expected_retirement_rate * 100:.0f}% later, "
                f"deferring is the better arithmetic. This is the situation for "
                f"senior officers and dual-income households already in the 24% "
                f"bracket or above.")

    return ("Split",
            f"At {marginal_rate_now * 100:.0f}% now against an expected "
            f"{expected_retirement_rate * 100:.0f}% later, the two are close "
            f"enough that splitting hedges the rate risk. Contributing to both "
            f"also gives you two pools to draw from in retirement, which is worth "
            f"something on its own.")
