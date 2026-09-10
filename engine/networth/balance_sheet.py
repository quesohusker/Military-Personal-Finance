"""
Net worth, with the military pension valued as the asset it is.

A civilian planner shows a 20-year retiree a modest balance sheet and a scary
withdrawal rate. That picture is wrong, because the largest asset the household
owns is missing from it: an inflation-indexed, government-backed, lifetime
annuity, plus (often) a tax-free VA disability stream on top.

Valuing them changes two things materially:

  * The balance sheet stops understating the household. A retired O-5's pension
    alone is commonly worth more in present value than their entire TSP.
  * Asset allocation changes. A COLA'd pension behaves like a very large
    inflation-protected bond holding. A retiree whose essential spending is
    already covered by pension plus VA can rationally hold far more equity than
    the standard rule of thumb implies -- the sequence risk that rule exists to
    manage simply is not there for the covered portion.

IMPORTANT, AND STATED WHEREVER THE NUMBER APPEARS: putting a pension on a
balance sheet is a contested practice. Not all advisors do it, and the
objections are legitimate. See VALUATION_CAVEAT below.
"""

from __future__ import annotations
from dataclasses import dataclass, field, asdict


# --------------------------------------------------------------------------
# Annuity valuation
# --------------------------------------------------------------------------

DEFAULT_REAL_DISCOUNT = 0.03

VALUATION_CAVEAT = (
    "**Treating a pension as a balance sheet asset is not a universally "
    "accepted practice, and the objections are fair ones.**\n\n"
    "- **There is no cash-out value.** You cannot sell it, borrow against it, "
    "pledge it as collateral, or leave it to an heir. It stops when you do "
    "(reduced to whatever SBP you elected).\n"
    "- **You cannot buy one either.** No commercial product matches it. A "
    "true inflation-indexed lifetime annuity is barely sold in the US retail "
    "market at any price, so the figure below is a reasoned estimate of what "
    "an equivalent would cost, not a market quote.\n"
    "- **It is not fungible with savings.** A dollar of portfolio can be spent "
    "today, moved, or given away. A dollar of pension arrives monthly and only "
    "monthly. Adding them produces a number that is useful for one purpose and "
    "misleading for others.\n\n"
    "**What the number does tell you:** roughly what it would cost to buy an "
    "income stream paying the same inflation-adjusted amount, from your age to "
    "your assumed life expectancy. That is a comparison — a way to see the "
    "scale of what you have earned against the scale of your portfolio — and "
    "it is the right frame for two specific decisions: how much equity risk "
    "your portfolio can carry, and whether a lump-sum buyout offer is fair.\n\n"
    "**Do not** use it as a spendable balance, in a withdrawal-rate "
    "calculation, or as an estate figure."
)

SHORT_CAVEAT = ("A replacement-cost estimate, not a cash value. You cannot "
                "sell this, borrow against it, or leave it to an heir — and "
                "you could not buy an equivalent at any price.")


def annuity_present_value(annual_amount: float, years: float,
                          real_discount_rate: float = DEFAULT_REAL_DISCOUNT,
                          deferral_years: float = 0.0) -> float:
    """
    Present value of a COLA-adjusted annuity, in real terms.

    Because military retired pay and VA compensation are both indexed to
    inflation, they are valued with a REAL discount rate and a level real
    payment. Discounting a COLA'd stream at a nominal rate understates it
    badly -- that error is what makes the BRS lump-sum offer look reasonable.
    """
    if annual_amount <= 0 or years <= 0:
        return 0.0
    r = real_discount_rate
    n = years
    if abs(r) < 1e-9:
        pv = annual_amount * n
    else:
        pv = annual_amount * (1.0 - (1.0 + r) ** -n) / r
    if deferral_years > 0:
        pv /= (1.0 + r) ** deferral_years
    return pv


@dataclass
class IncomeStreamValue:
    label: str = ""
    annual_amount: float = 0.0
    years: float = 0.0
    deferral_years: float = 0.0
    present_value: float = 0.0      # replacement cost, NOT a cash value
    is_taxable: bool = True
    note: str = ""

    @property
    def replacement_cost(self) -> float:
        """Preferred name. 'Present value' invites reading it as a balance."""
        return self.present_value


# --------------------------------------------------------------------------
# Balance sheet
# --------------------------------------------------------------------------

