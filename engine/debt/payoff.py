"""
Consumer debt payoff: avalanche, snowball, and the SCRA interest cap.

The mechanics that matter and that most calculators get wrong:

  * The monthly budget stays CONSTANT. When a debt is retired, its minimum
    payment rolls into the attack on the next one. That cascade is the whole
    point of both methods -- a model that just pays minimums plus a fixed extra
    understates how fast the tail clears.
  * A minimum payment below the monthly interest never retires the debt. The
    balance grows forever. That has to be detected and said plainly rather than
    silently running to the iteration cap.
  * SCRA caps interest at 6% on obligations incurred BEFORE active duty, for
    the duration of service. It is not automatic -- the member must invoke it in
    writing with a copy of their orders -- and it is the single highest-return
    financial action available to a service member carrying pre-service debt.
"""

from __future__ import annotations
from dataclasses import dataclass, field, asdict

STRATEGY_AVALANCHE = "Avalanche — highest interest rate first"
STRATEGY_SNOWBALL = "Snowball — smallest balance first"
STRATEGY_CUSTOM = "Custom order"
STRATEGIES = [STRATEGY_AVALANCHE, STRATEGY_SNOWBALL, STRATEGY_CUSTOM]

# Statutory SCRA ceiling on pre-service obligations during active duty.
SCRA_RATE_CAP = 0.06

MAX_MONTHS = 1200  # 100 years; anything reaching this never pays off


@dataclass
class Debt:
    name: str = ""
    balance: float = 0.0
    apr: float = 0.0                    # annual rate as a decimal, e.g. 0.2249
    minimum_payment: float = 0.0
    kind: str = "Credit card"

    # SCRA eligibility. The cap applies only to obligations incurred before
    # the member entered active duty.
    incurred_before_service: bool = False

    # Ordering hint for STRATEGY_CUSTOM; lower goes first.
    priority: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


DEBT_KINDS = ["Credit card", "Auto loan", "Personal loan", "Student loan — federal",
              "Student loan — private", "Medical", "Payday / title loan",
              "Family / other", "Mortgage", "Other"]


def effective_apr(debt: Debt, scra_active: bool,
                  cap: float = SCRA_RATE_CAP) -> float:
    """The rate actually charged, after any SCRA reduction."""
    if scra_active and debt.incurred_before_service:
        return min(debt.apr, cap)
    return debt.apr


def order_debts(debts: list[Debt], strategy: str, scra_active: bool = False,
                cap: float = SCRA_RATE_CAP) -> list[Debt]:
    """
    Attack order. Avalanche sorts on the EFFECTIVE rate, not the nominal one --
    invoking SCRA can reorder the queue, and sorting on the headline rate would
    send extra payments at a debt that is no longer the expensive one.
    """
    if strategy == STRATEGY_SNOWBALL:
        return sorted(debts, key=lambda d: (d.balance, -d.apr))
    if strategy == STRATEGY_CUSTOM:
        return sorted(debts, key=lambda d: (d.priority, d.balance))
    return sorted(debts, key=lambda d: (-effective_apr(d, scra_active, cap), d.balance))


@dataclass
class MonthRow:
    month: int = 0
    total_balance: float = 0.0
    interest_paid: float = 0.0
    principal_paid: float = 0.0
    payment: float = 0.0
    target: str = ""


@dataclass
class PayoffResult:
    strategy: str = ""
    months: int = 0
    total_interest: float = 0.0
    total_paid: float = 0.0
    monthly_budget: float = 0.0
    schedule: list = field(default_factory=list)
    payoff_month: dict = field(default_factory=dict)   # debt name -> month
    never_pays_off: list = field(default_factory=list)
    starting_balance: float = 0.0

    @property
    def years(self) -> float:
        return self.months / 12.0

    @property
    def is_solvable(self) -> bool:
        return not self.never_pays_off

    def to_frame(self):
        import pandas as pd
        return pd.DataFrame([asdict(r) for r in self.schedule])


def minimum_viable_payment(debts: list[Debt], scra_active: bool = False,
                           cap: float = SCRA_RATE_CAP) -> float:
    """
    The monthly total below which the balance can only grow: one month of
    interest across every debt. Useful for telling a user how far short they
    are rather than just reporting failure.
    """
    return sum(d.balance * effective_apr(d, scra_active, cap) / 12.0
               for d in debts if d.balance > 0)


