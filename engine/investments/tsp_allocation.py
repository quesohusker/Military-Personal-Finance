"""
How the money is actually invested: the five TSP funds, the L funds, and the
one fact about a military balance sheet that changes the answer.

THE MILITARY INSIGHT, WHICH COMES FIRST.
A retired service member with a COLA'd pension and VA compensation already owns
an enormous bond-like asset. It is inflation-indexed, federally backed, pays
monthly for life, and has no default risk and no duration risk that the holder
can feel. Nothing sold at retail resembles it. Valued at what an equivalent
income stream would cost to replace (engine/networth/balance_sheet.py), it is
routinely worth more than the entire TSP.

That has a direct consequence for allocation, and it runs the opposite way to
the advice a retiree is usually given. If the pension is the bond position,
then holding a "balanced" 60/40 inside the TSP on top of it produces a
household that is perhaps 85% fixed income -- far more conservative than
anybody intended, and almost certainly too conservative for money that has to
last forty years and support two generations. The same person's investable
assets can carry MORE equity than a civilian's at the same age, not less.

SEQUENCE-OF-RETURNS RISK IS WHAT THE PENSION ACTUALLY INSURES.
The reason to de-risk near retirement is not that shares are riskier at 60 than
at 30. It is that a bad first decade of withdrawals is unrecoverable: you sell
units to eat, and units sold at the bottom never come back. That risk exists
only for spending funded by SELLING. Where guaranteed income covers the
spending, there is nothing to sell, so there is no sequence risk to manage on
that portion -- and a coverage ratio above 1.0 means the portfolio need not be
touched in a bad year at all.

WHAT THIS MODULE DOES NOT DO. It never names a security outside the TSP's own
funds. There is no ticker in this file and there should never be one. The TSP
funds are the whole opportunity set here because that is what the member
actually holds, and because the honest finding on this page is usually about
fees and asset location rather than about picking anything.

NUMBERS THAT AGE. The expense ratios and the L Fund glide path are published
figures that move a little every year. Every one carries a VERIFY entry below
saying what it is, where to check it and how far to trust it. Nothing on this
page turns on a basis point or on two points of equity, and the module is
written so that it would not.
"""

from __future__ import annotations
from dataclasses import dataclass, field

from engine.networth import balance_sheet as BS

# ==========================================================================
# The five funds
# ==========================================================================

FUND_CODES = ("G", "F", "C", "S", "I")
EQUITY_CODES = ("C", "S", "I")
FIXED_CODES = ("G", "F")

# Net expense ratios, in PERCENT of assets. See VERIFY["expense_ratios"].
EXPENSE_RATIO_YEAR = 2026
# CHECKED against tsp.gov/funds-individual (fetched 2026-09-10). Each fund is
# identified by the index it tracks, which is how the page orders them:
# G Treasury, F Bloomberg Aggregate, C S&P 500, S DJ Completion, I MSCI ACWI
# IMI ex USA ex China ex Hong Kong. Every one came in BELOW the figure
# carried here from recollection, by roughly a third for G.
EXPENSE_RATIOS_PCT = {
    "G": 0.034,
    "F": 0.035,
    "C": 0.035,
    "S": 0.051,
    "I": 0.048,
}

# What the page quotes when it needs one number for "the TSP". A hair above
# the C Fund and a hair below the S Fund; every real portfolio lands here.
TSP_TYPICAL_EXPENSE_PCT = 0.05

# The industry comparison. An advisor-managed IRA at 1% of assets a year is
# the standard offer a retiree receives, and it is charged on top of whatever
# the underlying funds cost.
TYPICAL_ADVISOR_FEE_PCT = 1.0

# Interfund transfer rules. Two unrestricted transfers a calendar month; after
# that the only transfer allowed is one that moves money INTO the G Fund.
IFT_UNRESTRICTED_PER_MONTH = 2
IFT_COST = 0.0

# How far off target is worth acting on. Trading is free here, so the band is
# about not fiddling rather than about cost.
REBALANCE_BAND_PTS = 5.0

# The phrase that marks the "your percentages do not total 100" problem, so
# findings() can report it once with a dollar figure instead of twice.
MIS_SUM_MARK = "not 100%"

# Chart categories. Fixed strings, so a colour scale can name its domain.
KIND_STOCKS = "Stocks"
KIND_FIXED = "Bonds and G"
KIND_LIFECYCLE = "Lifecycle fund"
KINDS = (KIND_STOCKS, KIND_FIXED, KIND_LIFECYCLE)


@dataclass(frozen=True)
class Fund:
    code: str
    name: str
    what: str
    is_equity: bool
    expense_ratio_pct: float
    note: str = ""


