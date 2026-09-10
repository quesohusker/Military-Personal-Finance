"""
Spouse income, modelled with the interruptions a military career imposes on it.

This is the part a civilian planner structurally cannot do. Boldin and every
tool like it treats a spouse's earnings as a continuous career with a growth
rate. A military spouse's earnings are not continuous: they stop at every PCS,
restart at a lower rate in a new labour market, and lose the seniority that was
accumulating.

The numbers are not small. Military spouse unemployment has run above 20% for
more than a decade, with substantial underemployment on top. The lifetime
earnings gap -- and the retirement savings that gap never generated -- frequently
exceeds the present value of the service member's pension.

Modelling it honestly does two things. It stops the household plan from
assuming income that will not arrive, and it puts a number on a cost that is
usually carried silently.
"""

from __future__ import annotations
from dataclasses import dataclass, field, asdict

# Typical gap between arriving at a new duty station and earning again.
DEFAULT_MONTHS_UNEMPLOYED_PER_PCS = 5.0

# How far pay typically resets on a move, before rebuilding.
DEFAULT_WAGE_RESET = 0.12

# How fast the reset is recovered, per year in place.
DEFAULT_RECOVERY_PER_YEAR = 0.06

# Reimbursement available for re-licensing after a PCS on orders.
LICENSE_REIMBURSEMENT_CAP = 1_000.0


CAREER_PORTABLE = "Portable or remote"
CAREER_LICENSED = "Licensed profession"
CAREER_LOCAL = "Local employment"
CAREER_FEDERAL = "Federal employee"
CAREER_SELF = "Self-employed / business owner"
CAREER_NONE = "Not employed"
CAREER_TYPES = [CAREER_PORTABLE, CAREER_LICENSED, CAREER_LOCAL, CAREER_FEDERAL,
                CAREER_SELF, CAREER_NONE]

# How much of the standard interruption each career type actually suffers.
INTERRUPTION_FACTOR = {
    CAREER_PORTABLE: 0.15,   # remote work mostly survives a move
    CAREER_FEDERAL: 0.50,    # military spouse preference helps, but is not instant
    CAREER_LICENSED: 1.10,   # re-licensing in a new state adds delay
    CAREER_LOCAL: 1.00,
    CAREER_SELF: 0.60,       # the business moves, the client base does not
    CAREER_NONE: 0.0,
}

CAREER_NOTES = {
    CAREER_PORTABLE: ("Remote and portable work is the single most effective "
                      "answer to this problem. It is why so much military "
                      "spouse career advice points at it."),
    CAREER_FEDERAL: ("Military spouse preference in federal hiring, and the "
                     "ability to transfer within an agency, cut the gap "
                     "substantially — though a transfer still takes months."),
    CAREER_LICENSED: ("A licensed profession is the hardest case: the job "
                      "exists everywhere but the licence does not travel. The "
                      "Veterans Auto and Education Improvement Act of 2022 "
                      "requires states to honour an out-of-state licence after "
                      "a PCS on orders, and DoD reimburses re-licensing up to "
                      f"${LICENSE_REIMBURSEMENT_CAP:,.0f} per move. Both help; "
                      "neither is instant."),
    CAREER_LOCAL: ("Locally-held employment restarts from zero at every duty "
                   "station — new employer, new market, no accumulated "
                   "seniority."),
    CAREER_SELF: ("A business can move, but its clients and referral network "
                  "usually cannot. Expect revenue to rebuild rather than "
                  "resume."),
    CAREER_NONE: "",
}


@dataclass
class SpouseIncome:
    employed: bool = False
    career_type: str = CAREER_LOCAL
    annual_income: float = 0.0

    is_dual_military: bool = False
    dual_military_grade: str = ""

    # How the interruption behaves. Defaults are typical; every one is editable.
    months_unemployed_per_pcs: float = DEFAULT_MONTHS_UNEMPLOYED_PER_PCS
    wage_reset_on_move: float = DEFAULT_WAGE_RESET
    recovery_per_year: float = DEFAULT_RECOVERY_PER_YEAR
    real_growth_in_place: float = 0.01

    # Retirement saving the spouse does out of their own earnings.
    retirement_contribution_pct: float = 0.0
    employer_match_pct: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SpouseYear:
    year: int = 0
    years_of_service: float = 0.0
    moved: bool = False
    months_worked: float = 12.0
    wage_rate_annual: float = 0.0    # the rate they are earning at
    earned: float = 0.0              # what they actually receive
    uninterrupted: float = 0.0       # what a civilian career would have paid
    lost: float = 0.0


@dataclass
class SpouseProjection:
    years: list = field(default_factory=list)
    total_earned: float = 0.0
    total_uninterrupted: float = 0.0
    total_lost: float = 0.0
    total_retirement_lost: float = 0.0
    n_moves: int = 0

    @property
    def lost_share(self) -> float:
        return (self.total_lost / self.total_uninterrupted
                if self.total_uninterrupted else 0.0)


