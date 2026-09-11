"""
Military pay, worked out and then handed back to be confirmed.

PAUL'S RULE, and the reason this module exists: "Base pay, BAS, and BAH is a
known quantity. Ask about special pays, and confirm the gross and net pay
amounts, as they may be affected by deduction amounts or something like a
garnishment."

So the app computes what a member of that grade, at that longevity, at that
ZIP code SHOULD be paid -- and it is right about the entitlements, because
they come off published tables:

    basic pay   grade + years of service      engine/pay/basepay.py
    BAS         grade                          engine/pay/bas.py
    BAH         duty ZIP + grade + dependants  engine/pay/bah.py

None of those is a question. What the app CANNOT see is the deductions column:
an allotment, a debt collection, a garnishment, a support order, a TSP loan
repayment. Any of those moves what actually arrives, and none of them is
derivable from anything on the plan. So the two figures a member is asked for
are the two the LES prints and a deduction moves -- GROSS and NET -- and they
are asked as a confirmation of the app's own arithmetic rather than as a form.

THE RESOLUTION RULE IS THE ONE THE APP ALREADY HAS.
`engine/pay/taxable.py::resolve_basic_monthly()` says it for basic pay: the LES
figure wins, the published table is the fallback. `resolve_gross_monthly()` and
`resolve_net_monthly()` below say it for the whole packet. A confirmed figure
of 0.0 means "not confirmed" and the computed figure stands.

WHAT NET MEANS HERE. Entitlements less the deductions the app can price:
the TSP election, the SGLI premium, FICA, and income tax withheld at the
standard deduction. It is an ESTIMATE and it is labelled as one everywhere it
is shown -- withholding follows a W-4 this app has never seen, and the whole
point of asking is that the real figure is on a document the member is holding.

This module imports from `engine.funnel`, `engine.pay`, `engine.tax` and
`engine.benefits`. It must never import `engine.intake` (which imports it),
`streamlit` or `ui.panel`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from engine.benefits import life_insurance as LI
from engine.pay import bah as BAH
from engine.pay import bas as BAS
from engine.pay import basepay as BP
from engine.pay import grades as G
from engine.profile import Household
from engine.tax import federal as F
from engine.tax import state as ST
from engine.tax import tables as T

SOURCE_COMPUTED = "the published tables"
SOURCE_CONFIRMED = "the figure you confirmed from your LES"

#: Below this, the member's figure and the app's agree for every purpose the
#: app has. Rounding, a mid-month rate change, a few cents of interest -- not
#: worth a paragraph of explanation. Above it, something is going on that the
#: member should be told about, because it is usually a deduction they can
#: name.
MATERIAL_GAP_MONTHLY = 25.0

# FICA. 6.2% Old-Age, Survivors and Disability Insurance plus 1.45% Hospital
# Insurance, on the member's share.
#
# CHECKED against 26 U.S.C. 3101(a) and (b). These two rates have not moved
# since 1990 and are the one part of a pay packet that does not need a fresh
# table every January. The OASDI wage base is NOT applied: it is an annual cap
# that only the most senior officers approach, this is a monthly figure, and
# applying it would need a base rate that does change every year. A member it
# binds on will see the app's net come out slightly low, and their own figure
# wins anyway.
FICA_OASDI_RATE = 0.062
FICA_MEDICARE_RATE = 0.0145
FICA_NOTE = ("FICA at 6.2 percent for Social Security and 1.45 percent for "
             "Medicare, on basic pay and taxable special pays. Allowances "
             "carry no FICA.")


@dataclass
class PayCheck:
    """One month of military pay, computed and then compared with the LES."""

    # ---- What the tables say you are paid ------------------------------
    basic: float = 0.0
    bas: float = 0.0
    bah: float = 0.0
    special_taxable: float = 0.0
    special_untaxed: float = 0.0
    basic_source: str = ""
    bah_source: str = ""

    # ---- What the tables say comes out again ---------------------------
    tsp: float = 0.0
    sgli: float = 0.0
    fica: float = 0.0
    federal_tax: float = 0.0
    state_tax: float = 0.0

    # ---- What the member confirmed, if anything ------------------------
    gross_confirmed: float = 0.0
    net_confirmed: float = 0.0

    notes: list = field(default_factory=list)

    # ------------------------------------------------------------------
    @property
    def taxable(self) -> float:
        """What lands on the W-2: basic pay and taxable special pays."""
        return self.basic + self.special_taxable

    @property
    def untaxed(self) -> float:
        """BAH, BAS and any non-taxable special pay. Outside income tax."""
        return self.bah + self.bas + self.special_untaxed

    @property
    def gross_computed(self) -> float:
        return self.taxable + self.untaxed

    @property
    def deductions_computed(self) -> float:
        return self.tsp + self.sgli + self.fica + self.federal_tax + self.state_tax

    @property
    def net_computed(self) -> float:
        return max(0.0, self.gross_computed - self.deductions_computed)

    @property
    def gross(self) -> float:
        """The gross the app should use. The confirmed figure wins."""
        return self.gross_confirmed if self.gross_confirmed > 0 else self.gross_computed

    @property
    def net(self) -> float:
        """The net the app should use. The confirmed figure wins."""
        return self.net_confirmed if self.net_confirmed > 0 else self.net_computed

    @property
    def gross_source(self) -> str:
        return SOURCE_CONFIRMED if self.gross_confirmed > 0 else SOURCE_COMPUTED

    @property
    def net_source(self) -> str:
        return SOURCE_CONFIRMED if self.net_confirmed > 0 else SOURCE_COMPUTED

    @property
    def gross_gap(self) -> float:
        """Confirmed less computed. Negative means less arrives than the tables say."""
        return (self.gross_confirmed - self.gross_computed
                if self.gross_confirmed > 0 else 0.0)

    @property
    def net_gap(self) -> float:
        return (self.net_confirmed - self.net_computed
                if self.net_confirmed > 0 else 0.0)

    def gross_is_material(self) -> bool:
        return abs(self.gross_gap) >= MATERIAL_GAP_MONTHLY

    def net_is_material(self) -> bool:
        return abs(self.net_gap) >= MATERIAL_GAP_MONTHLY

    def entitlement_rows(self) -> list[tuple[str, float]]:
        rows = [("Basic pay", self.basic), ("BAS", self.bas)]
        if self.bah:
            rows.append(("BAH", self.bah))
        if self.special_taxable:
            rows.append(("Special pays, taxable", self.special_taxable))
        if self.special_untaxed:
            rows.append(("Special pays, untaxed", self.special_untaxed))
        return rows

    def deduction_rows(self) -> list[tuple[str, float]]:
        return [("TSP contribution", self.tsp),
                ("SGLI premium", self.sgli),
                ("FICA", self.fica),
                ("Federal income tax, estimated", self.federal_tax),
                ("State income tax, estimated", self.state_tax)]


def _is_officer(m) -> bool:
    try:
        return G.is_officer(G.get(m.grade))
    except KeyError:
        return False


def _federal_monthly(annual_taxable: float, married: bool) -> float:
    """
    Income tax on military wages alone, at the standard deduction.

    A W-4 is not on the plan and never will be, so this is the honest middle:
    the tax a member with no other income and no adjustments would owe on
    these wages. It is labelled an estimate wherever it is shown, and it is
    the piece the member's own net figure is most likely to disagree with.
    """
    status = T.MFJ if married else T.SINGLE
    over = max(0.0, annual_taxable - T.STANDARD_DEDUCTION_2026[status])
    return F.bracket_tax(over, T.FEDERAL_BRACKETS_2026[status]) / 12.0


def _state_monthly(annual_taxable: float, state: str) -> float:
    """
    State tax at the domicile's effective rate. SCRA: the duty state does not
    tax military pay, so this reads the state of legal residence and no other.
    """
    rule = ST.get_rule(state or "")
    return max(0.0, annual_taxable) * max(0.0, rule.rate) / 12.0


def compute(h: Household, today: date | None = None) -> PayCheck:
    """
    A month of pay for a serving member: entitlements, deductions, and the gap.

    Not gated on the funnel -- it is gated on being paid. A veteran or retiree
    has no LES and gets an empty packet.
    """
    m = h.member
    p = PayCheck()
    if not m.is_serving:
        p.notes.append("No military pay: you are not serving.")
        return p

    bp = BP.lookup(m.grade, m.years_of_service, BP.load(),
                   override_monthly=m.basic_pay_monthly_override)
    p.basic = bp.monthly if bp.found else 0.0
    p.basic_source = bp.note or ""
    if not bp.found:
        p.notes.append(BP.MISSING_DATA_NOTE)

    p.bas = m.bas_monthly_override or BAS.bas_monthly(_is_officer(m)).monthly

    if m.lives_in_government_housing:
        p.bah = 0.0
        p.bah_source = ("You live in government housing, so the allowance is "
                        "paid to the housing partner rather than to you.")
    elif m.bah_monthly_override > 0:
        p.bah = float(m.bah_monthly_override)
        p.bah_source = "From your LES."
    else:
        r = BAH.lookup_or_average(m.duty_zip, m.grade, m.has_dependents,
                                  BAH.load())
        p.bah = r.monthly if r.found else 0.0
        p.bah_source = r.note or (r.mha_name or "")

    special = max(0.0, float(m.special_pay_monthly or 0.0))
    if m.special_pay_taxable:
        p.special_taxable = special
    else:
        p.special_untaxed = special

    # ---- the deductions column, as far as the app can see it ------------
    p.tsp = p.basic * max(0.0, float(m.tsp_contribution_pct or 0.0))
    p.sgli = LI.sgli_monthly(float(m.sgli_coverage or 0.0))
    p.fica = p.taxable * (FICA_OASDI_RATE + FICA_MEDICARE_RATE)
    p.federal_tax = _federal_monthly(p.taxable * 12.0, bool(h.has_spouse))
    p.state_tax = _state_monthly(p.taxable * 12.0, h.state_of_legal_residence)

    p.gross_confirmed = max(0.0, float(m.gross_pay_monthly_confirmed or 0.0))
    p.net_confirmed = max(0.0, float(m.net_pay_monthly_confirmed or 0.0))
    return p


def resolve_gross_monthly(h: Household) -> tuple[float, str]:
    """The gross to use, and where it came from. The confirmed figure wins."""
    p = compute(h)
    return p.gross, p.gross_source


def resolve_net_monthly(h: Household) -> tuple[float, str]:
    """The net to use, and where it came from. The confirmed figure wins."""
    p = compute(h)
    return p.net, p.net_source


def derive_gross(h: Household) -> float | None:
    """What the tables make the gross. None when there is no military pay."""
    p = compute(h)
    return p.gross_computed if h.member.is_serving else None


def derive_net(h: Household) -> float | None:
    """What the tables make the net, before anything the app cannot see."""
    p = compute(h)
    return p.net_computed if h.member.is_serving else None


def _money(x: float) -> str:
    return f"{x:,.0f} dollars"


def findings(h: Household) -> list[tuple[str, str, str]]:
    """
    What to say about the gap, as (severity, headline, detail) triples.

    Silence when the two figures agree, because a difference inside rounding
    is not worth a paragraph. When they do not agree, the member's figure is
    the one in use and the app says so rather than quietly dropping either.
    """
    out: list[tuple[str, str, str]] = []
    if not h.member.is_serving:
        return out
    p = compute(h)

    for name, gap, used, material in (
            ("gross", p.gross_gap, p.gross, p.gross_is_material()),
            ("net", p.net_gap, p.net, p.net_is_material())):
        if gap == 0.0:
            continue
        if not material:
            out.append(("good",
                        f"Your {name} pay matches what the app worked out",
                        f"Within {_money(MATERIAL_GAP_MONTHLY)} a month, which "
                        f"is rounding. The app is using your figure, "
                        f"{_money(used)} a month."))
            continue
        direction = "less than" if gap < 0 else "more than"
        cause = ("a deduction, an allotment or a garnishment — the app cannot "
                 "see the deductions column of an LES"
                 if gap < 0 else
                 "a special pay, a bonus or an allowance the app has not been "
                 "told about")
        out.append(("warn",
                    f"Your {name} pay is {_money(abs(gap))} a month "
                    f"{direction} the tables produce",
                    f"The app is using your figure, {_money(used)} a month, "
                    f"not its own. A difference that size is usually {cause}. "
                    f"It is worth knowing which, because it is money leaving "
                    f"every month."))
    return out


def statement(h: Household) -> list[tuple[str, str]]:
    """
    The pay packet as rows of (label, figure), for the confirmation step.

    Read-only on purpose: Paul's rule is that this is a confirmation, not a
    form. The only two widgets on the card are the gross and the net.
    """
    if not h.member.is_serving:
        return []
    p = compute(h)
    rows = [(label, f"{value:,.2f}") for label, value in p.entitlement_rows()]
    rows.append(("Taxable", f"{p.taxable:,.2f}"))
    rows.append(("Untaxed", f"{p.untaxed:,.2f}"))
    rows.append(("Gross", f"{p.gross_computed:,.2f}"))
    rows += [(label, f"-{value:,.2f}" if value else f"{0.0:,.2f}")
             for label, value in p.deduction_rows()]
    rows.append(("Net, estimated", f"{p.net_computed:,.2f}"))
    return rows
