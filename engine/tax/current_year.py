"""
What THIS year's federal return looks like, for a serving member or a retiree.

The projection engine in engine/tax/federal.py answers a thirty-year question.
This module answers a one-year one -- what lands on the W-2 in January and what
the return built on it will say -- and it exists because three things about a
military return are routinely got wrong, each in the member's disfavour:

  1. THE EARNED INCOME CREDIT LOOKS OUT OF REACH AND IS NOT. BAH and BAS never
     enter earned income or AGI, and pay earned in a combat zone is excluded
     too. A junior enlisted family with two children and $70,000 of real
     compensation can show $35,000 of W-2 wages and qualify for a credit worth
     thousands. Many never claim it because their total pay looks too high.

  2. THE COMBAT-PAY ELECTION CUTS BOTH WAYS. IRC 32(c)(2)(B)(vi) lets a member
     elect to count nontaxable combat pay (W-2 box 12, code Q) as earned income
     for the EITC. On the phase-in side that raises the credit; on the phase-out
     side it destroys it. The only way to know is to compute it both ways, so
     the engine does.

  3. THE SAVER'S CREDIT IS MISSED. Roth TSP contributions qualify, junior
     enlisted AGI sits inside the limits, and the credit is claimed by almost
     nobody who is eligible for it. 2026 is its last year as a credit -- from
     2027 it becomes the Saver's Match under SECURE 2.0.

Brackets and the standard deduction come from engine/tax/federal.py and
engine/tax/tables.py; the state comes from engine/tax/state.py and
engine/tax/domicile.py; the pay figures come from engine/pay/taxable.py and the
exclusion from engine/tax/military.py. Nothing in those tables is restated here.

The credit parameters below are the only figures this module owns. They are
2026 amounts from Rev. Proc. 2025-32 as reported by secondary sources; the IRS
text itself could not be reached when they were entered. Every one is marked
VERIFY and gathered in one place per credit so the annual update is a single
edit.
"""

from __future__ import annotations
from dataclasses import dataclass, field
import math

from engine.tax import tables as T
from engine.tax import federal as F
from engine.tax import state as ST
from engine.tax import military as M
from engine.tax import domicile as D
from engine.pay import taxable as TX
from engine.pay import grades as G, bah as BAH, bas as BAS
from engine.pay import bah_nonlocality as NL
from engine.profile import Household, ServiceMember, GUARD, RESERVE

TAX_YEAR = T.TAX_YEAR_BASIS   # 2026

# ==========================================================================
# 2026 credit parameters -- VERIFY against Rev. Proc. 2025-32 before relying
# on any of them. Each dict carries its year so a stale table is visible.
# ==========================================================================

# Earned Income Tax Credit, IRC 32. The credit and phase-out rates are
# statutory and do not change; the dollar amounts are indexed annually.
# Keyed by number of qualifying children (3 means "three or more").
EITC_2026 = {
    "year": 2026,
    "source": "Rev. Proc. 2025-32 sec. 3.06 -- VERIFY",
    "credit_rate": {0: 0.0765, 1: 0.34, 2: 0.40, 3: 0.45},          # statutory
    "phaseout_rate": {0: 0.0765, 1: 0.1598, 2: 0.2106, 3: 0.2106},  # statutory
    # Earned income at which the credit reaches its maximum.
    "earned_income_amount": {0: 8_680, 1: 13_020, 2: 18_290, 3: 18_290},  # VERIFY
    # Published maximum credit (= credit_rate x earned_income_amount, rounded).
    "max_credit": {0: 664, 1: 4_427, 2: 7_316, 3: 8_231},              # VERIFY
    # AGI (or earned income, whichever is greater) at which the phase-out begins.
    "phaseout_threshold": {
        T.SINGLE: {0: 10_860, 1: 23_890, 2: 23_890, 3: 23_890},        # VERIFY
        # CHECKED against Rev. Proc. 2025-32 s4.06, table at p.15. The
        # childless MFJ threshold is 18,140; it was carried as 18,130.
        T.MFJ:    {0: 18_140, 1: 31_160, 2: 31_160, 3: 31_160},
    },
    "investment_income_limit": 12_200,                                 # VERIFY
    # Without a qualifying child the claimant must be 25 to 64.
    "childless_min_age": 25,
    "childless_max_age": 64,
}

# Child Tax Credit, IRC 24, as made permanent by OBBBA. The $2,200 is indexed
# from 2026 in $100 steps rounded down, so it stays $2,200 for 2026; the
# refundable ceiling is indexed separately. The phase-out thresholds are
# statutory and unindexed.
CTC_2026 = {
    "year": 2026,
    "source": "Rev. Proc. 2025-32 sec. 3.05 -- VERIFY",
    "per_child": 2_200,                 # VERIFY
    "refundable_max_per_child": 1_700,  # VERIFY (Additional Child Tax Credit)
    "refundable_rate": 0.15,            # statutory: 15% of earned income over the floor
    "earned_income_floor": 2_500,       # statutory
    "other_dependent": 500,             # statutory, nonrefundable
    "phaseout_start": {T.MFJ: 400_000, T.SINGLE: 200_000},   # statutory
    "phaseout_per_1000": 50,            # statutory
}

# Retirement Savings Contributions Credit, IRC 25B. Tiers are (AGI ceiling,
# credit rate); above the last ceiling there is no credit. Head of household
# sits between the two and is not modelled.
SAVERS_CREDIT_2026 = {
    "year": 2026,
    "source": "Rev. Proc. 2025-32 / Notice 2025-67 -- VERIFY",
    "max_contribution_per_person": 2_000,   # statutory
    "tiers": {
        T.MFJ:    [(48_500, 0.50), (52_500, 0.20), (80_500, 0.10)],   # VERIFY
        T.SINGLE: [(24_250, 0.50), (26_250, 0.20), (40_250, 0.10)],   # VERIFY
    },
    "min_age": 18,
    # SECURE 2.0 sec. 103 replaces the credit with a government match paid
    # into the account for taxable years beginning after 31 Dec 2026.
    "last_year_as_credit": 2026,
}

