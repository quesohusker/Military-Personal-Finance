"""
Estate — beneficiaries, wills, inheritance tax and gifting.

THE ONE THING TO TAKE FROM THIS MODULE: a beneficiary designation overrides a
will. Every dollar in the TSP, in SGLI and in an IRA passes by the form on
file at the plan administrator, not by whatever the will says, and no probate
court reads either one first. A will that leaves "everything to my wife" does
not move a cent of a TSP still naming a mother from basic training or a spouse
from a marriage that ended in 2011.

That is not a hypothetical. It is the single most common estate disaster in
military families, because the paperwork is done once at accession, at a desk,
in a stack of forty other forms, and then never touched again through two
marriages and three children. The Supreme Court has been explicit that the
form wins: in Ridgway v. Ridgway, 454 U.S. 46 (1981) SGLI proceeds went to the
named beneficiary even though a state divorce decree had ordered them held for
the children of the first marriage. Federal law preempts the decree. The
person on the form is paid.

WHAT ELSE IS HERE

  * Wills and powers of attorney, which are FREE at any installation legal
    assistance office (10 U.S.C. 1044) for anyone serving and for retirees on
    a space-available basis. A military testamentary instrument prepared there
    is exempt from state formality requirements (10 U.S.C. 1044d) and must be
    given the same effect as a will executed under state law. There is no
    financial reason for a service member not to have a will.

  * Inheritance taxation. A traditional TSP or IRA left to anyone other than a
    spouse falls under the SECURE Act ten-year rule and is fully taxable at the
    HEIR's marginal rate. That is the strongest estate argument for Roth
    conversions there is, and it is stronger for a military retiree than for
    almost anyone else, because the pension keeps the retiree's own bracket
    high enough that the usual "convert in the empty years" advice never gets a
    cheap window. See pages/14_Roth_Conversions.py for the lifetime analysis;
    this module only prices what the heir loses.

  * Federal estate tax, which almost no military family will ever pay, and the
    state estate and inheritance taxes, which some will. Naming the states is
    the useful part.

  * Gifting: the annual exclusion, Form 709, the 529 five-year election, and
    the Roth IRA for a child with a summer job.

EVERY FIGURE IS REAL — today's dollars — like the rest of the app, and every
hard-coded statutory number carries a VERIFY note in VERIFY below. This machine
cannot reach irs.gov, so the figures are stated from knowledge with their
confidence recorded rather than presented as checked.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from engine import mortality as MORT
from engine.benefits.life_insurance import SGLI_MAX

# --------------------------------------------------------------------------
# 2026 statutory figures. ONE place. Every entry has a VERIFY note below.
# --------------------------------------------------------------------------

FIGURE_YEAR = 2026

# Basic exclusion amount per person, unified for gift and estate tax.
FEDERAL_ESTATE_EXEMPTION = 15_000_000.0
ESTATE_TAX_TOP_RATE = 0.40

# Annual gift tax exclusion, per recipient, per donor, per year.
ANNUAL_GIFT_EXCLUSION = 19_000.0

# Gifts to a spouse who is not a US citizen get no unlimited marital
# deduction, only this much a year. Relevant far more often in military
# families than in the general population.
NON_CITIZEN_SPOUSE_ANNUAL_EXCLUSION = 194_000.0

# IRC 529(c)(2)(B): five years of annual exclusion in one contribution.
SUPERFUND_YEARS = 5

# SECURE Act (2019): a designated beneficiary who is not an "eligible
# designated beneficiary" must empty an inherited retirement account by
# 31 December of the tenth year after the year of death.
SECURE_DRAIN_YEARS = 10

DEFAULT_HEIR_MARGINAL_RATE = 0.24

VERIFY = {
    "FEDERAL_ESTATE_EXEMPTION": (
        "VERIFY at irs.gov: 2026 basic exclusion amount, $15,000,000 per "
        "person. Set by the 2025 reconciliation act (P.L. 119-21) for "
        "decedents dying and gifts made after 2025, indexed for inflation "
        "thereafter. This REPLACED the scheduled 31 Dec 2025 TCJA sunset that "
        "would have cut the exemption roughly in half — a great deal of "
        "published planning advice still assumes that sunset happened. "
        "Confidence HIGH on the figure, MEDIUM that no later change applies."),
    "ESTATE_TAX_TOP_RATE": (
        "VERIFY at irs.gov: top federal estate and gift tax rate, 40%. "
        "Unchanged since 2013. Confidence HIGH."),
    "ANNUAL_GIFT_EXCLUSION": (
        "VERIFY at irs.gov: 2026 annual gift tax exclusion, $19,000 per "
        "recipient per donor (Rev. Proc. 2025-32). It is indexed but rounded "
        "down to the nearest $1,000, so it holds still for a year or two at a "
        "time — it was $18,000 in 2024 and $19,000 in 2025. "
        "Confidence MEDIUM-HIGH."),
    "NON_CITIZEN_SPOUSE_ANNUAL_EXCLUSION": (
        "VERIFY at irs.gov: 2026 annual exclusion for gifts to a non-citizen "
        "spouse, $194,000 (it was $190,000 in 2025). Confidence MEDIUM-LOW — "
        "check this one before relying on it."),
    "SUPERFUND_YEARS": (
        "IRC 529(c)(2)(B). Five years of annual exclusion may be elected on "
        "one 529 contribution, so $95,000 per beneficiary per donor in 2026 "
        "and $190,000 from a married couple electing to split. Derived from "
        "the annual exclusion, so it inherits that figure's confidence."),
    "SECURE_DRAIN_YEARS": (
        "SECURE Act of 2019, sec. 401. Ten years for a non-eligible "
        "designated beneficiary. Confidence HIGH."),
    "STATE_ESTATE_TAX": (
        "VERIFY with each state's revenue department: which states levy their "
        "own estate or inheritance tax, and at what threshold. The list moves "
        "— Iowa finished phasing its inheritance tax out on 1 Jan 2025 and "
        "Washington raised its exclusion in 2025. Thresholds here are "
        "approximate and unindexed ones drift in real terms every year. "
        "Confidence MEDIUM on the membership of the list, MEDIUM-LOW on the "
        "individual thresholds."),
}


# --------------------------------------------------------------------------
# State death taxes. The federal exemption is irrelevant to almost every
# military family; these are not.
# --------------------------------------------------------------------------

# state -> (approximate exemption, note). VERIFY: see VERIFY["STATE_ESTATE_TAX"].
STATE_ESTATE_TAX = {
    "Oregon": (1_000_000.0, "the lowest threshold in the country, and not indexed"),
    "Massachusetts": (2_000_000.0, "raised from $1M in 2023"),
    "Rhode Island": (1_800_000.0, "indexed, roughly $1.8M"),
    "Washington": (3_000_000.0, "raised to about $3M in 2025; top rate 35%"),
    "Minnesota": (3_000_000.0, "not indexed"),
    "Illinois": (4_000_000.0, "not indexed"),
    "Maryland": (5_000_000.0, "also levies an inheritance tax"),
    "Vermont": (5_000_000.0, ""),
    "Maine": (7_000_000.0, "indexed"),
    "New York": (7_200_000.0, "a 'cliff' — exceed it by more than 5% and the "
                              "whole estate is taxed, not just the excess"),
    "Connecticut": (15_000_000.0, "matched to the federal exemption"),
    "Hawaii": (5_500_000.0, ""),
    "District of Columbia": (4_900_000.0, ""),
}

# Paid by the RECIPIENT, on what they receive, usually with the rate set by how
# closely related they are. A spouse is exempt everywhere; children are exempt
# in every one of these except Pennsylvania (4.5%) and Nebraska (1%).
STATE_INHERITANCE_TAX = {
    "Kentucky": "children and spouses exempt; siblings, nieces and nephews are not",
    "Maryland": "10% on collateral heirs; spouse and children exempt",
    "Nebraska": "1% on children above a small exemption; higher on remoter heirs",
    "New Jersey": "spouse and children exempt; siblings and others are not",
    "Pennsylvania": "4.5% on transfers to children, 12% to siblings, 15% to others",
}

# A surviving spouse in a community property state gets a step-up in basis on
# BOTH halves of community property, not just the decedent's half. Three of
# these are the classic military domicile choices, so this is worth more to
# service members than to the general population.
COMMUNITY_PROPERTY_STATES = (
    "Arizona", "California", "Idaho", "Louisiana", "Nevada", "New Mexico",
    "Texas", "Washington", "Wisconsin",
)

# 5 U.S.C. 8424(d), applied by the TSP when no valid designation is on file.
TSP_ORDER_OF_PRECEDENCE = (
    "Your spouse",
    "Your children in equal shares, and the descendants of any who died first",
    "Your parents in equal shares, or the survivor of them",
    "The appointed executor or administrator of your estate",
    "Your next of kin under the law of the state where you lived",
)

# 38 U.S.C. 1970(a), applied to SGLI when no valid SGLV 8286 is on file.
SGLI_ORDER_OF_PRECEDENCE = (
    "Your spouse",
    "Your children in equal shares, and the descendants of any who died first",
    "Your parents in equal shares, or the survivor of them",
    "The executor or administrator of your estate",
    "Your next of kin under the law of the state where you lived",
)

LEGAL_ASSISTANCE = (
    "A will, a general power of attorney, a special power of attorney and an "
    "advance medical directive are all free at any installation legal "
    "assistance office under 10 U.S.C. 1044 — for anyone serving, and for "
    "retirees and their dependents on a space-available basis. A military "
    "testamentary instrument prepared there is exempt from state formality "
    "requirements under 10 U.S.C. 1044d and has to be given the same effect "
    "as a will executed under state law, which matters when you sign in "
    "Germany, die domiciled in Texas and own a house in Virginia. There is no "
    "cost reason to be without one."
)


# --------------------------------------------------------------------------
# A finding that knows what it is worth
# --------------------------------------------------------------------------

_SEVERITY_RANK = {"bad": 0, "warn": 1, "info": 2, "good": 3}


@dataclass(frozen=True)
class Finding:
    """
    (severity, headline, detail) for ui.panel.render_findings, plus the money.

    `dollars` is what is at stake if the finding is ignored — the balance that
    would pass to the wrong person, the tax an heir would pay, the estate a
    court would distribute without instructions. It exists so the list can be
    ordered by consequence instead of by the order the checks happen to run in.
    Iterating a Finding yields exactly the three fields render_findings wants.
    """
    severity: str
    headline: str
    detail: str = ""
    dollars: float = 0.0

    def __iter__(self):
        return iter((self.severity, self.headline, self.detail))

    def __len__(self) -> int:
        return 3

    def __getitem__(self, i):
        return (self.severity, self.headline, self.detail)[i]


def order_by_dollars(items) -> list[Finding]:
    """Most money first; severity breaks a tie so a crisis outranks a note."""
    return sorted(items,
                  key=lambda f: (-float(f.dollars),
                                 _SEVERITY_RANK.get(f.severity, 9)))


def _money(x: float) -> str:
    sign = "-" if x < 0 else ""
    return f"{sign}${abs(x):,.0f}"


def _pct(x: float, decimals: int = 0) -> str:
    return f"{x * 100:.{decimals}f}%"


# --------------------------------------------------------------------------
# Beneficiary designations
# --------------------------------------------------------------------------

@dataclass
class Account:
    """One account that passes by designation rather than by will."""
    key: str = ""
    label: str = ""
    balance: float = 0.0
    designated: bool = False
    form: str = ""
    where: str = ""
    precedence: tuple = ()


def designated_accounts(h) -> list[Account]:
    """
    The three things that do not read your will, with what is in them.

    Only the member's own accounts. A spouse's TSP and IRA carry their own
    designations and this plan holds one set of answers, which is itself worth
    saying out loud on the page.
    """
    m = h.member
    e = h.estate
    tsp = float(m.tsp_traditional_balance) + float(m.tsp_roth_balance)
    ira = float(m.ira_traditional_balance) + float(m.ira_roth_balance)
    return [
        Account("tsp", "Thrift Savings Plan", tsp,
                bool(e.tsp_beneficiary_current), "Form TSP-3",
                "tsp.gov, under My Account — the paper TSP-3 was retired when "
                "designations moved online, and a paper form mailed today is "
                "returned unprocessed",
                TSP_ORDER_OF_PRECEDENCE),
        Account("sgli", "SGLI", float(m.sgli_coverage),
                bool(e.sgli_beneficiary_current), "Form SGLV 8286",
                "SOES, through milConnect — the online system replaced the "
                "paper form, and a form sitting in a personnel file from 2009 "
                "is still the one that pays",
                SGLI_ORDER_OF_PRECEDENCE),
        Account("ira", "IRA", ira,
                bool(e.ira_beneficiary_current), "the custodian's form",
                "your brokerage's beneficiary page — Vanguard, Fidelity and "
                "Schwab each keep it somewhere different, and none of them "
                "will remind you",
                ()),
    ]


def beneficiary_checklist(h) -> list[Finding]:
    """
    Findings on the three designations, ordered by the money behind them.

    Any FUNDED account with no current designation is severity "bad". Not
    "warn": the money goes somewhere, it goes there irrevocably, and the person
    it goes to is decided by a form nobody has read in a decade.
    """
    out: list[Finding] = []
    accounts = designated_accounts(h)
    m = h.member

    for a in accounts:
        if a.balance <= 0:
            continue
        if not a.designated:
            order = ""
            if a.precedence:
                order = ("  With nothing valid on file the statutory order of "
                         "precedence applies instead: "
                         + "; ".join(x.lower() for x in a.precedence)
                         + ". That order pays your parents before your "
                           "long-term partner and pays a minor child directly, "
                           "into a court-supervised guardianship.")
            out.append(Finding(
                "bad",
                f"{a.label}: {_money(a.balance)} with no current beneficiary "
                f"designation.",
                f"This is the largest single point of failure in most military "
                f"estates. {a.label} pays whoever is named on {a.form} — not "
                f"whoever your will names, not whoever a divorce decree names, "
                f"and not whoever everyone assumes. Update it at {a.where}."
                + order,
                dollars=a.balance))
        else:
            out.append(Finding(
                "good",
                f"{a.label}: {_money(a.balance)} is designated and you have "
                f"confirmed it is current.",
                f"Re-confirm it after every marriage, divorce, birth and death "
                f"in the family, and read the actual form rather than "
                f"remembering what you put on it. {a.form}, at {a.where}.",
                dollars=a.balance))

    funded_total = sum(a.balance for a in accounts if a.balance > 0)
    stale = [a for a in accounts if a.balance > 0 and not a.designated]

    if funded_total > 0:
        out.append(Finding(
            "info",
            f"{_money(funded_total)} of your estate never reaches your will.",
            "A beneficiary designation is a contract with the plan; a will "
            "directs only what is left over after every contract has been "
            "honoured. In Ridgway v. Ridgway (1981) the Supreme Court held "
            "that SGLI proceeds go to the named beneficiary even against a "
            "state divorce decree ordering otherwise — federal law preempts "
            "the decree, and the person on the form is paid. Naming an "
            "ex-spouse and dying is not a mistake anyone can fix afterwards.",
            dollars=funded_total))

    if not stale and funded_total > 0:
        out.append(Finding(
            "info", "Set a date to check the forms again.",
            "Designations do not expire, which is the problem — they simply "
            "keep being right about a family that has changed. A birthday or "
            "a PCS is as good a trigger as any, and the check takes ten "
            "minutes online.",
            dollars=0.0))

    if m.is_serving and float(m.sgli_coverage) <= 0:
        out.append(Finding(
            "warn", "You show no SGLI coverage.",
            f"Full SGLI is {_money(SGLI_MAX)} for roughly the price of a "
            f"streaming subscription, at any age, with no underwriting — "
            f"nothing on the commercial market is close for a 45-year-old. If "
            f"you declined it, that was a decision; if the figure is simply "
            f"not entered, put it in on the Profile page.",
            dollars=SGLI_MAX))

    if h.has_spouse:
        out.append(Finding(
            "info", "Your spouse's accounts carry their own designations.",
            "This plan holds one set of answers. Their TSP or 401(k), their "
            "IRA and any employer life insurance each name someone, and the "
            "same ex-spouse problem applies in exactly the same way. Do both "
            "sets in the same sitting.",
            dollars=0.0))

    return order_by_dollars(out)


# --------------------------------------------------------------------------
# What an heir actually receives
# --------------------------------------------------------------------------

def heir_tax_on_traditional(balance: float, heir_marginal_rate: float) -> float:
    """
    Income tax an heir pays on an inherited TRADITIONAL balance.

    Under the SECURE Act ten-year rule a non-spouse beneficiary must empty the
    account by the end of the tenth year after death, and every dollar taken
    out is ordinary income to them. Modelled as a single flat rate rather than
    a bracket walk, because the answer is dominated by one fact: those
    withdrawals land on top of the heir's own peak-earning salary, not into
    the empty low brackets a retiree gets to fill.

    A Roth balance is also subject to the ten-year rule, but the withdrawals
    are tax-free — the rule costs the heir a decade of further tax-free
    growth, not tax.
    """
    b = max(0.0, float(balance))
    r = min(1.0, max(0.0, float(heir_marginal_rate)))
    return b * r


@dataclass
class InheritanceComparison:
    """Same money, three wrappers, three very different amounts delivered."""
    heir_marginal_rate: float = DEFAULT_HEIR_MARGINAL_RATE
    drain_years: int = SECURE_DRAIN_YEARS

    traditional_balance: float = 0.0
    roth_balance: float = 0.0
    taxable_balance: float = 0.0
    insurance_proceeds: float = 0.0

    heir_tax_on_traditional: float = 0.0
    traditional_after_tax: float = 0.0
    roth_after_tax: float = 0.0
    taxable_after_tax: float = 0.0
    insurance_after_tax: float = 0.0

    total_before_tax: float = 0.0
    total_after_tax: float = 0.0

    # What the heir would gain if today's traditional balance were Roth.
    gap_if_converted: float = 0.0

    notes: list = field(default_factory=list)

    @property
    def per_dollar_gap(self) -> float:
        """Cents of every traditional dollar that never reach the heir."""
        return min(1.0, max(0.0, self.heir_marginal_rate))


def inheritance_comparison(h, heir_marginal_rate: float = DEFAULT_HEIR_MARGINAL_RATE,
                           spouse_inherits: bool = False) -> InheritanceComparison:
    """
    Price the wrapper, on the household's own balances.

    `spouse_inherits` switches off the ten-year rule and the heir tax: a
    surviving spouse may roll an inherited IRA into their own, and a surviving
    spouse is the only person who can keep money inside the TSP.
    """
    m = h.member
    rate = 0.0 if spouse_inherits else heir_marginal_rate
    c = InheritanceComparison(
        heir_marginal_rate=min(1.0, max(0.0, float(heir_marginal_rate))),
        traditional_balance=float(m.tsp_traditional_balance)
        + float(m.ira_traditional_balance),
        roth_balance=float(m.tsp_roth_balance) + float(m.ira_roth_balance),
        taxable_balance=float(h.taxable_brokerage),
        insurance_proceeds=float(m.sgli_coverage),
    )

    c.heir_tax_on_traditional = heir_tax_on_traditional(c.traditional_balance, rate)
    c.traditional_after_tax = c.traditional_balance - c.heir_tax_on_traditional
    # A Roth is subject to the same ten-year deadline and none of the tax.
    c.roth_after_tax = c.roth_balance
    # IRC 1014: basis is stepped up to the value on the date of death, so an
    # heir who sells the day after inherits no capital gain at all.
    c.taxable_after_tax = c.taxable_balance
    # IRC 101(a): life insurance proceeds are not income to the beneficiary.
    c.insurance_after_tax = c.insurance_proceeds

    c.total_before_tax = (c.traditional_balance + c.roth_balance
                          + c.taxable_balance + c.insurance_proceeds)
    c.total_after_tax = (c.traditional_after_tax + c.roth_after_tax
                         + c.taxable_after_tax + c.insurance_after_tax)
    c.gap_if_converted = heir_tax_on_traditional(c.traditional_balance,
                                                 c.heir_marginal_rate)

    if spouse_inherits:
        c.notes.append(
            "A surviving SPOUSE is treated differently from every other heir. "
            "They may roll an inherited IRA into their own and treat it as "
            "theirs, restarting the clock on their own life expectancy, and "
            "they are the only person who can keep money inside the TSP.")
    else:
        c.notes.append(
            f"A non-spouse heir must empty an inherited traditional balance "
            f"within {c.drain_years} years, and every dollar is ordinary "
            f"income to THEM. At {_pct(c.heir_marginal_rate)} that is "
            f"{_money(c.heir_tax_on_traditional)} of your "
            f"{_money(c.traditional_balance)}, taken during their peak "
            f"earning years rather than into empty brackets.")

    c.notes.append(
        "The TSP does not hold money for a non-spouse beneficiary at all. "
        "They take a single payment — fully taxable in one year, which for a "
        "large balance can push an ordinary salary into the top bracket — or "
        "they direct a transfer to an inherited IRA. The transfer has to be "
        "set up before the TSP pays out; a cheque that arrives cannot be put "
        "back.")
    c.notes.append(
        "The trap inside the spousal option: a surviving spouse who leaves "
        "the money in a TSP beneficiary participant account passes a much "
        "worse asset on. When THEY die, the balance is paid to their "
        "beneficiaries as a single taxable payment and cannot be rolled to an "
        "inherited IRA. Rolling the TSP out to an IRA fixes it, and is one of "
        "the few genuinely urgent things a military survivor should do.")
    c.notes.append(
        "Your taxable brokerage is the opposite case. Basis steps up to the "
        "date-of-death value, so an appreciated holding your heir sells "
        "immediately carries no capital gain. That reverses the usual "
        "ordering advice late in life: do not sell appreciated taxable assets "
        "to fund gifts. Gift cash, spend the traditional accounts first, and "
        "let the appreciated shares reach the step-up.")
    c.notes.append(
        "SGLI and any commercial life insurance are income-tax-free to the "
        "beneficiary. They are still counted in your gross estate for the "
        "federal estate tax, which matters only to the very few households "
        "anywhere near the exemption.")
    return c


# --------------------------------------------------------------------------
# Federal and state death taxes
# --------------------------------------------------------------------------

@dataclass
class EstateTax:
    gross_estate: float = 0.0
    debts: float = 0.0
    taxable_estate: float = 0.0
    exemption_applied: float = 0.0
    married: bool = False
    portability_used: bool = False
    amount_over_exemption: float = 0.0
    federal_tax: float = 0.0
    headroom: float = 0.0
    multiple_of_exemption: float = 0.0
    state: str = ""
    state_note: str = ""
    notes: list = field(default_factory=list)

    @property
    def owes_federal_estate_tax(self) -> bool:
        return self.federal_tax > 0


def federal_estate_tax(taxable_estate: float, married: bool = False,
                       exemption: float = FEDERAL_ESTATE_EXEMPTION,
                       lifetime_gifts_reported: float = 0.0,
                       portability: bool = True) -> float:
    """
    Federal estate tax on a taxable estate, at the top rate.

    The exemption is unified: taxable gifts reported on Form 709 during life
    consume it, so they are subtracted here. A married couple can shelter
    twice the exemption through PORTABILITY — the surviving spouse may use the
    deceased spouse's unused exclusion — but only if an estate tax return
    (Form 706) is actually filed for the first death, which is exactly the
    return nobody files when no tax is due.

    Modelled at the flat top rate. The graduated schedule below the exemption
    is irrelevant: the credit shelters all of it, so the first taxable dollar
    is already at 40%.
    """
    shelter = max(0.0, float(exemption) - max(0.0, float(lifetime_gifts_reported)))
    if married and portability:
        shelter *= 2.0
    over = max(0.0, float(taxable_estate) - shelter)
    return over * ESTATE_TAX_TOP_RATE


def state_death_tax_note(state: str) -> str:
    """One sentence on the user's own state, or an empty string."""
    s = (state or "").strip()
    if not s:
        return ""
    parts = []
    if s in STATE_ESTATE_TAX:
        threshold, note = STATE_ESTATE_TAX[s]
        parts.append(f"{s} levies its own ESTATE tax from about "
                     f"{_money(threshold)}"
                     + (f" — {note}" if note else "") + ".")
    if s in STATE_INHERITANCE_TAX:
        parts.append(f"{s} levies an INHERITANCE tax, paid by the recipient: "
                     f"{STATE_INHERITANCE_TAX[s]}.")
    if not parts:
        parts.append(f"{s} has neither an estate tax nor an inheritance tax, "
                     f"so the federal exemption is the only threshold that "
                     f"applies to you.")
    if s in COMMUNITY_PROPERTY_STATES:
        parts.append(f"{s} is a community property state, which is worth real "
                     f"money to a surviving spouse: basis steps up on BOTH "
                     f"halves of community property at the first death, not "
                     f"just the deceased spouse's half.")
    return "  ".join(parts)