def project_spouse_income(spouse: SpouseIncome, moves, start_year: int,
                          start_yos: float, end_yos: float,
                          investment_return: float = 0.05) -> SpouseProjection:
    """
    Spouse earnings year by year, against the counterfactual of an
    uninterrupted civilian career.

    `moves` is the PCS list from the career timeline -- anything with an
    `at_years_of_service` attribute.

    The counterfactual is deliberately conservative: it assumes the same
    starting salary growing at the same in-place rate, with no interruptions.
    It does not assume the spouse would have been promoted faster elsewhere,
    though in practice that is usually part of the loss too.
    """
    out = SpouseProjection()
    if not spouse.employed or spouse.annual_income <= 0:
        return out

    move_years = sorted({round(float(getattr(mv, "at_years_of_service", 0)), 1)
                         for mv in (moves or [])})
    out.n_moves = len(move_years)

    factor = INTERRUPTION_FACTOR.get(spouse.career_type, 1.0)
    if spouse.is_dual_military:
        # A dual-military spouse does not lose income to a PCS -- they are on
        # orders too. Joint-spouse assignment is not guaranteed, but pay is.
        factor = 0.0

    rate = spouse.annual_income
    counterfactual = spouse.annual_income
    n = max(1, int(round(end_yos - start_yos)) + 1)

    for i in range(n):
        yos = start_yos + i
        year = start_year + i
        moved = any(abs(yos - my) < 0.5 for my in move_years)

        months_off = 0.0
        if moved and factor > 0:
            months_off = min(12.0, spouse.months_unemployed_per_pcs * factor)
            rate = rate * (1.0 - spouse.wage_reset_on_move * factor)
        else:
            # Rebuild toward the counterfactual while in place.
            rate *= (1.0 + spouse.real_growth_in_place)
            if rate < counterfactual:
                rate = min(counterfactual,
                           rate * (1.0 + spouse.recovery_per_year))

        counterfactual *= (1.0 + spouse.real_growth_in_place)

        months_worked = 12.0 - months_off
        earned = rate * (months_worked / 12.0)

        row = SpouseYear(year=year, years_of_service=yos, moved=moved,
                         months_worked=months_worked, wage_rate_annual=rate,
                         earned=earned, uninterrupted=counterfactual,
                         lost=max(0.0, counterfactual - earned))
        out.years.append(row)
        out.total_earned += earned
        out.total_uninterrupted += counterfactual
        out.total_lost += row.lost

    # Retirement savings never made on income never earned, compounded to the
    # end of the projection.
    save_rate = spouse.retirement_contribution_pct + spouse.employer_match_pct
    if save_rate > 0:
        total = 0.0
        for i, row in enumerate(out.years):
            years_to_grow = len(out.years) - i
            total += row.lost * save_rate * ((1.0 + investment_return) ** years_to_grow)
        out.total_retirement_lost = total

    return out


def _money(x: float) -> str:
    return f"${x:,.0f}"


def findings(spouse: SpouseIncome, proj: SpouseProjection) -> list[tuple[str, str, str]]:
    """(severity, headline, detail)."""
    out = []

    if not spouse.employed:
        out.append(("info", "No spouse income is modelled.",
                    "If your spouse works, or intends to, add it — a second "
                    "income changes the plan more than any investment decision "
                    "in it. If they do not, that is a legitimate choice, and "
                    "the household plan should account for a single earner "
                    "rather than assume a second one appears."))
        return out

    if spouse.is_dual_military:
        out.append(("good", "Dual military — no PCS income interruption.",
                    "Both of you are on orders, so a move does not stop either "
                    "income. The real risk is different: joint-spouse assignment "
                    "is a request, not a guarantee, and a geographic separation "
                    "means running two households on pay calculated for one "
                    "location each."))
        return out

    if proj.n_moves == 0:
        out.append(("info", "No PCS moves are on your timeline yet.",
                    "Add planned moves on the Career page and this will price "
                    "what each one costs your spouse's earnings."))
        return out

    if proj.total_lost > 0:
        out.append(("bad",
                    f"PCS moves cost your spouse about {_money(proj.total_lost)} "
                    f"in earnings.",
                    f"Across {proj.n_moves} move(s), against an uninterrupted "
                    f"career earning {_money(proj.total_uninterrupted)}, your "
                    f"spouse is projected to earn {_money(proj.total_earned)} — "
                    f"a shortfall of {proj.lost_share * 100:.0f}%. This is the "
                    f"largest cost in most military family finances and it is "
                    f"almost never on the balance sheet. It is not a reason not "
                    f"to serve; it is a reason to plan around it deliberately."))

    if proj.total_retirement_lost > 0:
        out.append(("warn",
                    f"And about {_money(proj.total_retirement_lost)} of "
                    f"retirement savings that income never generated.",
                    "Earnings that never arrived could not be contributed, and "
                    "could not compound. This is the compounding half of the "
                    "cost, and it is usually larger than the wages themselves."))

    note = CAREER_NOTES.get(spouse.career_type, "")
    if note:
        sev = "good" if spouse.career_type == CAREER_PORTABLE else "info"
        out.append((sev, f"Career type: {spouse.career_type}.", note))

    if spouse.career_type == CAREER_LICENSED:
        out.append(("info", "Claim the licence reimbursement at every move.",
                    f"DoD reimburses up to "
                    f"${LICENSE_REIMBURSEMENT_CAP:,.0f} per PCS for "
                    f"re-licensing and certification costs. It is per move, not "
                    f"once per career, and it is routinely left unclaimed."))

    if spouse.career_type in (CAREER_LOCAL, CAREER_LICENSED) and proj.total_lost > 50_000:
        out.append(("info", "Portable work is the lever that actually moves this.",
                    "The single largest reduction available is a role that "
                    "survives a move — remote, contract, or federal with "
                    "transfer rights. Change the career type above to see what "
                    "that would be worth over the same set of moves."))

    return out