# Flat federal withholding on supplemental wages (bonuses). Statutory, equal
# to the third bracket rate, which OBBBA made permanent.
SUPPLEMENTAL_WITHHOLDING_RATE = 0.22


# ==========================================================================
# Household facts
# ==========================================================================

def filing_status_for(h: Household) -> str:
    """The engine models joint and single. A married member files jointly."""
    return T.MFJ if h.has_spouse else T.SINGLE


def spouse_wages_for(h: Household) -> float:
    if not h.has_spouse:
        return 0.0
    s = h.spouse_income
    return float(s.annual_income) if s.employed else 0.0


def _kids(n) -> int:
    """The EITC parameters stop at three; more children change nothing."""
    return max(0, min(3, int(n or 0)))


def _status(status: str) -> str:
    return status if status in T.FILING_STATUSES else T.SINGLE


def _money(x: float) -> str:
    return f"${x:,.0f}"


# ==========================================================================
# The W-2 picture
# ==========================================================================

@dataclass
class W2Picture:
    """One year of a member's pay, divided the way the W-2 divides it."""
    serving: bool = True
    basic_pay: float = 0.0
    special_pay_taxable: float = 0.0
    bonus: float = 0.0
    bonus_excluded: float = 0.0          # a bonus paid in the zone is excluded whole
    bah: float = 0.0
    bas: float = 0.0
    other_allowances: float = 0.0        # non-taxable special pays (HFP, FSA, ...)
    czte_months: int = 0
    czte_excluded: float = 0.0           # basic + taxable special pay excluded
    czte_note: str = ""
    tsp_total: float = 0.0               # everything the member puts in
    tsp_roth: float = 0.0
    tsp_traditional: float = 0.0
    tsp_traditional_box1_reduction: float = 0.0   # the part that came from taxed pay
    box1: float = 0.0                    # federal taxable wages
    notes: list = field(default_factory=list)

    @property
    def combat_pay(self) -> float:
        """W-2 box 12, code Q: nontaxable combat pay."""
        return self.czte_excluded + self.bonus_excluded

    @property
    def taxable_before_exclusions(self) -> float:
        return self.basic_pay + self.special_pay_taxable + self.bonus

    @property
    def allowances(self) -> float:
        return self.bah + self.bas + self.other_allowances

    @property
    def gross(self) -> float:
        return self.taxable_before_exclusions + self.allowances

    @property
    def fica_wages(self) -> float:
        """Social Security and Medicare wages: CZTE pay and TSP deferrals stay in."""
        return self.taxable_before_exclusions

    @property
    def never_taxed(self) -> float:
        return self.gross - self.box1

    @property
    def untaxed_share(self) -> float:
        return (self.never_taxed / self.gross) if self.gross > 0 else 0.0

    def rows(self) -> list[dict]:
        """Tidy rows for the chart and its table: component, amount, treatment."""
        out = [
            ("Box 1 wages", self.box1, "Taxed"),
            ("Traditional TSP", self.tsp_traditional_box1_reduction, "Deferred"),
            ("Combat-zone pay", self.combat_pay, "Excluded (box 12-Q)"),
            ("BAH", self.bah, "Never taxed"),
            ("BAS", self.bas, "Never taxed"),
            ("Other allowances", self.other_allowances, "Never taxed"),
        ]
        return [{"Component": c, "Amount": a, "Treatment": t} for c, a, t in out
                if a > 0.5]


def w2_picture(m: ServiceMember, *, bonus_paid_in_zone: bool = False,
               bah_data=None, elective_limit: float | None = None,
               czte_months: int | None = None) -> W2Picture:
    """
    Build the year's W-2 from the profile.

    Box 1 is basic pay plus taxable special pays and bonuses, less the months
    excluded in a combat zone, less the traditional TSP deferral that came out
    of pay that was actually taxable. A traditional contribution made from
    excluded pay reduces nothing -- there is nothing left to reduce -- so the
    deferral is pro-rated to the share of pay that stayed taxable.
    """
    w = W2Picture(serving=m.is_serving)
    if not m.is_serving:
        w.notes.append("No military pay: retired pay is reported on a 1099-R, "
                       "not a W-2, and is handled on the return below.")
        return w

    tp = TX.compute(m)
    w.notes.extend(tp.notes)
    w.basic_pay = tp.basic_monthly * 12.0
    w.special_pay_taxable = tp.special_monthly_taxable * 12.0
    w.bonus = tp.bonus_annual
    if m.special_pay_monthly and not m.special_pay_taxable:
        w.other_allowances = float(m.special_pay_monthly) * 12.0

    # Allowances, resolved the way the Pay page resolves them.
    try:
        grade = G.get(m.grade)
        is_officer = G.is_officer(grade)
    except KeyError:
        is_officer = False
    if m.lives_in_government_housing:
        p = NL.partial(m.grade)
        w.bah = (p.monthly if p.found else 0.0) * 12.0
    elif m.bah_monthly_override > 0:
        w.bah = float(m.bah_monthly_override) * 12.0
    else:
        data = bah_data if bah_data is not None else BAH.load()
        r = BAH.lookup_or_average(m.duty_zip, m.grade, m.has_dependents, data)
        w.bah = r.monthly * 12.0 if r.found else 0.0
        if r.found and r.is_average:
            w.notes.append("BAH is the national median for your grade because "
                           "no duty ZIP is set on the Profile page.")
    w.bas = (float(m.bas_monthly_override) or BAS.bas_monthly(is_officer).monthly) * 12.0

    if m.component in (GUARD, RESERVE):
        w.notes.append("Guard and Reserve drill pay is not modelled separately: "
                       "this treats basic pay as full-time. Use the LES override "
                       "on the Pay page to enter what you actually earn.")

    # The exclusion. The page may override the months: a member planning a
    # deployment wants to see the return it produces before it happens, and a
    # member back from one wants the months they actually served, not the
    # figure the profile was last saved with.
    if czte_months is None:
        months = int(m.months_deployed_this_year) if m.in_combat_zone else 0
    else:
        months = max(0, min(12, int(czte_months)))
    split = M.CompensationSplit(basic_pay=w.basic_pay,
                                special_pay_taxable=w.special_pay_taxable,
                                bah=w.bah, bas=w.bas,
                                other_nontaxable=w.other_allowances)
    M.apply_czte(split, m.grade, months)
    w.czte_months = split.czte_months
    w.czte_excluded = split.czte_excluded
    if w.czte_months > 0:
        _, w.czte_note = M.czte_monthly_exclusion(
            m.grade, w.basic_pay / 12.0, w.special_pay_taxable / 12.0)
        if w.bonus > 0 and bonus_paid_in_zone:
            w.bonus_excluded = w.bonus

    # TSP. Elections are a percentage of basic pay, capped by the deferral limit.
    limit = elective_limit
    if limit is None:
        limit = T.EMPLOYER_PLAN_DEFERRAL_LIMIT
        if m.age(TAX_YEAR) >= 50:
            limit += T.EMPLOYER_PLAN_CATCHUP_50
    w.tsp_total = min(float(m.tsp_contribution_pct) * w.basic_pay, limit)
    w.tsp_roth = w.tsp_total * float(m.tsp_roth_share)
    w.tsp_traditional = w.tsp_total - w.tsp_roth

    taxable_pay = split.taxable_before_czte
    share_still_taxable = (split.federal_taxable / taxable_pay) if taxable_pay > 0 else 0.0
    w.tsp_traditional_box1_reduction = w.tsp_traditional * share_still_taxable
    if w.tsp_traditional > 0 and share_still_taxable < 1.0:
        w.notes.append("Traditional TSP contributions made from combat-zone pay "
                       "are tax-exempt contributions: they reduce nothing "
                       "because that pay was never taxable. Only the share made "
                       "from taxed months lowers box 1.")

    w.box1 = max(0.0, split.federal_taxable + (w.bonus - w.bonus_excluded)
                 - w.tsp_traditional_box1_reduction)
    return w