def estate_tax_check(h, exemption: float = FEDERAL_ESTATE_EXEMPTION) -> EstateTax:
    """
    Size the estate against the federal exemption, and name the state risk.

    The gross estate is bigger than most people expect — it includes the full
    market value of the house rather than the equity, and it includes life
    insurance proceeds on a policy you owned, SGLI among them. It does NOT
    include your pension: retired pay stops at death and SBP is an annuity to
    your survivor, so neither has an estate value. That is a real asset your
    family loses and a real amount your estate does not owe tax on.
    """
    m = h.member
    gross = (float(h.cash_savings) + float(h.taxable_brokerage)
             + float(m.tsp_traditional_balance) + float(m.tsp_roth_balance)
             + float(m.ira_traditional_balance) + float(m.ira_roth_balance)
             + float(m.sdp_balance)
             + float(h.home_value) + float(h.vehicles_value)
             + float(h.other_assets) + float(m.sgli_coverage))

    debts = float(h.mortgage_balance) + sum(
        max(0.0, float(getattr(d, "balance", 0.0))) for d in (h.debts or []))

    t = EstateTax(gross_estate=gross, debts=debts,
                  taxable_estate=max(0.0, gross - debts),
                  married=bool(h.has_spouse), portability_used=bool(h.has_spouse),
                  state=(h.state_of_legal_residence or "").strip())
    shelter = exemption * (2.0 if t.married else 1.0)
    t.exemption_applied = shelter
    t.amount_over_exemption = max(0.0, t.taxable_estate - shelter)
    t.federal_tax = federal_estate_tax(t.taxable_estate, married=t.married,
                                       exemption=exemption)
    t.headroom = max(0.0, shelter - t.taxable_estate)
    t.multiple_of_exemption = (t.taxable_estate / shelter) if shelter else 0.0
    t.state_note = state_death_tax_note(t.state)

    if not t.owes_federal_estate_tax:
        t.notes.append(
            f"Your estate is {_money(t.taxable_estate)} against a "
            f"{_money(shelter)} federal exemption"
            + (" — doubled because a married couple can use both." if t.married
               else " for one person.")
            + f" You are {_money(t.headroom)} below it. Federal estate tax is "
            f"not your problem, and any advice that starts there is selling "
            f"you something.")
    else:
        t.notes.append(
            f"Your estate of {_money(t.taxable_estate)} is "
            f"{_money(t.amount_over_exemption)} over the exemption, which at "
            f"{_pct(ESTATE_TAX_TOP_RATE)} is {_money(t.federal_tax)} of "
            f"federal estate tax. At this size, get a specialist estate "
            f"attorney — not an installation legal assistance office, which "
            f"does simple wills and does them well but does not do this.")

    if t.married:
        t.notes.append(
            "Portability is not automatic. To use your spouse's unused "
            "exemption, an estate tax return (Form 706) has to be filed for "
            "the FIRST death, in the nine months after it, even though no tax "
            "is due — which is precisely the return grieving families skip. "
            "There is a simplified late election available for several years "
            "afterwards, and it is a great deal of trouble compared with "
            "filing on time.")

    t.notes.append(
        "The exemption itself is a policy question, not a fact. The 2017 tax "
        "act's doubling was scheduled to expire at the end of 2025 and would "
        "have cut it roughly in half; the 2025 law set the current figure "
        "instead and indexed it. It is 'permanent' in the sense that it has "
        "no sunset date written into it, which is the same sense in which the "
        "last one was permanent.")

    if t.state_note:
        t.notes.append(t.state_note)
    t.notes.append(
        "The state that taxes your estate is the state you are DOMICILED in "
        "when you die, plus any state where you own real property. While you "
        "serve, the SCRA keeps your domicile from changing just because you "
        "were ordered somewhere. It stops protecting you the day you retire "
        "and settle — retiring to Oregon or Massachusetts puts an ordinary "
        "military estate above a state threshold that the federal figure "
        "would never come near.")
    return t


