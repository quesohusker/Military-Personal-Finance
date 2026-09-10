"""
The military financial priority waterfall, as a rule engine.

This is the part a civilian planner cannot do. The civilian flowchart is close
but wrong in five specific places, and each of those differences is worth real
money to a service member:

  1. THE TSP MATCH ONLY EXISTS UNDER BRS. A High-3 member contributing 5% "for
     the match" is getting nothing for it. The step must branch on DIEMS date,
     not be shown to everyone.
  2. THE MATCH IS ON BASIC PAY ONLY -- not BAH, not BAS, not special pays. "5%
     of your income" is the wrong instruction and understates nothing but
     overstates the contribution needed.
  3. HSA IS UNAVAILABLE TO ACTIVE DUTY. TRICARE is not a high-deductible plan.
     The civilian order ranks HSA above maxing the 401(k); for a service member
     the step simply does not exist, and showing it is actively misleading.
  4. SDP OUTRANKS EVERYTHING DURING A DEPLOYMENT. A guaranteed 10% on up to
     $10,000, risk-free, has no civilian equivalent and beats every other use
     of a marginal dollar including the match.
  5. SCRA COMES BEFORE THE DEBT STEP, not inside it. Capping pre-service debt
     at 6% can reorder the entire payoff queue before you optimise it.

Each step reports its own status, the dollars still required, and a concrete
next action. Nothing here is advice in the abstract -- every step either
applies to this member or is explicitly marked as not applying, and says why.
"""

from __future__ import annotations
from dataclasses import dataclass, field

from engine.profile import (Household, ServiceMember, ACTIVE, GUARD, RESERVE,
                            RETIRED, VETERAN, CIVILIAN, SERVING, has_tsp_match,
                            SYS_BRS, SYS_HIGH3, SYS_REDUX, SYS_FINAL_PAY)
from engine.debt.payoff import Debt, SCRA_RATE_CAP

DONE = "done"
IN_PROGRESS = "in_progress"
NOT_STARTED = "not_started"
NOT_APPLICABLE = "not_applicable"


@dataclass
class Step:
    key: str = ""
    order: int = 0
    title: str = ""
    status: str = NOT_STARTED
    why: str = ""
    action: str = ""
    amount_needed: float = 0.0
    amount_done: float = 0.0
    target: float = 0.0
    military_note: str = ""
    weight: float = 1.0

    @property
    def applies(self) -> bool:
        return self.status != NOT_APPLICABLE

    @property
    def complete(self) -> bool:
        return self.status == DONE

    @property
    def progress(self) -> float:
        if self.status == DONE:
            return 1.0
        if self.target <= 0:
            return 0.0
        return max(0.0, min(1.0, self.amount_done / self.target))


@dataclass
class WaterfallResult:
    steps: list = field(default_factory=list)
    score: float = 0.0
    current: Step | None = None
    completed: int = 0
    applicable: int = 0

    def by_key(self, key: str) -> Step | None:
        return next((s for s in self.steps if s.key == key), None)

    @property
    def active_steps(self) -> list:
        return [s for s in self.steps if s.applies]


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def monthly_basic_pay(m: ServiceMember) -> float:
    """
    Basic pay only -- never BAH, BAS or special pays.

    The LES override wins. Otherwise fall back to the published table, which is
    what makes the waterfall usable before the member has typed anything in.
    """
    if m.basic_pay_monthly_override > 0:
        return m.basic_pay_monthly_override
    try:
        from engine.pay import basepay as BP
        r = BP.lookup(m.grade, m.years_of_service, BP.load())
        return r.monthly if r.found else 0.0
    except Exception:
        return 0.0


def _fmt(x: float) -> str:
    return f"${x:,.0f}"


def _emergency_target(h: Household, months: float) -> float:
    if h.monthly_expenses > 0:
        return h.monthly_expenses * months
    return 0.0


def high_interest_debts(h: Household, threshold: float = 0.08) -> list[Debt]:
    scra = any(d.incurred_before_service for d in h.debts)
    out = []
    for d in h.debts:
        if d.balance <= 0:
            continue
        rate = min(d.apr, SCRA_RATE_CAP) if (scra and d.incurred_before_service) else d.apr
        if rate >= threshold:
            out.append(d)
    return out


# --------------------------------------------------------------------------
# Steps
# --------------------------------------------------------------------------