# ==========================================================================
# Earned Income Tax Credit
# ==========================================================================

@dataclass
class EITCResult:
    eligible: bool = False
    n_children: int = 0
    earned_income: float = 0.0
    agi: float = 0.0
    credit: float = 0.0
    max_credit: float = 0.0
    phase: str = ""          # phase-in | plateau | phase-out | none
    reason: str = ""


def earned_income_credit(earned_income: float, agi: float, n_children: int,
                         status: str, *, investment_income: float = 0.0,
                         age: int | None = None, params: dict | None = None
                         ) -> EITCResult:
    """
    The credit as the statute computes it: the credit rate on earned income up
    to the earned-income amount, less the phase-out rate on whichever of AGI
    or earned income is larger above the threshold.
    """
    p = params or EITC_2026
    k = _kids(n_children)
    status = _status(status)
    r = EITCResult(n_children=k, earned_income=earned_income, agi=agi,
                   max_credit=float(p["max_credit"][k]))

    if investment_income > p["investment_income_limit"]:
        r.reason = (f"Investment income above {_money(p['investment_income_limit'])} "
                    f"disqualifies the credit.")
        r.phase = "none"
        return r
    if k == 0 and age is not None and not (p["childless_min_age"] <= age
                                            <= p["childless_max_age"]):
        r.reason = (f"Without a qualifying child the claimant must be "
                    f"{p['childless_min_age']} to {p['childless_max_age']}.")
        r.phase = "none"
        return r
    if earned_income <= 0:
        r.reason = "No earned income: the credit needs wages that count."
        r.phase = "none"
        return r

    rate = p["credit_rate"][k]
    amount = p["earned_income_amount"][k]
    credit = min(rate * earned_income, r.max_credit)
    threshold = p["phaseout_threshold"][status][k]
    base = max(agi, earned_income)
    reduction = p["phaseout_rate"][k] * max(0.0, base - threshold)
    r.credit = max(0.0, credit - reduction)
    r.eligible = r.credit > 0

    if not r.eligible:
        r.phase = "none"
        r.reason = (f"Income of {_money(base)} is above the "
                    f"{_money(completed_phaseout(k, status, p))} limit for "
                    f"{k if k < 3 else '3 or more'} "
                    f"{'child' if k == 1 else 'children'}.")
    elif reduction > 0:
        r.phase = "phase-out"
        r.reason = (f"Above the {_money(threshold)} threshold the credit shrinks "
                    f"by {p['phaseout_rate'][k] * 100:.2f} cents per dollar.")
    elif earned_income < amount:
        r.phase = "phase-in"
        r.reason = (f"Below {_money(amount)} of earned income the credit is still "
                    f"growing at {rate * 100:.0f} cents per dollar.")
    else:
        r.phase = "plateau"
        r.reason = "At the maximum credit."
    return r


def completed_phaseout(n_children: int, status: str, params: dict | None = None) -> float:
    """Income at which the credit reaches zero -- derived, not hard-coded."""
    p = params or EITC_2026
    k = _kids(n_children)
    status = _status(status)
    return (p["phaseout_threshold"][status][k]
            + p["max_credit"][k] / p["phaseout_rate"][k])


@dataclass
class EITCComparison:
    combat_pay: float = 0.0
    without_election: EITCResult = field(default_factory=EITCResult)
    with_election: EITCResult = field(default_factory=EITCResult)
    recommend_election: bool = False
    gain: float = 0.0          # what the better choice is worth over the worse
    note: str = ""

    @property
    def best(self) -> EITCResult:
        return self.with_election if self.recommend_election else self.without_election

    @property
    def credit(self) -> float:
        return self.best.credit


