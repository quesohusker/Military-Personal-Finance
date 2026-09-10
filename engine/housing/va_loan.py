"""
The VA home loan: the funding fee, the exemption nobody claims, entitlement,
and the value of a low rate you can hand to a buyer.

Four things in here are routinely missed, and each is worth five figures:

  1. THE FUNDING FEE EXEMPTION. A veteran receiving -- or merely ENTITLED to
     receive -- VA compensation for a service-connected disability pays no
     funding fee at all. That is a rating of 10% or more, not 30, not 100. On
     a $400,000 loan the fee runs $8,600 on a first use and $13,200 on a
     subsequent use, so the exemption is worth between those two numbers. A
     rating granted AFTER closing is retroactive to the effective date of the
     award, and the fee is refundable. People leave that money at the lender.

  2. NO MORTGAGE INSURANCE, EVER. A conventional loan at the same loan-to-value
     carries PMI until the balance reaches 78% of the original value. The VA
     loan does not, at any LTV, for the life of the loan. That saving usually
     dwarfs the funding fee.

  3. ASSUMABILITY. A VA loan can be assumed by a qualified buyer AT THE
     ORIGINAL RATE. A 2.125% loan in a 6.5% market is not a liability, it is a
     saleable asset, and it is close to the only asset a junior member owns
     that a market dislocation made MORE valuable. Nobody prices it, because
     the mortgage industry has no reason to teach them to.

  4. THE ENTITLEMENT STAYS WITH THE LOAN. On an assumption by a non-veteran,
     the seller's entitlement remains tied to that house until the loan is paid
     off. It can be released only if the buyer is an eligible veteran who
     SUBSTITUTES their own entitlement. Sell that way without asking, and the
     next house has to be bought with a down payment.

PROVENANCE. Every figure below carries the year it applies to and a VERIFY
note. This machine cannot reach va.gov or fhfa.gov, so the rates are from
memory of the published schedules, not from the documents. Correct them in one
place -- FIGURES -- and every page follows.
"""

from __future__ import annotations
from dataclasses import dataclass, field

# ==========================================================================
# The figures. ONE place. Every entry has a VERIFY note below.
# ==========================================================================
FIGURES = {
    "year": 2026,

    # ---- Funding fee, purchase or construction, as a share of the loan ----
    # Keyed by (subsequent_use, down-payment band). Bands are: under 5%,
    # 5% to under 10%, 10% or more.
    "fee_first_use": {"under_5": 0.0215, "five_to_ten": 0.0150, "ten_plus": 0.0125},
    "fee_subsequent": {"under_5": 0.0330, "five_to_ten": 0.0150, "ten_plus": 0.0125},

    # ---- Refinance ----
    "fee_irrrl": 0.0050,                 # streamline, any use
    "fee_cashout_first_use": 0.0215,
    "fee_cashout_subsequent": 0.0330,

    # ---- Entitlement ----
    "basic_entitlement": 36_000.0,       # 38 U.S.C. 3703(a)
    "conforming_limit_2026": 832_750.0,  # one unit, baseline counties
    "guaranty_share": 0.25,              # VA guarantees 25% of the loan

    # ---- The exemption ----
    "exempt_min_rating": 10,

    # ---- Comparison assumptions, NOT VA figures ----
    # Private mortgage insurance on a conventional loan at the same LTV, as an
    # annual share of the loan balance. Real quotes move with credit score;
    # these are mid-range for a 700-760 score.
    "pmi_annual_rate_by_ltv": [(0.95, 0.0110), (0.90, 0.0075),
                               (0.85, 0.0050), (0.80, 0.0035)],
    "pmi_auto_termination_ltv": 0.78,    # Homeowners Protection Act of 1998
    "pmi_request_ltv": 0.80,
}