# --------------------------------------------------------------------------
# Gifting
# --------------------------------------------------------------------------

def annual_exclusion(married: bool = False,
                     exclusion: float = ANNUAL_GIFT_EXCLUSION) -> float:
    """Per recipient, per year. A married couple may give twice as much."""
    return float(exclusion) * (2.0 if married else 1.0)


def superfund_529(married: bool = False,
                  exclusion: float = ANNUAL_GIFT_EXCLUSION) -> float:
    """
    Five years of annual exclusion into a 529, in one contribution.

    Elected on Form 709 and then spread over five years, so no further
    exclusion-covered gifts to that beneficiary are available until it runs
    out. If the donor dies inside the five years, the unused part comes back
    into their estate — which is a reason to make the election early rather
    than as a deathbed manoeuvre.
    """
    return float(exclusion) * SUPERFUND_YEARS * (2.0 if married else 1.0)


def roth_ira_for_a_child(child_earned_income: float,
                         ira_limit: float = 7_500.0) -> float:
    """
    What may go into a Roth IRA for a child with a real job.

    The contribution is capped by the child's own EARNED income, so a teenager
    who makes $4,000 lifeguarding can have $4,000 put in — and it does not
    have to be their $4,000. A parent or grandparent may fund it, which makes
    it a gift covered many times over by the annual exclusion. Started at 16,
    a single $4,000 contribution has fifty years of tax-free compounding ahead
    of it, and the child's bracket now is almost certainly the lowest one they
    will ever be in.
    """
    return max(0.0, min(float(child_earned_income), float(ira_limit)))