def eitc_both_ways(taxable_earned: float, combat_pay: float, agi: float,
                   n_children: int, status: str, *, investment_income: float = 0.0,
                   age: int | None = None) -> EITCComparison:
    """
    IRC 32(c)(2)(B)(vi): a member may elect to treat nontaxable combat pay as
    earned income for the EITC. It is all or nothing, it never enters AGI, and
    it can raise or lower the credit -- so compute both and pick.
    """
    c = EITCComparison(combat_pay=max(0.0, combat_pay))
    c.without_election = earned_income_credit(
        taxable_earned, agi, n_children, status,
        investment_income=investment_income, age=age)
    c.with_election = earned_income_credit(
        taxable_earned + c.combat_pay, agi, n_children, status,
        investment_income=investment_income, age=age)
    a, b = c.without_election.credit, c.with_election.credit
    c.recommend_election = c.combat_pay > 0 and b > a + 0.5
    c.gain = abs(b - a)
    if c.combat_pay <= 0:
        c.note = "No combat-zone pay this year, so there is nothing to elect."
    elif c.recommend_election:
        c.note = (f"Electing your {_money(c.combat_pay)} of combat pay into "
                  f"earned income raises the credit from {_money(a)} to "
                  f"{_money(b)}. Tick the election on Schedule EIC.")
    elif b < a:
        c.note = (f"Leave the combat pay out: electing it in would push you "
                  f"further into the phase-out and cut the credit from "
                  f"{_money(a)} to {_money(b)}.")
    else:
        c.note = "The election makes no difference to the credit this year."
    return c


# ==========================================================================
# Saver's Credit
# ==========================================================================

@dataclass
class SaversCredit:
    eligible: bool = False
    agi: float = 0.0
    rate: float = 0.0
    contributions: list = field(default_factory=list)   # per person, capped
    credit_before_limit: float = 0.0
    credit: float = 0.0                                  # after the tax limit
    ceiling: float = 0.0                                 # top AGI for any credit
    note: str = ""


def savers_credit(agi: float, status: str, contributions: list,
                  *, member_age: int, tax_available: float,
                  params: dict | None = None) -> SaversCredit:
    """
    10, 20 or 50 percent of up to $2,000 of retirement contributions per
    person, by AGI tier. Roth TSP and Roth IRA contributions count. It is
    nonrefundable, so it is limited to the tax it can offset.
    """
    p = params or SAVERS_CREDIT_2026
    status = _status(status)
    tiers = p["tiers"][status]
    s = SaversCredit(agi=agi, ceiling=float(tiers[-1][0]))
    cap = p["max_contribution_per_person"]
    s.contributions = [min(cap, max(0.0, float(c))) for c in contributions]

    if member_age < p["min_age"]:
        s.note = f"The claimant must be at least {p['min_age']}."
        return s
    for ceiling, rate in tiers:
        if agi <= ceiling:
            s.rate = rate
            break
    if s.rate == 0.0:
        s.note = (f"AGI of {_money(agi)} is above the {_money(s.ceiling)} "
                  f"ceiling for the credit.")
        return s

    s.eligible = True
    s.credit_before_limit = s.rate * sum(s.contributions)
    s.credit = min(s.credit_before_limit, max(0.0, tax_available))
    if s.credit_before_limit <= 0:
        s.note = (f"Your AGI qualifies for the {s.rate * 100:.0f}% tier but no "
                  f"contributions are recorded to apply it to.")
    elif s.credit < s.credit_before_limit:
        s.note = (f"{s.rate * 100:.0f}% of {_money(sum(s.contributions))} would be "
                  f"{_money(s.credit_before_limit)}, but the credit is "
                  f"nonrefundable and only {_money(s.credit)} of tax is there to "
                  f"offset.")
    else:
        s.note = (f"{s.rate * 100:.0f}% of {_money(sum(s.contributions))} of "
                  f"qualifying contributions. Claim it on Form 8880.")
    return s


# ==========================================================================
# Child Tax Credit
# ==========================================================================

@dataclass
class ChildCredits:
    n_children: int = 0
    n_other_dependents: int = 0
    total_after_phaseout: float = 0.0    # CTC + other-dependent credit
    nonrefundable: float = 0.0
    refundable: float = 0.0              # the Additional Child Tax Credit
    refundable_ceiling: float = 0.0
    earned_income_limit: float = 0.0     # 15% of earned income over the floor
    phaseout_reduction: float = 0.0
    note: str = ""


def child_tax_credit(n_children: int, n_other_dependents: int, agi: float,
                     status: str, *, tax_available: float,
                     earned_income_for_actc: float,
                     params: dict | None = None) -> ChildCredits:
    """
    Nonrefundable first, against whatever tax is left; the unused child portion
    then comes back as the Additional Child Tax Credit, limited to 15% of
    earned income over $2,500 and to the per-child ceiling.

    Combat pay counts as earned income here WITHOUT an election -- IRC 24(d)(1)
    says so directly -- which is why a fully deployed member with a zero box 1
    still receives the refundable credit in full.
    """
    p = params or CTC_2026
    status = _status(status)
    c = ChildCredits(n_children=max(0, int(n_children)),
                     n_other_dependents=max(0, int(n_other_dependents)))
    gross = c.n_children * p["per_child"] + c.n_other_dependents * p["other_dependent"]
    if gross <= 0:
        c.note = "No qualifying children or other dependents."
        return c

    over = max(0.0, agi - p["phaseout_start"][status])
    c.phaseout_reduction = min(gross, math.ceil(over / 1000.0) * p["phaseout_per_1000"])
    c.total_after_phaseout = gross - c.phaseout_reduction

    c.nonrefundable = min(c.total_after_phaseout, max(0.0, tax_available))
    unused = c.total_after_phaseout - c.nonrefundable
    c.refundable_ceiling = c.n_children * p["refundable_max_per_child"]
    c.earned_income_limit = p["refundable_rate"] * max(
        0.0, earned_income_for_actc - p["earned_income_floor"])
    c.refundable = max(0.0, min(unused, c.refundable_ceiling, c.earned_income_limit))

    if c.refundable > 0:
        c.note = (f"{_money(c.nonrefundable)} offsets tax; {_money(c.refundable)} "
                  f"is refunded as the Additional Child Tax Credit.")
    elif unused > 0:
        c.note = (f"{_money(unused)} of the credit goes unused: the refundable "
                  f"part is limited to 15% of earned income over "
                  f"{_money(p['earned_income_floor'])}.")
    else:
        c.note = f"The full {_money(c.total_after_phaseout)} offsets tax."
    return c