VERIFY = {
    "fee_first_use":
        "VERIFY at va.gov/housing-assistance/home-loans/funding-fee-and-closing-costs: "
        "2026 purchase funding fee, first use — 2.15% under 5% down, 1.50% at "
        "5% to under 10%, 1.25% at 10% or more. Confidence MEDIUM-HIGH: these "
        "rates have been stable since the Blue Water Navy Vietnam Veterans Act "
        "rates took effect on 1 January 2020, but the schedule is statutory and "
        "Congress has changed it before.",
    "fee_subsequent":
        "VERIFY at va.gov: 2026 purchase funding fee, subsequent use — 3.30% "
        "under 5% down. At 5% or more down the subsequent-use rate is the same "
        "as first use (1.50% / 1.25%), which is the part people get wrong: a "
        "10% down payment removes the entire subsequent-use penalty. "
        "Confidence MEDIUM-HIGH.",
    "fee_irrrl":
        "VERIFY at va.gov: 0.50% funding fee on an Interest Rate Reduction "
        "Refinance Loan, first or subsequent use. Confidence MEDIUM-HIGH.",
    "fee_cashout_first_use":
        "VERIFY at va.gov: 2.15% / 3.30% on a cash-out refinance. Confidence "
        "MEDIUM.",
    "basic_entitlement":
        "VERIFY at 38 U.S.C. 3703(a): basic entitlement of $36,000. Unchanged "
        "for decades. Confidence HIGH.",
    "conforming_limit_2026":
        "VERIFY at fhfa.gov: the 2026 baseline conforming loan limit for a "
        "one-unit property, which is what sets bonus (Tier 2) entitlement and "
        "therefore the zero-down ceiling on PARTIAL entitlement. Confidence "
        "MEDIUM — the 2025 baseline was $806,500 and this is the 2026 figure "
        "from memory, not from the FHFA notice. High-cost counties are higher; "
        "check your own county. Note that since the Blue Water Navy Act "
        "(1 January 2020) there is NO loan limit at all on FULL entitlement.",
    "exempt_min_rating":
        "VERIFY at va.gov: the funding fee is waived for a veteran receiving or "
        "entitled to receive VA compensation for a service-connected "
        "disability, which begins at a 10% rating. Also waived for a surviving "
        "spouse of a veteran who died in service or from a service-connected "
        "disability, and for a service member on active duty who has received "
        "a Purple Heart. Confidence HIGH on the categories; the exact wording "
        "of 'entitled to receive' (it covers a veteran who would be paid "
        "compensation but for receiving retired pay) is worth reading in full.",
    "pmi_annual_rate_by_ltv":
        "NOT a VA figure. An assumption about the conventional loan the VA loan "
        "is being compared against. Typical borrower-paid monthly PMI for a "
        "700-760 credit score. Confidence LOW as a quote, MEDIUM as a planning "
        "range: real rates run from about 0.20% to 1.50% a year depending on "
        "score and LTV. Get your own quote before relying on the comparison.",
    "pmi_auto_termination_ltv":
        "VERIFY at 12 U.S.C. 4902 (Homeowners Protection Act of 1998): PMI "
        "terminates automatically at 78% of the ORIGINAL value on the original "
        "amortisation schedule, and may be cancelled on request at 80%. "
        "Confidence HIGH.",
}

# Down-payment bands
BAND_UNDER_5 = "under_5"
BAND_5_TO_10 = "five_to_ten"
BAND_10_PLUS = "ten_plus"

EXEMPT_RATED = "rated"
EXEMPT_SURVIVING_SPOUSE = "surviving_spouse"
EXEMPT_PURPLE_HEART = "purple_heart"


# ==========================================================================
# Amortisation. Shared with rent_vs_buy.
# ==========================================================================

def monthly_payment(principal: float, annual_rate_pct: float,
                    years: float) -> float:
    """Level payment that retires `principal` over `years`."""
    if principal <= 0 or years <= 0:
        return 0.0
    n = years * 12.0
    r = annual_rate_pct / 100.0 / 12.0
    if abs(r) < 1e-12:
        return principal / n
    return principal * r / (1.0 - (1.0 + r) ** -n)


def remaining_balance(principal: float, annual_rate_pct: float, years: float,
                      months_elapsed: float) -> float:
    """Balance after `months_elapsed` payments on a level-payment loan."""
    if principal <= 0 or years <= 0:
        return 0.0
    n = years * 12.0
    k = max(0.0, min(months_elapsed, n))
    r = annual_rate_pct / 100.0 / 12.0
    if abs(r) < 1e-12:
        return principal * (1.0 - k / n)
    pmt = monthly_payment(principal, annual_rate_pct, years)
    bal = principal * (1.0 + r) ** k - pmt * ((1.0 + r) ** k - 1.0) / r
    return max(0.0, bal)


def total_interest(principal: float, annual_rate_pct: float,
                   years: float) -> float:
    """Interest paid over the full term."""
    if principal <= 0 or years <= 0:
        return 0.0
    return monthly_payment(principal, annual_rate_pct, years) * years * 12.0 - principal


def present_value_monthly(monthly_amount: float, months: float,
                          annual_discount_pct: float) -> float:
    """PV of a level monthly stream, discounted monthly."""
    if monthly_amount == 0 or months <= 0:
        return 0.0
    r = annual_discount_pct / 100.0 / 12.0
    if abs(r) < 1e-12:
        return monthly_amount * months
    return monthly_amount * (1.0 - (1.0 + r) ** -months) / r


# ==========================================================================
# The funding fee
# ==========================================================================

@dataclass
class Exemption:
    exempt: bool = False
    reason: str = ""
    detail: str = ""


def exemption(va_rating: int = 0, is_surviving_spouse: bool = False,
              purple_heart_on_active_duty: bool = False,
              receives_va_compensation: bool = False) -> Exemption:
    """
    Who pays no funding fee at all.

    A rating of 10% is enough. So is entitlement to compensation that is being
    offset by retired pay -- 'entitled to receive' is the statutory test, not
    'receiving'. So is a Purple Heart, for a member still on active duty, which
    is the one category that applies to somebody who is not a veteran yet.
    """
    if is_surviving_spouse:
        return Exemption(True, EXEMPT_SURVIVING_SPOUSE,
                         "Surviving spouse of a veteran who died in service or "
                         "from a service-connected disability. The exemption is "
                         "yours in your own right.")
    if purple_heart_on_active_duty:
        return Exemption(True, EXEMPT_PURPLE_HEART,
                         "Active-duty service member who has received a Purple "
                         "Heart. This one applies before you are a veteran, and "
                         "it is the category most often missed because it sits "
                         "outside the disability rules entirely.")
    if receives_va_compensation or va_rating >= FIGURES["exempt_min_rating"]:
        return Exemption(True, EXEMPT_RATED,
                         f"Rated at {max(va_rating, FIGURES['exempt_min_rating'])}% "
                         f"and so receiving — or entitled to receive — VA "
                         f"compensation for a service-connected disability. "
                         f"Ten percent is the whole test.")
    return Exemption(False, "", "")