def _annuity_factor(years: int, rate: float) -> float:
    """Future value of $1 a year, paid at the end of each year, at `rate`."""
    n = max(0, int(years))
    if n == 0:
        return 0.0
    r = float(rate)
    if abs(r) < 1e-12:
        return float(n)
    return ((1.0 + r) ** n - 1.0) / r


@dataclass
class GiftYear:
    year: int = 0
    donor_age: int = 0
    child_years_elapsed: int = 0
    required_gift_per_child: float = 0.0
    planned_gift_per_child: float = 0.0
    exclusion_per_child: float = 0.0
    over_exclusion: bool = False
    excess_per_child: float = 0.0
    required_value_per_child: float = 0.0
    planned_value_per_child: float = 0.0
    target_per_child: float = 0.0


@dataclass
class GiftingPlan:
    n_children: int = 0
    start_year: int = 0
    end_year: int = 0
    years: int = 0
    real_return: float = 0.0
    donor_age_now: int = 0
    life_expectancy_age: int = 0

    target_per_child: float = 0.0
    required_annual_gift_per_child: float = 0.0
    required_annual_gift_total: float = 0.0
    required_total_gifted_per_child: float = 0.0

    planned_annual_gift_per_child: float = 0.0
    planned_annual_gift_total: float = 0.0
    planned_value_per_child: float = 0.0
    shortfall_per_child: float = 0.0

    exclusion_per_child: float = 0.0
    married: bool = False
    capped_years: list = field(default_factory=list)
    excess_per_child_per_year: float = 0.0
    reportable_gifts: bool = False

    bequest_per_child_before_tax: float = 0.0
    bequest_per_child_after_tax: float = 0.0
    heir_tax_at_death: float = 0.0
    heir_marginal_rate: float = DEFAULT_HEIR_MARGINAL_RATE
    estate_at_death: float = 0.0

    rows: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    @property
    def cap_binds(self) -> bool:
        return bool(self.capped_years)

    @property
    def reaches_target(self) -> bool:
        return (self.target_per_child > 0
                and self.planned_value_per_child >= self.target_per_child - 1.0)

    @property
    def unmet_per_child(self) -> float:
        """
        What the target would still be short of, counting BOTH routes.

        Gifting is not the only way a child ends up with money. If the
        do-nothing bequest already clears the target there is nothing at
        stake, whatever the gifting schedule says — and saying so is more
        use than a large scary number.
        """
        if self.target_per_child <= 0:
            return 0.0
        best = max(self.planned_value_per_child, self.bequest_per_child_after_tax)
        return max(0.0, self.target_per_child - best)

    @property
    def bequest_alone_reaches_target(self) -> bool:
        return (self.target_per_child > 0
                and self.bequest_per_child_after_tax >= self.target_per_child)