# ==========================================================================
# Withholding
# ==========================================================================

def typical_withholding(status: str, *, military_wages_full_year: float,
                        share_withheld: float, bonus_taxable: float,
                        retired_pay: float, spouse_wages: float,
                        civilian_wages: float) -> float:
    """
    What the year's withholding looks like on plain W-4s: every payer --
    DFAS, the spouse's employer, a second-career employer -- withholds as if
    its wages were the household's only income, each taking the full standard
    deduction. That is exactly why two-earner and pension-plus-wages
    households are under-withheld. Nothing is withheld on excluded combat pay,
    and bonuses are withheld at the flat supplemental rate.
    """
    status = _status(status)
    regime = F.regime_for_year(F.TaxPolicy(), TAX_YEAR, status, 0, 1)

    def one(stream: float) -> float:
        return F.bracket_tax(max(0.0, stream - regime.standard_deduction),
                             regime.ordinary_brackets)

    return (one(military_wages_full_year) * max(0.0, min(1.0, share_withheld))
            + bonus_taxable * SUPPLEMENTAL_WITHHOLDING_RATE
            + one(retired_pay) + one(spouse_wages) + one(civilian_wages))


def project_withholding(withheld_ytd: float, les_month: int) -> float:
    """Straight-line the year-to-date figure from the LES to a full year."""
    month = max(1, min(12, int(les_month or 12)))
    return max(0.0, float(withheld_ytd)) * 12.0 / month


# ==========================================================================
# The return
# ==========================================================================

@dataclass
class StateEstimate:
    state: str = ""
    rate: float = 0.0
    tax: float = 0.0
    military_pay_taxed: float = 0.0     # the part of box 1 the state reaches
    retired_pay_taxed: float = 0.0
    other_income_taxed: float = 0.0
    exempts_military_pay: bool = False
    no_income_tax: bool = False
    note: str = ""


@dataclass
class ReturnEstimate:
    year: int = TAX_YEAR
    status: str = T.SINGLE
    n_children: int = 0
    n_other_dependents: int = 0
    age: int = 0

    w2: W2Picture = field(default_factory=W2Picture)
    member_wages: float = 0.0            # box 1
    spouse_wages: float = 0.0
    civilian_wages: float = 0.0
    retired_pay: float = 0.0             # taxable, 1099-R
    va_compensation: float = 0.0         # never in AGI
    investment_income: float = 0.0

    agi: float = 0.0
    deductions: float = 0.0
    taxable_income: float = 0.0
    tax_before_credits: float = 0.0
    marginal_rate: float = 0.0

    savers: SaversCredit = field(default_factory=SaversCredit)
    child: ChildCredits = field(default_factory=ChildCredits)
    eitc: EITCComparison = field(default_factory=EITCComparison)

    nonrefundable_credits: float = 0.0
    tax_after_credits: float = 0.0
    refundable_credits: float = 0.0

    withheld_ytd: float = 0.0
    les_month: int = 12
    withholding_projected: float = 0.0
    typical_withholding: float = 0.0
    withholding_is_estimate: bool = False
    refund: float = 0.0                  # positive = refund, negative = balance due

    state: StateEstimate = field(default_factory=StateEstimate)
    findings: list = field(default_factory=list)

    @property
    def earned_income_taxable(self) -> float:
        return self.member_wages + self.spouse_wages + self.civilian_wages

    @property
    def total_compensation(self) -> float:
        """Everything the household actually receives, taxed or not."""
        return (self.w2.gross + self.spouse_wages + self.civilian_wages
                + self.retired_pay + self.va_compensation + self.investment_income)

    @property
    def received(self) -> float:
        """
        What the MEMBER is paid, in cash, before anyone divides it up: military
        pay and allowances, retired pay, VA compensation and a second career.
        The spouse's wages are their own W-2 and are left out of the picture.
        """
        return (self.w2.gross + self.retired_pay + self.va_compensation
                + self.civilian_wages)

    @property
    def taxed(self) -> float:
        """The part of that which reaches a tax return."""
        return self.member_wages + self.retired_pay + self.civilian_wages

    @property
    def never_on_the_w2(self) -> float:
        return max(0.0, self.received - self.taxed)

    def picture_rows(self) -> list[dict]:
        """
        Tidy rows for the compensation chart: every dollar the member is paid,
        labelled by how the tax code treats it. The amounts sum to `received`,
        and the rows marked "Taxed" sum to `taxed`, so the chart cannot drift
        from the return below it.
        """
        rows = list(self.w2.rows())
        if self.civilian_wages > 0.5:
            rows.insert(0, {"Component": "Civilian wages",
                            "Amount": self.civilian_wages, "Treatment": "Taxed"})
        if self.retired_pay > 0.5:
            rows.insert(0, {"Component": "Retired pay (1099-R)",
                            "Amount": self.retired_pay, "Treatment": "Taxed"})
        if self.va_compensation > 0.5:
            rows.append({"Component": "VA compensation",
                         "Amount": self.va_compensation,
                         "Treatment": "Never taxed"})
        return rows

    def lines(self) -> list[tuple[str, float]]:
        """The return, line by line, in Form 1040 order."""
        out = [("Wages (box 1)", self.member_wages)]
        if self.spouse_wages:
            out.append(("Spouse wages", self.spouse_wages))
        if self.civilian_wages:
            out.append(("Civilian wages", self.civilian_wages))
        if self.retired_pay:
            out.append(("Military retired pay (1099-R)", self.retired_pay))
        if self.investment_income:
            out.append(("Interest, dividends and gains", self.investment_income))
        out += [
            ("Adjusted gross income", self.agi),
            ("Standard deduction", -self.deductions),
            ("Taxable income", self.taxable_income),
            ("Tax", self.tax_before_credits),
        ]
        if self.savers.credit:
            out.append(("Saver's Credit", -self.savers.credit))
        if self.child.nonrefundable:
            out.append(("Child Tax Credit (nonrefundable)", -self.child.nonrefundable))
        out.append(("Tax after credits", self.tax_after_credits))
        out.append(("Federal tax withheld (projected)", self.withholding_projected))
        if self.child.refundable:
            out.append(("Additional Child Tax Credit", self.child.refundable))
        if self.eitc.credit:
            out.append(("Earned Income Credit", self.eitc.credit))
        out.append(("Refund" if self.refund >= 0 else "Balance due", abs(self.refund)))
        return out


