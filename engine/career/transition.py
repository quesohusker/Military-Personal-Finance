"""
Leaving the service the ordinary way: the last twelve months in, and the first
twelve out.

The medical-board page covers the involuntary, catastrophic exit. This module
covers the one almost everybody actually takes -- an ETS date, or twenty years
and a retirement ceremony -- where nothing goes wrong and money is still lost
in five predictable places:

  1. LEAVE. Sold leave pays BASIC PAY ONLY. No BAH, no BAS, and it is taxable
     as ordinary income. The same day taken as terminal leave is paid at full
     compensation -- basic pay plus both allowances, with the allowances
     untaxed -- and it is a day you are free to start a civilian job while
     still on the military payroll. The sell-back cap is a CAREER cap of 60
     days, not an annual one: days sold at a re-enlistment ten years ago are
     gone from the balance for good.

  2. THE CASH-FLOW GAP. Military pay stops on the separation date. The final
     settlement -- sold leave, travel, adjustments -- arrives weeks later, and
     the first retired pay typically 30 to 60 days after that. A member who
     budgets to the day of separation meets a hole they did not plan for, and
     fills it with a credit card at 22%.

  3. VA TIMING. Retired pay starts the month after retirement. VA compensation
     starts only after the rating decision. Filing BDD -- Benefits Delivery at
     Discharge -- in the window 180 to 90 days before separation gets the
     rating decided at or near day one. Miss the window and the wait is months
     of no VA payment at all. The entitlement survives (a claim filed within a
     year of separation is effective the day after separation, and the arrears
     are paid as a lump), but the CASH does not arrive on time, and that is
     what breaks a budget.

  4. THE TSP LOAN. An outstanding loan at separation must be repaid or it is
     declared a taxable distribution -- income tax on the balance plus the 10%
     early-withdrawal penalty under 59 1/2. The escape hatch people miss is the
     rule of 55: separate in or after the calendar year you turn 55 and the
     penalty does not apply to that plan at all.

  5. THE FINAL MOVE. A retiree has up to three years to take a
     government-funded move to a home of selection. A separatee has 180 days,
     extendable in some cases to a year, and to a more limited destination.
     Letting it lapse spends five figures of your own money on a move the
     government would have paid for.

PROVENANCE. Every rule-of-thumb interval and dollar figure lives in FIGURES,
with a VERIFY note beside it. This module cannot reach dfas.mil, va.gov or the
JTR, so the entries are from memory of the published rules and are planning
estimates, not tariffs. Correct them in one place and every page follows.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date, timedelta
import calendar

from engine.profile import Household, ServiceMember, RETIRED
from engine.coach import prime_directive as PD
from engine.pay import bah as BAH
from engine.pay import bas as BAS
from engine.pay import grades as G
from engine.benefits import life_insurance as LI
from engine.retirement import systems as RS

# ==========================================================================
# Figures. ONE place, each with a VERIFY note below.
# ==========================================================================
FIGURES = {
    # ---- Leave -------------------------------------------------------
    "days_in_pay_month": 30,             # a leave day is 1/30 of monthly pay
    "sellback_career_cap_days": 60.0,    # career, not annual
    "leave_accrual_days_per_month": 2.5,
    "supplemental_withholding": 0.22,    # flat federal rate on a lump payment

    # ---- Final pay timing, days after the separation date -------------
    "final_settlement_days_low": 14,
    "final_settlement_days_high": 45,
    "first_retired_pay_days_low": 30,
    "first_retired_pay_days_high": 60,

    # ---- VA ------------------------------------------------------------
    "bdd_window_open_days": 180,         # earliest you may file BDD
    "bdd_window_close_days": 90,         # latest you may file BDD
    "bdd_months_to_first_payment": 1,    # decided at or near separation
    "claim_months_to_decision": 5,       # a standard post-service claim
    "retro_filing_window_months": 12,    # file inside this and it back-dates

    # ---- Health cover ---------------------------------------------------
    "tamp_days": 180,                    # involuntary separations only
    "chcbp_enroll_days": 60,
    "chcbp_max_months": 18,

    # ---- Unemployment ---------------------------------------------------
    "ucx_typical_weeks": 26,

    # ---- The final move -------------------------------------------------
    "final_move_retiree_years": 3,
    "final_move_separatee_days": 180,
    "final_move_separatee_max_days": 365,
    "final_move_typical_value": 12_000.0,   # a CONUS household-goods move

    # ---- TSP -------------------------------------------------------------
    "tsp_early_withdrawal_penalty": 0.10,
    "rule_of_55_age": 55,
    "penalty_free_age": 59.5,
    "tsp_loan_notice_days": 90,
}

VERIFY = {
    "sellback_career_cap_days":
        "VERIFY at dfas.mil / 37 U.S.C. 501: 60 days of leave may be sold in a "
        "career, and the temporary wartime increase has expired. Confidence "
        "HIGH on the cap, MEDIUM on any service-specific exception.",
    "days_in_pay_month":
        "VERIFY: a day of leave is paid at 1/30 of monthly basic pay, the same "
        "divisor a drill period uses. Confidence HIGH.",
    "supplemental_withholding":
        "VERIFY at irs.gov Pub 15: the flat supplemental wage withholding rate. "
        "This is WITHHOLDING, not your tax; the return settles it. Confidence "
        "HIGH, but the member's own marginal rate is the better input.",
    "final_settlement_days_low":
        "VERIFY at dfas.mil: the final separation settlement typically lands two "
        "to six weeks after separation. Confidence MEDIUM — it varies by branch "
        "and by how clean the out-processing was.",
    "first_retired_pay_days_low":
        "VERIFY at dfas.mil: retired pay is payable from the month after "
        "retirement, but establishing the account typically takes 30 to 60 days. "
        "Arrears are paid. Confidence MEDIUM on the interval, HIGH on the "
        "entitlement date.",
    "bdd_window_open_days":
        "VERIFY at va.gov: Benefits Delivery at Discharge accepts claims from a "
        "member with 180 to 90 days left on active duty who is available for VA "
        "examinations before separation. Confidence HIGH.",
    "claim_months_to_decision":
        "VERIFY at va.gov: the VA publishes average days to complete a "
        "disability claim, which has run around four to six months. Confidence "
        "LOW — it moves, and an individual claim can be much slower.",
    "retro_filing_window_months":
        "VERIFY at 38 CFR 3.400(b)(2): a claim received within one year of "
        "separation is effective the day after separation, so the wait is paid "
        "in arrears. Confidence HIGH.",
    "tamp_days":
        "VERIFY at tricare.mil: the Transitional Assistance Management Program "
        "gives 180 days of premium-free TRICARE after qualifying INVOLUNTARY "
        "separations. Confidence HIGH on the length, MEDIUM on the full list of "
        "qualifying separations.",
    "chcbp_enroll_days":
        "VERIFY at tricare.mil: CHCBP must be elected within 60 days of losing "
        "TRICARE and runs up to 18 months. It is premium-based and the premium "
        "is substantial. Confidence HIGH on the windows.",
    "ucx_typical_weeks":
        "VERIFY with the state workforce agency: UCX is administered by the "
        "states, so eligibility, the weekly amount, the duration and any offset "
        "for retired pay are all state law. Confidence LOW on any national "
        "figure — this is why the module refuses to quote one.",
    "final_move_retiree_years":
        "VERIFY in the JTR: a retiree generally has three years to complete a "
        "government-funded move to a home of selection; a separatee generally "
        "180 days, extendable. Confidence MEDIUM.",
    "final_move_typical_value":
        "A PLANNING ESTIMATE for a CONUS household-goods move plus travel, not "
        "a quote. An OCONUS move is far more. Replace it with your own number.",
    "rule_of_55_age":
        "VERIFY at IRC 72(t)(2)(A)(v) and tsp.gov: separation from service in or "
        "after the calendar year you reach 55 exempts distributions from THAT "
        "plan from the 10% penalty. Confidence HIGH.",
    "tsp_loan_notice_days":
        "VERIFY at tsp.gov: after separation the TSP sends a notice and gives a "
        "deadline to repay the loan in full before it is declared a taxable "
        "distribution. Confidence MEDIUM on the exact interval.",
}

DAYS_IN_PAY_MONTH = FIGURES["days_in_pay_month"]
SELLBACK_CAREER_CAP_DAYS = FIGURES["sellback_career_cap_days"]

# The three ways to dispose of a leave balance.
TAKE = "Take it as terminal leave"
SELL = "Sell it back"
HYBRID = "Sell to the cap, take the rest"
LEAVE_CHOICES = [TAKE, SELL, HYBRID]

RETIRING = "Retiring"
SEPARATING = "Separating"
EXIT_KINDS = [RETIRING, SEPARATING]


# ==========================================================================
# Pay components
# ==========================================================================

def pay_components(m: ServiceMember, bah_data=None,
                   basepay_table=None) -> tuple[float, float, float]:
    """
    (basic, BAH, BAS) monthly, resolved the same way every other page does it:
    the LES override wins, then the published table.
    """
    basic = PD.monthly_basic_pay(m)

    if m.lives_in_government_housing:
        bah = 0.0
    elif m.bah_monthly_override > 0:
        bah = float(m.bah_monthly_override)
    else:
        data = bah_data if bah_data is not None else BAH.load()
        r = BAH.lookup(m.duty_zip, m.grade, m.has_dependents, data)
        bah = r.monthly if r.found else 0.0

    if m.bas_monthly_override > 0:
        bas = float(m.bas_monthly_override)
    else:
        try:
            officer = G.is_officer(G.get(m.grade))
        except KeyError:
            officer = False
        bas = BAS.bas_monthly(officer).monthly

    return float(basic), float(bah), float(bas)


# ==========================================================================
# Leave: sell it, take it, or both
# ==========================================================================

def daily_basic(basic_monthly: float) -> float:
    """A day of leave is one thirtieth of monthly BASIC pay. Nothing else."""
    return max(0.0, basic_monthly) / DAYS_IN_PAY_MONTH


def daily_allowances(bah_monthly: float, bas_monthly: float) -> float:
    return (max(0.0, bah_monthly) + max(0.0, bas_monthly)) / DAYS_IN_PAY_MONTH


def sell_leave_value(days: float, basic_monthly: float) -> float:
    """
    What selling `days` pays, gross.

    BASIC PAY ONLY. This is the single most misunderstood number in a
    transition brief: people budget the sale at their full LES gross and are
    short by the allowances.
    """
    return max(0.0, days) * daily_basic(basic_monthly)


def terminal_leave_value(days: float, basic_monthly: float, bah_monthly: float,
                         bas_monthly: float) -> float:
    """What the same days are worth taken as terminal leave: everything."""
    return max(0.0, days) * (daily_basic(basic_monthly)
                             + daily_allowances(bah_monthly, bas_monthly))


def sellback_cap_remaining(days_already_sold: float = 0.0) -> float:
    return max(0.0, SELLBACK_CAREER_CAP_DAYS - max(0.0, days_already_sold))


@dataclass
class LeaveOption:
    label: str = ""
    days_sold: float = 0.0
    days_taken: float = 0.0
    sold_gross: float = 0.0          # basic pay only, taxable
    terminal_basic: float = 0.0      # basic pay for the days taken, taxable
    terminal_allowances: float = 0.0  # BAH + BAS for those days, untaxed
    tax: float = 0.0
    marginal_rate: float = 0.0
    note: str = ""

    @property
    def taxable(self) -> float:
        return self.sold_gross + self.terminal_basic

    @property
    def gross(self) -> float:
        return self.sold_gross + self.terminal_basic + self.terminal_allowances

    @property
    def after_tax(self) -> float:
        return self.gross - self.tax

    @property
    def cash_at_separation(self) -> float:
        """The lump the settlement actually pays. Terminal leave pays none."""
        return self.sold_gross * (1.0 - self.marginal_rate)


@dataclass
class LeaveComparison:
    days: float = 0.0
    days_already_sold: float = 0.0
    cap_remaining: float = 0.0
    cap_binds: bool = False
    days_over_cap: float = 0.0
    basic_daily: float = 0.0
    allowance_daily: float = 0.0
    marginal_rate: float = 0.0

    take: LeaveOption = field(default_factory=LeaveOption)
    sell: LeaveOption = field(default_factory=LeaveOption)
    hybrid: LeaveOption = field(default_factory=LeaveOption)

    advantage_of_taking: float = 0.0     # after tax, taking minus selling
    notes: list = field(default_factory=list)

    @property
    def options(self) -> list:
        return [self.take, self.sell, self.hybrid]

    @property
    def best(self) -> LeaveOption:
        return max(self.options, key=lambda o: o.after_tax)

    def option(self, label: str) -> LeaveOption:
        return next((o for o in self.options if o.label == label), self.take)


def compare_leave(days: float, basic_monthly: float, bah_monthly: float,
                  bas_monthly: float, days_already_sold: float = 0.0,
                  marginal_rate: float | None = None) -> LeaveComparison:
    """
    The three ways to dispose of a leave balance, in dollars.

    THE FRAME, stated plainly because it decides the answer: the separation
    date is the same under all three. Terminal leave does not extend it -- it
    is the last stretch of it, paid at full compensation. So a day taken is
    worth basic pay plus both allowances; the same day sold is worth basic pay
    alone, and is taxed. Selling is the only option that produces a LUMP, which
    is why it looks bigger on a bank statement and is smaller in fact.
    """
    rate = (FIGURES["supplemental_withholding"] if marginal_rate is None
            else max(0.0, min(0.9, marginal_rate)))
    days = max(0.0, days)
    cap = sellback_cap_remaining(days_already_sold)
    sellable = min(days, cap)

    c = LeaveComparison(days=days, days_already_sold=max(0.0, days_already_sold),
                        cap_remaining=cap, cap_binds=days > cap + 1e-9,
                        days_over_cap=max(0.0, days - cap),
                        basic_daily=daily_basic(basic_monthly),
                        allowance_daily=daily_allowances(bah_monthly, bas_monthly),
                        marginal_rate=rate)

    def build(label: str, sold: float, taken: float) -> LeaveOption:
        o = LeaveOption(label=label, days_sold=sold, days_taken=taken,
                        sold_gross=sell_leave_value(sold, basic_monthly),
                        terminal_basic=taken * c.basic_daily,
                        terminal_allowances=taken * c.allowance_daily,
                        marginal_rate=rate)
        o.tax = o.taxable * rate
        return o

    c.take = build(TAKE, 0.0, days)
    c.sell = build(SELL, sellable, days - sellable)
    c.hybrid = build(HYBRID, sellable, days - sellable)

    c.take.note = ("Full pay and both allowances for every day, and the "
                   "allowances are untaxed. You are on the rolls the whole "
                   "time, so TRICARE, the commissary and leave accrual all "
                   "continue — and nothing stops you starting a civilian job "
                   "during it.")
    c.sell.note = ("Basic pay only, at one thirtieth of the monthly rate a day, "
                   "and taxable. You work the days you would otherwise have "
                   "been on leave for.")
    c.hybrid.note = ("Sell up to the career cap, take the rest. With a balance "
                     "at or under the cap this is the same thing as selling.")

    c.advantage_of_taking = c.take.after_tax - c.sell.after_tax

    if c.cap_binds:
        c.notes.append(
            f"The 60-day career cap binds. You have {days:,.0f} days and only "
            f"{cap:,.0f} may be sold, so {c.days_over_cap:,.0f} days must be "
            f"taken as leave or lost. Days sold earlier in your career count "
            f"against the same 60 — check your record before you plan on it.")
    if c.allowance_daily > 0:
        c.notes.append(
            f"Every day taken rather than sold is worth "
            f"${c.allowance_daily:,.0f} more, because BAH and BAS are paid on "
            f"leave and are not paid on a sell-back. Over {days:,.0f} days that "
            f"is ${c.advantage_of_taking:,.0f}.")
    else:
        c.notes.append(
            "No BAH or BAS is showing for you — in government quarters, or the "
            "duty ZIP is not set. If you do draw allowances, taking leave is "
            "worth more than this page shows.")
    c.notes.append(
        f"Selling is the only option that pays a LUMP: about "
        f"${c.sell.cash_at_separation:,.0f} after withholding, and it arrives "
        f"with the final settlement rather than on your last day. Terminal "
        f"leave pays no lump — it pays your ordinary cheque, for days you do "
        f"not work. If you line a civilian start date up inside terminal leave "
        f"you draw both salaries at once, which no sell-back can match.")
    return c


# ==========================================================================
# VA timing: the BDD window, and what missing it costs
# ==========================================================================

@dataclass
class VATiming:
    expected_monthly: float = 0.0
    filed_bdd: bool = False
    days_until_separation: int | None = None
    window_opens_in_days: int | None = None
    in_window: bool = False
    too_early: bool = False
    too_late: bool = False
    months_to_first_payment: float = 0.0
    gap_months: float = 0.0
    gap_dollars: float = 0.0
    back_pay: float = 0.0
    notes: list = field(default_factory=list)


def va_timing(expected_monthly: float, filed_bdd: bool = False,
              days_until_separation: int | None = None,
              months_to_decision: float | None = None) -> VATiming:
    """
    When the first VA payment lands, and what the wait costs in cash.

    Retired pay starts the month after retirement whatever happens. VA
    compensation starts only when the rating decision is signed, and that is
    the piece the member controls: file BDD inside the 180-to-90-day window and
    the decision is ready at or near separation.

    The gap is a CASH-FLOW cost, not a forfeiture: file within a year of
    separation and the effective date is the day after separation, so the
    months are paid in arrears eventually. Eventually does not pay the rent.
    """
    monthly = max(0.0, expected_monthly)
    open_at = FIGURES["bdd_window_open_days"]
    close_at = FIGURES["bdd_window_close_days"]

    if months_to_decision is None:
        months = (FIGURES["bdd_months_to_first_payment"] if filed_bdd
                  else FIGURES["claim_months_to_decision"])
    else:
        months = max(0.0, months_to_decision)

    v = VATiming(expected_monthly=monthly, filed_bdd=filed_bdd,
                 days_until_separation=days_until_separation,
                 months_to_first_payment=months)

    # The BDD window is measured backwards from the separation date.
    if days_until_separation is not None:
        v.in_window = close_at <= days_until_separation <= open_at
        v.too_early = days_until_separation > open_at
        v.too_late = days_until_separation < close_at
        v.window_opens_in_days = max(0, days_until_separation - open_at)

    # Month 1 after separation is when a decided claim first pays, so the gap
    # is everything beyond that.
    v.gap_months = max(0.0, months - FIGURES["bdd_months_to_first_payment"])
    v.gap_dollars = v.gap_months * monthly
    v.back_pay = v.gap_dollars

    if filed_bdd:
        v.notes.append(
            "BDD filed: the examinations happen before you separate and the "
            "decision is normally ready at or within a month of your "
            "separation date. That is the whole point of the programme.")
    elif v.in_window:
        v.notes.append(
            f"You are inside the BDD window right now — "
            f"{days_until_separation} days out, and the window is "
            f"{open_at} to {close_at} days before separation. File this week. "
            f"You must also be available for VA examinations before you "
            f"separate, which is why the window closes at {close_at} days.")
    elif v.too_early:
        v.notes.append(
            f"Too early for BDD: it opens {open_at} days before separation, in "
            f"about {v.window_opens_in_days} days. Put it in the calendar now "
            f"— gathering the private medical evidence is the slow part, and "
            f"you can do that today.")
    elif v.too_late:
        v.notes.append(
            f"Past the BDD window: it closes {close_at} days before separation "
            f"and you are {days_until_separation} days out. File a fully "
            f"developed claim the day after you separate instead, and make sure "
            f"every complaint is in the service treatment record before your "
            f"final physical — an undocumented condition is the hard one to "
            f"prove later.")

    if v.gap_dollars > 0:
        v.notes.append(
            f"At ${monthly:,.0f} a month, {v.gap_months:g} months of waiting is "
            f"${v.gap_dollars:,.0f} of income that does not arrive when the "
            f"bills do. File within "
            f"{FIGURES['retro_filing_window_months']} months of separation and "
            f"the award back-dates to the day after separation, so the money "
            f"comes eventually — as a lump, taxed nowhere, and months late.")
    return v


# ==========================================================================
# The month-by-month cash-flow picture
# ==========================================================================

def _month_start(d: date) -> date:
    return date(d.year, d.month, 1)


def add_months(d: date, n: int) -> date:
    total = d.year * 12 + (d.month - 1) + n
    y, mo = divmod(total, 12)
    return date(y, mo + 1, min(d.day, calendar.monthrange(y, mo + 1)[1]))


@dataclass
class MonthRow:
    offset: int = 0
    month: date = None
    label: str = ""
    military_pay: float = 0.0
    leave_settlement: float = 0.0
    retired_pay: float = 0.0
    va_pay: float = 0.0
    expenses: float = 0.0

    @property
    def income(self) -> float:
        return (self.military_pay + self.leave_settlement + self.retired_pay
                + self.va_pay)

    @property
    def shortfall(self) -> float:
        return max(0.0, self.expenses - self.income)


@dataclass
class CashFlow:
    rows: list = field(default_factory=list)
    separation_date: date = None
    monthly_expenses: float = 0.0
    settlement_offset: int = 1
    retired_pay_offset: int = 0
    va_offset: int = 0
    total_shortfall: float = 0.0
    months_short: int = 0
    worst_month: MonthRow | None = None
    reserve_needed: float = 0.0
    notes: list = field(default_factory=list)


def cash_flow(separation_date: date, basic_monthly: float, bah_monthly: float,
              bas_monthly: float, monthly_expenses: float, *,
              is_retiring: bool = False, retired_pay_monthly: float = 0.0,
              va_monthly: float = 0.0, va: VATiming | None = None,
              leave_option: LeaveOption | None = None,
              months_before: int = 3, months_after: int = 6,
              settlement_offset: int = 1,
              retired_pay_offset: int | None = None) -> CashFlow:
    """
    Income month by month across the separation date, against expenses.

    The separation month is prorated: pay stops on the separation date, not at
    the end of the month, and that alone surprises people.
    """
    military = max(0.0, basic_monthly) + max(0.0, bah_monthly) + max(0.0, bas_monthly)
    if retired_pay_offset is None:
        # 30 to 60 days to establish the account -> the second month, in
        # practice, with the first month paid in arrears when it catches up.
        retired_pay_offset = 2
    va_offset = 1 + int(round(va.gap_months)) if va is not None else 1

    cf = CashFlow(separation_date=separation_date,
                  monthly_expenses=max(0.0, monthly_expenses),
                  settlement_offset=settlement_offset,
                  retired_pay_offset=retired_pay_offset,
                  va_offset=va_offset)

    days_in_month = calendar.monthrange(separation_date.year,
                                        separation_date.month)[1]
    served_share = min(1.0, separation_date.day / days_in_month)

    for off in range(-abs(months_before), abs(months_after) + 1):
        d = add_months(_month_start(separation_date), off)
        row = MonthRow(offset=off, month=d, label=d.strftime("%b %Y"),
                       expenses=cf.monthly_expenses)
        if off < 0:
            row.military_pay = military
        elif off == 0:
            row.military_pay = military * served_share
        if off == settlement_offset and leave_option is not None:
            row.leave_settlement = leave_option.cash_at_separation
        if is_retiring and off >= retired_pay_offset:
            row.retired_pay = max(0.0, retired_pay_monthly)
        if off >= va_offset:
            row.va_pay = max(0.0, va_monthly)
        cf.rows.append(row)

    after = [r for r in cf.rows if r.offset >= 0]
    cf.total_shortfall = sum(r.shortfall for r in after)
    cf.months_short = sum(1 for r in after if r.shortfall > 0)
    cf.worst_month = max(after, key=lambda r: r.shortfall) if after else None
    cf.reserve_needed = cf.total_shortfall

    if cf.monthly_expenses <= 0:
        cf.notes.append(
            "No monthly expense figure is entered, so this cannot size the gap "
            "for you. Put your real monthly spending on the What I am worth "
            "page and come back — it is the number this whole page turns on.")
    else:
        cf.notes.append(
            f"Your last military pay covers only {served_share * 100:.0f}% of "
            f"{separation_date.strftime('%B')} — pay stops on the separation "
            f"date, not at the end of the month.")
        cf.notes.append(
            "Your last LES is the document to keep: it is where the leave "
            "balance, the final tax withholding and any government debt appear, "
            "and it is far harder to get hold of once your account closes.")
        cf.notes.append(
            f"The final settlement — sold leave, travel, adjustments — normally "
            f"lands {FIGURES['final_settlement_days_low']} to "
            f"{FIGURES['final_settlement_days_high']} days after you separate. "
            f"It is also the payment most likely to be wrong: check it against "
            f"your leave balance and your last LES the day it arrives.")
        if is_retiring:
            cf.notes.append(
                f"Retired pay is payable from the month after retirement, but "
                f"DFAS typically takes "
                f"{FIGURES['first_retired_pay_days_low']} to "
                f"{FIGURES['first_retired_pay_days_high']} days to establish "
                f"the account. You are paid in arrears once it does; you still "
                f"have to eat in the meantime.")
        cf.notes.append(
            "This timeline carries military and government income only — no "
            "civilian salary, because this page does not ask for a start date. "
            "If you have a job lined up, the real gap is the months before it "
            "starts, and terminal leave is how you make that number smaller.")
        if cf.total_shortfall > 0:
            cf.notes.append(
                f"Across the {len(after)} months from separation this model is "
                f"${cf.total_shortfall:,.0f} short of your expenses, in "
                f"{cf.months_short} of them. That is the cash you need set "
                f"aside BEFORE your last day — not a line of credit, cash.")
        else:
            cf.notes.append(
                "Income covers expenses in every month of this window. Keep the "
                "emergency fund anyway: the settlement and the first retired "
                "pay are the two payments most likely to slip.")
    return cf


# ==========================================================================
# The TSP at separation
# ==========================================================================

@dataclass
class TSPAtSeparation:
    loan_balance: float = 0.0
    age_at_separation: float = 0.0
    age_in_separation_year: int = 0
    rule_of_55: bool = False
    penalty_applies: bool = False
    income_tax: float = 0.0
    penalty: float = 0.0
    total_cost: float = 0.0
    notes: list = field(default_factory=list)


def tsp_at_separation(loan_balance: float, birth_year: int,
                      separation_date: date, marginal_rate: float | None = None
                      ) -> TSPAtSeparation:
    """
    What an unpaid TSP loan costs at separation, and whether the rule of 55
    saves the penalty.

    Payroll deductions stop the moment military pay does. The TSP sends a
    notice with a deadline; miss it and the outstanding balance is declared a
    taxable distribution -- ordinary income tax on the whole balance, plus 10%
    if you are under 59 1/2 and the rule of 55 does not apply.

    THE RULE OF 55 IS THE PART PEOPLE MISS. It is not age 55 at the time of the
    withdrawal: it is separation from service in or after the CALENDAR YEAR you
    reach 55. Retire in March of the year you turn 55 and it applies. It also
    applies only to the plan you separated from -- roll the balance to an IRA
    and the exception is gone.
    """
    rate = (FIGURES["supplemental_withholding"] if marginal_rate is None
            else max(0.0, min(0.9, marginal_rate)))
    bal = max(0.0, loan_balance)

    age_in_year = separation_date.year - int(birth_year or 0)
    born_mid = date(int(birth_year or 1900), 7, 1)
    exact_age = (separation_date - born_mid).days / 365.25

    t = TSPAtSeparation(loan_balance=bal, age_at_separation=max(0.0, exact_age),
                        age_in_separation_year=age_in_year,
                        rule_of_55=age_in_year >= FIGURES["rule_of_55_age"])
    t.penalty_applies = (bal > 0 and not t.rule_of_55
                         and t.age_at_separation < FIGURES["penalty_free_age"])
    t.income_tax = bal * rate
    t.penalty = bal * FIGURES["tsp_early_withdrawal_penalty"] if t.penalty_applies else 0.0
    t.total_cost = t.income_tax + t.penalty

    if bal <= 0:
        t.notes.append(
            "No TSP loan outstanding. If you are thinking of taking one before "
            "you separate, this is the reason not to: repayment stops with "
            "military pay and the balance becomes taxable income in a year "
            "when your income is already lumpy.")
        return t

    t.notes.append(
        f"Repayment comes out of military pay, and military pay stops. The TSP "
        f"gives you roughly {FIGURES['tsp_loan_notice_days']} days from the "
        f"notice to repay ${bal:,.0f} in full. Miss it and the balance is a "
        f"taxable distribution.")
    if t.penalty_applies:
        t.notes.append(
            f"You separate in the year you turn {age_in_year}, before the year "
            f"you turn {FIGURES['rule_of_55_age']}, so the rule of 55 does not "
            f"reach you and you are under {FIGURES['penalty_free_age']:g}. An "
            f"unpaid balance costs about ${t.income_tax:,.0f} in tax plus "
            f"${t.penalty:,.0f} of penalty — ${t.total_cost:,.0f} to convert "
            f"your own money into someone else's.")
    elif t.rule_of_55:
        t.notes.append(
            f"You separate in the year you turn {age_in_year}, which is in or "
            f"after the year you reach {FIGURES['rule_of_55_age']}, so the rule "
            f"of 55 applies and the 10% penalty does not. The tax on an unpaid "
            f"balance still does — about ${t.income_tax:,.0f}. And note the "
            f"exception belongs to the TSP alone: roll the money to an IRA and "
            f"you lose it until 59 1/2.")
    else:
        t.notes.append(
            f"You are past {FIGURES['penalty_free_age']:g}, so there is no "
            f"penalty. The tax on an unpaid balance still applies — about "
            f"${t.income_tax:,.0f}.")
    return t


# ==========================================================================
# Health cover, unemployment, and the final move
# ==========================================================================

PATH_RETIREE_TRICARE = "Retiree TRICARE, immediately"
PATH_TAMP = "TAMP, then CHCBP"
PATH_CHCBP = "CHCBP only"


@dataclass
class HealthCover:
    path: str = ""
    free_days: int = 0
    tamp_applies: bool = False
    chcbp_available: bool = False
    chcbp_enroll_days: int = 0
    chcbp_max_months: int = 0
    note: str = ""


def health_cover(is_retiring: bool, involuntary: bool = False) -> HealthCover:
    """
    Which of the three health paths you land on. The costs belong on the
    healthcare page; this only decides which door you go through and when it
    shuts.
    """
    if is_retiring:
        return HealthCover(
            path=PATH_RETIREE_TRICARE, free_days=0, tamp_applies=False,
            chcbp_available=False,
            note=("A retiree moves straight onto retiree TRICARE — Prime or "
                  "Select — with an enrollment fee and a catastrophic cap from "
                  "day one. There is no gap, but there is now a bill where "
                  "active-duty cover was free, and you must actively enroll. "
                  "Price both plans on the healthcare page before you pick."))

    if involuntary:
        return HealthCover(
            path=PATH_TAMP, free_days=FIGURES["tamp_days"], tamp_applies=True,
            chcbp_available=True,
            chcbp_enroll_days=FIGURES["chcbp_enroll_days"],
            chcbp_max_months=FIGURES["chcbp_max_months"],
            note=(f"An involuntary separation under honourable conditions "
                  f"generally carries TAMP: {FIGURES['tamp_days']} days of "
                  f"premium-free TRICARE after separation. When it ends, CHCBP "
                  f"is the bridge — up to "
                  f"{FIGURES['chcbp_max_months']} months, and you must elect it "
                  f"within {FIGURES['chcbp_enroll_days']} days of losing cover. "
                  f"CHCBP is paid, and not cheaply. Price it on the healthcare "
                  f"page against whatever a civilian employer offers."))

    return HealthCover(
        path=PATH_CHCBP, free_days=0, tamp_applies=False, chcbp_available=True,
        chcbp_enroll_days=FIGURES["chcbp_enroll_days"],
        chcbp_max_months=FIGURES["chcbp_max_months"],
        note=(f"An ordinary voluntary separation carries no TAMP: TRICARE ends "
              f"with your last day. CHCBP is the bridge — up to "
              f"{FIGURES['chcbp_max_months']} months — but it is premium-based "
              f"and you have only {FIGURES['chcbp_enroll_days']} days from "
              f"losing cover to elect it. Miss that and there is no bridge at "
              f"all. Price CHCBP on the healthcare page against a marketplace "
              f"plan and against your new employer's."))


@dataclass
class Unemployment:
    likely_eligible: bool = False
    retired_pay_offset_risk: bool = False
    typical_weeks: int = 0
    note: str = ""


def unemployment(is_retiring: bool, state: str = "") -> Unemployment:
    """
    UCX -- Unemployment Compensation for Ex-servicemembers.

    THIS MODULE WILL NOT QUOTE AN AMOUNT. UCX is federal money administered
    under STATE law: the weekly benefit, the duration, whether retired pay
    offsets it, and whether your separation counts as voluntary are all decided
    by the state you file in. A national figure here would be a guess dressed
    as an answer.
    """
    where = f" in {state}" if state else ""
    if is_retiring:
        return Unemployment(
            likely_eligible=True, retired_pay_offset_risk=True,
            typical_weeks=FIGURES["ucx_typical_weeks"],
            note=(f"Retirees are frequently eligible for UCX too, and most "
                  f"never file because they assume a pension disqualifies "
                  f"them. Some states reduce the weekly benefit by retired pay "
                  f"and some do not — it is state law, so ask the state "
                  f"workforce agency{where} rather than the internet. File in "
                  f"the week you separate: benefits generally start from the "
                  f"claim, not from the separation, so waiting throws weeks "
                  f"away. Take your DD-214 member copy 4."))
    return Unemployment(
        likely_eligible=True, retired_pay_offset_risk=False,
        typical_weeks=FIGURES["ucx_typical_weeks"],
        note=(f"A separating member under honourable conditions is usually "
              f"eligible for UCX, including one who simply reached the end of "
              f"an enlistment — completing a contract is not quitting. The "
              f"weekly amount, the duration and the rules are set by state "
              f"law{where}, so the state workforce agency is the only "
              f"authority. File in the week you separate, with your DD-214 "
              f"member copy 4; benefits run from the claim, not from your last "
              f"day."))


@dataclass
class FinalMove:
    is_retiring: bool = False
    deadline_days: int = 0
    deadline_label: str = ""
    home_of_selection: bool = False
    typical_value: float = 0.0
    note: str = ""


def final_move(is_retiring: bool) -> FinalMove:
    """The last government-funded move, and how long you have to use it."""
    if is_retiring:
        yrs = FIGURES["final_move_retiree_years"]
        return FinalMove(
            is_retiring=True, deadline_days=int(yrs * 365),
            deadline_label=f"{yrs} years", home_of_selection=True,
            typical_value=FIGURES["final_move_typical_value"],
            note=(f"A retiree generally has {yrs} years from the retirement "
                  f"date to take a government-funded move, and it goes to a "
                  f"HOME OF SELECTION — you are not tied to where you enlisted. "
                  f"That is deliberate: it lets you take a job first and move "
                  f"once you know where the work is. Extensions exist but must "
                  f"be requested before the deadline, not after. A CONUS "
                  f"household-goods move plus travel is real money to buy "
                  f"yourself, and an OCONUS one is far more."))
    days = FIGURES["final_move_separatee_days"]
    return FinalMove(
        is_retiring=False, deadline_days=days,
        deadline_label=f"{days} days",
        home_of_selection=False,
        typical_value=FIGURES["final_move_typical_value"],
        note=(f"A separating member generally has {days} days — extendable "
              f"toward {FIGURES['final_move_separatee_max_days']} in some "
              f"cases, with approval — and the entitlement runs to your home of "
              f"record or the place you entered active duty, not anywhere you "
              f"choose. You may move somewhere else, but the government pays "
              f"only up to the cost of the authorised destination. This is a "
              f"much shorter fuse than a retiree's, and it is the one people "
              f"let lapse."))


# ==========================================================================
# The whole picture
# ==========================================================================

@dataclass
class Transition:
    is_retiring: bool = False
    separation_date: date = None
    days_until_separation: int = 0
    basic_monthly: float = 0.0
    bah_monthly: float = 0.0
    bas_monthly: float = 0.0
    retired_pay_monthly: float = 0.0
    retired_pay_is_estimate: bool = False

    leave: LeaveComparison = field(default_factory=LeaveComparison)
    chosen: LeaveOption = field(default_factory=LeaveOption)
    va: VATiming = field(default_factory=VATiming)
    flow: CashFlow = field(default_factory=CashFlow)
    tsp: TSPAtSeparation = field(default_factory=TSPAtSeparation)
    health: HealthCover = field(default_factory=HealthCover)
    ucx: Unemployment = field(default_factory=Unemployment)
    move: FinalMove = field(default_factory=FinalMove)
    insurance_saving_10yr: float = 0.0
    insurance_saving_lifetime: float = 0.0
    notes: list = field(default_factory=list)


def parse_separation_date(value, default_days_ahead: int = 180,
                          today: date | None = None) -> date:
    """A blank or unreadable planned separation date becomes a placeholder."""
    today = today or date.today()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat((value or "").strip())
    except (ValueError, AttributeError, TypeError):
        return today + timedelta(days=default_days_ahead)


def analyze(h: Household, *, is_retiring: bool | None = None,
            leave_days: float | None = None, days_already_sold: float = 0.0,
            leave_choice: str = TAKE, separation_date=None,
            expected_va_monthly: float | None = None, filed_bdd: bool = False,
            tsp_loan_balance: float = 0.0, involuntary: bool = False,
            marginal_rate: float | None = None,
            months_before: int = 3, months_after: int = 6,
            today: date | None = None, bah_data=None,
            basepay_table=None) -> Transition:
    """Everything the page shows, computed once from the Household."""
    m = h.member
    today = today or date.today()

    sep = parse_separation_date(
        separation_date if separation_date is not None else m.planned_separation_date,
        today=today)

    if is_retiring is None:
        is_retiring = (m.component == RETIRED or m.years_of_service >= 20
                       or m.retired_pay_monthly > 0)

    basic, bah, bas = pay_components(m, bah_data, basepay_table)

    retired = float(m.retired_pay_monthly or 0.0)
    estimate = False
    if is_retiring and retired <= 0 and basic > 0:
        retired = RS.retired_pay(m.retirement_system, m.years_of_service, basic).monthly
        estimate = retired > 0

    days = float(m.leave_balance_days if leave_days is None else leave_days)
    va_monthly = float(m.va_disability_monthly if expected_va_monthly is None
                       else expected_va_monthly)

    t = Transition(is_retiring=bool(is_retiring), separation_date=sep,
                   days_until_separation=(sep - today).days,
                   basic_monthly=basic, bah_monthly=bah, bas_monthly=bas,
                   retired_pay_monthly=retired, retired_pay_is_estimate=estimate)

    t.leave = compare_leave(days, basic, bah, bas, days_already_sold, marginal_rate)
    t.chosen = t.leave.option(leave_choice)
    t.va = va_timing(va_monthly, filed_bdd, t.days_until_separation)
    t.flow = cash_flow(sep, basic, bah, bas, h.monthly_expenses,
                       is_retiring=t.is_retiring, retired_pay_monthly=retired,
                       va_monthly=va_monthly, va=t.va, leave_option=t.chosen,
                       months_before=months_before, months_after=months_after)
    t.tsp = tsp_at_separation(tsp_loan_balance, m.birth_year, sep, marginal_rate)
    t.health = health_cover(t.is_retiring, involuntary)
    t.ucx = unemployment(t.is_retiring, h.current_state)
    t.move = final_move(t.is_retiring)

    # VGLI against level term, from the module that already models it. Ten
    # years is the horizon that ranks against the other numbers on this page;
    # the lifetime figure is the real size of the decision, and both are shown.
    cover = float(m.sgli_coverage or 0.0)
    if cover > 0:
        sep_age = max(17, min(70, sep.year - int(m.birth_year or 1990)))
        t.insurance_saving_10yr = max(0.0, LI.compare(
            cover, sep_age, sep_age + 10, term_years=10).saving)
        t.insurance_saving_lifetime = max(0.0, LI.compare(cover, sep_age).saving)

    if estimate:
        t.notes.append(
            f"No retired pay is entered, so this uses an estimate from your "
            f"{m.retirement_system} multiplier and current basic pay: "
            f"${retired:,.0f} a month. Replace it with the figure on your "
            f"retirement orders as soon as you have it.")
    if not m.is_serving and m.component != RETIRED:
        t.notes.append(
            "Your component is not a serving one, so the pay figures here come "
            "from the table for your grade rather than from a live LES.")
    return t


# ==========================================================================
# Findings, ordered by dollars at stake
# ==========================================================================

def findings(t: Transition) -> list[tuple[str, str, str]]:
    """(severity, headline, detail), largest dollar consequence first."""
    scored: list[tuple[float, int, str, str, str]] = []

    def add(stake: float, tiebreak: int, sev: str, head: str, detail: str):
        scored.append((max(0.0, stake), tiebreak, sev, head, detail))

    # ---- Leave ---------------------------------------------------------
    lv = t.leave
    if lv.days > 0:
        if lv.advantage_of_taking > 0:
            add(lv.advantage_of_taking, 0, "warn",
                f"Taking your {lv.days:,.0f} days as terminal leave is worth "
                f"${lv.advantage_of_taking:,.0f} more than selling them.",
                f"Sold leave pays basic pay only — ${lv.basic_daily:,.0f} a day "
                f"— and it is taxable. The same day on terminal leave pays "
                f"${lv.basic_daily + lv.allowance_daily:,.0f}, because BAH and "
                f"BAS keep coming and neither is taxed. Selling everything "
                f"nets about ${lv.sell.after_tax:,.0f}; taking it is worth "
                f"about ${lv.take.after_tax:,.0f}. And the days themselves are "
                f"the real prize: you are on the payroll, with TRICARE, while "
                f"you start a civilian job.")
        else:
            add(0.0, 5, "info",
                f"With no BAH or BAS showing, selling and taking your "
                f"{lv.days:,.0f} days come to the same money.",
                "Check that your duty ZIP and housing status are right on Who "
                "I am. If you do draw allowances, taking the leave wins — that "
                "is the whole margin.")
        if lv.cap_binds:
            over_value = lv.days_over_cap * lv.basic_daily
            add(over_value, 1, "bad",
                f"The 60-day career cap stops you selling "
                f"{lv.days_over_cap:,.0f} of your days.",
                f"The cap is a CAREER cap, not an annual one — days sold at a "
                f"re-enlistment years ago still count against the same 60. "
                f"Those {lv.days_over_cap:,.0f} days must be taken as leave or "
                f"they are lost outright, which at "
                f"${lv.basic_daily + lv.allowance_daily:,.0f} a day of "
                f"compensation is ${lv.days_over_cap * (lv.basic_daily + lv.allowance_daily):,.0f} "
                f"of value. Build the terminal leave into your date now, before "
                f"the orders are cut.")

    # ---- The cash-flow gap ---------------------------------------------
    flow = t.flow
    if flow.total_shortfall > 0:
        worst = flow.worst_month
        add(flow.total_shortfall, 0, "bad",
            f"Set aside ${flow.reserve_needed:,.0f} in cash before your last "
            f"day.",
            f"Military pay stops on {t.separation_date:%d %B %Y} and covers "
            f"only part of that month. The final settlement lands "
            f"{FIGURES['final_settlement_days_low']}–"
            f"{FIGURES['final_settlement_days_high']} days later"
            + (f", and the first retired pay "
               f"{FIGURES['first_retired_pay_days_low']}–"
               f"{FIGURES['first_retired_pay_days_high']} days after that"
               if t.is_retiring else "")
            + f". Against ${flow.monthly_expenses:,.0f} a month of expenses "
              f"this model runs short in {flow.months_short} of the "
              f"{len([r for r in flow.rows if r.offset >= 0])} months from "
              f"separation"
            + (f", worst in {worst.label} at ${worst.shortfall:,.0f}."
               if worst and worst.shortfall > 0 else ".")
            + " This is the gap people fill with a credit card at 22%.")
    elif flow.monthly_expenses > 0:
        add(0.0, 4, "good",
            "Your income covers your expenses through the separation window.",
            "The two payments most likely to slip are the final settlement and "
            "the first retired pay. Keep the emergency fund intact until both "
            "have actually arrived and both have been checked for errors.")

    # ---- VA timing ------------------------------------------------------
    va = t.va
    if va.expected_monthly > 0:
        if not va.filed_bdd and va.gap_dollars > 0:
            sev = "bad" if (va.in_window or va.too_early) else "warn"
            head = (f"Not filing BDD costs you ${va.gap_dollars:,.0f} of "
                    f"cash-flow — {va.gap_months:g} months at "
                    f"${va.expected_monthly:,.0f}.")
            add(va.gap_dollars, 0, sev, head, " ".join(va.notes))
        elif va.filed_bdd:
            add(va.gap_dollars, 2, "good",
                f"BDD filed: your VA compensation should start within about a "
                f"month of separation.",
                f"That is roughly ${va.expected_monthly:,.0f} a month arriving "
                f"on time instead of after a claim queue, and it is the "
                f"difference between a soft landing and a hard one. Keep every "
                f"examination appointment before you separate — a missed exam "
                f"is what turns a BDD claim back into an ordinary one.")
    else:
        add(0.0, 6, "info",
            "No expected VA compensation is entered, so this page cannot time "
            "it for you.",
            "Even a member who feels fine usually has something service-"
            "connected on the record. Put an expected monthly figure in on the "
            "left and the timeline will show you what the wait costs.")

    # ---- The TSP loan ---------------------------------------------------
    tsp = t.tsp
    if tsp.loan_balance > 0:
        sev = "bad" if tsp.penalty_applies else "warn"
        head = (f"Your ${tsp.loan_balance:,.0f} TSP loan becomes a taxable "
                f"distribution if it is not repaid — about "
                f"${tsp.total_cost:,.0f} in tax"
                + (" and penalty." if tsp.penalty_applies else ", with no penalty."))
        add(tsp.total_cost, 0, sev, head,
            " ".join(tsp.notes) +
            " Repay it from the final settlement if you can — that is the one "
            "lump of cash timed to arrive for exactly this.")

    # ---- The final move -------------------------------------------------
    mv = t.move
    add(mv.typical_value, 1, "warn",
        f"Your last government-funded move must be used within "
        f"{mv.deadline_label} of separation.",
        mv.note + " Diarise the deadline the day your orders are cut.")

    # ---- Life insurance -------------------------------------------------
    if t.insurance_saving_10yr > 0:
        add(t.insurance_saving_10yr, 2, "warn",
            f"Sort your life insurance BEFORE you separate — about "
            f"${t.insurance_saving_10yr:,.0f} in the first ten years alone, and "
            f"${t.insurance_saving_lifetime:,.0f} over a lifetime.",
            f"SGLI continues free for "
            f"{LI.SGLI_FREE_DAYS_AFTER_SEPARATION} days after separation. VGLI "
            f"is issued with NO health questions within "
            f"{LI.VGLI_GUARANTEED_DAYS} days, with proof of good health to "
            f"{LI.VGLI_FINAL_DEADLINE_DAYS} days, and not at all after that. "
            f"Level term is usually far cheaper than VGLI for a healthy "
            f"member, so apply for term and be APPROVED while the guaranteed "
            f"window is still open, keeping VGLI as the fallback. The full "
            f"comparison is on the medical-separation and insurance page.")

    # ---- The TSP itself -------------------------------------------------
    add(0.0, 3, "info",
        "You may leave the money in the TSP, and it is cheaper than almost any "
        "IRA.",
        "Separation does not force you out. What separation DOES change: you "
        "can no longer contribute, and you can no longer do a Roth conversion "
        "inside the TSP — the plan has no conversion facility at all. A "
        "conversion needs an IRA, which means rolling traditional money out "
        "first, and that trades the TSP's expense ratio for the IRA's. Work "
        "the sizes on the Should I convert to Roth? page before you move "
        "anything; the low-income year right after separation is often the "
        "cheapest conversion window you will ever get.")

    # ---- Health cover ---------------------------------------------------
    add(0.0, 3, "warn", f"Health cover after separation: {t.health.path}.",
        t.health.note)

    # ---- Unemployment ---------------------------------------------------
    add(0.0, 3, "info", "File for UCX unemployment in the week you separate.",
        t.ucx.note)

    scored.sort(key=lambda r: (-r[0], r[1]))
    return [(sev, head, detail) for _, _, sev, head, detail in scored]


# ==========================================================================
# The countdown
# ==========================================================================

@dataclass
class Milestone:
    months_out: int = 0
    label: str = ""
    items: list = field(default_factory=list)


def countdown(t: Transition) -> list[Milestone]:
    """What to do at twelve, six, three and one month out. Ordered, dated."""
    lv = t.leave
    keep = lv.advantage_of_taking > 0

    twelve = Milestone(12, "Twelve months out", [
        "Start the transition class (TAP) — it is mandatory and the good "
        "sessions fill first.",
        f"Pull your leave balance and your record of leave already SOLD. The "
        f"{SELLBACK_CAREER_CAP_DAYS:.0f}-day cap is a career cap and a sale you "
        f"forgot about eats into it.",
        "Get every complaint into your service treatment record. An "
        "undocumented condition is the one you cannot prove later.",
        "Decide, roughly, where you will live. It sets the final move, the "
        "state that taxes you, and your civilian job search.",
        "Stop taking TSP loans. Anything outstanding at separation has to be "
        "repaid out of a month with no military pay in it.",
    ])

    six = Milestone(6, "Six months out", [
        f"File BDD as soon as you are {FIGURES['bdd_window_open_days']} days "
        f"out — the window is {FIGURES['bdd_window_open_days']} to "
        f"{FIGURES['bdd_window_close_days']} days before separation and it does "
        f"not reopen.",
        "Gather private medical records and nexus evidence now; that is the "
        "part that takes weeks.",
        ("Plan terminal leave into your separation date and tell your chain "
         "early." if keep else
         "Decide sell versus terminal leave and put it in writing."),
        "Apply for commercial level term life insurance and get APPROVED "
        "before you separate, while VGLI's guaranteed-acceptance window is "
        "still open behind you.",
        "Build the cash reserve this page sized. Cash, not credit.",
    ])

    three = Milestone(3, "Three months out", [
        f"Last chance for BDD: the window closes "
        f"{FIGURES['bdd_window_close_days']} days out.",
        "Book the final physical and the dental exam. They are free now and "
        "they are not free afterwards.",
        ("Confirm retiree TRICARE enrollment — it is not automatic."
         if t.is_retiring else
         f"Diary the CHCBP election: {FIGURES['chcbp_enroll_days']} days from "
         f"losing TRICARE, and there is no extension."),
        "Get the final move counselled and scheduled, or at least understand "
        "the deadline you are agreeing to.",
        "Check your SGLI and TSP beneficiary designations. They do not follow "
        "you out.",
    ])

    one = Milestone(1, "One month out", [
        "Verify the leave balance on your LES against what your orders say, "
        "and fix it before your last day, not after.",
        "Get at least twenty copies of the DD-214, member copy 4. You will "
        "need it for the VA, the state, the employer and the unemployment "
        "office.",
        ("Confirm your DFAS myPay retired account and your bank details — the "
         "first retired pay goes to whatever DFAS has on file."
         if t.is_retiring else
         "Update myPay contact details so the final settlement and the W-2 "
         "reach you."),
        "File for UCX unemployment in the week you separate, not once the "
        "money runs out.",
        "Check the final settlement when it arrives: leave days, travel, and "
        "any debt the government thinks you owe.",
    ])

    out = [twelve, six, three, one]
    for ms in out:
        ms.label = f"{ms.label} — {add_months(t.separation_date, -ms.months_out):%b %Y}"
    return out