FUNDS: dict[str, Fund] = {
    "G": Fund(
        "G", "G Fund — Government Securities",
        "Short-term non-marketable US Treasury securities issued to the TSP "
        "alone.", False, EXPENSE_RATIOS_PCT["G"],
        "The genuinely unique holding in the whole plan, and the reason a "
        "member should think hard before leaving. It pays a rate set to the "
        "average yield of outstanding Treasury issues of four years or longer "
        "— intermediate-term interest — while the principal cannot fall. A "
        "bond fund pays intermediate yields and loses value when rates rise; "
        "a money market fund cannot lose value and pays short-term yields. "
        "The G Fund does both halves at once, and it is not for sale anywhere "
        "else at any price. It is the best cash-like bond substitute available "
        "to any American investor, and it is available only inside the TSP."),
    "F": Fund(
        "F", "F Fund — Fixed Income Index",
        "The broad US investment-grade bond market, tracking the Bloomberg US "
        "Aggregate.", False, EXPENSE_RATIOS_PCT["F"],
        "A real bond fund: it carries duration, so its price falls when rates "
        "rise, as 2022 demonstrated at a scale most holders had never seen. "
        "For a member who already has access to the G Fund, the F Fund's job "
        "is narrow — it adds credit and duration exposure the G Fund does not "
        "have, and it can lose money in the years you would most want it not "
        "to."),
    "C": Fund(
        "C", "C Fund — Common Stock Index",
        "The S&P 500: large US companies.", True, EXPENSE_RATIOS_PCT["C"],
        "About 80% of the US market by value. Held with the S Fund in market "
        "proportions (roughly 80/20) it reproduces the total US market."),
    "S": Fund(
        "S", "S Fund — Small Cap Stock Index",
        "The completion index — every US company outside the S&P 500, so "
        "small and mid caps.", True, EXPENSE_RATIOS_PCT["S"],
        "It is called the small cap fund and it is really the completion fund. "
        "Roughly 20% C-plus-S in the S Fund gives the whole US market; a "
        "member who wants only 'the market' does not need to choose between "
        "them."),
    "I": Fund(
        "I", "I Fund — International Stock Index",
        "Developed and emerging markets outside the US, less China and "
        "Hong Kong.", True,
        EXPENSE_RATIOS_PCT["I"],
        "Read this if you last looked at the I Fund before 2024. It tracked "
        "the MSCI EAFE index for its whole life — developed markets only, no "
        "emerging markets, no Canada. The benchmark was changed to a broader "
        "all-country index -- MSCI ACWI IMI ex USA ex China ex Hong Kong -- "
        "so an I Fund holding now includes emerging markets it did not "
        "include before, and deliberately excludes China and Hong Kong. If "
        "you sized this position on the old fund, you are holding something "
        "different from what you bought."),
}


def fund(code: str) -> Fund:
    return FUNDS[code.strip().upper()]


def is_equity(code: str) -> bool:
    return code.strip().upper() in EQUITY_CODES


# ==========================================================================
# The L funds and the glide path
# ==========================================================================
#
# Each L Fund is a fixed mix of the five funds that grows steadily more
# conservative as its target date approaches, rebalanced daily. What matters
# for everything on this page is the EQUITY SHARE -- C plus S plus I -- because
# that is the number that has to be added to any individual funds held
# alongside it.
#
# The far-dated funds sit at essentially all equity and stay there for
# decades; the glide only begins about twenty-five years out. See
# VERIFY["l_fund_equity"].

L_FUND_YEAR = 2025          # vintage of the glide-path figures below

L_INCOME = "L Income"

L_FUND_EQUITY_PCT = {
    L_INCOME: 30.0,
    "L 2030": 55.0,
    "L 2035": 62.0,
    "L 2040": 68.0,
    "L 2045": 74.0,
    "L 2050": 80.0,
    "L 2055": 99.0,
    "L 2060": 99.0,
    "L 2065": 99.0,
    "L 2070": 99.0,
    "L 2075": 99.0,
}

L_FUNDS = list(L_FUND_EQUITY_PCT)

# L 2025 reached its horizon and was folded into L Income; the lineup steps in
# fives from L 2030 upward, and a new fund is added at the top roughly every
# five years.
L_FUND_TARGET_YEARS = [int(n.split()[1]) for n in L_FUNDS if n != L_INCOME]


VERIFY = {
    "expense_ratios":
        f"VERIFY at tsp.gov: {EXPENSE_RATIO_YEAR} NET expense ratios, in "
        f"percent of assets — G {EXPENSE_RATIOS_PCT['G']:.3f}, "
        f"F {EXPENSE_RATIOS_PCT['F']:.3f}, C {EXPENSE_RATIOS_PCT['C']:.3f}, "
        f"S {EXPENSE_RATIOS_PCT['S']:.3f}, I {EXPENSE_RATIOS_PCT['I']:.3f}. "
        f"Confidence MEDIUM on the third decimal and HIGH on the magnitude: "
        f"every TSP fund has cost between about 0.04% and 0.06% for years, and "
        f"the net figure moves a basis point or two annually with forfeitures "
        f"and trading costs. Nothing on this page changes if these are each a "
        f"basis point out; the comparison that matters is against 1.00%, which "
        f"is twenty times larger.",
    "l_fund_equity":
        f"VERIFY at tsp.gov: approximate EQUITY share (C+S+I) of each L Fund, "
        f"{L_FUND_YEAR} vintage, rounded to whole points. Confidence MEDIUM. "
        f"The shape is not in doubt — the far-dated funds hold essentially all "
        f"equity, the glide begins roughly twenty-five years from the target "
        f"date, and L Income holds about 30% equity rather than the 20% it "
        f"held before the 2019 change — but any individual fund can be two or "
        f"three points off these figures, and each one drifts every quarter "
        f"by design. Check the current allocation before using a number here "
        f"to size a position.",
    "l_fund_lineup":
        f"VERIFY at tsp.gov: the lineup runs L Income and then five-year steps "
        f"L 2030 through L 2075. Confidence MEDIUM-HIGH through L 2070 and LOW "
        f"for L 2075, which is the fund that would be added at the top of the "
        f"lineup around 2029 and may not exist yet. L 2025 reached its horizon "
        f"and was rolled into L Income in mid-{L_FUND_YEAR}.",
    "ift_rules":
        "VERIFY at tsp.gov: interfund transfers cost nothing, and two per "
        "calendar month are unrestricted; after the second, the only transfer "
        "the system will accept is one moving money INTO the G Fund. "
        "Confidence HIGH. The practical consequence is asymmetric: you can "
        "always de-risk, and you cannot always re-risk.",
    "advisor_fee":
        f"{TYPICAL_ADVISOR_FEE_PCT:.2f}% of assets a year is the standard "
        f"advisory fee on a rolled-over IRA, and is a market convention rather "
        f"than a published figure. Confidence HIGH as a typical number, and it "
        f"is deliberately conservative in two ways: it ignores the underlying "
        f"funds' own expense ratios, which are usually several times the TSP's "
        f"on top of the advisory fee, and it ignores any commission or "
        f"surrender charge on an annuity or a loaded fund.",
}


def l_fund_equity_pct(name: str) -> float:
    """Equity share of a lifecycle fund, in percent. 0 for anything unknown."""
    return L_FUND_EQUITY_PCT.get((name or "").strip(), 0.0)