def _state_estimate(h: Household, est: ReturnEstimate) -> StateEstimate:
    """The state of legal residence, through engine/tax/state.py."""
    name = h.state_of_legal_residence or ""
    rule = ST.get_rule(name)
    prof = D.profile(name)
    s = StateEstimate(state=name, rate=prof.rate,
                      no_income_tax=prof.rate <= 0,
                      exempts_military_pay=(prof.rate <= 0
                                            or prof.active_duty_exempt_share >= 1.0))
    s.military_pay_taxed = est.member_wages * (1.0 - prof.active_duty_exempt_share)
    s.retired_pay_taxed = est.retired_pay * (1.0 - prof.retired_pay_exempt_share)
    s.other_income_taxed = est.spouse_wages + est.civilian_wages + est.investment_income
    s.tax = ST.state_tax(rule, est.age, est.retired_pay, 0.0,
                         s.military_pay_taxed + s.other_income_taxed, 0.0, 0.0)
    if s.no_income_tax:
        s.note = f"{name} has no income tax."
    elif prof.active_duty_exempt_share >= 1.0 and est.member_wages > 0:
        s.note = (f"{name} exempts active-duty pay but taxes everything else at "
                  f"{prof.rate * 100:.2f}%.")
    elif prof.note:
        s.note = prof.note
    if s.tax > 0 and not s.no_income_tax:
        s.note += (" This is an effective-rate estimate with no state standard "
                   "deduction or credits, so it runs high for a low income.")
    return s


def estimate(h: Household, *, status: str | None = None,
             n_children: int | None = None, spouse_wages: float | None = None,
             withheld_ytd: float | None = None, les_month: int = 12,
             investment_income: float = 0.0, bonus_paid_in_zone: bool = False,
             czte_months: int | None = None, bah_data=None) -> ReturnEstimate:
    """
    This year's federal return for the household.

    `withheld_ytd` is the TAX YTD figure from the FED TAXES block of the LES
    (plus any spouse withholding), and `les_month` the month that LES covers;
    None means "assume plain-W-4 withholding for the year". Everything else
    comes from the profile unless overridden.
    """
    m = h.member
    est = ReturnEstimate()
    est.status = _status(status or filing_status_for(h))
    est.n_children = max(0, int(h.n_dependents if n_children is None else n_children))
    est.n_other_dependents = max(0, int(h.n_dependents) - est.n_children)
    est.age = m.age(TAX_YEAR)

    est.w2 = w2_picture(m, bonus_paid_in_zone=bonus_paid_in_zone,
                        czte_months=czte_months, bah_data=bah_data)
    est.member_wages = est.w2.box1
    est.spouse_wages = max(0.0, float(spouse_wages_for(h) if spouse_wages is None
                                      else spouse_wages))
    if est.status != T.MFJ:
        est.spouse_wages = 0.0
    est.civilian_wages = max(0.0, float(m.civilian_wages_annual))
    est.retired_pay = TX.annual_retired_pay(m)
    est.va_compensation = float(m.va_disability_monthly) * 12.0 + float(m.crsc_monthly) * 12.0
    est.investment_income = max(0.0, float(investment_income))

    # Federal core: brackets and deduction from the projection engine.
    n65 = int(est.age >= 65)
    if h.has_spouse and h.spouse is not None and h.spouse.age(TAX_YEAR) >= 65:
        n65 += 1
    n_people = 2 if est.status == T.MFJ else 1
    regime = F.regime_for_year(F.TaxPolicy(), TAX_YEAR, est.status, n65, n_people)
    est.state = _state_estimate(h, est)
    core = F.compute_year_tax(
        regime=regime, status=est.status,
        wages=est.member_wages + est.spouse_wages + est.civilian_wages,
        military_pension=est.retired_pay, other_pension=0.0,
        taxable_withdrawals=0.0, conversion=0.0, social_security=0.0,
        interest_and_nonqual_div=est.investment_income, qualified_dividends=0.0,
        capital_gains=0.0, tax_exempt_interest=0.0, n_people_65plus=n65,
        ss_deflator=1.0, niit_deflator=1.0, index_niit=False,
        state_tax_amount=est.state.tax, irmaa_amount=0.0)
    est.agi = core.agi
    est.deductions = core.deductions
    est.taxable_income = core.taxable_income
    est.tax_before_credits = core.federal_total
    est.marginal_rate = core.marginal_rate

    # Credits, in Form 1040 order: the Saver's Credit is taken before the
    # child credit, which pushes more of the child credit into its refundable
    # form -- so a "nonrefundable" credit still ends up in the refund.
    contributions = [est.w2.tsp_total + float(m.ira_contributed_this_year)]
    if est.status == T.MFJ:
        contributions.append(float(h.spouse_income.retirement_contribution_pct)
                             * est.spouse_wages)
    est.savers = savers_credit(est.agi, est.status, contributions,
                               member_age=est.age,
                               tax_available=est.tax_before_credits)
    remaining = est.tax_before_credits - est.savers.credit
    est.child = child_tax_credit(
        est.n_children, est.n_other_dependents, est.agi, est.status,
        tax_available=remaining,
        earned_income_for_actc=est.earned_income_taxable + est.w2.combat_pay)
    remaining -= est.child.nonrefundable
    est.nonrefundable_credits = est.savers.credit + est.child.nonrefundable
    est.tax_after_credits = max(0.0, remaining)

    est.eitc = eitc_both_ways(est.earned_income_taxable, est.w2.combat_pay,
                              est.agi, est.n_children, est.status,
                              investment_income=est.investment_income, age=est.age)
    est.refundable_credits = est.child.refundable + est.eitc.credit

    # Withholding.
    # The share of regular military pay that stayed taxable, and so had tax
    # withheld from it. The bonus is withheld separately at the flat
    # supplemental rate, so it belongs in neither half of this fraction.
    regular = est.w2.basic_pay + est.w2.special_pay_taxable
    still_taxed = (est.w2.box1 + est.w2.tsp_traditional_box1_reduction
                   - est.w2.bonus + est.w2.bonus_excluded)
    share = (still_taxed / regular) if regular > 0 else 0.0
    est.typical_withholding = typical_withholding(
        est.status,
        military_wages_full_year=(est.w2.basic_pay + est.w2.special_pay_taxable
                                  - est.w2.tsp_traditional),
        share_withheld=share,
        bonus_taxable=est.w2.bonus - est.w2.bonus_excluded,
        retired_pay=est.retired_pay, spouse_wages=est.spouse_wages,
        civilian_wages=est.civilian_wages)
    est.les_month = max(1, min(12, int(les_month or 12)))
    if withheld_ytd is None:
        est.withholding_is_estimate = True
        est.withholding_projected = est.typical_withholding
        est.withheld_ytd = est.typical_withholding * est.les_month / 12.0
    else:
        est.withheld_ytd = max(0.0, float(withheld_ytd))
        est.withholding_projected = project_withholding(est.withheld_ytd, est.les_month)

    est.refund = (est.withholding_projected + est.refundable_credits
                  - est.tax_after_credits)
    est.findings = findings(h, est)
    return est