def fee_band(down_payment_pct: float) -> str:
    if down_payment_pct >= 10.0:
        return BAND_10_PLUS
    if down_payment_pct >= 5.0:
        return BAND_5_TO_10
    return BAND_UNDER_5


def funding_fee_rate(down_payment_pct: float = 0.0,
                     subsequent_use: bool = False,
                     loan_purpose: str = "purchase") -> float:
    """The gross rate before any exemption, as a decimal share of the loan."""
    if loan_purpose == "irrrl":
        return FIGURES["fee_irrrl"]
    if loan_purpose == "cashout":
        return (FIGURES["fee_cashout_subsequent"] if subsequent_use
                else FIGURES["fee_cashout_first_use"])
    table = FIGURES["fee_subsequent"] if subsequent_use else FIGURES["fee_first_use"]
    return table[fee_band(down_payment_pct)]


@dataclass
class FundingFee:
    loan_amount: float = 0.0
    down_payment_pct: float = 0.0
    subsequent_use: bool = False
    loan_purpose: str = "purchase"

    gross_rate: float = 0.0          # what it would cost without the exemption
    gross_amount: float = 0.0
    rate: float = 0.0                # what it actually costs
    amount: float = 0.0

    exempt: bool = False
    exempt_reason: str = ""
    exempt_detail: str = ""
    exemption_worth: float = 0.0

    financed: bool = True
    financed_loan_amount: float = 0.0
    payment_without_fee: float = 0.0
    payment_with_fee: float = 0.0
    extra_payment_monthly: float = 0.0
    extra_interest_over_term: float = 0.0

    first_use_amount: float = 0.0     # for the "$8,600 to $13,200" framing
    subsequent_use_amount: float = 0.0

    notes: list = field(default_factory=list)


def funding_fee(loan_amount: float, down_payment_pct: float = 0.0,
                subsequent_use: bool = False, va_rating: int = 0,
                is_surviving_spouse: bool = False,
                purple_heart_on_active_duty: bool = False,
                receives_va_compensation: bool = False,
                finance_it: bool = True, rate_pct: float = 6.5,
                years: float = 30.0,
                loan_purpose: str = "purchase") -> FundingFee:
    """
    What the fee costs, what the exemption is worth, and what financing it does.

    Financing the fee is the default because almost everybody does it -- it
    keeps cash in hand at closing. It is not free: the fee is borrowed at the
    mortgage rate for thirty years, so a $8,600 fee financed at 6.5% costs
    about $11,000 in interest on top of the fee itself.
    """
    loan = max(0.0, float(loan_amount))
    ex = exemption(va_rating, is_surviving_spouse, purple_heart_on_active_duty,
                   receives_va_compensation)

    gross_rate = funding_fee_rate(down_payment_pct, subsequent_use, loan_purpose)
    f = FundingFee(
        loan_amount=loan, down_payment_pct=down_payment_pct,
        subsequent_use=subsequent_use, loan_purpose=loan_purpose,
        gross_rate=gross_rate, gross_amount=loan * gross_rate,
        exempt=ex.exempt, exempt_reason=ex.reason, exempt_detail=ex.detail,
        financed=finance_it,
    )
    f.rate = 0.0 if ex.exempt else gross_rate
    f.amount = loan * f.rate
    f.exemption_worth = f.gross_amount if ex.exempt else 0.0

    f.first_use_amount = loan * funding_fee_rate(down_payment_pct, False, loan_purpose)
    f.subsequent_use_amount = loan * funding_fee_rate(down_payment_pct, True, loan_purpose)

    f.financed_loan_amount = loan + (f.amount if finance_it else 0.0)
    f.payment_without_fee = monthly_payment(loan, rate_pct, years)
    f.payment_with_fee = monthly_payment(f.financed_loan_amount, rate_pct, years)
    f.extra_payment_monthly = f.payment_with_fee - f.payment_without_fee
    if finance_it and f.amount > 0:
        f.extra_interest_over_term = f.extra_payment_monthly * years * 12.0 - f.amount

    f.notes = _fee_notes(f, years, rate_pct)
    return f


def _money(x: float) -> str:
    return f"${x:,.0f}"