def is_l_fund(name: str) -> bool:
    return (name or "").strip() in L_FUND_EQUITY_PCT


def l_fund_for_year(year: int) -> str:
    """
    The L Fund whose target date is nearest the year the money is needed.

    Note what the argument is NOT: the year you leave the service. A major who
    retires at 42 and picks L 2045 has chosen a fund that will be two-thirds
    bonds while they still have forty years of spending ahead of them. The TSP's
    own instruction is to choose by when you will START WITHDRAWING, and for a
    member with a pension covering the early years that date is often decades
    after the uniform comes off.
    """
    if year <= L_FUND_TARGET_YEARS[0] - 3:
        return L_INCOME
    nearest = min(L_FUND_TARGET_YEARS, key=lambda y: (abs(y - year), y))
    return f"L {nearest}"


@dataclass
class LFundPick:
    fund: str = L_INCOME
    withdrawal_year: int = 0
    withdrawal_age: int = 0
    equity_pct: float = 0.0
    note: str = ""


def suggested_l_fund(h, withdrawal_age: int = 62,
                     current_year: int = 2026) -> LFundPick:
    """The L Fund matching the year this member starts drawing on the TSP."""
    m = h.member
    year = int(m.birth_year) + int(withdrawal_age)
    name = l_fund_for_year(year)
    return LFundPick(
        fund=name, withdrawal_year=year, withdrawal_age=int(withdrawal_age),
        equity_pct=l_fund_equity_pct(name),
        note=(f"Chosen for the year you would start withdrawing ({year}, when "
              f"you are {withdrawal_age}), not the year you leave the service. "
              f"That is the TSP's own instruction and it matters most to "
              f"military members, who separate decades before they spend this "
              f"money."))


# ==========================================================================
# What you actually hold
# ==========================================================================

@dataclass
class EquityShare:
    """The equity share of a TSP account, L Fund included."""
    equity_pct: float = 0.0          # points of the whole account
    fixed_pct: float = 0.0
    direct_equity_pct: float = 0.0   # from C, S, I held individually
    lifecycle_equity_pct: float = 0.0  # the equity inside the L Fund
    allocation_total_pct: float = 0.0
    l_fund: str = ""
    l_fund_pct: float = 0.0
    l_fund_equity_pct: float = 0.0
    problems: list = field(default_factory=list)

    @property
    def sums_to_100(self) -> bool:
        return abs(self.allocation_total_pct - 100.0) < 0.05

    @property
    def is_empty(self) -> bool:
        return self.allocation_total_pct <= 0.0

    @property
    def unassigned_pct(self) -> float:
        return 100.0 - self.allocation_total_pct

    @property
    def equity_share_of_allocated_pct(self) -> float:
        """Equity as a share of what has actually been allocated."""
        if self.allocation_total_pct <= 0:
            return 0.0
        return self.equity_pct / self.allocation_total_pct * 100.0


def weights(inv) -> dict:
    """Every line of the allocation, in points of the account."""
    out = {c: max(0.0, float(getattr(inv, f"tsp_{c.lower()}_pct", 0.0) or 0.0))
           for c in FUND_CODES}
    name = (getattr(inv, "tsp_lifecycle_fund", "") or "").strip()
    out["L"] = (max(0.0, float(getattr(inv, "tsp_lifecycle_pct", 0.0) or 0.0))
                if is_l_fund(name) else 0.0)
    return out


def equity_share(inv) -> EquityShare:
    """
    Equity share of the TSP, counting the equity held inside any L Fund.

    A member holding 50% L 2050 and 50% C Fund does not hold 50% equity. They
    hold 50% plus 80% of the other half -- 90% -- and that is exactly the
    arithmetic people do not do. Holding an L Fund alongside individual funds
    is the most common way a TSP allocation ends up somewhere nobody chose.
    """
    w = weights(inv)
    name = (getattr(inv, "tsp_lifecycle_fund", "") or "").strip()
    l_pct = w["L"]
    l_eq = l_fund_equity_pct(name)

    direct_equity = sum(w[c] for c in EQUITY_CODES)
    direct_fixed = sum(w[c] for c in FIXED_CODES)
    life_equity = l_pct * l_eq / 100.0
    life_fixed = l_pct - life_equity

    r = EquityShare(
        equity_pct=direct_equity + life_equity,
        fixed_pct=direct_fixed + life_fixed,
        direct_equity_pct=direct_equity,
        lifecycle_equity_pct=life_equity,
        allocation_total_pct=direct_equity + direct_fixed + l_pct,
        l_fund=name if is_l_fund(name) else "",
        l_fund_pct=l_pct,
        l_fund_equity_pct=l_eq,
    )

    raw_name = (getattr(inv, "tsp_lifecycle_fund", "") or "").strip()
    if raw_name and not is_l_fund(raw_name):
        r.problems.append(
            f"'{raw_name}' is not one of the TSP's lifecycle funds. The lineup "
            f"is {L_INCOME} and then five-year steps "
            f"{L_FUND_TARGET_YEARS[0]} to {L_FUND_TARGET_YEARS[-1]}.")

    if r.is_empty:
        r.problems.append(
            "No allocation entered yet, so nothing below knows what you own. "
            "Your allocation is on the TSP website under Account Activity; it "
            "takes a minute to copy across.")
    elif not r.sums_to_100:
        over = r.allocation_total_pct > 100.0
        r.problems.append(
            f"Your allocation adds to {r.allocation_total_pct:.0f}%, "
            f"{MIS_SUM_MARK}. "
            + (f"That is {r.allocation_total_pct - 100.0:.0f} points more than "
               f"you have — the TSP would reject this election."
               if over else
               f"{r.unassigned_pct:.0f}% is unaccounted for. If that is really "
               f"sitting in the G Fund, say so; every number below is computed "
               f"on what you entered."))

    if r.l_fund_pct > 0 and (direct_equity + direct_fixed) > 0:
        r.problems.append(
            f"You hold {r.l_fund} alongside individual funds. An L Fund is a "
            f"complete portfolio that rebalances itself down a glide path; "
            f"funds held next to it push your real equity share away from the "
            f"one the L Fund is steering to — here, to {r.equity_pct:.0f}%. "
            f"Pick one approach or the other.")

    return r