def _step_les(h: Household) -> Step:
    m = h.member
    s = Step(key="les", order=0, title="Know your LES and your budget", weight=0.5,
             why="Gross pay is meaningless in the military without the split "
                 "between taxable and non-taxable. BAH and BAS are untaxed, so "
                 "your effective tax rate is well below a civilian's at the "
                 "same total compensation — and that changes every decision "
                 "below.")
    missing = []
    if h.monthly_expenses <= 0:
        missing.append("your monthly expenses")
    if m.is_serving and monthly_basic_pay(m) <= 0:
        missing.append("your basic pay")

    if missing:
        s.status = NOT_STARTED
        s.action = ("Enter " + " and ".join(missing) + ". Everything below is "
                    "computed from these.")
    else:
        s.status = DONE
        using_table = m.is_serving and m.basic_pay_monthly_override <= 0
        s.action = ("Verify your LES quarterly: SGLI election, TSP election, "
                    "dependency status, and allotments.")
        if using_table:
            s.action += (f" Basic pay is currently coming from the published "
                         f"{h.limits.year} pay table "
                         f"({_fmt(monthly_basic_pay(m))} a month). Enter the "
                         f"figure from your LES on the Pay page if it differs.")
    if m.is_serving:
        s.military_note = ("Check that dependency status on your LES matches "
                           "reality — it drives BAH and a stale entry is both a "
                           "pay error and a debt you will be asked to repay.")
    return s


def _step_sdp(h: Household) -> Step:
    m = h.member
    cap = h.limits.sdp_cap
    s = Step(key="sdp", order=1, target=cap, weight=2.0,
             title="Savings Deposit Program — 10% guaranteed", 
             why="A guaranteed 10% annual return, compounded monthly, on up to "
                 f"{_fmt(cap)}. Risk-free and government-backed. Nothing in "
                 "civilian finance competes, so while you are eligible this "
                 "outranks every other use of a dollar — including the TSP "
                 "match.")
    if not (m.is_serving and m.is_deployed and m.drawing_hostile_fire_pay):
        s.status = NOT_APPLICABLE
        s.action = ("Available only while deployed to a designated combat zone "
                    "drawing hostile fire or imminent danger pay.")
        return s

    s.amount_done = m.sdp_balance
    if m.sdp_balance >= cap - 1:
        s.status = DONE
        s.action = f"Funded to the {_fmt(cap)} cap. Interest continues for 90 days after you redeploy."
    else:
        s.status = IN_PROGRESS if m.sdp_balance > 0 else NOT_STARTED
        s.amount_needed = cap - m.sdp_balance
        s.action = (f"Deposit {_fmt(s.amount_needed)} more, up to the {_fmt(cap)} "
                    f"cap. Deposits come from unallotted pay in multiples of $5 "
                    f"and start on day 31 of the deployment.")
    s.military_note = ("You can only feed it from monthly pay, so a short "
                       "deployment cannot reach the cap without deliberate "
                       "planning from day 31. Interest is taxable even though "
                       "the pay that funded it was not.")
    return s


def _step_starter_ef(h: Household) -> Step:
    target = _emergency_target(h, 1.0) or 1_000.0
    s = Step(key="starter_ef", order=2, target=target, amount_done=h.cash_savings,
             title="Starter emergency fund", weight=1.5,
             why="A cash buffer so an unexpected bill does not become a "
                 "high-interest debt.")
    if h.cash_savings >= target:
        s.status = DONE
        s.action = f"You have {_fmt(h.cash_savings)} in cash."
    else:
        s.status = IN_PROGRESS if h.cash_savings > 0 else NOT_STARTED
        s.amount_needed = target - h.cash_savings
        s.action = f"Save {_fmt(s.amount_needed)} more to reach {_fmt(target)}."
    if h.member.is_serving:
        s.military_note = ("Your job loss risk is near zero and TRICARE means no "
                           "medical deductible shock, so the civilian one-month "
                           "floor is defensible here — but see the full fund "
                           "step for why the military reasons for cash are "
                           "different, and larger.")
    return s


