"""
Buying at this station against renting at BAH, over a PCS horizon.

The civilian rent-versus-buy calculation assumes you choose when to sell. A
service member does not. Orders arrive, and the house is sold into whatever
market exists on the day -- or it is not sold at all, and you become a landlord
in a state you no longer live in.

That single difference reorders the whole answer. Buying wins on a long enough
horizon almost everywhere, because the transaction costs amortise: roughly 2-3%
to buy and 6-8% to sell means the house has to appreciate about 9% before you
are even. At typical appreciation that takes four to six years. A three-year
assignment does not get there, and three years is the modal tour length.

WHAT THIS MODEL DOES

Two paths, identical starting wealth, compared month by month in nominal terms:

  BUY   Pay the down payment, the closing costs and any funding fee up front.
        Then principal, interest, property tax, insurance, maintenance at 1% of
        value a year. At the horizon, sell: value less selling costs less the
        remaining balance.
  RENT  Invest that same up-front cash, plus every month that owning costs more
        than renting, at the expected portfolio return. Rent grows with
        inflation and is capped at 105% of BAH, because that is what the
        allowance is set to cover.

Whichever path costs less in a given month, the OTHER path invests the
difference -- so neither side gets a free ride on cash flow. The answer is the
horizon at which the two lines cross.

THREE MILITARY-SPECIFIC ITEMS, all of which move the answer:

  1. THE THREE-YEAR TOUR. See above. Run the horizon table before the realtor
     tells you that renting is throwing money away.
  2. THE ACCIDENTAL LANDLORD. Not selling is a decision too. It carries
     vacancy, a 8-10% management fee, repairs you cannot inspect, and tenant
     law in a state you have left. It is a business, and it is the default
     outcome of buying on a short tour into a flat market.
  3. THE CAPITAL GAINS SUSPENSION. Section 121 excludes $250,000 of gain
     ($500,000 married) if you lived in the home two of the last five years.
     For qualified official extended duty that five-year window can be
     SUSPENDED for up to ten years -- so up to fifteen years to sell and still
     exclude the gain. This is a genuine and large advantage, and it is the
     single best reason to keep a house you were going to sell at a loss.
"""

from __future__ import annotations
from dataclasses import dataclass, field

from engine.pay.bah import DEFAULT_HOUSING_COST_SHARE
from engine.housing.va_loan import monthly_payment, remaining_balance

# ==========================================================================
# Defaults. Assumptions about the world, not published figures.
# ==========================================================================
DEFAULTS = {
    "closing_cost_pct": 2.5,        # 2-3% of price, buyer side
    "selling_cost_pct": 7.0,        # 6-8%: commission, concessions, title
    "maintenance_pct": 1.0,         # of value, per year
    "insurance_pct": 0.5,           # homeowner's, of value, per year
    "property_tax_pct": 1.1,        # of value, per year, when not entered
    "max_horizon_years": 15,
}

# The Section 121 suspension, for the notes below.
SECTION_121_SUSPENSION_YEARS = 10
SECTION_121_EXCLUSION_SINGLE = 250_000
SECTION_121_EXCLUSION_JOINT = 500_000

SECTION_121_VERIFY = (
    "VERIFY at irs.gov Publication 523 and 26 U.S.C. 121(d)(9): the five-year "
    "lookback for the two-of-five-year use test may be suspended for up to 10 "
    "years of qualified official extended duty — duty at a station at least 50 "
    "miles from the residence, or living in government quarters under orders, "
    "for more than 90 days or for an indefinite period. The election is made "
    "for one property at a time. Confidence MEDIUM-HIGH on the rule, LOWER on "
    "whether your particular orders qualify: this is worth ten minutes with a "
    "tax professional or the installation legal assistance office, because the "
    "amount at stake is the tax on the entire gain."
)


# ==========================================================================
# The comparison
# ==========================================================================

@dataclass
class HorizonRow:
    year: int = 0
    home_value: float = 0.0
    mortgage_balance: float = 0.0
    equity: float = 0.0
    sale_proceeds: float = 0.0          # after selling costs, after payoff
    own_investments: float = 0.0
    own_net: float = 0.0
    rent_portfolio: float = 0.0
    rent_net: float = 0.0
    advantage: float = 0.0              # own_net - rent_net; positive = buy
    own_monthly_cost: float = 0.0
    rent_monthly: float = 0.0
    cumulative_own_outlay: float = 0.0
    cumulative_rent_outlay: float = 0.0