def allocation_rows(inv) -> list[dict]:
    """One row per holding, for a chart or a table. Zero lines are dropped."""
    w = weights(inv)
    es = equity_share(inv)
    rows = []
    for c in FUND_CODES:
        if w[c] <= 0:
            continue
        f = FUNDS[c]
        rows.append({"Fund": f"{c} Fund", "Percent": w[c],
                     "Kind": KIND_STOCKS if f.is_equity else KIND_FIXED,
                     "What": f.what,
                     "Expense ratio": f.expense_ratio_pct})
    if w["L"] > 0:
        rows.append({"Fund": es.l_fund, "Percent": w["L"], "Kind": KIND_LIFECYCLE,
                     "What": f"A whole portfolio in one fund, currently "
                             f"{es.l_fund_equity_pct:.0f}% stocks",
                     "Expense ratio": _l_fund_expense_pct(es.l_fund_equity_pct)})
    return rows


def _l_fund_expense_pct(equity_pct: float) -> float:
    """An L Fund charges the weighted cost of what it holds, and no more."""
    eq = max(0.0, min(100.0, equity_pct)) / 100.0
    stock = (EXPENSE_RATIOS_PCT["C"] * 0.65 + EXPENSE_RATIOS_PCT["S"] * 0.10
             + EXPENSE_RATIOS_PCT["I"] * 0.25)
    bond = EXPENSE_RATIOS_PCT["G"] * 0.85 + EXPENSE_RATIOS_PCT["F"] * 0.15
    return stock * eq + bond * (1 - eq)


# ==========================================================================
# Drift from target, and what to do about it
# ==========================================================================

@dataclass
class Drift:
    equity_pct: float = 0.0
    target_pct: float = 0.0
    drift_pts: float = 0.0        # positive = more equity than you intended
    band_pts: float = REBALANCE_BAND_PTS
    direction: str = "hold"       # "add" | "reduce" | "hold"
    moves: list = field(default_factory=list)   # (from, to, points)
    l_fund_switch: str = ""       # the L Fund nearest the target, if in one
    dollars: float = 0.0          # value of the drift, if a balance was given
    headline: str = ""
    note: str = ""

    @property
    def in_band(self) -> bool:
        return self.direction == "hold"


def closest_l_fund(target_equity_pct: float) -> str:
    """The lifecycle fund whose equity share sits nearest a target."""
    return min(L_FUNDS,
               key=lambda n: abs(L_FUND_EQUITY_PCT[n] - target_equity_pct))


def versus_target(inv, tsp_balance: float = 0.0,
                  band_pts: float = REBALANCE_BAND_PTS) -> Drift:
    """
    Drift from the target equity share, and the interfund transfer that fixes it.

    Rebalancing inside the TSP is free — no commission, no spread, no tax event,
    because it all happens inside a retirement account. The only limit is
    procedural: two unrestricted interfund transfers a calendar month, after
    which the system accepts only transfers INTO the G Fund. So de-risking is
    always possible and adding equity is not, which is worth knowing before the
    month you decide to act.
    """
    es = equity_share(inv)
    target = float(getattr(inv, "target_equity_pct", 0.0) or 0.0)
    d = Drift(equity_pct=es.equity_pct, target_pct=target, band_pts=band_pts)
    d.drift_pts = es.equity_pct - target
    d.dollars = abs(d.drift_pts) / 100.0 * max(0.0, float(tsp_balance or 0.0))

    if es.is_empty:
        d.headline = "No allocation entered, so there is nothing to compare."
        d.note = ("Enter what you hold on the left and this becomes the "
                  "difference between where you are and where you meant to be.")
        return d

    if abs(d.drift_pts) <= band_pts:
        d.direction = "hold"
        d.headline = (f"You are at {es.equity_pct:.0f}% stocks against a "
                      f"{target:.0f}% target — inside the {band_pts:.0f}-point "
                      f"band.")
        d.note = ("Nothing to do. Rebalancing costs nothing here, which is a "
                  "reason to do it when it is needed and not a reason to do it "
                  "constantly.")
        return d

    w = weights(inv)
    pts = abs(d.drift_pts)
    if d.drift_pts > 0:
        d.direction = "reduce"
        d.moves = _moves(w, EQUITY_CODES, ["G"], pts)
        d.headline = (f"You hold {es.equity_pct:.0f}% stocks against a "
                      f"{target:.0f}% target — {pts:.0f} points more risk "
                      f"than you chose.")
        d.note = ("Moving money into the G Fund is the one interfund transfer "
                  "the TSP always allows, however many you have already made "
                  "this month.")
    else:
        d.direction = "add"
        d.moves = _moves(w, FIXED_CODES, ["C", "S"], pts)
        d.headline = (f"You hold {es.equity_pct:.0f}% stocks against a "
                      f"{target:.0f}% target — {pts:.0f} points less risk "
                      f"than you chose.")
        d.note = (f"Adding equity needs one of your "
                  f"{IFT_UNRESTRICTED_PER_MONTH} unrestricted interfund "
                  f"transfers for the month. After those, transfers may only "
                  f"move money into the G Fund.")

    if es.l_fund_pct > 0:
        # The equity may be sitting inside the L Fund, where the individual
        # funds cannot supply the move. A point moved out of an L Fund only
        # changes the equity share by that fund's own equity share, so the
        # transfer has to be grossed up.
        if not d.moves and es.l_fund_equity_pct > 0:
            gross = pts * 100.0 / es.l_fund_equity_pct
            if d.direction == "reduce":
                d.moves = [(es.l_fund, "G", round(min(gross, es.l_fund_pct), 1))]
            else:
                room = sum(w[c] for c in FIXED_CODES)
                if room > 0:
                    d.moves = [("G", es.l_fund, round(min(gross, room), 1))]
        switch = closest_l_fund(target)
        d.l_fund_switch = "" if switch == es.l_fund else switch
        if d.l_fund_switch:
            d.note += (f" You are in {es.l_fund}, at "
                       f"{es.l_fund_equity_pct:.0f}% stocks. The cleaner fix "
                       f"is to move to {d.l_fund_switch}, which sits at "
                       f"{l_fund_equity_pct(d.l_fund_switch):.0f}%, rather "
                       f"than bolting individual funds onto a fund that "
                       f"rebalances itself.")
        else:
            d.note += (" You are already in the L Fund closest to your "
                       "target, so the target and the fund disagree — decide "
                       "which of the two you actually believe.")
    return d