def simulate(debts: list[Debt], monthly_extra: float = 0.0,
             strategy: str = STRATEGY_AVALANCHE, scra_active: bool = False,
             scra_cap: float = SCRA_RATE_CAP,
             budget_override: float = 0.0) -> PayoffResult:
    """
    Run the payoff month by month.

    `monthly_extra` is what the household can put toward debt ABOVE the sum of
    the minimum payments. `budget_override`, if set, replaces the whole computed
    budget -- use it to compare a fixed total payment across strategies.
    """
    live = [Debt(**d.to_dict()) for d in debts if d.balance > 0]
    result = PayoffResult(strategy=strategy)
    result.starting_balance = sum(d.balance for d in live)

    if not live:
        return result

    budget = (budget_override if budget_override > 0
              else sum(d.minimum_payment for d in live) + monthly_extra)
    result.monthly_budget = budget

    # A budget that cannot cover one month's interest never retires anything.
    if budget <= minimum_viable_payment(live, scra_active, scra_cap):
        result.never_pays_off = [d.name for d in live]
        result.months = 0
        return result

    balances = {d.name: d.balance for d in live}
    total_interest = 0.0
    total_paid = 0.0

    for month in range(1, MAX_MONTHS + 1):
        active = [d for d in live if balances[d.name] > 0.005]
        if not active:
            result.months = month - 1
            break

        # 1. Accrue interest.
        month_interest = 0.0
        for d in active:
            rate = effective_apr(d, scra_active, scra_cap) / 12.0
            interest = balances[d.name] * rate
            balances[d.name] += interest
            month_interest += interest

        remaining_budget = budget
        month_principal = 0.0

        # 2. Minimums on everything except the attack target, which gets
        #    whatever is left after the others are covered.
        queue = [d for d in order_debts(active, strategy, scra_active, scra_cap)]
        target = queue[0]

        for d in queue[1:]:
            pay = min(d.minimum_payment, balances[d.name], remaining_budget)
            pay = max(0.0, pay)
            balances[d.name] -= pay
            remaining_budget -= pay
            month_principal += pay

        # 3. Everything left goes at the target, cascading to the next debt if
        #    the target is cleared mid-month.
        for d in queue:
            if remaining_budget <= 0:
                break
            if balances[d.name] <= 0.005:
                continue
            pay = min(balances[d.name], remaining_budget)
            balances[d.name] -= pay
            remaining_budget -= pay
            month_principal += pay

        total_interest += month_interest
        total_paid += month_principal
        for d in active:
            if balances[d.name] <= 0.005 and d.name not in result.payoff_month:
                result.payoff_month[d.name] = month
                balances[d.name] = 0.0

        result.schedule.append(MonthRow(
            month=month,
            total_balance=sum(max(0.0, b) for b in balances.values()),
            interest_paid=month_interest,
            principal_paid=month_principal,
            payment=month_principal,
            target=target.name,
        ))
    else:
        result.never_pays_off = [d.name for d in live
                                 if balances[d.name] > 0.005]
        result.months = MAX_MONTHS

    result.total_interest = total_interest
    result.total_paid = total_paid
    return result


@dataclass
class StrategyComparison:
    results: dict = field(default_factory=dict)     # strategy -> PayoffResult
    best_by_interest: str = ""
    best_by_speed: str = ""
    interest_gap: float = 0.0
    months_gap: int = 0
    scra_savings: float = 0.0
    scra_months_saved: int = 0


def compare_strategies(debts: list[Debt], monthly_extra: float = 0.0,
                       scra_active: bool = False,
                       scra_cap: float = SCRA_RATE_CAP) -> StrategyComparison:
    """
    Run avalanche and snowball on identical budgets, and price the SCRA cap.

    Avalanche always wins on arithmetic. Snowball wins often enough in practice
    -- people stick with it -- that quantifying the gap is more useful than
    declaring a winner: if the gap is small, the motivational method is the
    right recommendation.
    """
    out = StrategyComparison()
    for strategy in (STRATEGY_AVALANCHE, STRATEGY_SNOWBALL):
        out.results[strategy] = simulate(debts, monthly_extra, strategy,
                                         scra_active, scra_cap)

    solvable = {k: v for k, v in out.results.items() if v.is_solvable}
    if solvable:
        out.best_by_interest = min(solvable, key=lambda k: solvable[k].total_interest)
        out.best_by_speed = min(solvable, key=lambda k: solvable[k].months)
        interests = [v.total_interest for v in solvable.values()]
        months = [v.months for v in solvable.values()]
        out.interest_gap = max(interests) - min(interests)
        out.months_gap = max(months) - min(months)

    # What invoking SCRA is worth, on the better of the two methods.
    if any(d.incurred_before_service for d in debts):
        best = out.best_by_interest or STRATEGY_AVALANCHE
        without = simulate(debts, monthly_extra, best, scra_active=False)
        with_scra = simulate(debts, monthly_extra, best, scra_active=True,
                             scra_cap=scra_cap)
        if without.is_solvable and with_scra.is_solvable:
            out.scra_savings = without.total_interest - with_scra.total_interest
            out.scra_months_saved = without.months - with_scra.months

    return out