@dataclass
class RentVsBuy:
    price: float = 0.0
    loan_amount: float = 0.0
    down_payment: float = 0.0
    upfront_cash: float = 0.0
    closing_costs: float = 0.0
    funding_fee: float = 0.0

    monthly_pi: float = 0.0
    monthly_piti: float = 0.0
    monthly_all_in: float = 0.0         # PITI + maintenance + HOA
    rent_monthly: float = 0.0
    rent_is_bah_capped: bool = False
    bah_monthly: float = 0.0

    appreciation_pct: float = 0.0
    nominal_return_pct: float = 0.0

    rows: list = field(default_factory=list)
    break_even_years: float | None = None
    horizon_years: float = 0.0
    advantage_at_horizon: float = 0.0
    verdict: str = ""
    buy_wins_at_horizon: bool = False
    notes: list = field(default_factory=list)


def effective_rent(monthly_rent: float, bah_monthly: float,
                   share: float = DEFAULT_HOUSING_COST_SHARE) -> tuple[float, bool]:
    """
    What renting actually costs, and whether BAH is what set it.

    The comparison is against renting at the allowance, so a rent figure above
    105% of BAH is not the alternative being modelled -- if you would rent for
    less than you would spend owning, the honest comparison uses the cheaper
    one. Returns (rent, capped_by_bah).
    """
    cap = max(0.0, bah_monthly) * share
    r = max(0.0, monthly_rent)
    if r > 0 and cap > 0:
        return (min(r, cap), r > cap)
    if r > 0:
        return (r, False)
    return (cap, cap > 0)