def _moves(w: dict, sources, dests, pts: float) -> list:
    """
    Split `pts` out of the source funds and into the destinations.

    Sources are drawn in proportion to what is there, so the member sells what
    they have most of. Destinations follow the same rule, falling back to the
    first named fund when the destination side is empty.
    """
    avail = {c: w.get(c, 0.0) for c in sources if w.get(c, 0.0) > 0}
    total = sum(avail.values())
    if total <= 0:
        return []
    pts = min(pts, total)

    have = {c: w.get(c, 0.0) for c in dests if w.get(c, 0.0) > 0}
    dest_total = sum(have.values())
    if dest_total > 0:
        dest_mix = {c: v / dest_total for c, v in have.items()}
    else:
        dest_mix = {dests[0]: 1.0}

    out = []
    for src, held in sorted(avail.items(), key=lambda kv: -kv[1]):
        take = pts * held / total
        for dst, share in sorted(dest_mix.items(), key=lambda kv: -kv[1]):
            amount = take * share
            if amount >= 0.5:
                out.append([src, dst, round(amount, 1)])
    if not out:
        return []
    # Rounding each leg independently leaves a total that does not equal the
    # drift it is meant to close, which reads as an arithmetic error. The
    # remainder goes on the largest leg.
    out[0][2] = round(out[0][2] + pts - sum(row[2] for row in out), 1)
    return [tuple(row) for row in out]


def describe_moves(moves) -> str:
    """One phrase for a list of transfers, used by the page and the findings."""
    return "; ".join(
        f"{pts:g} {'point' if abs(pts - 1.0) < 1e-9 else 'points'} "
        f"from {src} to {dst}" for src, dst, pts in moves)


# ==========================================================================
# THE MILITARY INSIGHT: you already own a very large bond
# ==========================================================================

@dataclass
class PensionAsBond:
    guaranteed_monthly: float = 0.0
    guaranteed_annual: float = 0.0
    replacement_cost: float = 0.0     # NOT a cash value. See BS.VALUATION_CAVEAT
    portfolio: float = 0.0            # investable assets
    combined: float = 0.0
    bond_like_pct: float = 0.0        # replacement cost / combined
    years_valued: float = 0.0
    life_expectancy: int = 0
    real_discount_rate: float = BS.DEFAULT_REAL_DISCOUNT
    streams: list = field(default_factory=list)

    @property
    def applies(self) -> bool:
        return self.replacement_cost > 0 and self.portfolio > 0

    def household_equity_pct(self, portfolio_equity_pct: float) -> float:
        """
        What a given TSP allocation means for the whole balance sheet.

        100% stocks in the portfolio is not a 100% stock household when the
        pension is two-thirds of everything you own.
        """
        if self.combined <= 0:
            return portfolio_equity_pct
        return portfolio_equity_pct * self.portfolio / self.combined

    def portfolio_equity_for(self, household_target_pct: float) -> float:
        """
        The portfolio equity share that produces a given household-level share.

        Frequently above 100, which is the finding rather than an error: it
        means no achievable allocation of this portfolio reaches that
        household-level risk, because the pension is holding the other side
        of the see-saw down.
        """
        if self.portfolio <= 0:
            return 0.0
        return household_target_pct * self.combined / self.portfolio


def pension_as_bond(h, life_expectancy: int | None = None,
                    real_discount_rate: float | None = None,
                    current_year: int = 2026) -> PensionAsBond:
    """
    Value the guaranteed income and express it as a share of everything.

    The replacement cost comes from engine/networth/balance_sheet.py, so this
    page and the balance sheet page cannot drift apart. Read
    BS.VALUATION_CAVEAT before quoting the number: it is what an equivalent
    inflation-indexed lifetime income would COST TO REPLACE, not a balance, not
    something that can be sold, and not something that can be left to an heir.
    """
    from engine import mortality as MORT

    m = h.member
    if real_discount_rate is None:
        real_discount_rate = float(
            getattr(h.assumptions, "real_discount_rate_pct",
                    BS.DEFAULT_REAL_DISCOUNT * 100)) / 100.0
    if life_expectancy is None:
        life_expectancy = MORT.life_expectancy(m.age(current_year), m.sex)

    bs = BS.from_household(h, life_expectancy=int(life_expectancy),
                           real_discount_rate=real_discount_rate,
                           current_year=current_year)

    monthly = (m.retired_pay_monthly + m.va_disability_monthly + m.crsc_monthly)
    r = PensionAsBond(
        guaranteed_monthly=monthly,
        guaranteed_annual=monthly * 12.0,
        replacement_cost=bs.streams_present_value,
        portfolio=bs.investable_assets,
        years_valued=max(0.0, life_expectancy - m.age(current_year)),
        life_expectancy=int(life_expectancy),
        real_discount_rate=real_discount_rate,
        streams=list(bs.streams),
    )
    r.combined = r.replacement_cost + r.portfolio
    r.bond_like_pct = (r.replacement_cost / r.combined * 100.0
                       if r.combined > 0 else 0.0)
    return r


# ==========================================================================
# Sequence-of-returns risk, and the pension as a floor
# ==========================================================================