def _step_tsp_match(h: Household) -> Step:
    m = h.member
    system = m.retirement_system
    s = Step(key="tsp_match", order=3, title="Capture the full TSP match", weight=2.0,
             why="An immediate 100% return on the first 3% and 50% on the next "
                 "2%. Nothing else in this list returns that.")

    if not m.is_serving:
        s.status = NOT_APPLICABLE
        s.action = "Applies while serving."
        return s

    if not has_tsp_match(system):
        s.status = NOT_APPLICABLE
        s.action = (f"You are under {system}, which has no TSP match. There is "
                    f"no free money to capture, so contribute to the TSP on its "
                    f"own merits — go straight to the Roth IRA and Roth TSP "
                    f"steps below.")
        s.military_note = ("This is the most common piece of bad advice given to "
                           "legacy-system members: 'always get the match.' Under "
                           f"{system} there is no match to get.")
        return s

    basic = monthly_basic_pay(m)
    s.target = 0.05
    s.amount_done = m.tsp_contribution_pct

    if m.tsp_contribution_pct >= 0.05 - 1e-9:
        s.status = DONE
        got = basic * 0.05 * 12 if basic else 0
        s.action = (f"You contribute {m.tsp_contribution_pct * 100:.0f}% and are "
                    f"receiving the full match"
                    + (f" — {_fmt(got)} a year of service money." if got else "."))
    else:
        s.status = IN_PROGRESS if m.tsp_contribution_pct > 0 else NOT_STARTED
        gap = 0.05 - m.tsp_contribution_pct
        s.amount_needed = basic * gap * 12 if basic else 0
        s.action = (f"Raise your TSP contribution from "
                    f"{m.tsp_contribution_pct * 100:.0f}% to 5% of basic pay."
                    + (f" You are leaving about {_fmt(basic * gap * 12)} a year "
                       f"of service matching on the table." if basic else ""))
    s.military_note = ("The match is computed on BASIC PAY ONLY — not BAH, not "
                       "BAS, not special or incentive pays. Contributing more "
                       "than 5% earns no additional match, though it may still "
                       "be right for other reasons. Your own contributions and "
                       "the match vest immediately; only the automatic 1% has a "
                       "two-year vesting cliff.")
    return s


def _step_scra(h: Household) -> Step:
    s = Step(key="scra", order=4, title="Invoke the SCRA 6% interest cap", weight=1.5,
             why="The Servicemembers Civil Relief Act caps interest at 6% on "
                 "obligations you took on BEFORE entering active duty, for as "
                 "long as you serve. Interest above 6% is forgiven, not "
                 "deferred.")
    m = h.member
    eligible = [d for d in h.debts
                if d.incurred_before_service and d.balance > 0 and d.apr > SCRA_RATE_CAP]

    if not m.is_serving:
        s.status = NOT_APPLICABLE
        s.action = "SCRA rate relief applies during active duty service."
        return s
    if not h.debts:
        s.status = NOT_APPLICABLE
        s.action = "No debts recorded."
        return s
    if not eligible:
        s.status = DONE
        s.action = ("No pre-service debt above 6% recorded. If you have any that "
                    "is not listed here, add it — this is free money.")
        return s

    total = sum(d.balance for d in eligible)
    rough = sum(d.balance * (d.apr - SCRA_RATE_CAP) for d in eligible)
    s.status = NOT_STARTED
    s.amount_needed = rough
    s.action = (f"Write to each lender for {', '.join(d.name for d in eligible)} "
                f"({_fmt(total)} of pre-service debt). Include a copy of your "
                f"orders and request the 6% cap. Roughly {_fmt(rough)} a year of "
                f"interest at current balances.")
    s.military_note = ("It is not automatic — you must request it in writing with "
                       "your orders. The lender must apply it retroactively to "
                       "the start of your active duty and forgive the excess. "
                       "Debt incurred DURING service is not covered; that is the "
                       "most common misunderstanding. Do this before optimising "
                       "your payoff order, because it can change which debt is "
                       "actually the expensive one.")
    return s


def _step_high_interest_debt(h: Household) -> Step:
    s = Step(key="high_interest_debt", order=5, weight=2.0,
             title="Eliminate high-interest debt",
             why="Paying off a 22% card is a guaranteed, tax-free 22% return. No "
                 "investment offers that with certainty.")
    targets = high_interest_debts(h)
    if not h.debts:
        s.status = NOT_APPLICABLE
        s.action = "No debts recorded."
        return s
    if not targets:
        s.status = DONE
        s.action = "No debt above 8% after the SCRA cap. Move on."
        return s

    total = sum(d.balance for d in targets)
    worst = max(targets, key=lambda d: d.apr)
    s.status = IN_PROGRESS
    s.target = total
    s.amount_needed = total
    s.action = (f"{_fmt(total)} across {len(targets)} debt(s) above 8%. Attack "
                f"{worst.name} first at {worst.apr * 100:.1f}%.")
    s.military_note = ("The Military Lending Act caps most consumer credit to "
                       "service members and dependents at 36% and bans payday "
                       "and title loans for covered borrowers — if you were sold "
                       "one on active duty the contract may be void. Army "
                       "Emergency Relief, Navy-Marine Corps Relief, the Air Force "
                       "Aid Society and Coast Guard Mutual Assistance make "
                       "interest-free emergency loans; use them instead of a "
                       "high-rate lender.")
    return s