def compare(price: float,
            mortgage_rate_pct: float,
            *,
            down_payment_pct: float = 0.0,
            term_years: float = 30.0,
            monthly_rent: float = 0.0,
            bah_monthly: float = 0.0,
            annual_property_tax: float = 0.0,
            appreciation_pct: float | None = None,
            inflation_pct: float = 2.5,
            real_return_pct: float = 4.0,
            closing_cost_pct: float | None = None,
            selling_cost_pct: float | None = None,
            maintenance_pct: float | None = None,
            insurance_pct: float | None = None,
            hoa_monthly: float = 0.0,
            renters_insurance_monthly: float = 0.0,
            funding_fee_amount: float = 0.0,
            finance_funding_fee: bool = True,
            itemized_deduction_rate: float = 0.0,
            horizon_years: float = 3.0,
            max_years: int | None = None) -> RentVsBuy:
    """
    Buy here, or rent here and invest the difference?

    Everything is NOMINAL: rents and house prices grow with inflation, the
    portfolio earns the real return compounded with inflation, and the mortgage
    payment is fixed. Mixing a real return with nominal appreciation is the
    commonest way this calculation goes wrong, and it always goes wrong in
    favour of buying.
    """
    p = max(0.0, float(price))
    max_years = int(max_years or DEFAULTS["max_horizon_years"])
    closing_pct = DEFAULTS["closing_cost_pct"] if closing_cost_pct is None else closing_cost_pct
    sell_pct = DEFAULTS["selling_cost_pct"] if selling_cost_pct is None else selling_cost_pct
    maint_pct = DEFAULTS["maintenance_pct"] if maintenance_pct is None else maintenance_pct
    ins_pct = DEFAULTS["insurance_pct"] if insurance_pct is None else insurance_pct
    g = inflation_pct if appreciation_pct is None else appreciation_pct

    nominal_return = ((1.0 + real_return_pct / 100.0)
                      * (1.0 + inflation_pct / 100.0) - 1.0) * 100.0

    rent0, capped = effective_rent(monthly_rent, bah_monthly)

    r = RentVsBuy(price=p, appreciation_pct=g, nominal_return_pct=nominal_return,
                  rent_monthly=rent0, rent_is_bah_capped=capped,
                  bah_monthly=bah_monthly, horizon_years=horizon_years,
                  funding_fee=funding_fee_amount)

    if p <= 0:
        r.verdict = "Enter a purchase price to compare."
        r.notes = _traps(r, horizon_years)
        return r

    r.down_payment = p * down_payment_pct / 100.0
    r.closing_costs = p * closing_pct / 100.0
    r.loan_amount = p - r.down_payment + (funding_fee_amount if finance_funding_fee else 0.0)
    r.upfront_cash = (r.down_payment + r.closing_costs
                      + (0.0 if finance_funding_fee else funding_fee_amount))

    tax_annual0 = (annual_property_tax if annual_property_tax > 0
                   else p * DEFAULTS["property_tax_pct"] / 100.0)

    r.monthly_pi = monthly_payment(r.loan_amount, mortgage_rate_pct, term_years)
    r.monthly_piti = r.monthly_pi + tax_annual0 / 12.0 + p * ins_pct / 100.0 / 12.0
    r.monthly_all_in = r.monthly_piti + p * maint_pct / 100.0 / 12.0 + hoa_monthly

    # ---- month by month -------------------------------------------------
    g_m = (1.0 + g / 100.0) ** (1.0 / 12.0) - 1.0
    infl_m = (1.0 + inflation_pct / 100.0) ** (1.0 / 12.0) - 1.0
    ret_m = (1.0 + nominal_return / 100.0) ** (1.0 / 12.0) - 1.0
    loan_m = mortgage_rate_pct / 100.0 / 12.0

    value = p
    balance = r.loan_amount
    rent = rent0
    own_invest = 0.0
    rent_port = r.upfront_cash
    cum_own = r.upfront_cash
    cum_rent = 0.0

    months = max_years * 12
    break_even_month: float | None = None
    prev_adv: float | None = None
    rows: list[HorizonRow] = []

    for m in range(1, months + 1):
        interest = balance * loan_m
        principal_paid = max(0.0, min(balance, r.monthly_pi - interest))
        balance = max(0.0, balance - principal_paid)

        tax_m = tax_annual0 * (value / p) / 12.0
        ins_m = value * ins_pct / 100.0 / 12.0
        maint_m = value * maint_pct / 100.0 / 12.0
        own_cost = r.monthly_pi + tax_m + ins_m + maint_m + hoa_monthly
        if balance <= 0:
            own_cost = tax_m + ins_m + maint_m + hoa_monthly
        if itemized_deduction_rate > 0:
            own_cost -= itemized_deduction_rate * (interest + tax_m)

        rent_cost = rent + renters_insurance_monthly

        own_invest *= (1.0 + ret_m)
        rent_port *= (1.0 + ret_m)
        diff = own_cost - rent_cost
        if diff > 0:
            rent_port += diff
        else:
            own_invest += -diff

        cum_own += own_cost
        cum_rent += rent_cost

        value *= (1.0 + g_m)
        rent *= (1.0 + infl_m)

        proceeds = value * (1.0 - sell_pct / 100.0) - balance
        own_net = proceeds + own_invest
        adv = own_net - rent_port

        if break_even_month is None and adv >= 0:
            if prev_adv is not None and prev_adv < 0:
                frac = -prev_adv / (adv - prev_adv)
                break_even_month = (m - 1) + frac
            else:
                break_even_month = float(m)
        prev_adv = adv

        if m % 12 == 0:
            rows.append(HorizonRow(
                year=m // 12, home_value=value, mortgage_balance=balance,
                equity=value - balance, sale_proceeds=proceeds,
                own_investments=own_invest, own_net=own_net,
                rent_portfolio=rent_port, rent_net=rent_port, advantage=adv,
                own_monthly_cost=own_cost, rent_monthly=rent_cost,
                cumulative_own_outlay=cum_own, cumulative_rent_outlay=cum_rent))

    r.rows = rows
    r.break_even_years = (break_even_month / 12.0) if break_even_month else None
    r.advantage_at_horizon = advantage_at(r, horizon_years)
    r.buy_wins_at_horizon = r.advantage_at_horizon > 0
    r.verdict = _verdict(r)
    r.notes = _traps(r, horizon_years)
    return r