def _fee_notes(f: FundingFee, years: float, rate_pct: float) -> list[str]:
    notes = []

    if f.exempt:
        notes.append(
            f"**You pay no funding fee.** {f.exempt_detail} On this "
            f"{_money(f.loan_amount)} loan the fee would otherwise have been "
            f"{_money(f.gross_amount)} at {f.gross_rate * 100:.2f}%. That is "
            f"the whole of it — not a discount, not a rebate, nothing.")
        notes.append(
            "If the rating came through AFTER you closed on a VA loan, the "
            "exemption is retroactive to the effective date of the award and "
            "the fee is REFUNDABLE. Ask your lender or the VA Regional Loan "
            "Centre for a funding fee refund; nobody will offer it to you.")
    else:
        notes.append(
            f"The fee is {f.gross_rate * 100:.2f}% of the loan — "
            f"{_money(f.gross_amount)} on {_money(f.loan_amount)} — because you "
            f"are putting {f.down_payment_pct:.0f}% down on a "
            f"{'subsequent' if f.subsequent_use else 'first'} use of your "
            f"entitlement.")
        if f.subsequent_use and f.down_payment_pct < 5.0:
            saving = f.loan_amount * (FIGURES["fee_subsequent"][BAND_UNDER_5]
                                      - FIGURES["fee_subsequent"][BAND_5_TO_10])
            notes.append(
                f"Putting 5% down would cut the fee from "
                f"{FIGURES['fee_subsequent'][BAND_UNDER_5] * 100:.2f}% to "
                f"{FIGURES['fee_subsequent'][BAND_5_TO_10] * 100:.2f}% — a "
                f"saving of {_money(saving)}. On a subsequent use the down "
                f"payment buys down the fee much harder than on a first use; "
                f"at 5% down the two are identical.")
        if not f.subsequent_use and f.down_payment_pct < 5.0:
            saving = f.loan_amount * (FIGURES["fee_first_use"][BAND_UNDER_5]
                                      - FIGURES["fee_first_use"][BAND_5_TO_10])
            notes.append(
                f"Five percent down would cut the fee to "
                f"{FIGURES['fee_first_use'][BAND_5_TO_10] * 100:.2f}%, saving "
                f"{_money(saving)}. Weigh that against keeping the cash: for a "
                f"member with no emergency fund, the cash usually wins.")

    if f.financed and f.amount > 0:
        notes.append(
            f"Financed into the loan, the fee adds "
            f"{_money(f.extra_payment_monthly)} a month and "
            f"{_money(f.extra_interest_over_term)} of interest over "
            f"{years:.0f} years at {rate_pct:.3g}%. That is the real price of "
            f"rolling it in — it is a loan at your mortgage rate, not a waiver.")

    notes.append(
        "The funding fee replaces mortgage insurance; it does not sit on top "
        "of it. A VA loan carries no PMI at any loan-to-value, for the life of "
        "the loan, which is usually worth more than the fee costs.")
    return notes


# ==========================================================================
# No PMI: what the VA loan avoids
# ==========================================================================

def pmi_annual_rate(ltv: float) -> float:
    """Assumed conventional PMI rate for a loan-to-value ratio."""
    for threshold, rate in FIGURES["pmi_annual_rate_by_ltv"]:
        if ltv > threshold:
            return rate
    if ltv > FIGURES["pmi_request_ltv"]:
        return FIGURES["pmi_annual_rate_by_ltv"][-1][1]
    return 0.0


@dataclass
class PMIComparison:
    ltv: float = 0.0
    assumed_annual_rate: float = 0.0
    monthly: float = 0.0
    months_until_78_ltv: float = 0.0
    total_paid: float = 0.0
    present_value: float = 0.0
    assumption: str = ""
    note: str = ""


def pmi_saving(loan_amount: float, home_price: float, rate_pct: float,
               years: float = 30.0, annual_rate: float | None = None,
               discount_rate_pct: float | None = None) -> PMIComparison:
    """
    What a conventional loan at the same LTV would charge for mortgage
    insurance, and for how long.

    PMI is not forever: the Homeowners Protection Act terminates it at 78% of
    the ORIGINAL value on the original amortisation schedule. So the honest
    comparison runs to that month, not to the end of the loan.
    """
    price = max(0.0, float(home_price))
    loan = max(0.0, float(loan_amount))
    if price <= 0 or loan <= 0:
        return PMIComparison(assumption="No loan to compare.")

    ltv = loan / price
    rate = pmi_annual_rate(ltv) if annual_rate is None else annual_rate
    c = PMIComparison(ltv=ltv, assumed_annual_rate=rate,
                      monthly=loan * rate / 12.0)

    if rate <= 0:
        c.assumption = (f"At {ltv * 100:.0f}% loan-to-value a conventional loan "
                        f"would not carry PMI either, so this is not where the "
                        f"VA loan wins.")
        return c

    # Month at which the balance falls to 78% of the ORIGINAL value.
    target = price * FIGURES["pmi_auto_termination_ltv"]
    months = 0.0
    if loan > target:
        lo, hi = 0.0, years * 12.0
        for _ in range(60):
            mid = (lo + hi) / 2.0
            if remaining_balance(loan, rate_pct, years, mid) > target:
                lo = mid
            else:
                hi = mid
        months = hi
    c.months_until_78_ltv = months
    c.total_paid = c.monthly * months
    c.present_value = present_value_monthly(
        c.monthly, months,
        rate_pct if discount_rate_pct is None else discount_rate_pct)

    c.assumption = (f"Assumes borrower-paid monthly PMI at "
                    f"{rate * 100:.2f}% of the loan a year at "
                    f"{ltv * 100:.0f}% loan-to-value. Real quotes run from "
                    f"about 0.20% to 1.50% depending on credit score — get "
                    f"your own before you rely on this.")
    c.note = (f"A conventional loan at the same {ltv * 100:.0f}% "
              f"loan-to-value would charge about {_money(c.monthly)} a month "
              f"of mortgage insurance for roughly "
              f"{months / 12.0:.1f} years, until the balance reaches 78% of "
              f"the purchase price — {_money(c.total_paid)} in total, "
              f"{_money(c.present_value)} in present value. The VA loan "
              f"charges none of it, at any loan-to-value, ever.")
    return c


# ==========================================================================
# Entitlement
# ==========================================================================