def gifting_plan(h, heir_marginal_rate: float = DEFAULT_HEIR_MARGINAL_RATE,
                 current_year: int | None = None,
                 exclusion: float = ANNUAL_GIFT_EXCLUSION) -> GiftingPlan:
    """
    What it takes to hand each child a target sum, and what dying would deliver.

    Everything is REAL — today's dollars. The gift is level in real terms and
    made at the end of each year from `gifting_start_year` through the year the
    member's life expectancy runs out, and it compounds at the assumed real
    return in the child's hands from the moment it lands. So

        target = gift * ((1 + r)^n - 1) / r

    and the required gift is that solved for `gift`.

    The comparison is against doing nothing: the household's own investable
    assets, grown at the same real return to the same year and split between
    the children, less the tax the heirs owe on whatever is still in a
    traditional account. That figure ignores both future saving and future
    spending, so read it as a ceiling on the do-nothing case rather than a
    forecast.
    """
    m = h.member
    e = h.estate
    year_now = int(current_year or date.today().year)
    age_now = m.age(year_now)
    life_age = MORT.life_expectancy(age_now, m.sex)
    end_year = int(m.birth_year) + int(life_age)

    r = float(h.assumptions.real_return_pct) / 100.0
    start = int(e.gifting_start_year or year_now)
    if start < year_now:
        start = year_now
    n_years = max(0, end_year - start + 1)

    n_children = max(0, int(e.n_children))
    target = max(0.0, float(e.target_legacy_per_child))
    planned = max(0.0, float(e.annual_gift_per_child))
    married = bool(h.has_spouse)
    cap = annual_exclusion(married, exclusion)

    p = GiftingPlan(
        n_children=n_children, start_year=start, end_year=end_year,
        years=n_years, real_return=r, donor_age_now=age_now,
        life_expectancy_age=int(life_age), target_per_child=target,
        planned_annual_gift_per_child=planned,
        planned_annual_gift_total=planned * n_children,
        exclusion_per_child=cap, married=married,
        heir_marginal_rate=min(1.0, max(0.0, float(heir_marginal_rate))),
    )

    if n_children <= 0:
        p.notes.append(
            "No children entered, so there is nothing to plan here. The "
            "annual exclusion applies per RECIPIENT and the recipient does "
            "not have to be a child — a sibling, a parent, a godchild and a "
            "friend each have their own.")
        return p

    if n_years <= 0:
        p.notes.append(
            f"The start year {start} is after the planning horizon of "
            f"{end_year}, so there is no gifting window. Move the start year "
            f"earlier.")
        return p

    factor = _annuity_factor(n_years, r)
    if target > 0 and factor > 0:
        p.required_annual_gift_per_child = target / factor
    p.required_annual_gift_total = p.required_annual_gift_per_child * n_children
    p.required_total_gifted_per_child = p.required_annual_gift_per_child * n_years

    # ---- The two schedules, year by year --------------------------------
    req_value = 0.0
    plan_value = 0.0
    for i in range(n_years):
        y = start + i
        req_value = req_value * (1.0 + r) + p.required_annual_gift_per_child
        plan_value = plan_value * (1.0 + r) + planned
        # The exclusion is indexed, so in today's dollars it holds still. A
        # level real gift therefore either clears it every year or none.
        operative = max(p.required_annual_gift_per_child, planned)
        over = operative > cap + 1e-9
        row = GiftYear(
            year=y, donor_age=age_now + i, child_years_elapsed=i + 1,
            required_gift_per_child=p.required_annual_gift_per_child,
            planned_gift_per_child=planned,
            exclusion_per_child=cap, over_exclusion=over,
            excess_per_child=max(0.0, operative - cap),
            required_value_per_child=req_value,
            planned_value_per_child=plan_value,
            target_per_child=target)
        p.rows.append(row)
        if over:
            p.capped_years.append(y)

    p.planned_value_per_child = plan_value
    p.shortfall_per_child = max(0.0, target - plan_value)
    p.excess_per_child_per_year = max(
        0.0, max(p.required_annual_gift_per_child, planned) - cap)
    p.reportable_gifts = p.excess_per_child_per_year > 0

    # ---- What a bequest would instead deliver ---------------------------
    investable = (float(h.cash_savings) + float(h.taxable_brokerage)
                  + float(m.tsp_traditional_balance) + float(m.tsp_roth_balance)
                  + float(m.ira_traditional_balance) + float(m.ira_roth_balance))
    traditional = (float(m.tsp_traditional_balance)
                   + float(m.ira_traditional_balance))
    growth = (1.0 + r) ** max(0, end_year - year_now)
    p.estate_at_death = investable * growth
    p.heir_tax_at_death = heir_tax_on_traditional(traditional * growth,
                                                  p.heir_marginal_rate)
    after_tax_estate = p.estate_at_death - p.heir_tax_at_death
    if n_children > 0:
        p.bequest_per_child_before_tax = p.estate_at_death / n_children
        p.bequest_per_child_after_tax = after_tax_estate / n_children

    # ---- Notes ----------------------------------------------------------
    p.notes.append(
        f"To hand each of {n_children} "
        f"{'child' if n_children == 1 else 'children'} "
        f"{_money(target)} by {end_year}, give "
        f"{_money(p.required_annual_gift_per_child)} each a year from {start} "
        f"— {_money(p.required_annual_gift_total)} a year in total, "
        f"{_money(p.required_total_gifted_per_child * n_children)} of your own "
        f"money over {n_years} years, compounding at "
        f"{_pct(r, 1)} above inflation in their hands.")

    if p.capped_years:
        p.notes.append(
            f"That is above the {_money(cap)} annual exclusion"
            + (" for a married couple giving jointly" if married
               else " a single donor has")
            + f", by {_money(p.excess_per_child_per_year)} per child per year, "
            f"in {len(p.capped_years)} of the {n_years} years. Nothing is "
            f"owed — you file Form 709 and the excess is charged against your "
            f"lifetime exemption of "
            f"{_money(FEDERAL_ESTATE_EXEMPTION)}. That is REPORTING, not tax, "
            f"and at this scale it will never be tax."
            + ("" if married else
               " If you are married, splitting the gift with your spouse "
               "doubles the exclusion and may remove the filing entirely."))
    else:
        p.notes.append(
            f"That is inside the {_money(cap)} annual exclusion, so there is "
            f"no Form 709, no reporting and no use of your lifetime "
            f"exemption. Write the cheque and say nothing to anyone.")

    if planned > 0:
        verdict = ("reaches" if p.reaches_target else
                   f"falls {_money(p.shortfall_per_child)} short of")
        p.notes.append(
            f"You are gifting {_money(planned)} per child per year, which "
            f"{verdict} {_money(target)} by {end_year} — "
            f"{_money(p.planned_value_per_child)} in today's dollars.")
    elif target > 0:
        p.notes.append(
            "You are not gifting anything yet, so on the current plan each "
            "child receives whatever is left at death instead.")

    if p.bequest_per_child_after_tax > 0:
        p.notes.append(
            f"Doing nothing instead: today's {_money(investable)} of "
            f"investable assets, untouched and growing at {_pct(r, 1)} real, "
            f"would be {_money(p.estate_at_death)} by {end_year} — "
            f"{_money(p.bequest_per_child_after_tax)} per child after the "
            f"{_money(p.heir_tax_at_death)} of income tax your heirs owe on "
            f"the traditional share. That figure ignores both what you add and "
            f"what you spend, so treat it as a ceiling on the do-nothing case, "
            f"not a forecast.")

    p.notes.append(
        f"Two moves that are worth more than the cash: a 529 takes "
        f"{_money(superfund_529(married, exclusion))} in a single "
        f"contribution under the five-year election on Form 709, and a child "
        f"with a summer job can have a Roth IRA funded up to their earned "
        f"income with your money — the lowest bracket they will ever be in, "
        f"with fifty years of tax-free compounding ahead of it.")

    p.notes.append(
        "Gifted property carries your basis over; inherited property gets a "
        "step-up. So gift CASH, not the appreciated fund you have held since "
        "2009 — selling that to fund a gift pays a capital gains tax your "
        "heirs would never have paid.")
    return p