def advantage_at(r: RentVsBuy, years: float) -> float:
    """Buying's advantage over renting at an arbitrary horizon, interpolated."""
    if not r.rows:
        return 0.0
    y = max(0.0, float(years))
    if y <= r.rows[0].year:
        # Below one year, interpolate from the up-front cash burn to year one.
        start = -(r.closing_costs + r.price * DEFAULTS["selling_cost_pct"] / 100.0)
        frac = y / r.rows[0].year if r.rows[0].year else 0.0
        return start + frac * (r.rows[0].advantage - start)
    if y >= r.rows[-1].year:
        return r.rows[-1].advantage
    lo = max((row for row in r.rows if row.year <= y), key=lambda x: x.year)
    hi = min((row for row in r.rows if row.year >= y), key=lambda x: x.year)
    if hi.year == lo.year:
        return lo.advantage
    frac = (y - lo.year) / (hi.year - lo.year)
    return lo.advantage + frac * (hi.advantage - lo.advantage)


def _money(x: float) -> str:
    sign = "-" if x < 0 else ""
    return f"{sign}${abs(x):,.0f}"


def _verdict(r: RentVsBuy) -> str:
    y = r.horizon_years
    if r.break_even_years is None:
        return (f"On these assumptions buying never catches renting inside "
                f"{len(r.rows)} years. That usually means the rent is well "
                f"below the cost of owning the same house — which is common "
                f"near a base, because BAH sets the rental market and "
                f"purchase prices are set by the civilian one.")
    if r.buy_wins_at_horizon:
        return (f"Buy. Over {y:.0f} years owning comes out about "
                f"{_money(r.advantage_at_horizon)} ahead, and it breaks even "
                f"at {r.break_even_years:.1f} years — inside your horizon.")
    return (f"Rent. Buying does not break even until {r.break_even_years:.1f} "
            f"years, and you expect {y:.0f} at this station. Selling at "
            f"{y:.0f} years costs you about "
            f"{_money(-r.advantage_at_horizon)} against renting and investing "
            f"the difference.")


def _traps(r: RentVsBuy, horizon: float) -> list[str]:
    notes = []

    if r.rent_is_bah_capped and r.bah_monthly > 0:
        notes.append(
            f"Rent is modelled at {_money(r.rent_monthly)} a month — "
            f"{DEFAULT_HOUSING_COST_SHARE * 100:.0f}% of your "
            f"{_money(r.bah_monthly)} BAH, which is what the allowance is set "
            f"to cover. If you would actually rent for less than that, the "
            f"case for renting is stronger than this shows.")

    if r.price > 0:
        round_trip = (DEFAULTS["closing_cost_pct"] + DEFAULTS["selling_cost_pct"])
        notes.append(
            f"The round trip costs about {round_trip:.0f}% of the price — "
            f"{_money(r.price * round_trip / 100.0)} on this house — before the "
            f"first dollar of interest. That is the hurdle appreciation has to "
            f"clear, and at {r.appreciation_pct:.1f}% a year it takes roughly "
            f"{round_trip / max(r.appreciation_pct, 0.1):.1f} years to clear it.")

    notes.append(
        "**A three-year tour rarely breaks even.** Three years is the modal "
        "assignment length and it is shorter than the break-even on almost any "
        "reasonable set of assumptions. Buying on a three-year tour is a bet on "
        "appreciation, not a way to stop wasting rent — and it is a bet made "
        "with an exit date you do not control.")

    notes.append(
        "**The accidental landlord.** If the market is soft when the orders "
        "arrive, most people rent the house out rather than sell at a loss. "
        "Price that outcome before you buy, not after: expect 8-10% of rent to "
        "a property manager, a month or more of vacancy per turnover, repairs "
        "you cannot inspect, and landlord-tenant law in a state you no longer "
        "live in. It also ties up your VA entitlement while the loan runs. It "
        "can work well — but it is a small business, not a passive asset.")

    notes.append(
        f"**The capital-gains rule bends for you.** Section 121 excludes "
        f"${SECTION_121_EXCLUSION_SINGLE:,} of gain (${SECTION_121_EXCLUSION_JOINT:,} "
        f"married filing jointly) if you lived in the home for two of the last "
        f"five years. On qualified official extended duty that five-year window "
        f"can be SUSPENDED for up to {SECTION_121_SUSPENSION_YEARS} years — so "
        f"up to fifteen years to sell and still exclude the gain. Almost no "
        f"civilian source mentions it, and it is the reason a house you rent "
        f"out after a PCS is far less of a tax problem for you than for "
        f"anybody else. {SECTION_121_VERIFY}")

    notes.append(
        "Mortgage interest and property tax are modelled as pure cost, with no "
        "deduction. For most junior and mid-career members that is right: the "
        "standard deduction is larger than the itemised total, and BAH is "
        "already tax-free, so there is no taxable income for the deduction to "
        "shelter. If you do itemise, set the deduction rate and the answer "
        "shifts toward buying.")

    return notes