@dataclass
class Entitlement:
    basic: float = 0.0
    bonus: float = 0.0
    total: float = 0.0
    used: float = 0.0
    available: float = 0.0
    full: bool = True
    county_limit: float = 0.0
    max_zero_down_loan: float | None = None     # None = no limit
    note: str = ""
    notes: list = field(default_factory=list)


def entitlement(county_limit: float | None = None,
                prior_loan_balance: float = 0.0,
                prior_entitlement_restored: bool = True,
                used_before: bool = False) -> Entitlement:
    """
    How much house you can buy with nothing down.

    On FULL entitlement there is no VA loan limit at all -- that changed with
    the Blue Water Navy Vietnam Veterans Act on 1 January 2020, and a great
    deal of advice still in circulation predates it. The conforming limit binds
    only on PARTIAL entitlement, which is what you have while a previous VA
    loan is still outstanding.
    """
    limit = float(county_limit or FIGURES["conforming_limit_2026"])
    basic = FIGURES["basic_entitlement"]
    total = limit * FIGURES["guaranty_share"]
    e = Entitlement(basic=basic, bonus=max(0.0, total - basic), total=total,
                    county_limit=limit)

    outstanding = max(0.0, float(prior_loan_balance))
    has_prior = outstanding > 0 or (used_before and not prior_entitlement_restored)

    if not has_prior:
        e.full = True
        e.used = 0.0
        e.available = total
        e.max_zero_down_loan = None
        e.note = ("Full entitlement. There is no VA loan limit — you can buy at "
                  "any price a lender will underwrite with nothing down, "
                  "subject only to income and the appraisal.")
        e.notes = [
            "The loan limit was removed for full entitlement on 1 January 2020 "
            "by the Blue Water Navy Vietnam Veterans Act. Any source telling "
            "you that you are capped at the conforming limit on full "
            "entitlement is out of date.",
            f"Full entitlement means either you have never used it, or you sold "
            f"the previous home and had the entitlement RESTORED. Restoration "
            f"is not automatic — you file VA Form 26-1880 for a new Certificate "
            f"of Eligibility. There is also a one-time restoration available "
            f"where the loan is paid off but you keep the property.",
        ]
        return e

    # Partial: entitlement in use is 25% of the outstanding prior loan.
    used = min(total, outstanding * FIGURES["guaranty_share"])
    e.full = False
    e.used = used
    e.available = max(0.0, total - used)
    # Zero down requires the guaranty to be 25% of the new loan.
    e.max_zero_down_loan = e.available / FIGURES["guaranty_share"]
    e.note = (f"Partial entitlement. About {_money(used)} of guaranty is tied up "
              f"in the loan you still have, leaving {_money(e.available)} — "
              f"enough to buy at up to {_money(e.max_zero_down_loan)} with "
              f"nothing down. Above that you put down 25% of the excess.")
    e.notes = [
        f"On partial entitlement the county conforming limit — "
        f"{_money(limit)} in a baseline county for {FIGURES['year']}, higher in "
        f"a high-cost one — is what caps the guaranty, so it caps the zero-down "
        f"price too.",
        "This is the second-VA-loan case, and it is common: keep the house at "
        "the last station as a rental, buy at the new one. It works. It also "
        "means the next purchase is smaller, and it means you are a landlord "
        "1,500 miles away.",
    ]
    return e


# ==========================================================================
# Assumability -- the asset nobody prices
# ==========================================================================

@dataclass
class Assumption:
    balance: float = 0.0
    years_left: float = 0.0
    current_rate_pct: float = 0.0
    market_rate_pct: float = 0.0
    rate_gap_pct: float = 0.0

    payment_at_current: float = 0.0
    payment_at_market: float = 0.0
    monthly_saving: float = 0.0

    value: float = 0.0                  # PV of the rate gap to the buyer
    value_pct_of_balance: float = 0.0
    total_nominal_saving: float = 0.0

    buyer_cash_needed: float = 0.0      # the equity gap they must cover
    entitlement_at_risk: float = 0.0
    notes: list = field(default_factory=list)


def assumability_value(balance: float, years_left: float,
                       current_rate_pct: float, market_rate_pct: float,
                       home_value: float = 0.0,
                       discount_rate_pct: float | None = None) -> Assumption:
    """
    What a below-market assumable loan is worth to the buyer who takes it on.

    The buyer assumes a debt of `balance` but pays `payment_at_current` on it.
    Discounted at the rate they would otherwise have to borrow at, that payment
    stream is worth less than the balance -- and the difference is the value of
    the loan, which is a real, transferable asset that shows up in the sale
    price if the seller knows to ask for it.

    Equivalently: the present value, at the market rate, of the payment gap
    over the remaining term. Both framings give the same number.
    """
    bal = max(0.0, float(balance))
    yrs = max(0.0, float(years_left))
    a = Assumption(balance=bal, years_left=yrs,
                   current_rate_pct=current_rate_pct,
                   market_rate_pct=market_rate_pct,
                   rate_gap_pct=market_rate_pct - current_rate_pct)
    if bal <= 0 or yrs <= 0:
        a.notes = ["No balance left to assume."]
        return a

    disc = market_rate_pct if discount_rate_pct is None else discount_rate_pct
    a.payment_at_current = monthly_payment(bal, current_rate_pct, yrs)
    a.payment_at_market = monthly_payment(bal, market_rate_pct, yrs)
    a.monthly_saving = a.payment_at_market - a.payment_at_current
    a.total_nominal_saving = a.monthly_saving * yrs * 12.0
    a.value = present_value_monthly(a.monthly_saving, yrs * 12.0, disc)
    a.value_pct_of_balance = a.value / bal if bal else 0.0

    a.buyer_cash_needed = max(0.0, float(home_value) - bal)
    a.entitlement_at_risk = bal * FIGURES["guaranty_share"]
    a.notes = _assumption_notes(a)
    return a