def _step_full_ef(h: Household) -> Step:
    months = 3.0 if h.member.is_serving else 6.0
    target = _emergency_target(h, months)
    s = Step(key="full_ef", order=6, target=target, amount_done=h.cash_savings,
             title=f"Full emergency fund — {months:.0f} months", weight=1.5,
             why="Cash for the disruptions that are not job loss.")
    if target <= 0:
        s.status = NOT_STARTED
        s.action = "Enter your monthly expenses so this can be sized."
        return s
    if h.cash_savings >= target:
        s.status = DONE
        s.action = f"You have {_fmt(h.cash_savings)}, covering {h.cash_savings / (target / months):.1f} months."
    else:
        s.status = IN_PROGRESS if h.cash_savings > 0 else NOT_STARTED
        s.amount_needed = target - h.cash_savings
        s.action = f"Save {_fmt(s.amount_needed)} more to reach {_fmt(target)}."
    if h.member.is_serving:
        s.military_note = ("The civilian reason for six months is job loss, which "
                           "you effectively do not face. Your reasons are "
                           "different and often bigger: PCS costs you float for "
                           "months before reimbursement, spouse income stops at "
                           "every move, and a DFAS pay error becomes a debt they "
                           "recoup from your paycheck. Three months is "
                           "defensible while serving; move toward six as you "
                           "approach separation, when job-loss risk becomes real.")
    else:
        s.military_note = ("Now that you are no longer serving, the civilian "
                           "job-loss rationale applies and six months is the "
                           "right target.")
    return s


def _step_roth_ira(h: Household) -> Step:
    lim = h.limits
    people = h.people()
    s = Step(key="roth_ira", order=7, title="Max the Roth IRA", weight=1.0,
             why="Tax-free growth and tax-free withdrawals, with no required "
                 "distributions ever.")
    total_limit = 0.0
    total_done = 0.0
    for p in people:
        cap = lim.ira_contribution + (lim.ira_catchup_50 if p.age() >= 50 else 0.0)
        total_limit += cap
        total_done += min(p.ira_contributed_this_year, cap)

    s.target = total_limit
    s.amount_done = total_done
    if total_done >= total_limit - 1:
        s.status = DONE
        s.action = f"Both {_fmt(total_limit)} contributed for {lim.year}."
    else:
        s.status = IN_PROGRESS if total_done > 0 else NOT_STARTED
        s.amount_needed = total_limit - total_done
        s.action = (f"Contribute {_fmt(s.amount_needed)} more to reach the "
                    f"{lim.year} limit of {_fmt(total_limit)}"
                    + (" across both of you." if len(people) > 1 else "."))
    if h.member.is_serving:
        s.military_note = ("Because BAH and BAS are untaxed, your marginal "
                           "bracket is unusually low relative to your real "
                           "income — which makes Roth the default rather than a "
                           "close call. Non-taxable combat pay still counts as "
                           "compensation for IRA purposes, so a fully tax-free "
                           "deployment year does not block a contribution.")
    return s


def _step_roth_tsp(h: Household) -> Step:
    lim = h.limits
    m = h.member
    s = Step(key="roth_tsp", order=8, title="Max the TSP", weight=1.0,
             why=f"The TSP has among the lowest expense ratios available "
                 f"anywhere, and the G Fund has no civilian equivalent.")
    if not m.is_serving:
        s.status = NOT_APPLICABLE
        s.action = ("You can no longer contribute to the TSP after separating, "
                    "though you may leave the balance there and roll money in.")
        return s

    cap = lim.tsp_elective_deferral
    if m.age() >= 60 and m.age() <= 63:
        cap += lim.tsp_catchup_60_63
    elif m.age() >= 50:
        cap += lim.tsp_catchup_50

    basic = monthly_basic_pay(m)
    contributing = basic * m.tsp_contribution_pct * 12 if basic else 0.0
    s.target = cap
    s.amount_done = contributing

    if contributing >= cap - 1:
        s.status = DONE
        s.action = f"On track to contribute the {lim.year} limit of {_fmt(cap)}."
    else:
        s.status = IN_PROGRESS if contributing > 0 else NOT_STARTED
        s.amount_needed = max(0.0, cap - contributing)
        s.action = (f"At {m.tsp_contribution_pct * 100:.0f}% of basic pay you are "
                    f"on track for {_fmt(contributing)} of the {_fmt(cap)} limit."
                    if basic else
                    f"Enter your basic pay to see how far {m.tsp_contribution_pct * 100:.0f}% gets you toward {_fmt(cap)}.")

    notes = ["Service automatic and matching contributions always land in the "
             "TRADITIONAL balance regardless of how you designate your own."]
    if m.in_combat_zone:
        notes.append(
            f"In a combat zone the annual addition limit of "
            f"{_fmt(lim.tsp_annual_addition)} applies rather than "
            f"{_fmt(lim.tsp_elective_deferral)} — but Roth TSP is still capped at "
            f"{_fmt(lim.tsp_elective_deferral)}. Fill Roth first, then overflow "
            f"tax-exempt pay into traditional up to the higher limit. Those "
            f"tax-exempt traditional dollars are never taxed again on "
            f"withdrawal, though their earnings are.")
    s.military_note = " ".join(notes)
    return s