def findings(r: RentVsBuy, years_at_station: float,
             owns_home: bool = False) -> list[tuple[str, str, str]]:
    """(severity, headline, detail)."""
    out: list[tuple[str, str, str]] = []
    if not r.rows:
        return out

    if r.break_even_years is None:
        out.append(("warn", "Buying does not break even on any horizon modelled.",
                    r.verdict))
    elif r.break_even_years > years_at_station:
        out.append(("warn",
                    f"Break-even is {r.break_even_years:.1f} years and you "
                    f"expect {years_at_station:.0f}.",
                    f"Selling at {years_at_station:.0f} years costs about "
                    f"{_money(-r.advantage_at_horizon)} against renting at BAH "
                    f"and investing the difference. The gap is transaction "
                    f"costs, not the mortgage: about "
                    f"{_money(r.price * (DEFAULTS['closing_cost_pct'] + DEFAULTS['selling_cost_pct']) / 100.0)} "
                    f"to buy and sell this house."))
    else:
        out.append(("good",
                    f"Break-even is {r.break_even_years:.1f} years, inside your "
                    f"{years_at_station:.0f}-year horizon.",
                    f"Owning comes out about {_money(r.advantage_at_horizon)} "
                    f"ahead at {years_at_station:.0f} years. That result is "
                    f"sensitive to the appreciation assumption — set it to "
                    f"zero and see what survives."))

    if years_at_station <= 3:
        out.append(("info", "A three-year tour is the hard case.",
                    "It is the modal assignment length and it is shorter than "
                    "almost any break-even. If you buy anyway, buy something "
                    "that rents easily near the gate rather than the house you "
                    "would choose to live in for twenty years — you are "
                    "buying a future rental whether you mean to or not."))

    out.append(("info", "If you PCS and cannot sell, the tax rule is on your side.",
                f"Section 121's two-of-five-year test can be suspended for up "
                f"to {SECTION_121_SUSPENSION_YEARS} years of qualified official "
                f"extended duty, giving you up to fifteen years to sell and "
                f"still exclude "
                f"${SECTION_121_EXCLUSION_JOINT:,} of gain filing jointly. "
                f"Make the election deliberately and keep the orders. VERIFY at "
                f"IRS Publication 523."))

    if owns_home:
        out.append(("info", "Renting it out is a business, not a plan.",
                    "Budget 8-10% for management, a month of vacancy per "
                    "turnover, and 1% of value a year for maintenance you "
                    "cannot supervise. Then check the cash flow against the "
                    "rent the BAH market will actually pay — near a base, rents "
                    "are capped by the allowance while prices are not."))

    return out


# ==========================================================================
# Disabled-veteran property tax exemptions, by state
# ==========================================================================
#
# INCOMPLETE AND UNVERIFIED. This machine cannot reach any state comptroller,
# so the table below is from memory. Every entry carries its own confidence,
# and `lookup` returns None -- not a guess -- for any state that is not in it.
# A wrong exemption here would be worth thousands of dollars a year in the
# wrong direction, so the absence of an entry means "go and find out", never
# "no exemption exists".
#
# Almost every state has SOMETHING. If your state is not here, search
# "<state> disabled veteran property tax exemption" and call the county
# assessor. Most of these have to be APPLIED FOR, most have a filing deadline,
# and several are retroactive to the effective date of the rating if you file
# late with the award letter.