@dataclass
class Coverage:
    guaranteed_monthly: float = 0.0
    monthly_expenses: float = 0.0
    ratio: float = 0.0            # guaranteed income / spending
    covered_pct: float = 0.0
    surplus_monthly: float = 0.0  # positive when income exceeds spending
    gap_monthly: float = 0.0      # positive when spending exceeds income
    gap_annual: float = 0.0
    portfolio: float = 0.0
    years_of_gap_covered: float = 0.0
    headline: str = ""
    detail: str = ""

    @property
    def fully_covered(self) -> bool:
        return self.ratio >= 1.0


def expenses_covered(h, portfolio: float | None = None) -> Coverage:
    """
    The share of spending that arrives whether markets cooperate or not.

    A ratio above 1.0 is the single most consequential fact on this page. It
    means the portfolio is not funding the grocery bill, so a 40% drawdown
    forces no sales at all, so the sequence-of-returns risk that every
    de-risking rule exists to manage is simply absent. The portfolio's job
    stops being 'survive the next five years' and becomes 'outgrow inflation
    over the next forty', and those two jobs want opposite allocations.
    """
    m = h.member
    monthly = m.retired_pay_monthly + m.va_disability_monthly + m.crsc_monthly
    spend = max(0.0, float(h.monthly_expenses or 0.0))

    if portfolio is None:
        portfolio = (h.cash_savings + h.taxable_brokerage
                     + sum(p.tsp_traditional_balance + p.tsp_roth_balance
                           + p.ira_traditional_balance + p.ira_roth_balance
                           + p.sdp_balance for p in h.people()))

    c = Coverage(guaranteed_monthly=monthly, monthly_expenses=spend,
                 portfolio=portfolio)
    if spend <= 0:
        c.headline = "Enter what you spend in a month and this fills in."
        c.detail = ("Your spending is on the **What I am worth** page. Without "
                    "it, nothing here can say what your pension covers.")
        return c

    c.ratio = monthly / spend
    c.covered_pct = min(999.0, c.ratio * 100.0)
    c.surplus_monthly = max(0.0, monthly - spend)
    c.gap_monthly = max(0.0, spend - monthly)
    c.gap_annual = c.gap_monthly * 12.0
    c.years_of_gap_covered = (portfolio / c.gap_annual
                              if c.gap_annual > 0 else float("inf"))

    if c.ratio >= 1.0:
        c.headline = (f"Your guaranteed income covers "
                      f"{c.covered_pct:.0f}% of what you spend.")
        c.detail = (
            "You do not have to sell anything in a bad year. That is the whole "
            "of sequence-of-returns risk, and it does not apply to you at "
            "current spending — a portfolio that is never drawn on cannot be "
            "forced to sell at the bottom. The rule that says to de-risk as you "
            "age exists to manage a risk your pension has already retired. "
            "Two caveats worth holding: this is today's spending, and a "
            "long-term care event or a change in household can move it a long "
            "way; and if you elected SBP, the survivor receives 55% of the base "
            "amount, so the floor your spouse would face is lower than the one "
            "you face.")
    else:
        c.headline = (f"Your guaranteed income covers "
                      f"{c.covered_pct:.0f}% of what you spend.")
        c.detail = (
            f"The remaining ${c.gap_monthly:,.0f} a month — ${c.gap_annual:,.0f} "
            f"a year — has to come from the portfolio, and that portion does "
            f"carry sequence risk. The usual answer is not to de-risk the whole "
            f"portfolio: it is to hold a few years of THAT GAP, not of total "
            f"spending, somewhere it cannot fall. The G Fund is built for "
            f"exactly this. At today's balances the portfolio covers the gap "
            f"for about {c.years_of_gap_covered:.0f} years before any growth.")
    return c


# ==========================================================================
# Asset location: which account holds which fund
# ==========================================================================

# What the bond side is assumed to earn above inflation. An assumption, not a
# published figure: the G Fund has paid roughly intermediate Treasury yields,
# which have run a point or so above inflation over long periods.
BOND_REAL_RETURN_PCT = 1.5


@dataclass
class Placement:
    roth: float = 0.0
    traditional: float = 0.0
    taxable: float = 0.0
    equity_pct: float = 0.0
    bond_dollars: float = 0.0
    swappable: float = 0.0
    years: int = 20
    equity_real_pct: float = 0.0
    bond_real_pct: float = BOND_REAL_RETURN_PCT
    tax_rate: float = 0.22
    gain: float = 0.0
    lines: list = field(default_factory=list)

    @property
    def applies(self) -> bool:
        return self.swappable > 0 and self.gain > 0