def _assumption_notes(a: Assumption) -> list[str]:
    notes = []
    if a.rate_gap_pct <= 0.05:
        notes.append(
            f"Your rate of {a.current_rate_pct:.3g}% is not below the market "
            f"rate of {a.market_rate_pct:.3g}%, so the assumability is worth "
            f"essentially nothing today. It is still a free option: if rates "
            f"rise, it becomes worth something without you doing anything.")
        return notes

    notes.append(
        f"Your loan can be ASSUMED by a qualified buyer at "
        f"{a.current_rate_pct:.3g}% while the market charges "
        f"{a.market_rate_pct:.3g}%. That saves them "
        f"{_money(a.monthly_saving)} a month for {a.years_left:.0f} years — "
        f"{_money(a.total_nominal_saving)} in nominal dollars, "
        f"{_money(a.value)} in present value, which is "
        f"{a.value_pct_of_balance * 100:.0f}% of the outstanding balance. "
        f"That is a real asset attached to your house, and it is worth roughly "
        f"what it would cost the buyer to buy the rate down.")
    notes.append(
        "It only turns into money if the listing says so. Price it into the "
        "sale, market the assumption explicitly, and expect the buyer's agent "
        "to have never handled one. Assumption processing runs through the "
        "servicer and takes longer than a normal close — VA charges a 0.5% "
        "assumption funding fee plus a processing fee — so start early.")
    if a.buyer_cash_needed > 0:
        notes.append(
            f"The catch is the equity gap. The buyer assumes the "
            f"{_money(a.balance)} balance but still owes you your equity of "
            f"about {_money(a.buyer_cash_needed)} — in cash, or through a "
            f"second lien. That narrows the buyer pool sharply, and it is why "
            f"assumptions are easier early in a loan than late.")
    notes.append(
        f"**Your entitlement goes with the loan.** On an assumption by a "
        f"non-veteran, about {_money(a.entitlement_at_risk)} of your "
        f"entitlement stays tied to that house until the loan is paid off — "
        f"which may be thirty years. You cannot buy the next house with a "
        f"zero-down VA loan while it is. The only clean release is an assumption "
        f"by an eligible veteran who SUBSTITUTES their own entitlement, which "
        f"must be requested and approved as part of the assumption. Ask for it "
        f"in writing before you sign anything.")
    return notes


# ==========================================================================
# Never prepay a cheap loan
# ==========================================================================

@dataclass
class PrepayVerdict:
    mortgage_rate_pct: float = 0.0
    expected_nominal_return_pct: float = 0.0
    spread_pct: float = 0.0
    prepay_wins: bool = False
    verdict: str = ""
    extra_monthly: float = 0.0
    years_compared: float = 0.0
    value_if_prepaid: float = 0.0       # interest saved on the loan
    value_if_invested: float = 0.0      # ending value of the same payments
    difference: float = 0.0
    notes: list = field(default_factory=list)


def prepay_verdict(mortgage_rate_pct: float, real_return_pct: float,
                   inflation_pct: float, balance: float = 0.0,
                   years_left: float = 0.0,
                   extra_monthly: float = 500.0) -> PrepayVerdict:
    """
    Whether paying the mortgage down early beats investing the same money.

    Paying down a mortgage earns exactly the mortgage rate, risk-free and
    after-tax. That is the whole of the argument for it. When the expected
    return on the portfolio -- REAL return compounded with inflation, not added
    to it -- is above the mortgage rate, prepaying converts a high-expected-
    return dollar into a low-return one, and the gap compounds for decades.

    A 2.75% mortgage held to term against a 6.6% nominal expectation is not a
    debt to be rid of. It is the cheapest leverage a household will ever be
    offered, and inflation is paying it down for you.
    """
    nominal = ((1.0 + real_return_pct / 100.0) * (1.0 + inflation_pct / 100.0)
               - 1.0) * 100.0
    v = PrepayVerdict(mortgage_rate_pct=mortgage_rate_pct,
                      expected_nominal_return_pct=nominal,
                      spread_pct=nominal - mortgage_rate_pct,
                      extra_monthly=extra_monthly,
                      years_compared=years_left)
    v.prepay_wins = mortgage_rate_pct > nominal

    if years_left > 0 and extra_monthly > 0:
        months = years_left * 12.0
        # Prepaying earns the mortgage rate on each extra dollar until the loan
        # would have ended.
        r_m = mortgage_rate_pct / 100.0 / 12.0
        r_i = nominal / 100.0 / 12.0
        v.value_if_prepaid = _future_value_monthly(extra_monthly, months, r_m)
        v.value_if_invested = _future_value_monthly(extra_monthly, months, r_i)
        v.difference = v.value_if_invested - v.value_if_prepaid

    v.verdict = _prepay_verdict_text(v, balance)
    v.notes = _prepay_notes(v, balance)
    return v