PROPERTY_TAX_VERIFY = (
    "VERIFY with the state comptroller or your county assessor. This table is "
    "INCOMPLETE — most states are missing — and every figure in it is from "
    "memory rather than from the statute. It is a prompt to go and look, not "
    "an authority. Exemptions almost always have to be applied for, usually "
    "have an annual filing deadline, and are often retroactive to the "
    "effective date of the rating."
)

# state -> list of (min_rating, max_rating, kind, amount, description)
# kind: "full" (whole homestead), "amount" (dollars off assessed value),
#       "percent" (share of the tax bill).
_TEXAS_SCHEDULE = [
    (10, 29, "amount", 5_000.0, "$5,000 off assessed value"),
    (30, 49, "amount", 7_500.0, "$7,500 off assessed value"),
    (50, 69, "amount", 10_000.0, "$10,000 off assessed value"),
    (70, 99, "amount", 12_000.0, "$12,000 off assessed value"),
    (100, 100, "full", 0.0, "Total exemption of the residence homestead"),
]

STATE_EXEMPTIONS: dict[str, dict] = {
    "TX": {
        "name": "Texas",
        "schedule": _TEXAS_SCHEDULE,
        "confidence": "MEDIUM-HIGH",
        "citation": "Tex. Tax Code 11.131 (100% / individually unemployable) "
                    "and 11.22 (partial schedule by rating).",
        "note": "At 100% — or at a lower rating with individual "
                "unemployability paid at the 100% rate — the residence "
                "homestead is fully exempt from property tax. Below that the "
                "exemption is a flat dollar amount off assessed value on the "
                "schedule above, which is small. A surviving spouse who has "
                "not remarried generally keeps the 100% exemption.",
    },
    "FL": {
        "name": "Florida",
        "schedule": [
            (10, 99, "amount", 5_000.0, "$5,000 off assessed value"),
            (100, 100, "full", 0.0, "Total exemption of the homestead"),
        ],
        "confidence": "MEDIUM",
        "citation": "Fla. Stat. 196.24 (10%+, $5,000) and 196.081 "
                    "(100% permanent and total, full exemption).",
        "note": "Florida also gives veterans aged 65 or over with a "
                "combat-related disability a discount equal to the rating "
                "percentage (Fla. Stat. 196.082), which is a separate and "
                "sometimes larger benefit.",
    },
    "VA": {
        "name": "Virginia",
        "schedule": [(100, 100, "full", 0.0, "Total exemption of the principal residence")],
        "confidence": "MEDIUM-HIGH",
        "citation": "Va. Const. art. X, sec. 6-A; Va. Code 58.1-3219.5.",
        "note": "100% permanent and total service-connected only — there is no "
                "partial schedule. Covers the principal residence and the land "
                "it sits on. A surviving spouse who does not remarry keeps it.",
    },
    "MI": {
        "name": "Michigan",
        "schedule": [(100, 100, "full", 0.0, "Total exemption of the homestead")],
        "confidence": "MEDIUM",
        "citation": "MCL 211.7b.",
        "note": "100% permanent and total, individually unemployable, or in "
                "receipt of a VA specially adapted housing grant. Michigan has "
                "repeatedly considered converting this exemption into an "
                "income-tax credit — confirm the current year's mechanism with "
                "the assessor before budgeting on it.",
    },
    "NJ": {
        "name": "New Jersey",
        "schedule": [(100, 100, "full", 0.0, "Total exemption of the dwelling")],
        "confidence": "MEDIUM",
        "citation": "N.J.S.A. 54:4-3.30.",
        "note": "100% permanent and total service-connected. Since 2020 the "
                "wartime-service requirement has been removed. A surviving "
                "spouse who does not remarry keeps it.",
    },
    "MD": {
        "name": "Maryland",
        "schedule": [(100, 100, "full", 0.0, "Total exemption of the dwelling")],
        "confidence": "MEDIUM",
        "citation": "Md. Code, Tax-Prop. 7-208.",
        "note": "100% permanent and total. Maryland has added a partial "
                "exemption at lower ratings in recent sessions — check the "
                "current year with the Department of Assessments and Taxation.",
    },
    "SC": {
        "name": "South Carolina",
        "schedule": [(100, 100, "full", 0.0, "Total exemption of the house and up to one acre")],
        "confidence": "MEDIUM",
        "citation": "S.C. Code 12-37-220(B)(1).",
        "note": "100% permanent and total service-connected, on the house and "
                "up to one acre.",
    },
    "OK": {
        "name": "Oklahoma",
        "schedule": [(100, 100, "full", 0.0, "Total exemption of the homestead")],
        "confidence": "MEDIUM",
        "citation": "Okla. Const. art. X, sec. 8E.",
        "note": "100% permanent and total service-connected. Oklahoma also "
                "exempts these households from state sales tax up to an annual "
                "cap, which is worth more than most people expect.",
    },
    "AL": {
        "name": "Alabama",
        "schedule": [(100, 100, "full", 0.0, "Total exemption of the homestead")],
        "confidence": "MEDIUM",
        "citation": "Ala. Code 40-9-21.",
        "note": "100% permanent and total service-connected, on the homestead "
                "and up to 160 acres.",
    },
    "IL": {
        "name": "Illinois",
        "schedule": [
            (30, 49, "amount", 2_500.0, "$2,500 off equalised assessed value"),
            (50, 69, "amount", 5_000.0, "$5,000 off equalised assessed value"),
            (70, 100, "full", 0.0, "Total exemption of the homestead"),
        ],
        "confidence": "MEDIUM",
        "citation": "35 ILCS 200/15-169 (Standard Homestead Exemption for "
                    "Veterans with Disabilities).",
        "note": "Illinois is one of the few states with a genuinely graduated "
                "schedule, and 70% is enough for a full exemption. It must be "
                "re-filed annually in most counties.",
    },
}