def _step_hsa(h: Household) -> Step:
    s = Step(key="hsa", order=9, title="Health Savings Account", weight=0.5,
             why="Triple tax advantage — deductible in, tax-free growth, tax-free "
                 "out for medical costs.")
    m = h.member
    if m.component == ACTIVE:
        s.status = NOT_APPLICABLE
        s.action = ("Not available to you. An HSA requires a high-deductible "
                    "health plan, and TRICARE is not one.")
        s.military_note = ("Civilian priority lists rank the HSA above maxing "
                           "your retirement plan. That advice does not transfer: "
                           "an active duty member simply cannot open one. It "
                           "becomes relevant if your spouse is on their "
                           "employer's high-deductible plan and not covered by "
                           "TRICARE, if you are Guard or Reserve not on orders, "
                           "or after you separate.")
        return s
    if m.component in (GUARD, RESERVE):
        s.status = NOT_STARTED
        s.action = ("Possible if you are not on TRICARE Reserve Select or active "
                    "orders and you carry a qualifying high-deductible plan.")
        return s
    s.status = NOT_STARTED
    s.action = ("Available if you are on a qualifying high-deductible health "
                "plan and not enrolled in Medicare.")
    return s


def _step_taxable(h: Household) -> Step:
    s = Step(key="taxable", order=10, title="Taxable investing and other goals",
             weight=0.5,
             why="Once the tax-advantaged space is full, a low-cost index "
                 "portfolio in a taxable account funds everything else.")
    if h.taxable_brokerage > 0:
        s.status = IN_PROGRESS
        s.action = f"You hold {_fmt(h.taxable_brokerage)} in taxable investments."
    else:
        s.status = NOT_STARTED
        s.action = "Fund this after the steps above are complete."
    s.military_note = ("Your untaxed allowances keep taxable income low, which "
                       "makes the 0% long-term capital gains bracket unusually "
                       "reachable — worth planning gains around, especially in a "
                       "deployment year.")
    return s


def _step_low_interest_debt(h: Household) -> Step:
    s = Step(key="low_interest_debt", order=11, title="Low-interest debt",
             weight=0.25,
             why="Optional. Below roughly 6% you are usually better off "
                 "investing the difference.")
    rest = [d for d in h.debts if d.balance > 0 and d.apr < 0.08]
    if not rest:
        s.status = NOT_APPLICABLE
        s.action = "No low-interest debt recorded."
        return s
    total = sum(d.balance for d in rest)
    s.status = IN_PROGRESS
    s.target = total
    s.amount_needed = total
    s.action = f"{_fmt(total)} of low-rate debt. Paying it down early is a preference, not a requirement."
    return s


STEP_BUILDERS = [
    _step_les, _step_sdp, _step_starter_ef, _step_tsp_match, _step_scra,
    _step_high_interest_debt, _step_full_ef, _step_roth_ira, _step_roth_tsp,
    _step_hsa, _step_taxable, _step_low_interest_debt,
]


def evaluate(h: Household) -> WaterfallResult:
    """Run the whole waterfall against a household."""
    steps = sorted((b(h) for b in STEP_BUILDERS), key=lambda s: s.order)
    result = WaterfallResult(steps=steps)

    active = [s for s in steps if s.applies]
    result.applicable = len(active)
    result.completed = sum(1 for s in active if s.complete)

    weight_total = sum(s.weight for s in active)
    if weight_total:
        earned = sum(s.weight * s.progress for s in active)
        result.score = round(100.0 * earned / weight_total, 1)

    result.current = next((s for s in active if not s.complete), None)
    return result