def _future_value_monthly(monthly: float, months: float, monthly_rate: float) -> float:
    if monthly <= 0 or months <= 0:
        return 0.0
    if abs(monthly_rate) < 1e-12:
        return monthly * months
    return monthly * ((1.0 + monthly_rate) ** months - 1.0) / monthly_rate


def _prepay_verdict_text(v: PrepayVerdict, balance: float) -> str:
    if v.prepay_wins:
        return (f"Prepay. Your mortgage costs {v.mortgage_rate_pct:.3g}% and "
                f"the portfolio is only expected to return "
                f"{v.expected_nominal_return_pct:.2f}% nominal, so every extra "
                f"dollar against the loan beats the same dollar invested — "
                f"and it beats it with certainty rather than on average.")
    return (f"Do not prepay. Your mortgage costs {v.mortgage_rate_pct:.3g}% "
            f"and the portfolio is expected to return "
            f"{v.expected_nominal_return_pct:.2f}% nominal — a spread of "
            f"{v.spread_pct:.2f} points in favour of investing. Paying this "
            f"loan down early loses money.")


def _prepay_notes(v: PrepayVerdict, balance: float) -> list[str]:
    notes = []
    if not v.prepay_wins and v.difference > 0 and v.years_compared > 0:
        notes.append(
            f"Concretely: {_money(v.extra_monthly)} a month for "
            f"{v.years_compared:.0f} years put against the loan is worth "
            f"{_money(v.value_if_prepaid)} at {v.mortgage_rate_pct:.3g}%. The "
            f"same money invested at {v.expected_nominal_return_pct:.2f}% is "
            f"worth {_money(v.value_if_invested)}. You give up "
            f"{_money(v.difference)} to be debt-free early.")
    notes.append(
        "Compare the mortgage rate against the NOMINAL expected return, not "
        "the real one. The mortgage payment is fixed in nominal dollars, so "
        "inflation erodes it — that is the whole reason a fixed-rate mortgage "
        "is a good thing to owe in an inflationary decade.")
    notes.append(
        "This is an arithmetic answer, not the whole answer. A paid-off house "
        "is a real reduction in required cash flow, which matters enormously "
        "if your income is about to change — separation, a medical board, a "
        "spouse's job lost to a PCS. If a guaranteed lower payment lets you "
        "sleep, that is a legitimate purchase and not an error.")
    notes.append(
        "Before any prepayment: the emergency fund comes first, then anything "
        "above about 6% APR (credit cards, most car loans), then the TSP match "
        "if you have one. A mortgage is near the bottom of that list even when "
        "prepaying does win.")
    return notes


# ==========================================================================
# IRRRL -- the streamline refinance
# ==========================================================================

@dataclass
class IRRRL:
    balance: float = 0.0
    years_left: float = 0.0
    current_rate_pct: float = 0.0
    new_rate_pct: float = 0.0
    funding_fee_rate: float = 0.0
    funding_fee_amount: float = 0.0
    exempt: bool = False
    other_closing_costs: float = 0.0
    total_cost: float = 0.0
    new_loan_amount: float = 0.0
    payment_now: float = 0.0
    payment_after: float = 0.0
    monthly_saving: float = 0.0
    break_even_months: float | None = None
    worth_it: bool = False
    notes: list = field(default_factory=list)


def irrrl(balance: float, years_left: float, current_rate_pct: float,
          new_rate_pct: float, va_rating: int = 0,
          is_surviving_spouse: bool = False,
          purple_heart_on_active_duty: bool = False,
          other_closing_costs: float = 2_000.0,
          new_term_years: float | None = None) -> IRRRL:
    """
    Interest Rate Reduction Refinance Loan: the streamline.

    No appraisal, no income documentation, no new Certificate of Eligibility,
    and a funding fee of 0.5% -- WAIVED, like every other VA funding fee, for a
    veteran rated at 10% or more.
    """
    bal = max(0.0, float(balance))
    term = float(new_term_years or years_left or 0.0)
    ex = exemption(va_rating, is_surviving_spouse, purple_heart_on_active_duty)

    r = IRRRL(balance=bal, years_left=years_left,
              current_rate_pct=current_rate_pct, new_rate_pct=new_rate_pct,
              exempt=ex.exempt, other_closing_costs=other_closing_costs)
    r.funding_fee_rate = 0.0 if ex.exempt else FIGURES["fee_irrrl"]
    r.funding_fee_amount = bal * r.funding_fee_rate
    r.total_cost = r.funding_fee_amount + other_closing_costs
    r.new_loan_amount = bal + r.total_cost

    r.payment_now = monthly_payment(bal, current_rate_pct, years_left)
    r.payment_after = monthly_payment(r.new_loan_amount, new_rate_pct, term)
    r.monthly_saving = r.payment_now - r.payment_after
    if r.monthly_saving > 0:
        r.break_even_months = r.total_cost / r.monthly_saving
        r.worth_it = r.break_even_months < min(36.0, term * 12.0)

    r.notes = _irrrl_notes(r)
    return r


