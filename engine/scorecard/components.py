"""
The eight components, one builder each.

docs/ARCHITECTURE.md §3 names them and says what each measures. Everything in
this module obeys four rules, and the rules are the design:

  1. AGGREGATE, DO NOT RE-DERIVE. Sixteen engine modules already emit
     (severity, headline, detail) findings and several already compute the
     exact quantity a component wants. A component reads those. Where an
     engine has already made a judgement, `bands.band_from_findings()` reads
     the band off its severities rather than inventing a second rule that
     disagrees with the first.

  2. EVERY RATING STATES ITS EVIDENCE (§8). A number with no visible
     derivation is worse than no number, so a component returns `evidence` --
     the two or three figures the band was read from -- and the page shows
     them next to the band. A rated component with no evidence is a bug, and
     tests/test_scorecard.py treats it as one.

  3. NEVER INVENT. Three statuses exist for the three ways a rating can fail
     to be established, and all three are C-5 (§3: "C-5 is also the honest
     home for 'you have not entered this yet' and 'this does not apply'"):

        NOT_ENTERED    the user has not answered. Counts in the roll-up --
                       unknown readiness is not readiness, and a blank plan
                       must not roll up to C-1 on nothing.
        NOT_MODELLED   the APP cannot compute it yet. Excluded from the
                       roll-up, because the tool's gap is not the user's
                       failing. This is the serving member's case (§4b).
        NOT_APPLICABLE it does not apply to this household. Excluded.

  4. EACH ONE POINTS AT THE PAGE THAT FIXES IT (§6). Nothing is deleted; a
     page becomes the drill-down for the component it moves.

Thresholds are declared inline, next to the thing they band, and never hidden
in a helper. A threshold nobody can find is a threshold nobody audits.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from engine.profile import Household
from engine.funnel import essential_monthly, has_essential_split
from engine.scorecard import bands as B
from engine.scorecard.bands import C1, C2, C5

# --------------------------------------------------------------------------
# Statuses
# --------------------------------------------------------------------------

RATED = "rated"
NOT_ENTERED = "not_entered"
NOT_MODELLED = "not_modelled"
NOT_RUN = "not_run"
NOT_APPLICABLE = "not_applicable"

#: Statuses that take part in the weighted roll-up. RATED because it is a
#: rating; NOT_ENTERED because the user can fix it and a plan is not ready on
#: figures nobody has supplied. The other three are excluded -- see rule 3.
COUNTED = (RATED, NOT_ENTERED)

STATUS_LABEL = {
    RATED: "Rated",
    NOT_ENTERED: "Not entered yet",
    NOT_MODELLED: "Cannot be computed yet",
    NOT_RUN: "Not run yet",
    NOT_APPLICABLE: "Does not apply to you",
}


# --------------------------------------------------------------------------
# The shapes
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Evidence:
    """
    One figure the rating was read from.

    `value` is pre-formatted TEXT, dollar signs and all, because the component
    knows how the figure should read and the page does not. The page escapes it
    -- `ui.panel.esc()` -- before handing it to markdown.
    """
    label: str
    value: str
    note: str = ""


@dataclass
class Component:
    """
    One rated area. The shape is `prime_directive.Step` with a band instead of
    a progress fraction: a `weight`, an applicability gate, and enough on the
    object for a page to render it without knowing what it is about.
    """
    key: str = ""
    order: int = 0
    title: str = ""
    question: str = ""            # what this component answers, in the second person
    weight: float = 1.0

    status: str = NOT_ENTERED
    rating: int = C5

    headline: str = ""
    detail: str = ""
    evidence: list = field(default_factory=list)
    findings: list = field(default_factory=list)   # the engine's own, for drill-down

    page: str = ""
    page_label: str = ""
    page_icon: str = "➡️"
    also: list = field(default_factory=list)       # (path, label, icon)

    # ---- the roll-up contract, identical to prime_directive.Step ----------
    @property
    def applies(self) -> bool:
        return self.status in COUNTED

    @property
    def readiness(self) -> float:
        return B.readiness(self.rating)

    # ---- presentation ----------------------------------------------------
    @property
    def code(self) -> str:
        return B.code(self.rating)

    @property
    def band_label(self) -> str:
        return B.label(self.rating)

    @property
    def bar(self) -> str:
        return B.bar(self.rating)

    @property
    def icon(self) -> str:
        return B.icon(self.rating)

    @property
    def status_label(self) -> str:
        return STATUS_LABEL.get(self.status, self.status)

    @property
    def is_rated(self) -> bool:
        return self.status == RATED

    def add(self, label: str, value: str, note: str = "") -> "Component":
        self.evidence.append(Evidence(label, value, note))
        return self


# --------------------------------------------------------------------------
# Small formatting helpers
# --------------------------------------------------------------------------
# Money is rendered with a single '$' and the page escapes it. NEVER build a
# string with two unescaped dollar signs in one span -- Streamlit reads the
# span between them as LaTeX and silently eats both.

def _m(x: float) -> str:
    x = float(x or 0.0)
    sign = "-" if x < 0 else ""
    return f"{sign}${abs(x):,.0f}"


def _mo(x: float) -> str:
    return _m(x) + " a month"


def _pc(x: float, decimals: int = 0) -> str:
    return f"{float(x or 0.0) * 100:.{decimals}f}%"


def _n(count: int, singular: str, plural: str = "") -> str:
    """'1 issue' / '2 issues'. Cheap, and it keeps headlines readable."""
    count = int(count)
    word = singular if count == 1 else (plural or singular + "s")
    return f"{count} {word}"


def _unrated(c: Component, status: str, headline: str, detail: str = "") -> Component:
    c.status = status
    c.rating = C5
    c.headline = headline
    c.detail = detail
    return c


def _sum(rows, attr: str) -> float:
    return float(sum(float(getattr(r, attr, 0.0) or 0.0) for r in rows or ()))


def _ending_portfolio(pr) -> float:
    return float(pr.ending_traditional + pr.ending_roth
                 + pr.ending_taxable + pr.ending_cash)


# ==========================================================================
# 1. Income floor
# ==========================================================================
# THE COMPONENT CIVILIAN TOOLS MISS (§3). Pension, VA compensation, CRSC,
# Social Security and a spouse's SSDI are all inflation-linked, and the VA
# slice is untaxed. A retiree whose floor covers essential spending is
# structurally safe in a way a civilian with identical net worth is not,
# because the portfolio is funding wants rather than survival.
#
# It is NOT retiree-only. `tsp_allocation.pension_as_bond()` sums retired pay
# + VA + CRSC, so a rated veteran with no pension still gets a partial floor.

#: floor / essential spending. 1.0 is the whole point of the component, so it
#: is C-1 rather than something above it: every essential dollar arrives
#: whether markets cooperate or not, and there is nothing left to improve.
FLOOR_CUTS = (1.00, 0.80, 0.60, 0.40)

#: Below this share covered before Social Security starts, with a claim more
#: than BRIDGE_YEARS away, the plan has a bridge to fund out of the portfolio
#: and the retirement floor alone flatters it. One band.
BRIDGE_COVER = 0.60
BRIDGE_YEARS = 2


def income_floor(h: Household, e) -> Component:
    c = Component(
        key="floor", order=1, weight=3.0, title="Income floor",
        question="Does guaranteed, inflation-linked income cover what you "
                 "could not cut?",
        page="pages/21_Investments.py", page_label="Investments", page_icon="📊",
        also=[("pages/15_Social_Security.py", "Social Security", "🧓"),
              ("pages/9_Survivor_and_VA.py", "Survivor Benefits", "🛡️"),
              ("pages/4_Assets_and_Debts.py", "Accounts", "🏦")])

    m = h.member

    # ---- the indexed streams, from the engine that already sums them ------
    from engine.investments import tsp_allocation as TSP
    try:
        pb = TSP.pension_as_bond(h)
        military = float(pb.guaranteed_monthly)
    except Exception:
        military = float(m.retired_pay_monthly + m.va_disability_monthly
                         + m.crsc_monthly)
    untaxed = float(m.va_disability_monthly + m.crsc_monthly)

    ss = h.social_security
    ssdi = float(ss.spouse_ssdi_monthly) if ss.spouse_on_ssdi else 0.0

    ss_monthly, ss_source, claim_age = 0.0, "", int(ss.claim_age or 67)
    try:
        from engine.income import social_security as SS
        a = SS.analyse(h)
        ss_monthly = float(a.benefit_at_claim) + float(a.spouse_benefit_at_claim)
        ss_source = a.pia_source
        claim_age = int(a.claim_age)
    except Exception:
        ss_monthly = 0.0

    today_floor = military + ssdi
    retirement_floor = today_floor + ss_monthly

    # ---- the three ways this cannot be rated -----------------------------
    if m.is_serving and m.retired_pay_monthly <= 0:
        c.add("Indexed income today", _mo(today_floor),
              "Retired pay, VA compensation, CRSC and a spouse's SSDI.")
        c.add("Social Security, from age " + str(claim_age), _mo(ss_monthly),
              ss_source or "Not estimated.")
        c.add("Military retired pay entered", _mo(m.retired_pay_monthly),
              "Nothing here assumes you reach twenty years.")
        return _unrated(
            c, NOT_MODELLED,
            "Your pension has not started, and the app does not model it starting yet.",
            e.coverage_note + " Put the retired pay you expect on the Pension "
            "page and this component rates from it — including the fact that "
            "a rated veteran with no pension at all still has a partial floor "
            "from VA compensation.")

    if float(h.monthly_expenses or 0.0) <= 0:
        c.add("Indexed income in retirement", _mo(retirement_floor))
        return _unrated(
            c, NOT_ENTERED, "You have not said what you spend in a month.",
            "The floor is a comparison, and half of it is missing. Enter total "
            "monthly spending, then the part of it you could not cut.")

    # NOT ANSWERED -- but sometimes the answer cannot change the band.
    #
    # `essential_monthly()` clamps the essential figure to total spending, so
    # essentials are never more than the total. If guaranteed income already
    # covers the WHOLE total, then it covers the essential part of it whatever
    # the split turns out to be, and the ratio is at least 1.0 by arithmetic
    # rather than by assumption. Refusing to rate there is not refusing to
    # guess -- there is nothing to guess -- and it would report the app's most
    # important component as "not established" for exactly the household §3
    # says the component exists to recognise: the retiree whose floor covers
    # everything and whose portfolio is therefore funding wants, not survival.
    #
    # Only the C-1 case is safe. At any lower coverage the split genuinely
    # decides the band -- a floor covering half of total spending is C-4 if
    # essentials are the whole total and C-1 if they are half of it -- so those
    # stay NOT_ENTERED.
    if not has_essential_split(h):
        total = float(h.monthly_expenses)
        if retirement_floor >= total:
            c.status = RATED
            c.rating = C1
            c.add("Indexed income in retirement", _mo(retirement_floor),
                  "Retired pay, VA, CRSC, SSDI and Social Security at "
                  + str(claim_age) + ".")
            c.add("Total spending", _mo(total),
                  "Everything, not just the part you could not cut.")
            c.add("Essentials covered", "at least "
                  + _pc(retirement_floor / total if total > 0 else 0),
                  "You have not split essential from discretionary spending, "
                  "and here it does not matter: guaranteed income covers your "
                  "ENTIRE spending, so it covers the essential part of it "
                  "whatever the split is.")
            if untaxed > 0:
                c.add("Of which untaxed", _mo(untaxed),
                      "VA compensation and CRSC are tax-free, so this buys "
                      "more than the same figure of wages or retired pay.")
            c.headline = ("Every dollar you spend — not just every essential "
                          "one — arrives whether markets cooperate or not.")
            c.detail = ("This is the position civilian planning tools have no "
                        "field for. Your indexed income covers total spending, "
                        "so the portfolio funds wants rather than survival and "
                        "a bad decade forces no sales at all. Answering the "
                        "essential-spending question will not change this "
                        "band, but the survivor component still needs it — it "
                        "asks the same question about one person instead of "
                        "two.")
            return c

        assumed = essential_monthly(h)
        c.add("Indexed income in retirement", _mo(retirement_floor))
        c.add("Total spending", _mo(h.monthly_expenses))
        c.add("Essential spending", "not answered",
              "Assuming " + _mo(assumed) + " would put the floor at "
              + _pc(retirement_floor / assumed if assumed else 0)
              + " of essentials — but that is the app's guess, not your answer.")
        return _unrated(
            c, NOT_ENTERED,
            "You have not said which part of your spending you could not cut.",
            "This is the one figure the component cannot be guessed from. §8: "
            "people understate it, and a floor rated against a guess is a "
            "confident wrong answer. The question is not a budget line — it is "
            "what would still have to be paid if everything optional stopped.")

    # ---- rate it ---------------------------------------------------------
    essential = essential_monthly(h)
    ratio = retirement_floor / essential if essential > 0 else 0.0
    today_ratio = today_floor / essential if essential > 0 else 0.0
    age_now = m.age()
    bridge_years = max(0, claim_age - age_now)
    has_bridge = (today_ratio < BRIDGE_COVER and bridge_years > BRIDGE_YEARS
                  and ss_monthly > 0)

    rating = B.band_for_ratio(ratio, FLOOR_CUTS)
    if has_bridge:
        rating = B.demote(rating, 1)

    c.status = RATED
    c.rating = rating
    c.add("Indexed income in retirement", _mo(retirement_floor),
          "Retired pay, VA, CRSC, SSDI and Social Security at " + str(claim_age) + ".")
    c.add("Essential spending", _mo(essential), "What you said you could not cut.")
    c.add("Essentials covered", _pc(ratio),
          "Guaranteed income divided by essential spending.")
    if untaxed > 0:
        c.add("Of which untaxed", _mo(untaxed),
              "VA compensation and CRSC are tax-free, so this buys more than "
              "the same figure of wages or retired pay.")
    if has_bridge:
        c.add("Before Social Security starts", _pc(today_ratio),
              "For " + str(bridge_years) + " more years the portfolio has to "
              "cover the difference. One band, for the bridge.")

    if ratio >= 1.0:
        c.headline = ("Every essential dollar arrives whether markets cooperate "
                      "or not.")
        c.detail = ("Your guaranteed, inflation-linked income covers "
                    + _pc(ratio) + " of essential spending. The portfolio is "
                    "funding wants, not survival, so a bad decade forces no "
                    "sales at all — that is sequence-of-returns risk, and it "
                    "does not apply to you. A civilian with your net worth and "
                    "no pension is not in this position.")
    elif ratio >= FLOOR_CUTS[2]:
        c.headline = ("Guaranteed income covers " + _pc(ratio)
                      + " of your essentials.")
        c.detail = ("The remaining " + _mo(max(0.0, essential - retirement_floor))
                    + " has to come from the portfolio every month, in every "
                    "market. That is the part exposed to a bad sequence of "
                    "returns.")
    else:
        c.headline = ("Most of your essential spending depends on the "
                      "portfolio.")
        c.detail = ("Guaranteed income covers " + _pc(ratio) + " of essentials, "
                    "leaving " + _mo(max(0.0, essential - retirement_floor))
                    + " a month that a bad market has to be sold into. Claiming "
                    "Social Security later, a VA re-evaluation and lowering the "
                    "essential figure itself all move this.")
    if ss_source:
        c.detail += " Social Security here is " + str(ss_source).lower() + "."
    return c


# ==========================================================================
# 2. Funded ratio
# ==========================================================================
# §4: `run_projection()` is already the spine and already reports
# `total_shortfall` and `years_with_shortfall`. Resources against needs is what
# those two describe, so the component reads them rather than building a
# second present-value model that would disagree with the first.

#: Share of lifetime spending the plan actually funds. A plan that funds all of
#: it and still has a balance left is C-1; the cuts below it are deliberately
#: tight, because a 5% lifetime shortfall is not a rounding error, it is
#: several years at the end with nothing in the account.
FUNDED_CUTS = (0.999, 0.98, 0.92, 0.80)

#: A shortfall spread over this many years or more is structural rather than a
#: single bad year, and costs an extra band.
CHRONIC_YEARS = 10


def funded_ratio(h: Household, e) -> Component:
    c = Component(
        key="funded", order=2, weight=2.5, title="Funded ratio",
        question="Do your resources cover your spending for as long as you live?",
        page="pages/4_Assets_and_Debts.py", page_label="Accounts", page_icon="🏦",
        also=[("pages/14_Roth_Conversions.py", "Roth Conversions", "🔁"),
              ("pages/17_Assumptions.py", "Assumptions", "🎛️")])

    if not e.covers_future:
        return _unrated(c, NOT_MODELLED,
                        "The projection does not reach back over your service.",
                        e.coverage_note)
    if not e.has_projection:
        return _unrated(c, NOT_MODELLED, "The projection did not run.",
                        e.projection_error or e.profile_error
                        or "No projection was available to read.")
    if float(h.monthly_expenses or 0.0) <= 0:
        return _unrated(c, NOT_ENTERED, "You have not said what you spend.",
                        "A funded ratio is resources over needs. Without a "
                        "spending figure there are no needs to divide by.")

    pr = e.projection
    rows = list(pr.rows)
    lifetime_spending = _sum(rows, "spending")
    shortfall = float(pr.total_shortfall)
    covered = (1.0 - shortfall / lifetime_spending) if lifetime_spending > 0 else 0.0
    ending = _ending_portfolio(pr)
    first_short = next((int(r.year) for r in rows
                        if float(getattr(r, "shortfall", 0.0) or 0.0) > 1.0), 0)
    last_year = int(rows[-1].year) if rows else 0

    if shortfall <= 1.0:
        rating = C1 if ending > 0 else C2
    else:
        rating = B.band_for_ratio(covered, FUNDED_CUTS)
        if int(pr.years_with_shortfall) >= CHRONIC_YEARS:
            rating = B.demote(rating, 1)

    c.status = RATED
    c.rating = rating
    c.add("Lifetime spending planned", _m(lifetime_spending),
          "Today's dollars, through " + str(last_year) + ".")
    c.add("Unfunded", _m(shortfall),
          "Spending the plan cannot pay for out of any account.")
    c.add("Spending funded", _pc(covered, 1))
    c.add("Left at the end of the plan", _m(ending),
          "Across every account, after tax on withdrawals.")
    last_wage_year = max((int(r.year) for r in rows
                          if float(getattr(r, "wages", 0.0) or 0.0) > 0), default=0)
    if last_wage_year:
        target = int(getattr(h, "target_retirement_age", 0) or 0)
        c.add("Last year of wages", str(last_wage_year),
              ("From the retirement age of " + str(target) + " you asked for."
               if target > 0 else
               "No target retirement age entered, so the plan assumes you work "
               "to the app's default stop age. Answering it changes this."))
    if first_short:
        c.add("First year you run short", str(first_short),
              str(int(pr.years_with_shortfall)) + " years fall short in total.")

    if shortfall <= 1.0 and ending > 0:
        c.headline = "The plan funds every year and still has money at the end."
        c.detail = ("On these assumptions nothing runs out. " + _m(ending)
                    + " remains in " + str(last_year) + ". Test it against bad "
                    "markets in the longevity component below — a plan that "
                    "works on the average path is not the same as a plan that "
                    "works.")
    elif shortfall <= 1.0:
        c.headline = "The plan funds every year, but finishes at zero."
        c.detail = ("Nothing runs out, and nothing is left over. There is no "
                    "margin for a bad sequence, a long-term care year or a "
                    "worse tax regime.")
    else:
        c.headline = ("The plan runs short in "
                      + _n(int(pr.years_with_shortfall), "year")
                      + ", starting in " + str(first_short or last_year) + ".")
        c.detail = (_m(shortfall) + " of planned spending has no account to come "
                    "out of. Spending, retirement age and the return assumption "
                    "are the three levers; the Assumptions page holds the third.")
    return c


# ==========================================================================
# 3. Longevity
# ==========================================================================
# §4: `MCSummary` already carries per-path shortfall. A success rate is
# `(shortfall == 0).mean()` -- one line -- and it is not reported anywhere in
# the app today because `win_rate()` answers the Roth question instead.

#: Share of paths with no shortfall at all.
SUCCESS_CUTS = (0.95, 0.85, 0.70, 0.50)


def longevity(h: Household, e) -> Component:
    c = Component(
        key="longevity", order=3, weight=2.0, title="Longevity",
        question="Does the plan survive bad markets, not just the average one?",
        page="pages/14_Roth_Conversions.py", page_label="Roth Conversions",
        page_icon="🔁",
        also=[("pages/17_Assumptions.py", "Assumptions", "🎛️"),
              ("pages/21_Investments.py", "Investments", "📊")])

    if not e.covers_future:
        return _unrated(c, NOT_MODELLED,
                        "The projection does not reach back over your service.",
                        e.coverage_note)
    if not e.has_mc:
        return _unrated(
            c, NOT_RUN, "The market test has not been run for this plan.",
            "Three hundred futures take a few seconds, which is too long to "
            "run every time this page opens. Run it from the button above and "
            "the rating fills in.")

    from engine.scorecard import inputs as IN
    mc = e.mc
    rate = IN.success_rate(mc)
    n = int(getattr(mc, "n_paths", 0))
    failed = int(round((1.0 - rate) * n))
    rating = B.band_for_ratio(rate, SUCCESS_CUTS)

    worst = ""
    try:
        p = mc.percentiles(mc.shortfall_no_convert, qs=(50, 95))
        worst = _m(p[95])
    except Exception:
        worst = ""

    c.status = RATED
    c.rating = rating
    c.add("Futures tested", f"{n:,}",
          "The same plan run against randomly drawn returns and inflation.")
    c.add("Paths that never ran short", _pc(rate, 1))
    c.add("Paths that ran short", f"{failed:,}")
    if worst:
        c.add("Shortfall in the worst 5%", worst,
              "Total unfunded spending across the whole plan on those paths.")

    if rate >= SUCCESS_CUTS[0]:
        c.headline = "The plan holds up in " + _pc(rate, 0) + " of futures."
        c.detail = ("A plan that survives almost every drawn sequence is not "
                    "relying on the average one arriving. Note that success "
                    "here means no year went unfunded — it says nothing about "
                    "how much was left over.")
    elif rate >= SUCCESS_CUTS[2]:
        c.headline = (_pc(1.0 - rate, 0) + " of futures run short.")
        c.detail = ("The plan works on the average path and fails on a bad "
                    "sequence. The fix is rarely a different allocation — it is "
                    "usually a lower essential floor, a later claim, or spending "
                    "that flexes when markets fall.")
    else:
        c.headline = ("The plan fails in " + _pc(1.0 - rate, 0) + " of futures.")
        c.detail = ("This is not a market-timing problem. Resources and needs "
                    "are too close together for the sequence of returns not to "
                    "decide the outcome.")
    return c


# ==========================================================================
# 4. Tax position
# ==========================================================================
# §3: conversion window used or wasted, and RMD exposure. All five figures are
# already on `ProjectionResult`.

#: Lifetime tax as a share of lifetime AGI. Lower is better.
TAX_DRAG_CUTS = (0.10, 0.15, 0.20, 0.26)

#: Share of what is left at the end still sitting in traditional accounts --
#: money on the balance sheet that is owed to the IRS rather than owned. Above
#: this the conversion window was not used, and it costs a band.
DEFERRED_SHARE = 0.50

#: IRMAA surcharges as a share of lifetime tax. Above this they are a policy
#: failure rather than a rounding error, and cost a band.
IRMAA_SHARE = 0.02


def tax_position(h: Household, e) -> Component:
    c = Component(
        key="tax", order=4, weight=1.5, title="Tax position",
        question="Are you using the low-rate years, or leaving the bill to "
                 "RMDs and IRMAA?",
        page="pages/14_Roth_Conversions.py", page_label="Roth Conversions",
        page_icon="🔁",
        also=[("pages/22_This_Years_Taxes.py", "Taxes", "🧾"),
              ("pages/16_Healthcare.py", "Healthcare", "🏥")])

    if not e.covers_future:
        return _unrated(c, NOT_MODELLED,
                        "The projection does not reach back over your service.",
                        e.coverage_note + " Your lowest-rate years are the ones "
                        "it cannot see: untaxed allowances now, and the gap "
                        "between leaving the service and the pension and Social "
                        "Security arriving.")
    if not e.has_projection:
        return _unrated(c, NOT_MODELLED, "The projection did not run.",
                        e.projection_error or e.profile_error
                        or "No projection was available to read.")

    pr = e.projection
    rows = list(pr.rows)
    lifetime_agi = _sum(rows, "agi")
    if lifetime_agi <= 0:
        return _unrated(c, NOT_ENTERED, "There is no income in the plan to tax.",
                        "Enter balances, retired pay and Social Security and "
                        "this component fills in.")

    drag = float(pr.lifetime_total_tax) / lifetime_agi
    ending = _ending_portfolio(pr)
    deferred = (float(pr.ending_traditional) / ending) if ending > 0 else 0.0
    irmaa = float(pr.lifetime_irmaa_surcharge)
    irmaa_share = (irmaa / float(pr.lifetime_total_tax)
                   if pr.lifetime_total_tax > 0 else 0.0)

    rating = B.band_for_cost(drag, TAX_DRAG_CUTS)
    reasons = []
    if deferred > DEFERRED_SHARE:
        rating = B.demote(rating, 1)
        reasons.append("more than half of what is left is still pre-tax")
    if irmaa > 0 and irmaa_share > IRMAA_SHARE:
        rating = B.demote(rating, 1)
        reasons.append("IRMAA surcharges are a material share of the bill")

    c.status = RATED
    c.rating = rating
    c.add("Lifetime tax", _m(pr.lifetime_total_tax),
          "Federal, state, NIIT, IRMAA and penalties, in today's dollars.")
    c.add("Effective lifetime rate", _pc(drag, 1),
          "Lifetime tax over lifetime adjusted gross income.")
    c.add("Peak marginal rate", _pc(pr.peak_marginal_rate),
          "The worst single year in the plan.")
    c.add("Forced out by RMDs", _m(pr.lifetime_rmds),
          "Withdrawals the law requires whether or not you want them.")
    c.add("Still pre-tax at the end", _m(pr.ending_traditional),
          _pc(deferred) + " of what is left. Your heirs pay the tax on it, "
          "inside ten years.")
    if irmaa > 0:
        c.add("IRMAA surcharges", _m(irmaa),
              "Medicare premium surcharges triggered by income two years "
              "earlier.")

    if rating <= C2:
        c.headline = "The tax on this plan is about as low as it goes."
        c.detail = ("An effective lifetime rate of " + _pc(drag, 1) + " on "
                    + _m(lifetime_agi) + " of income. There is no large deferred "
                    "balance waiting to be taxed at the worst moment.")
    else:
        why = "; ".join(reasons) if reasons else "the rate itself is high"
        c.headline = ("An effective lifetime rate of " + _pc(drag, 1)
                      + ", and " + _m(pr.ending_traditional) + " still pre-tax.")
        c.detail = ("Rated down because " + why + ". The lever is the window "
                    "between the year wages stop and the year RMDs start: "
                    "income is low, brackets are empty, and conversions made "
                    "then are the cheapest they will ever be. The Roth "
                    "Conversions page sizes it.")
    return c


# ==========================================================================
# 5. Healthcare
# ==========================================================================
# `benefits/healthcare` already runs a year-by-year lifetime cost and emits
# findings about continuity to 65, TRICARE For Life's Part B requirement, the
# IRMAA cliffs and long-term care. The band is read off those findings.
#
# ONE ASSUMPTION HAS TO BE SURFACED, AND IT IS LOAD-BEARING. For a serving
# member `lifetime_cost()` has to guess when they leave, and
# `default_leave_service_age()` guesses TWENTY YEARS -- so a member at six
# years is modelled as retiring with TRICARE For Life for life, the findings
# come back clean, and the band reads C-1: "nothing in the cover has a gap in
# it". That is a confident answer to a question the member has not answered.
# Whether they stay to 20 is the largest open decision in their life and the
# whole reason the Currently Serving funnel exists (§2, "the future is
# unwritten"); separating at twelve ends TRICARE outright and replaces it with
# a civilian premium for twenty-five years.
#
# §8: a rating must state the figures that produced it, and an invisible
# assumption is the opposite of that. So the assumption is written into the
# evidence, and a band resting on twenty years the member has not served costs
# one band -- not because the cover is poor today, but because continuity past
# a separation that has not been decided is not established.

def healthcare(h: Household, e) -> Component:
    c = Component(
        key="healthcare", order=5, weight=1.5, title="Healthcare",
        question="Are you covered from now to 65, and past it?",
        page="pages/16_Healthcare.py", page_label="Healthcare", page_icon="🏥",
        also=[("pages/9_Survivor_and_VA.py", "Survivor Benefits", "🛡️"),
              ("pages/11_Separation_and_Insurance.py", "Medical Separation", "⚕️")])

    from engine.benefits import healthcare as HC
    try:
        lc = HC.lifetime_cost(h)
        found = list(HC.findings(h, lc))
    except Exception as exc:                                  # pragma: no cover
        return _unrated(c, NOT_MODELLED, "The healthcare cost model did not run.",
                        str(exc))

    m = h.member
    rating = B.band_from_findings(found)

    # The twenty-year assumption, made visible and then paid for.
    serving = bool(m.is_serving)
    years_now = float(m.years_of_service or 0.0)
    leave_age = int(getattr(lc, "leave_service_age", 0) or 0)
    assumed_twenty = serving and bool(getattr(lc, "will_retire", False)) \
        and years_now < 20.0
    if assumed_twenty:
        rating = B.demote(rating, 1)

    c.status = RATED
    c.rating = rating
    c.findings = found

    tier = lc.irmaa_tier
    c.add("Lifetime cost, today's dollars", _m(lc.present_value),
          "Premiums, enrolment fees and out-of-pocket costs from "
          + str(lc.start_age) + " to " + str(lc.death_age) + ", discounted.")
    c.add("This year", _m(lc.first_year_cost))
    c.add("Retirement income Medicare will read", _m(lc.retirement_magi),
          "IRMAA looks at your income two years earlier, so a conversion "
          "raises a premium later.")
    if tier is not None:
        c.add("IRMAA tier", getattr(tier, "label", "") or "Standard premium")
    c.add("TRICARE group", str(lc.group), "Set by your DIEMS date, and nothing else.")
    if serving:
        c.add("This cost assumes you serve to",
              (f"{leave_age} — 20 years" if assumed_twenty else "your entered plan"),
              ("You are at " + f"{years_now:g}" + " years. Everything past 65 "
               "here is TRICARE For Life, which exists only if you retire from "
               "the military. Separating earlier replaces all of it with a "
               "civilian premium."
               if assumed_twenty else
               "Modelled as separating without a military retirement, so the "
               "cost after you leave is a civilian one."))

    n = B.count_severities(found)
    if assumed_twenty:
        c.headline = ("Your cover is sound while you serve, and everything "
                      "after it rests on reaching twenty years.")
        c.detail = ("The model assumes you retire from the military, which is "
                    "what puts TRICARE For Life behind Medicare at 65. You are "
                    "at " + f"{years_now:g}" + " years, so that is an "
                    "assumption rather than a fact, and it is worth one band on "
                    "its own: leaving at twelve does not reduce this cover, it "
                    "removes it. Nothing here assumes you reach twenty for any "
                    "other purpose."
                    + ("" if n["bad"] + n["warn"] == 0 else
                       " There are also " + _n(n["bad"], "urgent issue")
                       + " and " + _n(n["warn"], "lesser one")
                       + " to read on the Healthcare page."))
    elif c.rating == C1:
        c.headline = "Nothing in the cover has a gap in it."
        c.detail = ("Cost is not the same as risk: " + _m(lc.present_value)
                    + " of lifetime cost with continuous cover is a better "
                    "position than half that with a gap in it.")
    else:
        c.headline = (_n(n["bad"], "urgent issue") + " and "
                      + _n(n["warn"], "lesser one") + " in your cover.")
        c.detail = ("Read them on the Healthcare page. The two that cost the "
                    "most are almost always the same pair: declining Part B at "
                    "65, which ends TRICARE For Life permanently, and having no "
                    "plan at all for long-term care.")
    return c


# ==========================================================================
# 6. Survivor
# ==========================================================================
# §3: does the spouse still make it if you die first. This is an income
# question first -- VA compensation and retired pay both STOP at death, and
# only SBP and DIC replace any of them -- and a paperwork question second,
# because a beneficiary designation beats the will on every account that has
# one.

#: A one-person household is assumed to need this share of a two-person
#: household's essential spending. Housing, insurance and utilities barely
#: move; food and transport roughly halve. Documented rather than tuned.
SURVIVOR_NEED_SHARE = 0.75

#: survivor income / survivor need. Same shape as the floor, and for the same
#: reason: covering the essentials is the whole question.
SURVIVOR_CUTS = (1.00, 0.80, 0.60, 0.40)


def survivor(h: Household, e) -> Component:
    c = Component(
        key="survivor", order=6, weight=2.0, title="Survivor",
        question="Does your spouse still make it if you die first?",
        page="pages/9_Survivor_and_VA.py", page_label="Survivor Benefits",
        page_icon="🛡️",
        also=[("pages/20_Estate_and_Gifting.py", "Estate", "🎁"),
              ("pages/15_Social_Security.py", "Social Security", "🧓")])

    m = h.member
    has_dependants = bool(h.has_spouse) or int(h.estate.n_children) > 0
    if not has_dependants:
        return _unrated(
            c, NOT_APPLICABLE, "You have no spouse or dependent children.",
            "SBP, DIC and the survivor Social Security benefit are all "
            "family benefits. With nobody to leave an income to there is "
            "nothing here to rate, so this component is excluded from the "
            "overall rating rather than scored zero.")

    if m.is_serving:
        c.add("SGLI cover", _m(m.sgli_coverage),
              "A lump sum, not an income. It is not indexed and it does not "
              "replace a pension.")
        return _unrated(
            c, NOT_MODELLED,
            "Death in service is a different benefit set, and it is not modelled yet.",
            "The death gratuity, SGLI, dependency and indemnity compensation "
            "and the survivor's Social Security all behave differently from "
            "the SBP election you have not made yet. Rating this from the "
            "retiree model would describe a situation you are not in.")

    if float(h.monthly_expenses or 0.0) <= 0 or not has_essential_split(h):
        return _unrated(
            c, NOT_ENTERED, "You have not said what your household could not cut.",
            "The survivor question is the floor question asked about one "
            "person instead of two. It needs the same figure, and guessing it "
            "produces the same confident wrong answer.")

    # ---- what actually keeps arriving ------------------------------------
    from engine.benefits import sbp as SBP
    essential = essential_monthly(h)
    need = essential * SURVIVOR_NEED_SHARE

    dic_applies = bool(m.va_rating_permanent_total and int(m.va_rating) >= 100)
    age_now = m.age()
    sbp_annuity, dic = 0.0, 0.0
    sbp_found = []
    try:
        a = SBP.analyse(retired_pay_monthly=float(m.retired_pay_monthly),
                        retirement_age=max(38, min(age_now, 70)),
                        dic_applies=dic_applies)
        sbp_annuity = float(a.annuity_monthly) if m.sbp_elected else 0.0
        dic = float(a.dic_monthly)
        sbp_found = list(SBP.findings(a, bool(m.sbp_elected), bool(h.has_spouse)))
    except Exception:                                        # pragma: no cover
        sbp_annuity = 0.55 * float(m.retired_pay_monthly) if m.sbp_elected else 0.0

    ss = h.social_security
    ssdi = float(ss.spouse_ssdi_monthly) if ss.spouse_on_ssdi else 0.0
    survivor_ss = 0.0
    try:
        from engine.income import social_security as SS
        sa = SS.analyse(h)
        if sa.survivor is not None:
            survivor_ss = float(sa.survivor.survivor_receives)
        else:
            survivor_ss = float(sa.benefit_at_claim)
    except Exception:                                        # pragma: no cover
        survivor_ss = 0.0

    income = sbp_annuity + dic + survivor_ss + ssdi
    ratio = income / need if need > 0 else 0.0
    rating = B.band_for_ratio(ratio, SURVIVOR_CUTS)

    # ---- the paperwork, from the estate engine ---------------------------
    gaps = []
    try:
        from engine.estate import planning as EP
        gaps = [f for f in EP.beneficiary_checklist(h) if f.severity == "bad"]
    except Exception:                                        # pragma: no cover
        gaps = []
    if gaps:
        rating = B.demote(rating, 1)

    c.status = RATED
    c.rating = rating
    c.findings = list(sbp_found) + list(gaps)

    lost = float(m.retired_pay_monthly + m.va_disability_monthly + m.crsc_monthly)
    c.add("Income your survivor keeps", _mo(income),
          "SBP annuity, DIC, the larger Social Security check, and SSDI.")
    c.add("Income that stops at your death", _mo(lost),
          "Retired pay and VA compensation both end. Only SBP and DIC replace "
          "any part of them.")
    c.add("What one person needs", _mo(need),
          _pc(SURVIVOR_NEED_SHARE) + " of the household's essential spending.")
    c.add("Covered", _pc(ratio))
    if gaps:
        c.add("Accounts with no current beneficiary", str(len(gaps)),
              "A beneficiary designation beats the will. One band.")

    if ratio >= 1.0 and not gaps:
        c.headline = "Your survivor's essentials are covered without the portfolio."
        c.detail = (_mo(income) + " keeps arriving, against " + _mo(need)
                    + " of need. The portfolio is a cushion rather than the "
                    "plan.")
    elif ratio >= SURVIVOR_CUTS[2]:
        c.headline = ("Your survivor keeps " + _pc(ratio)
                      + " of what one person needs.")
        c.detail = ("The gap is " + _mo(max(0.0, need - income)) + " a month, "
                    "for the rest of their life, out of a portfolio that has "
                    "also just lost " + _mo(lost) + " a month of income."
                    + (" Fix the beneficiary designations first — they cost "
                       "nothing and they override the will." if gaps else ""))
    else:
        c.headline = "Your survivor does not make it on guaranteed income."
        c.detail = ("Only " + _mo(income) + " continues against " + _mo(need)
                    + " of need. SBP at 55% of base, the DIC offset, and "
                    "term cover for the years before the annuity starts are "
                    "the three things that move this.")
    return c


# ==========================================================================
# 7. Liquidity & debt
# ==========================================================================
# `coach/prime_directive` already holds the emergency-fund targets and the
# high-interest debt rule, including the SCRA 6% cap that reorders which debt
# is actually the expensive one. This reads those, so the scorecard and the
# Next Dollar page can never disagree about what counts as high-rate debt.

#: Reserve months held, over the target for this member. 1.0 is the target.
RESERVE_CUTS = (1.00, 0.67, 0.34, 0.01)

#: High-rate debt worth more than this many months of spending is a second
#: band, not a first.
DEBT_MONTHS_SEVERE = 6.0


def liquidity_and_debt(h: Household, e) -> Component:
    c = Component(
        key="liquidity", order=7, weight=1.5, title="Liquidity & debt",
        question="Can you absorb a shock without borrowing at a bad rate?",
        page="pages/6_Prime_Directive.py", page_label="Next Dollar", page_icon="🧭",
        also=[("pages/5_Debt_Payoff.py", "Debt Payoff", "💳"),
              ("pages/4_Assets_and_Debts.py", "Accounts", "🏦")])

    from engine.coach import prime_directive as PD

    spend = float(h.monthly_expenses or 0.0)
    if spend <= 0:
        c.add("Cash on hand", _m(h.cash_savings))
        return _unrated(c, NOT_ENTERED, "You have not said what you spend in a month.",
                        "A reserve is measured in months, and the months need a "
                        "denominator. This one figure unlocks it.")

    # Three months while serving, six after. The reasons differ -- a serving
    # member's job-loss risk is near zero but PCS float, a spouse's income
    # stopping at every move and a DFAS pay error are all real. The target
    # comes from prime_directive so the two pages cannot drift.
    serving = bool(h.member.is_serving)
    target_months = 3.0 if serving else 6.0
    months = float(h.cash_savings) / spend if spend > 0 else 0.0
    rating = B.band_for_ratio(months / target_months, RESERVE_CUTS)

    high = PD.high_interest_debts(h)
    high_total = float(sum(d.balance for d in high))
    worst = max(high, key=lambda d: d.apr) if high else None
    if high:
        rating = B.demote(rating,
                          2 if high_total > DEBT_MONTHS_SEVERE * spend else 1)

    c.status = RATED
    c.rating = rating
    c.add("Cash on hand", _m(h.cash_savings))
    c.add("Months of spending covered", f"{months:.1f}",
          "Target is " + f"{target_months:.0f}" + " months "
          + ("while you are serving." if serving else "now that you are not serving."))
    c.add("Debt above 8%", _m(high_total),
          ("Worst is " + worst.name + " at " + _pc(worst.apr, 1) + "."
           if worst else "None, after the SCRA cap is applied."))
    total_debt = float(sum(d.balance for d in h.debts if d.balance > 0))
    if total_debt > high_total:
        c.add("All debt", _m(total_debt),
              "Including the low-rate debt, which is a preference rather than "
              "an emergency.")

    if not high and months >= target_months:
        c.headline = (f"{months:.1f} months of reserve and no high-rate debt.")
        c.detail = ("A shock costs you cash rather than a credit card at 22%, "
                    "and nothing in the portfolio has to be sold to meet it.")
    elif high:
        c.headline = (_m(high_total) + " of debt above 8%.")
        c.detail = ("Paying it off is a guaranteed, tax-free return at that "
                    "rate, which nothing in the portfolio offers with "
                    "certainty. Next Dollar puts it in order, and applies the "
                    "SCRA 6% cap to pre-service debt first — that alone can "
                    "change which debt is actually the expensive one.")
    else:
        c.headline = (f"{months:.1f} months of reserve against a "
                      f"{target_months:.0f}-month target.")
        c.detail = ("The gap is " + _m(max(0.0, target_months * spend - h.cash_savings))
                    + ". Until it is closed, the next unexpected bill is "
                    "borrowed rather than paid.")
    return c


# ==========================================================================
# 8. Legacy
# ==========================================================================
# §3: "only scored when the user says it is a goal".
#
# WHAT COUNTS AS SAYING SO, decided and documented: a target legacy per child,
# a gifting programme already running, or children recorded on the ESTATE
# record. `Household.n_dependents` is deliberately NOT read here -- it is a pay
# and tax concept that includes a spouse, and treating it as legacy intent
# would score every married member on a goal they never stated. A user with no
# children and no target is not scored on legacy, and the component is excluded
# from the roll-up rather than rated zero.

#: What reaches heirs after tax, over what was asked for.
LEGACY_CUTS = (1.00, 0.80, 0.60, 0.40)

#: Share of the pre-tax estate that heirs hand straight back. Above this the
#: ten-year rule is doing real damage and it costs a band.
HEIR_TAX_SHARE = 0.20


def legacy(h: Household, e) -> Component:
    c = Component(
        key="legacy", order=8, weight=1.0, title="Legacy",
        question="Does what you want to leave actually arrive?",
        page="pages/20_Estate_and_Gifting.py", page_label="Estate", page_icon="🎁",
        also=[("pages/14_Roth_Conversions.py", "Roth Conversions", "🔁")])

    est = h.estate
    target_each = float(est.target_legacy_per_child or 0.0)
    n_children = int(est.n_children or 0)
    gifting = float(est.annual_gift_per_child or 0.0)

    if target_each <= 0 and n_children <= 0 and gifting <= 0:
        return _unrated(
            c, NOT_APPLICABLE, "You have not said a legacy is a goal.",
            "Nothing is assumed from the number of dependants you claim for "
            "pay — that includes a spouse and says nothing about heirs. Put a "
            "target per child, a gifting plan or a number of children on the "
            "Estate page and this component starts being rated. Until then it "
            "is excluded from the overall rating rather than scored zero.")

    from engine.estate import planning as EP
    found = []
    try:
        checklist = {f.headline for f in EP.beneficiary_checklist(h)}
        found = [f for f in EP.findings(h) if f.headline not in checklist]
    except Exception:                                        # pragma: no cover
        found = []

    rating = B.band_from_findings(found)
    to_heirs = heir_tax = 0.0
    measured = False

    if e.usable_projection and target_each > 0:
        pr = e.projection
        to_heirs = float(pr.heir_value_total)
        heir_tax = float(pr.heir_tax_paid)
        wanted = target_each * max(1, n_children)
        ratio = to_heirs / wanted if wanted > 0 else 0.0
        measured = True
        # The worse of the two readings. A plan that reaches the target with a
        # will nobody has signed has not reached the target.
        rating = B.worst(rating, B.band_for_ratio(ratio, LEGACY_CUTS))
        gross = to_heirs + heir_tax
        if gross > 0 and heir_tax / gross > HEIR_TAX_SHARE:
            rating = B.demote(rating, 1)
        c.add("Reaches your heirs after tax", _m(to_heirs))
        c.add("You asked for", _m(wanted),
              _m(target_each) + " each, for " + str(max(1, n_children)) + ".")
        c.add("Target met", _pc(ratio))
        c.add("Tax your heirs pay", _m(heir_tax),
              "Inherited traditional balances empty inside ten years, on top "
              "of the heir's own income.")
    elif e.usable_projection:
        pr = e.projection
        to_heirs = float(pr.heir_value_total)
        heir_tax = float(pr.heir_tax_paid)
        c.add("Reaches your heirs after tax", _m(to_heirs))
        c.add("Tax your heirs pay", _m(heir_tax))
        c.add("Target per child", "not set",
              "Set one and this component is rated against it rather than "
              "against the paperwork alone.")
    else:
        c.add("Children recorded", str(n_children))
        c.add("Target per child", _m(target_each) if target_each else "not set")
        c.add("Gifting each year", _m(gifting) if gifting else "none")

    n = B.count_severities(found)
    c.status = RATED
    c.rating = rating
    c.findings = found

    if c.rating <= C2 and measured:
        c.headline = "What you want to leave arrives, and the paperwork agrees."
        c.detail = (_m(to_heirs) + " reaches your heirs after every tax bill.")
    elif c.rating <= C2:
        c.headline = "Nothing in the estate paperwork is working against you."
        c.detail = ("Set a target per child and this component is rated on "
                    "whether the plan actually reaches it, rather than on the "
                    "paperwork alone.")
    else:
        c.headline = (_n(n["bad"], "urgent issue") + " and "
                      + _n(n["warn"], "lesser one") + " in how your estate passes.")
        c.detail = ("The largest is usually the ten-year rule: an inherited "
                    "traditional balance has to empty within ten years, on top "
                    "of the heir's own income, in their highest-earning decade. "
                    "Converting during your own low-rate years is the lever, "
                    "and it is the same lever as the tax component.")
    return c


# --------------------------------------------------------------------------
# The set, in order
# --------------------------------------------------------------------------

BUILDERS = (income_floor, funded_ratio, longevity, tax_position,
            healthcare, survivor, liquidity_and_debt, legacy)
