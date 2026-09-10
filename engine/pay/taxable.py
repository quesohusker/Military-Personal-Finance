"""
Taxable military pay, computed once and used everywhere.

Two pages used to disagree about this number. The Pay page worked it out
from the tables; the residency page asked the user to type it in, defaulting
to a round $60,000. A state-income-tax comparison run on a typed guess is not
a comparison, so the figure is now derived here and both pages read it.

WHAT COUNTS. Basic pay and taxable special pays, monthly, times twelve, plus
any bonus for the year. Bonuses are the piece people forget: a re-enlistment
bonus is ordinary taxable income in the year it is paid, and it is often the
single largest taxable event of a career -- unless it is paid while the
member is in a combat zone, in which case it is excluded entirely. That is
why re-enlistment is timed to deployments.

WHAT DOES NOT. BAH and BAS, which are outside federal and state income tax
alike. A retiree has no military pay; retired pay is a separate stream with
its own state rules, so it is returned separately.

This is the figure BEFORE the Combat Zone Tax Exclusion. The domicile
comparison wants the amount at stake in a normal year; the deployment page
handles the exclusion.
"""

from __future__ import annotations
from dataclasses import dataclass, field

from engine.pay import basepay as BP

SOURCE_LES = "your LES"
SOURCE_TABLE = "the pay table"
SOURCE_NONE = "not found — enter it on the Pay page"
SOURCE_NOT_SERVING = "no military pay (not serving)"


@dataclass
class TaxablePay:
    basic_monthly: float = 0.0
    basic_source: str = SOURCE_NONE
    special_monthly_taxable: float = 0.0
    bonus_annual: float = 0.0
    notes: list = field(default_factory=list)

    @property
    def monthly(self) -> float:
        return self.basic_monthly + self.special_monthly_taxable

    @property
    def annual(self) -> float:
        return self.monthly * 12.0 + self.bonus_annual

    @property
    def serving(self) -> bool:
        return self.basic_source != SOURCE_NOT_SERVING

    def lines(self) -> list[tuple[str, float]]:
        if not self.serving:
            return []
        out = [(f"Basic pay, from {self.basic_source}, x 12",
                self.basic_monthly * 12.0)]
        if self.special_monthly_taxable:
            out.append(("Taxable special pays x 12",
                        self.special_monthly_taxable * 12.0))
        if self.bonus_annual:
            out.append(("Bonuses this year", self.bonus_annual))
        return out

    def describe(self) -> str:
        if not self.serving:
            return ("No military pay: you are not serving. The comparison "
                    "runs on the retired pay entered on Who I am.")
        parts = [f"{label}: ${amt:,.0f}" for label, amt in self.lines()]
        return (" + ".join(parts)
                + f" = ${self.annual:,.0f} a year, before any combat-zone "
                "exclusion. BAH and BAS are not in it.")


def resolve_basic_monthly(m) -> tuple[float, str]:
    """The LES figure wins; the published table is the fallback."""
    if not m.is_serving:
        return 0.0, SOURCE_NOT_SERVING
    if m.basic_pay_monthly_override > 0:
        return float(m.basic_pay_monthly_override), SOURCE_LES
    table = BP.load()
    if table is None:
        return 0.0, SOURCE_NONE
    r = BP.lookup(m.grade, m.years_of_service, table)
    return (r.monthly, SOURCE_TABLE) if r.found else (0.0, SOURCE_NONE)


def compute(m) -> TaxablePay:
    basic, src = resolve_basic_monthly(m)
    t = TaxablePay(
        basic_monthly=basic, basic_source=src,
        special_monthly_taxable=(float(m.special_pay_monthly)
                                 if m.special_pay_taxable else 0.0),
        bonus_annual=float(getattr(m, "bonus_annual_taxable", 0.0) or 0.0))
    if src == SOURCE_NONE:
        t.notes.append("Basic pay could not be looked up for this grade and "
                       "length of service. Enter it from your LES on the "
                       "Pay page.")
    if m.special_pay_monthly and not m.special_pay_taxable:
        t.notes.append("Special pays are marked non-taxable, so they are left "
                       "out of this figure.")
    return t


def annual_retired_pay(m) -> float:
    """Retired pay is its own stream; zero means it has not been entered."""
    return float(m.retired_pay_monthly) * 12.0