def asset_location(h, years: int = 20,
                   bond_real_pct: float = BOND_REAL_RETURN_PCT,
                   tax_rate: float | None = None) -> Placement:
    """
    Which account should hold which fund, worked on this member's balances.

    The rule: the assets you expect to grow most belong where growth is never
    taxed. C and S in Roth; G and F in traditional. It changes nothing about
    your overall allocation — the same 70/30 across the household — and it
    changes which dollars the government has a claim on.

    Why it is worth more to a military retiree than to most people: a career
    of BRS matching lands entirely in the traditional balance whatever the
    member elected, so the traditional side tends to be the big one, and the
    pension is already a taxable income floor that those withdrawals stack on
    top of rather than filling empty low brackets underneath.

    The arithmetic below is the honest version. Swapping S dollars of equity
    from traditional into Roth (and the same dollars of bonds the other way)
    leaves the allocation untouched and changes the after-tax outcome by
        tax rate x S x [(1+equity)^n - (1+bond)^n]
    which is the tax the government would have collected on the DIFFERENCE in
    growth between the two assets.
    """
    inv = h.investments
    equity_pct = equity_share(inv).equity_pct

    roth = sum(p.tsp_roth_balance + p.ira_roth_balance for p in h.people())
    trad = sum(p.tsp_traditional_balance + p.ira_traditional_balance
               for p in h.people())
    equity_real = float(getattr(h.assumptions, "real_return_pct", 4.0))
    if tax_rate is None:
        tax_rate = BS.BalanceSheet().embedded_tax_rate

    p = Placement(roth=roth, traditional=trad, taxable=h.taxable_brokerage,
                  equity_pct=equity_pct, years=years,
                  equity_real_pct=equity_real, bond_real_pct=bond_real_pct,
                  tax_rate=tax_rate)

    p.bond_dollars = (1.0 - min(100.0, max(0.0, equity_pct)) / 100.0) * (roth + trad)
    p.swappable = max(0.0, min(roth, trad, p.bond_dollars))

    e = (1 + equity_real / 100.0) ** years
    b = (1 + bond_real_pct / 100.0) ** years
    p.gain = tax_rate * p.swappable * (e - b)

    if roth <= 0 and trad <= 0:
        p.lines.append(
            "Enter your TSP and IRA balances on the **What I am worth** page "
            "and this becomes a dollar figure on your own money.")
        return p

    p.lines.append(
        f"You hold ${roth:,.0f} in Roth (TSP and IRA) and ${trad:,.0f} in "
        f"traditional. Your bond and G Fund holdings come to about "
        f"${p.bond_dollars:,.0f} across both.")

    if p.swappable <= 0:
        p.lines.append(
            "There is nothing to relocate yet — you have bonds in only one "
            "type of account, so there is no swap to make. The rule still "
            "applies to every future contribution: growth assets into Roth, "
            "bonds and G into traditional.")
        return p

    p.lines.append(
        f"Hold ${p.swappable:,.0f} of C and S in the ROTH accounts and the "
        f"same ${p.swappable:,.0f} of G and F in the TRADITIONAL accounts, "
        f"rather than the other way round. Your overall mix is unchanged: "
        f"still {equity_pct:.0f}% stocks across the household.")
    p.lines.append(
        f"Over {years} years at {equity_real:.1f}% real for stocks and "
        f"{bond_real_pct:.1f}% real for bonds, that placement is worth about "
        f"${p.gain:,.0f} after tax, at an assumed {tax_rate * 100:.0f}% rate on "
        f"the traditional balance. The allocation did not change; only the "
        f"share of the growth the government has a claim on did.")
    p.lines.append(
        "Two military-specific notes. Every dollar of BRS matching lands in "
        "the TRADITIONAL balance however you designate your own contributions, "
        "so the traditional side grows whether you choose it or not — that is "
        "the side to fill with G and F. And tax-exempt combat-zone "
        "contributions sit in the traditional balance as principal that is "
        "never taxed again, though their earnings are: those dollars behave "
        "more like Roth than like the rest of the traditional balance.")
    return p


# ==========================================================================
# Fees: the TSP against the rollover pitch every retiree gets
# ==========================================================================

@dataclass
class FeeComparison:
    balance: float = 0.0
    years: int = 20
    real_return_pct: float = 4.0
    tsp_expense_pct: float = TSP_TYPICAL_EXPENSE_PCT
    advisor_pct: float = TYPICAL_ADVISOR_FEE_PCT
    tsp_value: float = 0.0
    advisor_value: float = 0.0
    cost: float = 0.0
    first_year_fee: float = 0.0
    cost_as_pct_of_balance: float = 0.0

    @property
    def multiple_of_tsp_cost(self) -> float:
        return (self.advisor_pct / self.tsp_expense_pct
                if self.tsp_expense_pct > 0 else 0.0)


def fee_drag(balance: float, years: int = 20, real_return_pct: float = 4.0,
             advisor_pct: float = TYPICAL_ADVISOR_FEE_PCT,
             tsp_expense_pct: float = TSP_TYPICAL_EXPENSE_PCT) -> FeeComparison:
    """
    What the rollover pitch costs, in dollars, on this member's balance.

    Every retiring service member is offered this: move the TSP into an IRA a
    firm manages for 1% of assets a year. The pitch is about service, choice
    and 'more investment options'. The cost is never quoted as a dollar figure
    over the holding period, because that figure is startling.

    A percent-of-assets fee is charged on the whole balance every year, so it
    compounds against you exactly as returns compound for you. Both sides are
    modelled as (1 + real return) x (1 - fee) each year, in today's dollars.

    This comparison is deliberately conservative: it assumes the managed
    account holds funds as cheap as the TSP's, which is rarely true, and it
    ignores commissions, loads and surrender charges entirely. The real gap is
    wider than the number this returns.
    """
    f = FeeComparison(balance=max(0.0, float(balance or 0.0)), years=int(years),
                      real_return_pct=real_return_pct,
                      tsp_expense_pct=tsp_expense_pct, advisor_pct=advisor_pct)
    g = 1.0 + real_return_pct / 100.0
    f.tsp_value = f.balance * (g * (1 - tsp_expense_pct / 100.0)) ** years
    f.advisor_value = f.balance * (
        g * (1 - (tsp_expense_pct + advisor_pct) / 100.0)) ** years
    f.cost = f.tsp_value - f.advisor_value
    f.first_year_fee = f.balance * advisor_pct / 100.0
    f.cost_as_pct_of_balance = (f.cost / f.balance * 100.0
                                if f.balance > 0 else 0.0)
    return f


def rollover_pitch(h, years: int = 20,
                   advisor_pct: float = TYPICAL_ADVISOR_FEE_PCT) -> FeeComparison:
    """fee_drag on this household's actual TSP and IRA balances."""
    balance = sum(p.tsp_traditional_balance + p.tsp_roth_balance
                  + p.ira_traditional_balance + p.ira_roth_balance
                  for p in h.people())
    return fee_drag(balance, years=years,
                    real_return_pct=float(getattr(h.assumptions,
                                                  "real_return_pct", 4.0)),
                    advisor_pct=advisor_pct)


def tsp_balance(h) -> float:
    return sum(p.tsp_traditional_balance + p.tsp_roth_balance
               for p in h.people())


# ==========================================================================
# Findings, ordered by dollars at stake
# ==========================================================================

def _money(x: float) -> str:
    sign = "-" if x < 0 else ""
    return f"{sign}${abs(x):,.0f}"