@dataclass
class BalanceSheet:
    # Liquid
    cash: float = 0.0
    taxable_brokerage: float = 0.0

    # Retirement, pre-tax
    tsp_traditional: float = 0.0
    ira_traditional: float = 0.0

    # Retirement, after-tax
    tsp_roth: float = 0.0
    ira_roth: float = 0.0

    # Other
    sdp_balance: float = 0.0
    home_value: float = 0.0
    vehicles: float = 0.0
    other_assets: float = 0.0

    # Liabilities
    mortgage_balance: float = 0.0
    consumer_debt: float = 0.0
    vehicle_debt: float = 0.0
    other_debt: float = 0.0

    # Income streams, valued separately
    streams: list = field(default_factory=list)

    # Assumed rate applied to pre-tax balances when reporting after-tax worth
    embedded_tax_rate: float = 0.22

    # ------------------------------------------------------------------
    @property
    def liquid_assets(self) -> float:
        return self.cash + self.taxable_brokerage + self.sdp_balance

    @property
    def pretax_retirement(self) -> float:
        return self.tsp_traditional + self.ira_traditional

    @property
    def aftertax_retirement(self) -> float:
        return self.tsp_roth + self.ira_roth

    @property
    def retirement_assets(self) -> float:
        return self.pretax_retirement + self.aftertax_retirement

    @property
    def investable_assets(self) -> float:
        """What is actually available to invest -- excludes the house and cars."""
        return self.liquid_assets + self.retirement_assets

    @property
    def total_assets(self) -> float:
        return (self.investable_assets + self.home_value + self.vehicles
                + self.other_assets)

    @property
    def total_liabilities(self) -> float:
        return (self.mortgage_balance + self.consumer_debt + self.vehicle_debt
                + self.other_debt)

    @property
    def net_worth(self) -> float:
        return self.total_assets - self.total_liabilities

    @property
    def embedded_tax(self) -> float:
        """Tax owed on pre-tax balances -- money on the balance sheet you do not own."""
        return self.pretax_retirement * self.embedded_tax_rate

    @property
    def net_worth_after_tax(self) -> float:
        return self.net_worth - self.embedded_tax

    @property
    def liquid_net_worth(self) -> float:
        """Excludes illiquid property; a better measure of resilience."""
        return self.investable_assets - self.consumer_debt - self.vehicle_debt

    @property
    def home_equity(self) -> float:
        return self.home_value - self.mortgage_balance

    @property
    def streams_present_value(self) -> float:
        return sum(s.present_value for s in self.streams)

    @property
    def net_worth_with_streams(self) -> float:
        """
        Net worth plus the estimated replacement cost of guaranteed income.

        This is a COMPARISON FIGURE, not a balance. It answers "what is the
        scale of what I have earned against the scale of my portfolio", which
        is the right question for allocation and for judging a buyout offer.
        It is the wrong number for a withdrawal rate, for estate planning, or
        for anything that assumes the money can be spent. See VALUATION_CAVEAT.
        """
        return self.net_worth_after_tax + self.streams_present_value

    def to_dict(self) -> dict:
        d = asdict(self)
        d["derived"] = {
            "total_assets": self.total_assets,
            "total_liabilities": self.total_liabilities,
            "net_worth": self.net_worth,
            "net_worth_after_tax": self.net_worth_after_tax,
            "liquid_net_worth": self.liquid_net_worth,
            "streams_present_value": self.streams_present_value,
            "net_worth_with_streams": self.net_worth_with_streams,
        }
        return d


# --------------------------------------------------------------------------
# Building one from a household
# --------------------------------------------------------------------------

def from_household(h, life_expectancy: int = 90,
                   real_discount_rate: float = DEFAULT_REAL_DISCOUNT,
                   current_year: int = 2026) -> BalanceSheet:
    """Assemble a balance sheet, valuing pension and VA streams where present."""
    from engine.debt.payoff import Debt  # local import avoids a cycle

    bs = BalanceSheet(
        cash=h.cash_savings,
        taxable_brokerage=h.taxable_brokerage,
        home_value=h.home_value,
        mortgage_balance=h.mortgage_balance,
        vehicles=h.vehicles_value,
        other_assets=h.other_assets,
    )

    for p in h.people():
        bs.tsp_traditional += p.tsp_traditional_balance
        bs.tsp_roth += p.tsp_roth_balance
        bs.ira_traditional += p.ira_traditional_balance
        bs.ira_roth += p.ira_roth_balance
        bs.sdp_balance += p.sdp_balance

    for d in h.debts:
        if d.balance <= 0:
            continue
        if d.kind == "Mortgage":
            bs.mortgage_balance += d.balance
        elif d.kind == "Auto loan":
            bs.vehicle_debt += d.balance
        elif d.kind in ("Credit card", "Personal loan", "Medical",
                        "Payday / title loan"):
            bs.consumer_debt += d.balance
        else:
            bs.other_debt += d.balance

    m = h.member
    age = m.age(current_year)
    years_left = max(0.0, life_expectancy - age)

    if m.retired_pay_monthly > 0 and years_left > 0:
        annual = m.retired_pay_monthly * 12.0
        pv = annuity_present_value(annual, years_left, real_discount_rate)
        bs.streams.append(IncomeStreamValue(
            label="Military retired pay", annual_amount=annual,
            years=years_left, present_value=pv, is_taxable=True,
            note=("A lifetime income stream indexed to inflation and backed by "
                  "the federal government. Valued with a real discount rate "
                  "because the payment keeps pace with prices — discounting a "
                  "COLA'd stream at a nominal rate is exactly what makes "
                  "lump-sum buyout offers look reasonable when they are not. "
                  + SHORT_CAVEAT)))

    va = m.va_disability_monthly * 12.0
    if va > 0 and years_left > 0:
        pv = annuity_present_value(va, years_left, real_discount_rate)
        bs.streams.append(IncomeStreamValue(
            label="VA disability compensation", annual_amount=va,
            years=years_left, present_value=pv, is_taxable=False,
            note=("Tax-free at federal and state level, and indexed to "
                  "inflation. Because it never appears in AGI it also leaves "
                  "room under the thresholds that govern Social Security "
                  "taxation, IRMAA and capital gains rates — worth more than an "
                  "equivalent taxable amount.")))

    crsc = m.crsc_monthly * 12.0
    if crsc > 0 and years_left > 0:
        bs.streams.append(IncomeStreamValue(
            label="CRSC (tax-free)", annual_amount=crsc, years=years_left,
            present_value=annuity_present_value(crsc, years_left, real_discount_rate),
            is_taxable=False))

    return bs