def payoff_findings(debts: list[Debt], comparison: StrategyComparison,
                    scra_active: bool) -> list[tuple[str, str, str]]:
    """
    Plain-language findings: (severity, headline, detail).
    Severity is one of good / warn / bad / info.
    """
    out = []
    if not debts:
        return out

    total = sum(d.balance for d in debts)
    if total <= 0:
        out.append(("good", "You have no consumer debt.",
                    "That clears step 3 of the priority waterfall. Every dollar "
                    "that would have gone to interest is now available to "
                    "invest."))
        return out

    avalanche = comparison.results.get(STRATEGY_AVALANCHE)
    snowball = comparison.results.get(STRATEGY_SNOWBALL)

    if avalanche and not avalanche.is_solvable:
        need = minimum_viable_payment(debts, scra_active)
        out.append(("bad", "At this payment level the debt never gets paid off.",
                    f"Your monthly budget of ${avalanche.monthly_budget:,.0f} is "
                    f"below the ${need:,.0f} of interest these balances accrue "
                    f"every month, so the total grows no matter how long you "
                    f"pay. You need at least ${need:,.0f} a month just to hold "
                    f"level. This is the situation Military OneSource financial "
                    f"counselling exists for, and it is free."))
        return out

    if avalanche and snowball:
        gap = comparison.interest_gap
        months_gap = comparison.months_gap
        if gap < 200 or (avalanche.total_interest > 0 and gap / avalanche.total_interest < 0.03):
            out.append(("info",
                        "Avalanche and snowball are within "
                        f"${gap:,.0f} of each other here.",
                        "The arithmetic barely separates them, so pick the one "
                        "you will actually stick to. Snowball clears your "
                        "smallest balance first, and the early win is worth more "
                        "than a rounding error in interest."))
        else:
            out.append(("good",
                        f"Avalanche saves ${gap:,.0f} and "
                        f"{months_gap} month(s) over snowball.",
                        "Attacking the highest rate first is meaningfully cheaper "
                        "at these balances. If you have tried and abandoned "
                        "avalanche before, snowball's early wins may still be the "
                        "better real-world choice — but this is what it costs."))

    high = [d for d in debts if d.apr >= 0.15 and d.balance > 0]
    if high:
        worst = max(high, key=lambda d: d.apr)
        out.append(("bad",
                    f"{worst.name} is at {worst.apr * 100:.1f}%.",
                    f"Paying this down is a guaranteed, tax-free "
                    f"{worst.apr * 100:.1f}% return. No investment offers that "
                    f"with certainty. It outranks everything except capturing "
                    f"your full TSP match, which is an immediate 100% return and "
                    f"beats any interest rate."))

    pre_service = [d for d in debts if d.incurred_before_service and d.apr > SCRA_RATE_CAP]
    if pre_service and comparison.scra_savings > 0:
        names = ", ".join(d.name for d in pre_service)
        out.append(("good",
                    f"Invoking SCRA on {names} would save "
                    f"${comparison.scra_savings:,.0f}.",
                    f"The Servicemembers Civil Relief Act caps interest at 6% on "
                    f"debts you took on BEFORE entering active duty, for as long "
                    f"as you serve. It is not automatic: write to each lender, "
                    f"include a copy of your orders, and ask for the cap. They "
                    f"must apply it retroactively to the start of your service "
                    f"and forgive the excess interest — not defer it. This is "
                    f"worth {comparison.scra_months_saved} month(s) off your "
                    f"payoff date."))
    elif pre_service and not scra_active:
        out.append(("warn",
                    "You may be leaving the SCRA interest cap on the table.",
                    "You have flagged debts as pre-service. Turn on the SCRA "
                    "option to see what capping them at 6% is worth."))

    payday = [d for d in debts if d.kind == "Payday / title loan"]
    if payday:
        out.append(("bad", "You have a payday or title loan.",
                    "The Military Lending Act caps most consumer credit to "
                    "service members and their dependents at a 36% Military "
                    "Annual Percentage Rate, and bans payday and title loans "
                    "secured by a vehicle title or a post-dated check for "
                    "covered borrowers. If you were sold one on active duty, the "
                    "contract may be void. Contact Military OneSource or your "
                    "installation legal assistance office before paying another "
                    "cent."))

    return out