def findings(h, years: int = 20) -> list[tuple[str, str, str]]:
    """
    (severity, headline, detail), largest dollar figure first.

    Ordering by dollars at stake is not a stylistic choice. It is what puts the
    pension-as-a-bond finding at the top for a retiree — the replacement cost
    of the guaranteed income is the biggest number on the page by a distance,
    and it is the one that should change the allocation decision. A page that
    led with a five-point rebalance would be burying it.
    """
    inv = h.investments
    es = equity_share(inv)
    bal = tsp_balance(h)
    out: list[tuple[float, str, str, str]] = []

    # -- the military insight ------------------------------------------------
    pb = pension_as_bond(h)
    if pb.applies:
        implied = pb.household_equity_pct(100.0)
        out.append((
            pb.replacement_cost, "info",
            f"You are already about {pb.bond_like_pct:.0f}% in bonds, before "
            f"the TSP holds a single one.",
            f"Replacing your guaranteed income — {_money(pb.guaranteed_annual)} "
            f"a year of retired pay and VA compensation, indexed to inflation "
            f"and backed by the federal government — would cost roughly "
            f"{_money(pb.replacement_cost)}. Against {_money(pb.portfolio)} of "
            f"investable assets that is {pb.bond_like_pct:.0f}% of the two "
            f"combined, and it behaves like an inflation-protected bond: it "
            f"pays monthly, it does not fall when markets do, and it never "
            f"runs out. This is a replacement-cost estimate, not a cash value "
            f"— you cannot sell it, borrow against it or leave it to an heir. "
            f"What it is good for is exactly this question. Put your entire "
            f"TSP in C, S and I and your HOUSEHOLD is still only "
            f"{implied:.0f}% equity. A 60/40 inside the portfolio would make "
            f"the household about "
            f"{pb.household_equity_pct(60.0):.0f}% equity — far more "
            f"conservative than anyone intends. This is why your investable "
            f"assets can carry more equity than a civilian's at the same age, "
            f"not less."))

    # -- the floor under the portfolio ---------------------------------------
    cov = expenses_covered(h, portfolio=pb.portfolio if pb.applies else None)
    if cov.guaranteed_monthly > 0 and cov.monthly_expenses > 0:
        out.append((
            cov.guaranteed_monthly * 12.0,
            "good" if cov.fully_covered else "info",
            cov.headline, cov.detail))

    # -- the rollover pitch ---------------------------------------------------
    fee = rollover_pitch(h, years=years)
    if fee.balance > 0 and fee.cost > 0:
        out.append((
            fee.cost, "warn",
            f"Rolling this into a 1%-of-assets IRA would cost about "
            f"{_money(fee.cost)} over {years} years.",
            f"On {_money(fee.balance)} at "
            f"{fee.real_return_pct:.1f}% real, the TSP's roughly "
            f"{fee.tsp_expense_pct:.2f}% leaves {_money(fee.tsp_value)} after "
            f"{years} years; the same money at "
            f"{fee.tsp_expense_pct + fee.advisor_pct:.2f}% leaves "
            f"{_money(fee.advisor_value)}. The difference — "
            f"{_money(fee.cost)}, or {fee.cost_as_pct_of_balance:.0f}% of what "
            f"you have today — is the price of the offer every retiring member "
            f"receives, usually within weeks of the retirement ceremony. The "
            f"first year alone costs {_money(fee.first_year_fee)}. That figure "
            f"is conservative: it assumes the managed account holds funds as "
            f"cheap as the TSP's, and ignores loads, commissions and surrender "
            f"charges. It is not an argument that advice is worthless — it is "
            f"an argument that advice priced as a permanent percentage of the "
            f"whole balance, for as long as you hold it, is a different "
            f"product from advice priced by the hour — and that the G Fund "
            f"does not exist outside the TSP at all."))

    # -- asset location -------------------------------------------------------
    loc = asset_location(h, years=years)
    if loc.applies:
        out.append((
            loc.gain, "info",
            f"Holding the growth in Roth and the bonds in traditional is worth "
            f"about {_money(loc.gain)}.",
            " ".join(loc.lines)))

    # -- the allocation itself ------------------------------------------------
    if not es.is_empty and not es.sums_to_100:
        stake = abs(es.allocation_total_pct - 100.0) / 100.0 * bal
        out.append((
            stake, "bad",
            f"Your fund percentages add to {es.allocation_total_pct:.0f}%, not "
            f"100%.",
            f"The TSP will not accept an election that does not total 100%, and "
            f"every figure on this page is computed on what you entered. "
            f"{_money(stake)} of your {_money(bal)} TSP is either unaccounted "
            f"for or double-counted."))

    d = versus_target(inv, tsp_balance=bal)
    if not d.in_band and not es.is_empty:
        out.append((
            d.dollars, "warn", d.headline,
            (f"Suggested interfund transfer: {describe_moves(d.moves)}. "
             if d.moves else "")
            + f"That is {_money(d.dollars)} of your TSP on the wrong side of "
              f"your own target. Interfund transfers are free — no commission, "
              f"no spread, and no tax event, because it happens inside a "
              f"retirement account. " + d.note))

    for problem in es.problems:
        if MIS_SUM_MARK in problem:
            continue      # already reported above, with its dollar figure
        out.append((0.0, "info" if es.is_empty else "warn",
                    problem.split(".")[0] + ".", problem))

    if es.equity_pct <= 0 and not es.is_empty and bal > 0:
        out.append((
            bal, "warn", "Your entire TSP is in fixed income.",
            f"The G Fund cannot lose principal, which is exactly why it cannot "
            f"outgrow inflation by much either. Over a retirement that has to "
            f"last thirty or forty years, {_money(bal)} held entirely in G and "
            f"F is a decision to accept a slow real loss in exchange for never "
            f"seeing a down year. If your pension already covers your "
            f"spending, that is a trade you are making without needing to."))

    out.sort(key=lambda row: -row[0])
    return [(sev, head, detail) for _, sev, head, detail in out]