# --------------------------------------------------------------------------
# Findings
# --------------------------------------------------------------------------

def _money(x: float) -> str:
    sign = "-" if x < 0 else ""
    return f"{sign}${abs(x):,.0f}"


def findings(bs: BalanceSheet, h=None) -> list[tuple[str, str, str]]:
    """(severity, headline, detail) -- severity is good / warn / bad / info."""
    out = []

    if bs.net_worth < 0:
        out.append(("bad", f"Your net worth is {_money(bs.net_worth)}.",
                    "You owe more than you own. That is common early in a "
                    "career, especially after a car purchase, and it is fixable "
                    "— but it means the priority waterfall matters more than "
                    "any investment decision right now."))

    if bs.streams:
        pv = bs.streams_present_value
        out.append(("info",
                    f"Replacing your guaranteed income would cost roughly "
                    f"{_money(pv)}.",
                    "That is an estimate of what an equivalent inflation-"
                    "adjusted lifetime income, from your age to your assumed "
                    "life expectancy, would cost to buy. **It is not a cash "
                    "value.** You cannot sell it, borrow against it or leave it "
                    "to an heir, and you could not purchase an equivalent at "
                    "any price — true inflation-indexed lifetime annuities are "
                    "barely sold at retail. Not every advisor puts this on a "
                    "balance sheet and the objection is a fair one. It is shown "
                    "because leaving it out entirely understates what you have "
                    "earned, and because it is the right frame for two "
                    "questions: how much equity risk your portfolio can carry, "
                    "and whether a buyout offer is fair."))

        if bs.investable_assets > 0 and pv > bs.investable_assets:
            out.append(("info",
                        "Replacing your guaranteed income would cost more than "
                        "your entire portfolio.",
                        f"{_money(pv)} of pension and benefits against "
                        f"{_money(bs.investable_assets)} of investable assets. "
                        f"That has a real consequence for allocation: a COLA'd "
                        f"pension behaves like a very large inflation-protected "
                        f"bond position. If it already covers your essential "
                        f"spending, the standard advice to de-risk with age is "
                        f"managing a sequence risk you do not have on that "
                        f"portion."))

    if bs.pretax_retirement > 0:
        share = bs.pretax_retirement / bs.retirement_assets if bs.retirement_assets else 0
        if share > 0.7:
            out.append(("warn",
                        f"{share * 100:.0f}% of your retirement savings is pre-tax.",
                        f"About {_money(bs.embedded_tax)} of that balance is "
                        f"tax you have not paid yet, at an assumed "
                        f"{bs.embedded_tax_rate * 100:.0f}%. Your pension is a "
                        f"taxable income floor that never goes away, so those "
                        f"withdrawals stack on top of it rather than filling "
                        f"empty low brackets."))

    if bs.consumer_debt > 0 and bs.liquid_assets < bs.consumer_debt:
        out.append(("warn",
                    "Your consumer debt exceeds your liquid savings.",
                    f"{_money(bs.consumer_debt)} owed against "
                    f"{_money(bs.liquid_assets)} available. An unplanned expense "
                    f"has nowhere to go except more debt."))

    if bs.home_value > 0:
        eq = bs.home_equity
        if eq < 0:
            out.append(("bad", "You are underwater on your home.",
                        f"The mortgage exceeds the value by {_money(-eq)}. With "
                        f"selling costs of 6-9% on top, a PCS in the near term "
                        f"would mean bringing cash to closing. Worth knowing "
                        f"before orders arrive rather than after."))
        elif bs.home_value > 0 and eq / bs.home_value < 0.08:
            out.append(("warn", "You have very little equity in your home.",
                        f"{_money(eq)} on a {_money(bs.home_value)} property. "
                        f"Selling costs alone would consume it. A VA loan with "
                        f"nothing down and the funding fee financed starts you "
                        f"roughly 2-3% underwater, so this is the normal "
                        f"position for the first few years — it is only a "
                        f"problem if you have to move."))

    if bs.vehicles > 0 and bs.vehicle_debt > bs.vehicles:
        out.append(("warn", "You owe more on your vehicles than they are worth.",
                    f"{_money(bs.vehicle_debt)} of debt against "
                    f"{_money(bs.vehicles)} of value. Rolling negative equity "
                    f"into the next purchase is how this compounds. Predatory "
                    f"auto lending near installations is a documented problem "
                    f"and the Military Lending Act caps covered credit at 36%."))

    return out