# --------------------------------------------------------------------------
# Everything, ordered by what it costs to ignore
# --------------------------------------------------------------------------

def findings(h, heir_marginal_rate: float = DEFAULT_HEIR_MARGINAL_RATE,
             has_poa: bool = False, current_year: int | None = None
             ) -> list[Finding]:
    """
    The whole page's advice, ordered by dollars at stake.

    Ordering by money rather than by topic is deliberate. A stale TSP
    designation on a $700,000 balance is a bigger problem than a federal
    estate tax that will never apply, and a list organised by subject buries
    it in the middle.
    """
    out: list[Finding] = list(beneficiary_checklist(h))
    m = h.member
    e = h.estate

    comp = inheritance_comparison(h, heir_marginal_rate)
    tax = estate_tax_check(h)
    plan = gifting_plan(h, heir_marginal_rate, current_year)

    # ---- The ten-year rule, which is the biggest number on most plans ----
    if comp.traditional_balance > 0:
        out.append(Finding(
            "warn",
            f"Your heirs lose {_money(comp.heir_tax_on_traditional)} of the "
            f"{_money(comp.traditional_balance)} sitting in traditional "
            f"accounts.",
            f"A non-spouse heir must empty an inherited traditional TSP or IRA "
            f"within {SECURE_DRAIN_YEARS} years and pays ordinary income tax "
            f"on every dollar, at {_pct(comp.heir_marginal_rate)} here. Those "
            f"withdrawals stack on top of a working adult's salary in their "
            f"peak earning years — there are no empty brackets to fill. The "
            f"same money in a Roth reaches them whole. This is the strongest "
            f"estate argument for Roth conversions, and the Roth Conversions "
            f"page prices it against your own lifetime tax bill.",
            dollars=comp.heir_tax_on_traditional))

    # ---- Wills and guardianship -----------------------------------------
    minor_children = max(int(e.n_children), int(h.n_dependents))
    designated = sum(a.balance for a in designated_accounts(h))
    # What a will actually controls is the probate estate: everything that is
    # NOT already spoken for by a designation. With minor children the stake
    # is the whole of it anyway, because a court-appointed guardian ends up
    # controlling the designated money too.
    probate_estate = max(0.0, tax.taxable_estate - designated)
    if not e.has_will:
        detail = ("A will does not control your TSP, your SGLI or your IRA — "
                  "those pass by designation. What it does control is "
                  "everything else, and one thing nothing else can touch: who "
                  "raises your children. Die without one and a court decides, "
                  "from whoever comes forward, under the law of whichever "
                  "state you were domiciled in. " + LEGAL_ASSISTANCE)
        out.append(Finding(
            "bad",
            "You have no will."
            + (f" You have {minor_children} "
               f"{'child' if minor_children == 1 else 'children'}."
               if minor_children else ""),
            detail,
            dollars=tax.taxable_estate if minor_children else probate_estate))
    else:
        out.append(Finding(
            "good", "You have a will.",
            "Check that it still names the right guardian for your children "
            "and the right executor, and that it has not been quietly revoked "
            "by a marriage or a divorce in the state you are now domiciled "
            "in. Re-doing it is free at legal assistance.",
            dollars=0.0))

    if not has_poa:
        out.append(Finding(
            "warn", "You have no power of attorney on file.",
            "A will is for after you die. A general power of attorney and an "
            "advance medical directive are for the eleven months you are "
            "deployed, or the six weeks you are unconscious — the far more "
            "likely case. Without them your spouse cannot sell the car, "
            "refinance the house, or make a medical decision for you, and a "
            "bank will not take their word for it. Both are free at legal "
            "assistance and take one appointment. Get a SPECIAL power of "
            "attorney for named tasks where you can: banks refuse general "
            "ones far more often than they refuse specific ones.",
            dollars=0.0))

    # ---- Gifting ---------------------------------------------------------
    if plan.n_children > 0 and plan.target_per_child > 0:
        # Only the part neither route delivers is genuinely at stake, and it
        # is a shortfall decades away — discounted back so it is ranked
        # against a beneficiary form that is wrong TODAY, not against a
        # number inflated by thirty years of compounding.
        d = float(h.assumptions.real_discount_rate_pct) / 100.0
        horizon = max(0, plan.end_year - int(current_year or date.today().year))
        gap = (plan.unmet_per_child * plan.n_children) / ((1.0 + d) ** horizon)
        if plan.bequest_alone_reaches_target:
            out.append(Finding(
                "info",
                f"A bequest alone already clears "
                f"{_money(plan.target_per_child)} per child.",
                f"On today's balances, untouched, each child would receive "
                f"about {_money(plan.bequest_per_child_after_tax)} at "
                f"{plan.end_year} after their own tax. The case for gifting "
                f"now is therefore not that the money would otherwise be "
                f"missing — it is TIMING. "
                f"{_money(plan.required_annual_gift_per_child)} a year from "
                f"{plan.start_year} arrives while a child is buying a house "
                f"and paying for childcare; the bequest arrives in "
                f"{plan.end_year}, when they may be close to retiring "
                f"themselves. That figure also ignores everything you will "
                f"spend between now and then, so do not read it as a promise.",
                dollars=0.0))
        if plan.planned_annual_gift_per_child <= 0:
            out.append(Finding(
                "info",
                f"Reaching {_money(plan.target_per_child)} per child needs "
                f"{_money(plan.required_annual_gift_per_child)} a year each, "
                f"starting {plan.start_year}.",
                f"{_money(plan.required_annual_gift_total)} a year across "
                f"{plan.n_children} "
                f"{'child' if plan.n_children == 1 else 'children'}, "
                f"compounding at {_pct(plan.real_return, 1)} real in their "
                f"hands until {plan.end_year}. Money given early does the "
                f"work; money given at death does none of it. "
                + ("It is inside the annual exclusion, so nothing is reported."
                   if not plan.cap_binds else
                   f"It is above the {_money(plan.exclusion_per_child)} annual "
                   f"exclusion, which means a Form 709 and a charge against "
                   f"your lifetime exemption — reporting, not tax."),
                dollars=gap))
        elif not plan.reaches_target:
            out.append(Finding(
                "warn",
                f"Your gifting falls {_money(plan.shortfall_per_child)} short "
                f"per child.",
                f"{_money(plan.planned_annual_gift_per_child)} a year reaches "
                f"{_money(plan.planned_value_per_child)} by {plan.end_year}, "
                f"against a {_money(plan.target_per_child)} target. "
                f"{_money(plan.required_annual_gift_per_child)} a year would "
                f"close it.",
                dollars=gap))
        else:
            out.append(Finding(
                "good",
                f"Your gifting reaches {_money(plan.target_per_child)} per "
                f"child by {plan.end_year}.",
                f"{_money(plan.planned_annual_gift_per_child)} a year each, "
                f"reaching {_money(plan.planned_value_per_child)}. "
                + ("Inside the annual exclusion, so there is nothing to "
                   "report." if not plan.cap_binds else
                   f"Above the {_money(plan.exclusion_per_child)} exclusion, "
                   f"so file Form 709 — reporting, not tax."),
                dollars=0.0))

    if plan.cap_binds:
        out.append(Finding(
            "info",
            f"Gifts above {_money(plan.exclusion_per_child)} per child a year "
            f"have to be reported.",
            f"Form 709, filed with your income tax return. Nothing is owed: "
            f"the excess is charged against your lifetime exemption of "
            f"{_money(FEDERAL_ESTATE_EXEMPTION)} per person, which you will "
            f"not exhaust. "
            + ("A married couple may split gifts and use both exclusions, "
               "which is already assumed here." if plan.married else
               "A married couple gets two exclusions — twice this figure."),
            dollars=0.0))

    # ---- Estate tax ------------------------------------------------------
    if tax.owes_federal_estate_tax:
        out.append(Finding(
            "warn",
            f"Federal estate tax of about {_money(tax.federal_tax)} would be "
            f"due.",
            tax.notes[0], dollars=tax.federal_tax))
    else:
        out.append(Finding(
            "good",
            "Federal estate tax does not apply to you.",
            f"{_money(tax.taxable_estate)} of gross estate against a "
            f"{_money(tax.exemption_applied)} exemption. Almost no military "
            f"family is anywhere near it. The thing actually worth checking is "
            f"your state: "
            + (tax.state_note or "enter your state of legal residence on the "
                                 "Profile page and this will name it."),
            dollars=0.0))

    state = (h.state_of_legal_residence or "").strip()
    if state in STATE_ESTATE_TAX:
        threshold, note = STATE_ESTATE_TAX[state]
        over = max(0.0, tax.taxable_estate - threshold)
        out.append(Finding(
            "warn" if over > 0 else "info",
            f"{state} levies its own estate tax from about "
            f"{_money(threshold)}.",
            (f"Your {_money(tax.taxable_estate)} gross estate is "
             f"{_money(over)} over it"
             if over > 0 else
             f"Your {_money(tax.taxable_estate)} gross estate is under it, but "
             f"the threshold does not move with prices and your estate does")
            + (f" — {note}. " if note else ". ")
            + "Remember that the gross estate includes the full value of your "
              "house rather than the equity, and your life insurance proceeds. "
              "Which state this is depends on where you are DOMICILED when you "
              "die, and the SCRA stops protecting that choice the day you stop "
              "serving.",
            dollars=over * 0.12))

    if m.sbp_elected or float(m.retired_pay_monthly) > 0:
        out.append(Finding(
            "info", "Your pension is not part of your estate.",
            "Retired pay stops at death and SBP is an annuity paid to your "
            "survivor, not an asset your estate owns or can leave to anyone. "
            "That cuts both ways: it is the largest thing your family loses, "
            "and it is the reason a military estate is usually far smaller "
            "than the household's standard of living implies. SBP and DIC are "
            "priced on the Survivor Benefits page.",
            dollars=0.0))

    return order_by_dollars(out)