# ==========================================================================
# Findings, ordered by what they are worth
# ==========================================================================

def findings(h: Household, est: ReturnEstimate) -> list[tuple[str, str, str]]:
    """(severity, headline, detail), largest dollars first."""
    out: list[tuple[float, str, str, str]] = []
    w = est.w2
    k = est.n_children

    # --- EITC ---------------------------------------------------------
    e = est.eitc
    if e.credit > 0:
        excluded = ["BAH", "BAS"] if w.serving else []
        if w.combat_pay > 0 and not e.recommend_election:
            excluded.append("combat-zone pay")
        out.append((e.credit, "good",
                    f"You qualify for the Earned Income Tax Credit: about "
                    f"{_money(e.credit)}.",
                    f"Your household actually receives about "
                    f"{_money(est.total_compensation)} this year, but earned "
                    f"income for the credit is {_money(e.best.earned_income)} and "
                    f"AGI is {_money(est.agi)}"
                    + (f" — {', '.join(excluded)} never enter it." if excluded else ".")
                    + f" {e.best.reason} The credit is refundable: you receive it "
                    f"even with no tax to offset. Claim it on Schedule EIC; "
                    f"free VITA preparers on most installations know this rule."))
    elif k > 0 or (EITC_2026["childless_min_age"] <= est.age
                   <= EITC_2026["childless_max_age"]):
        limit = completed_phaseout(k, est.status)
        gap = max(est.agi, e.best.earned_income) - limit
        out.append((0.0, "info",
                    "No Earned Income Credit this year.",
                    f"{e.best.reason} You are about {_money(max(0.0, gap))} over "
                    f"the {_money(limit)} limit for "
                    f"{'no children' if k == 0 else (str(k) + ' child' + ('ren' if k > 1 else ''))}. "
                    f"BAH and BAS never count, and pay earned in a combat zone "
                    f"is excluded, so a deployment year can bring it within reach."))

    # --- Combat-pay election ------------------------------------------
    if w.combat_pay > 0:
        if e.recommend_election:
            out.append((e.gain, "good",
                        f"Elect to count your combat pay for the EITC: worth "
                        f"{_money(e.gain)}.",
                        f"{e.note} IRC 32(c)(2)(B)(vi) lets you include "
                        f"nontaxable combat pay (W-2 box 12, code Q) in earned "
                        f"income for this credit only. It is all or nothing, and "
                        f"it does not touch your AGI or your tax."))
        elif e.gain > 0:
            out.append((e.gain, "warn",
                        f"Do NOT elect your combat pay into the EITC: it would "
                        f"cost {_money(e.gain)}.",
                        f"{e.note} Tax software asks this question in passing; "
                        f"answered wrongly it is the most expensive checkbox on a "
                        f"deployed member's return."))
        else:
            out.append((0.0, "info", "The combat-pay election changes nothing this year.",
                        e.note))

    # --- Saver's Credit -----------------------------------------------
    s = est.savers
    if s.credit > 0:
        out.append((s.credit, "good",
                    f"Claim the Saver's Credit: {_money(s.credit)} for retirement "
                    f"contributions you are already making.",
                    f"{s.note} Roth TSP and Roth IRA contributions qualify, and "
                    f"the credit sits on top of the tax-free growth. It is claimed "
                    f"by a small fraction of those eligible, largely because "
                    f"nobody asks. {SAVERS_CREDIT_2026['last_year_as_credit']} is "
                    f"its last year as a credit: from 2027 it becomes the Saver's "
                    f"Match, paid into your account instead."))
    elif s.eligible and s.credit_before_limit <= 0:
        potential = s.rate * SAVERS_CREDIT_2026["max_contribution_per_person"]
        out.append((potential, "warn",
                    f"Your AGI qualifies for the {s.rate * 100:.0f}% Saver's Credit "
                    f"but nothing is being contributed to claim it.",
                    f"Up to {_money(potential)} back on the first "
                    f"{_money(SAVERS_CREDIT_2026['max_contribution_per_person'])} "
                    f"you put into the TSP or an IRA this year. Set a TSP "
                    f"contribution on the Deployment page."))
    elif s.eligible and s.credit < s.credit_before_limit:
        out.append((s.credit_before_limit - s.credit, "info",
                    "The Saver's Credit is nonrefundable, and you have little tax "
                    "left for it to offset.",
                    f"{s.note} There is nothing to fix here: a return with no tax "
                    f"is the point. The credit simply has nothing to work on."))

    # --- Child Tax Credit ---------------------------------------------
    c = est.child
    if c.refundable > 0:
        out.append((c.refundable, "good",
                    f"{_money(c.refundable)} of your Child Tax Credit comes back as "
                    f"a refund even with no tax to offset.",
                    f"{c.note} The refundable part is 15% of earned income over "
                    f"{_money(CTC_2026['earned_income_floor'])}, up to "
                    f"{_money(CTC_2026['refundable_max_per_child'])} per child — "
                    f"and combat-zone pay counts as earned income here "
                    f"automatically, no election needed, so a fully deployed "
                    f"member with a zero box 1 still receives it."))
    elif c.total_after_phaseout > 0:
        out.append((c.nonrefundable, "good",
                    f"Your {_money(c.total_after_phaseout)} Child Tax Credit offsets "
                    f"{_money(c.nonrefundable)} of tax.",
                    c.note))

    # --- State ---------------------------------------------------------
    st_ = est.state
    duty = D.profile(h.current_state or "")
    if st_.no_income_tax:
        avoided = 0.0
        if (h.current_state or "").strip().lower() != (st_.state or "").strip().lower():
            avoided = (est.member_wages * (1.0 - duty.active_duty_exempt_share)
                       + est.retired_pay * (1.0 - duty.retired_pay_exempt_share)) * duty.rate
        out.append((avoided, "good",
                    f"{st_.state} has no income tax, so none of this is taxed "
                    f"again by a state."
                    + (f" That is about {_money(avoided)} a {h.current_state} "
                       f"resident on the same pay would owe." if avoided > 0 else ""),
                    "Under SCRA your military pay is taxed only by your state of "
                    "legal residence, wherever you are stationed. Keep the "
                    "domicile genuine: licence, voting, DD Form 2058."))
    elif st_.exempts_military_pay and (est.member_wages > 0 or est.retired_pay > 0):
        out.append((st_.tax, "warn" if st_.tax > 0 else "good",
                    f"{st_.state} exempts your military pay but taxes the rest of "
                    f"the household at {st_.rate * 100:.2f}%: about {_money(st_.tax)}.",
                    f"{st_.note} A spouse's salary or a second career is taxed in "
                    f"full where a no-income-tax state would take nothing — the "
                    f"difference between the two kinds of 'military-friendly' "
                    f"state. See Residency & GI Bill."))
    elif st_.tax > 0:
        n_free = len(D.NO_TAX_STATES) + len(D.exempt_but_taxing_states())
        out.append((st_.tax, "warn",
                    f"{st_.state} taxes your military income: about "
                    f"{_money(st_.tax)} in state tax this year.",
                    f"{st_.note} {n_free} states would take nothing on military "
                    f"pay. Domicile cannot simply be chosen — it is established at "
                    f"a genuine PCS — but it is worth knowing what it costs. See "
                    f"Residency & GI Bill."))

    # --- Spouse residency election ------------------------------------
    if (est.status == T.MFJ and est.spouse_wages > 0 and h.current_state
            and (h.current_state or "").strip().lower()
            != (st_.state or "").strip().lower()
            and duty.rate > st_.rate):
        gain = est.spouse_wages * (duty.rate - st_.rate)
        out.append((gain, "good",
                    f"Your spouse can elect {st_.state} for state tax too: worth "
                    f"about {_money(gain)} against {h.current_state}.",
                    f"The Veterans Auto and Education Improvement Act of 2022 lets "
                    f"a couple elect, each tax year, the member's state of legal "
                    f"residence for the spouse's income. On {_money(est.spouse_wages)} "
                    f"of wages that is the difference between {h.current_state}'s "
                    f"{duty.rate * 100:.2f}% and {st_.state}'s "
                    f"{st_.rate * 100:.2f}%. Their employer may still withhold "
                    f"{h.current_state} tax; the election is made on the return."))

    # --- Withholding ---------------------------------------------------
    over = est.withholding_projected - est.tax_after_credits
    if est.refund < 0:
        out.append((-est.refund, "bad",
                    f"You are on track to OWE about {_money(-est.refund)} in April.",
                    f"About {_money(est.withholding_projected)} withheld against "
                    f"{_money(est.tax_after_credits)} of tax after credits. Every "
                    f"payer — DFAS, a spouse's employer, a second career — "
                    f"withholds as if its cheque were your only income, each "
                    f"taking the whole standard deduction. Fix it in myPay with a "
                    f"new W-4: Step 2 for a second earner, or an extra amount on "
                    f"line 4(c)."))
    else:
        detail = (f"About {_money(est.withholding_projected)} withheld against "
                  f"{_money(est.tax_after_credits)} of tax after credits, plus "
                  f"{_money(est.refundable_credits)} of refundable credits.")
        if over > 1_000:
            detail += (f" {_money(over)} of that refund is your own money lent "
                       f"to the Treasury at 0%: a W-4 adjustment in myPay would "
                       f"put it in your pay each month instead.")
        elif est.refundable_credits > 0:
            detail += (" The refund is mostly refundable credits, not "
                       "over-withholding — there is nothing to adjust.")
        out.append((max(0.0, over), "info",
                    f"Expect a refund of about {_money(est.refund)}.", detail))
    if est.withholding_is_estimate:
        out.append((0.0, "info",
                    "Withholding is estimated from plain W-4 settings.",
                    "Enter the TAX YTD figure from the FED TAXES block of your "
                    "LES, and the month it covers, to replace the estimate."))
    if w.czte_months > 0 and not est.withholding_is_estimate:
        out.append((0.0, "info",
                    "Nothing is withheld in combat-zone months, so the straight-"
                    "line projection can drift.",
                    "If the deployment is behind you, withholding restarts and the "
                    "year's total will run higher than projected; if it is ahead, "
                    "lower. Re-check after your first LES back."))

    # --- Filing status --------------------------------------------------
    if est.status == T.SINGLE and k > 0:
        out.append((0.0, "info",
                    "You may qualify to file as head of household.",
                    "An unmarried member who pays more than half the cost of a "
                    "home for a qualifying child gets a larger standard deduction "
                    "and wider brackets than Single. This page models Single, so "
                    "it overstates your tax."))

    out.sort(key=lambda t: -t[0])
    return [(sev, head, detail) for _, sev, head, detail in out]