def _irrrl_notes(r: IRRRL) -> list[str]:
    notes = []
    if r.exempt:
        notes.append(
            f"The IRRRL funding fee is 0.5% — and it is waived for you, the "
            f"same as on a purchase. That is {_money(r.balance * FIGURES['fee_irrrl'])} "
            f"you do not pay. The waiver applies to every VA funding fee, not "
            f"just the first.")
    else:
        notes.append(
            f"The IRRRL funding fee is {FIGURES['fee_irrrl'] * 100:.1f}% — "
            f"{_money(r.funding_fee_amount)} on this balance. That is the "
            f"cheapest funding fee the VA charges, and it is why a streamline "
            f"is usually worth doing on a genuine rate drop.")
    if r.monthly_saving > 0 and r.break_even_months:
        notes.append(
            f"Saving {_money(r.monthly_saving)} a month against "
            f"{_money(r.total_cost)} of cost breaks even in "
            f"{r.break_even_months:.0f} months. If you might PCS before then, "
            f"it does not pay — and you will PCS.")
    elif r.new_rate_pct >= r.current_rate_pct:
        notes.append(
            "A streamline has to lower the rate (or move you off an ARM) to "
            "qualify at all. At this rate there is nothing to refinance.")
    notes.append(
        "Watch two things a streamline hides: RESETTING THE CLOCK back to "
        "thirty years lowers the payment while raising lifetime interest, and "
        "rolling costs into the balance means you are borrowing the closing "
        "costs at the mortgage rate. Ask for the payment on the SAME remaining "
        "term as a comparison.")
    return notes


# ==========================================================================
# Findings
# ==========================================================================

def findings(fee: FundingFee | None = None,
             pmi: PMIComparison | None = None,
             ent: Entitlement | None = None,
             assume: Assumption | None = None,
             prepay: PrepayVerdict | None = None,
             is_va_loan: bool = False,
             owns_home: bool = False,
             va_rating: int = 0) -> list[tuple[str, str, str]]:
    """(severity, headline, detail)."""
    out: list[tuple[str, str, str]] = []

    if fee is not None and fee.exempt and fee.gross_amount > 0:
        out.append(("good",
                    f"Your funding fee is waived — {_money(fee.gross_amount)} "
                    f"you do not pay.",
                    fee.exempt_detail + " On a $400,000 loan the same waiver is "
                    "worth between $8,600 and $13,200 depending on whether it "
                    "is a first or a subsequent use. If you have already closed "
                    "a VA loan and the rating was effective before that closing, "
                    "the fee is refundable — ask the VA Regional Loan Centre."))
    elif fee is not None and not fee.exempt and 0 < va_rating < 10:
        out.append(("info", "A 10% rating would waive the funding fee entirely.",
                    f"You are rated below 10%, so the fee applies — "
                    f"{_money(fee.gross_amount)} on this loan. Ten percent is "
                    f"the whole test, and it is not a high bar. If you have "
                    f"conditions you have never claimed, that claim is worth "
                    f"more than the monthly compensation alone."))
    elif fee is not None and not fee.exempt and va_rating == 0:
        out.append(("info", "No rating on file, so the funding fee applies.",
                    f"{_money(fee.gross_amount)} on this loan. A "
                    f"service-connected rating of 10% or more waives it "
                    f"completely — as does a Purple Heart while you are still "
                    f"on active duty. If you have an unfiled claim, file it "
                    f"before you close."))

    if pmi is not None and pmi.total_paid > 0:
        out.append(("good", "No mortgage insurance, at any loan-to-value.",
                    pmi.note + " " + pmi.assumption))

    if ent is not None and not ent.full and ent.max_zero_down_loan is not None:
        out.append(("warn", "You are on partial entitlement.",
                    ent.note + " Keeping the last house as a rental is what "
                    "usually causes this, and it is a legitimate choice — but "
                    "it constrains the next purchase, so decide it deliberately."))
    elif ent is not None and ent.full:
        out.append(("good", "Full entitlement: no VA loan limit.",
                    "Since 1 January 2020 there is no cap on a zero-down VA "
                    "loan for a veteran with full entitlement. Advice that "
                    "says otherwise predates the Blue Water Navy Act."))

    if assume is not None and assume.value > 5_000:
        out.append(("good",
                    f"Your rate is an asset worth about {_money(assume.value)}.",
                    f"A qualified buyer can ASSUME this loan at "
                    f"{assume.current_rate_pct:.3g}% while the market charges "
                    f"{assume.market_rate_pct:.3g}%. Price it into the listing "
                    f"— it is the single most valuable thing about the house "
                    f"and almost no listing mentions it. Two warnings: the "
                    f"buyer must cover your equity of about "
                    f"{_money(assume.buyer_cash_needed)} in cash, and your "
                    f"entitlement stays tied to the loan unless the buyer is a "
                    f"veteran who substitutes their own."))

    if prepay is not None and not prepay.prepay_wins and prepay.mortgage_rate_pct > 0:
        out.append(("info", "Do not pay this mortgage down early.",
                    prepay.verdict + " Put the money in the TSP or a brokerage "
                    "account instead, where it stays liquid — equity in a house "
                    "you have to sell from another time zone is not."))
    elif prepay is not None and prepay.prepay_wins and prepay.mortgage_rate_pct > 0:
        out.append(("info", "Paying this mortgage down early does beat investing.",
                    prepay.verdict + " Only after the emergency fund, any debt "
                    "above about 6%, and the TSP match, though."))

    if owns_home and not is_va_loan:
        out.append(("info", "This is not a VA loan.",
                    "If you are eligible and the rate is at or above the "
                    "market, refinancing into a VA loan removes PMI "
                    "immediately and permanently. That is a VA cash-out "
                    "refinance rather than a streamline — the streamline "
                    "(IRRRL) only refinances an existing VA loan."))

    return out