_STATE_ALIASES = {v["name"].upper(): k for k, v in STATE_EXEMPTIONS.items()}


@dataclass
class PropertyTaxExemption:
    state: str = ""
    state_code: str = ""
    rating: int = 0
    qualifies: bool = False
    full_exemption: bool = False
    kind: str = "none"                 # full | amount | percent | none
    exempt_value: float = 0.0          # dollars off assessed value
    description: str = ""
    citation: str = ""
    confidence: str = ""
    note: str = ""
    verify: str = PROPERTY_TAX_VERIFY

    def saving(self, annual_property_tax: float,
               assessed_value: float = 0.0) -> float:
        """Roughly what the exemption is worth a year, in tax."""
        if not self.qualifies or annual_property_tax <= 0:
            return 0.0
        if self.full_exemption:
            return annual_property_tax
        if self.kind == "percent":
            return annual_property_tax * self.exempt_value
        if self.kind == "amount" and assessed_value > 0:
            share = min(1.0, self.exempt_value / assessed_value)
            return annual_property_tax * share
        return 0.0


def normalise_state(state: str) -> str | None:
    """'tx', 'Texas', 'TEXAS' -> 'TX'. None if we do not have that state."""
    s = (state or "").strip().upper()
    if not s:
        return None
    if s in STATE_EXEMPTIONS:
        return s
    return _STATE_ALIASES.get(s)


def lookup(state: str, rating: int) -> PropertyTaxExemption | None:
    """
    The disabled-veteran property tax exemption for a state and a rating.

    Returns None -- deliberately, not a zero -- for any state not in the table.
    None means "this app does not know", which is different from "there is no
    exemption". Almost every state has one; most of them are not in here yet.
    """
    code = normalise_state(state)
    if code is None:
        return None

    entry = STATE_EXEMPTIONS[code]
    rating = int(max(0, min(100, rating or 0)))
    result = PropertyTaxExemption(
        state=entry["name"], state_code=code, rating=rating,
        citation=entry["citation"], confidence=entry["confidence"],
        note=entry["note"])

    for lo, hi, kind, amount, description in entry["schedule"]:
        if lo <= rating <= hi:
            result.qualifies = True
            result.kind = kind
            result.full_exemption = (kind == "full")
            result.exempt_value = amount
            result.description = description
            return result

    lowest = min(row[0] for row in entry["schedule"])
    result.description = (f"No exemption at a {rating}% rating in "
                          f"{entry['name']}; the schedule starts at {lowest}%.")
    return result


def states_covered() -> list[str]:
    return sorted(v["name"] for v in STATE_EXEMPTIONS.values())
