"""
The one place the app's planning assumptions are set, explained and checked.

Every projection in the app leans on the same handful of rates -- what a
portfolio earns above inflation, what rate values a guaranteed income stream,
how long to plan for -- and for a while each page asked for its own copy of
each. The numbers themselves live on `Household.assumptions`
(engine/profile.py, the `Assumptions` dataclass). This module is everything
around them: what each one means, what it does NOT mean, a defensible default
and range, three coherent presets, the tax scenarios in a form the Roth engine
can consume, converters for people who think in nominal terms, and a sanity
check that says when the set does not hang together.

REAL, NOT NOMINAL. The app works in today's dollars. Military retired pay, VA
compensation, SBP and Social Security are all indexed to prices, so in real
terms they are level streams, and they are valued with a REAL discount rate --
the return you could earn ABOVE inflation. Discounting a COLA'd stream at a
nominal rate counts inflation twice and understates a pension by a third or
more. `real_to_nominal` and `nominal_to_real` exist for the conversion at the
edge of the app; nothing inside it is nominal.

Units: every rate on `Assumptions` is in PERCENT (4.0 means 4%), and so is
every rate in this module. Engines take decimals; `as_decimals` bridges.
"""

from __future__ import annotations
from dataclasses import dataclass, fields
from typing import Sequence

from engine.profile import Assumptions, SYS_REDUX, SYS_NONE
from engine.tax import federal as F
from engine.tax import tables as T

# Severities, matching ui.panel.SEV_ICON.
SEV_GOOD, SEV_INFO, SEV_WARN, SEV_BAD = "good", "info", "warn", "bad"

# The three tax futures, as stored on Assumptions.tax_scenario.
TAX_CURRENT = "Current law"
TAX_SUNSET = "TCJA sunset"
TAX_HIGHER = "Higher"
TAX_SCENARIOS = [TAX_CURRENT, TAX_SUNSET, TAX_HIGHER]

# The "Higher" stress test adds this many points to every marginal rate.
HIGHER_POINTS = 5.0

# Above this a real return is assuming better than the all-stock record.
AGGRESSIVE_REAL_RETURN = 6.0
# Above this a real discount rate prices a government pension like a stock.
HIGH_DISCOUNT_RATE = 5.0

# Every field of Assumptions, in the order the page shows them. Introspected
# so a field added to the dataclass shows up here -- and fails the test that
# says every field has an explanation.
FIELDS = tuple(f.name for f in fields(Assumptions))

# Page titles, spelled as the sidebar spells them in Military_Finance.py, so
# the "which pages this moves" table reads the way the menu does.
PAGE_WORTH = "Accounts"
PAGE_TWENTY = "Pension"
PAGE_SURVIVOR = "Survivor Benefits"
PAGE_MEDICAL = "Medical Separation"
PAGE_CAREER = "Career"
PAGE_TSP = "Deployment"
PAGE_HOME_STATE = "Residency & GI Bill"
PAGE_ROTH = "Roth Conversions"
PAGE_THIS = "Assumptions"


# ==========================================================================
# Explanations
# ==========================================================================

@dataclass(frozen=True)
class Explanation:
    """Plain language for one assumption. Text, not numbers -- see `pages`."""
    field: str
    question: str            # the label the page uses; a prompt, not a noun
    unit: str
    what: str                # what it is
    what_not: str            # what it is NOT
    default: object
    reasoning: str           # why that default and that range
    hint: str                # one sentence for a widget's help text
    low: object = None       # inclusive bounds of the reasonable range
    high: object = None
    choices: tuple = ()      # for a categorical field, instead of low/high
    # (page title, how that page gets the number today)
    pages: tuple = ()

    def in_range(self, value) -> bool:
        if self.choices:
            return value in self.choices
        if isinstance(self.default, bool):
            return isinstance(value, bool)
        return self.low <= value <= self.high

    @property
    def default_text(self) -> str:
        return _fmt_value(self.field, self.default)

    @property
    def range_text(self) -> str:
        if self.choices:
            return " / ".join(self.choices)
        if isinstance(self.default, bool):
            return "yes for Final Pay, High-3 and BRS; no for CSB/REDUX"
        return f"{_fmt_value(self.field, self.low)} to {_fmt_value(self.field, self.high)}"


def _fmt_value(name: str, value) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, str):
        return value
    if name == "planning_margin_years":
        v = int(value)
        return f"{v} year{'' if abs(v) == 1 else 's'}"
    return f"{float(value):g}%"


_EXPLANATIONS = {
    "inflation_pct": Explanation(
        field="inflation_pct",
        question="Assume inflation of (%)",
        unit="% per year",
        what=("The rate prices rise. Inside this app it does one job of its "
              "own: it turns the real rates on this page into the nominal "
              "figures you see quoted elsewhere, and back again. The "
              "projections run in today's dollars, so inflation is already "
              "netted out of every stream that is indexed to it -- retired "
              "pay, VA compensation, SBP, Social Security."),
        what_not=("Not a return, and not something to add to a real rate by "
                  "hand: the arithmetic is (1 + real) x (1 + inflation) - 1, "
                  "not real + inflation. Not the military pay raise either -- "
                  "raises track the Employment Cost Index, a wage measure, "
                  "not the CPI. And not a lever on any pension value: those "
                  "are COLA'd, so they do not move when this does."),
        default=2.5, low=0.0, high=6.0,
        reasoning=("The Federal Reserve targets 2%. The long-run US average "
                   "is nearer 3%, and 2021-23 ran well above it. 2.5% splits "
                   "those. Past 6% sustained is a different economy, and a "
                   "plan kept in real terms is the right place to be if it "
                   "arrives."),
        hint=("Only used to convert between real and nominal figures and to "
              "erode tax thresholds Congress does not index. Pension values "
              "do not move with it."),
        pages=((PAGE_THIS, "the nominal equivalents shown on the right"),
               (PAGE_ROTH, "deflates the unindexed Social Security and NIIT "
                           "thresholds; the Roth profile carries its own "
                           "inflation field today")),
    ),
    "real_return_pct": Explanation(
        field="real_return_pct",
        question="Assume a real return of (%)",
        unit="% per year, above inflation",
        what=("What your invested money earns above inflation, per year, "
              "averaged over decades, after fees. A balanced TSP mix has "
              "historically earned around 4% real; the C Fund on its own "
              "nearer 6.5-7% real, with drawdowns of half along the way."),
        what_not=("Not the nominal figure on a fund factsheet -- take "
                  "inflation out properly, (1 + nominal) / (1 + inflation) - "
                  "1. Not the return of a good decade. Not a promise: the "
                  "projections apply it every year in a straight line, which "
                  "no market has ever done, so treat what they produce as a "
                  "central estimate, not a floor. And not the discount rate: "
                  "this is what risky money might earn; that is what safe "
                  "money does earn."),
        default=4.0, low=0.0, high=7.0,
        reasoning=("4% real is what a stock-and-bond portfolio has delivered "
                   "over most long windows in the US, and roughly what the "
                   "TSP's lifecycle funds are built around. 3% assumes bonds "
                   "do more of the work or fees bite; 5% assumes a heavy "
                   "stock tilt held through every crash. Past 6% you are "
                   "assuming the all-stock record repeats without its bad "
                   "decades; past 7% there is no history to point to."),
        hint=("Above inflation, after fees, averaged over decades. 4% is a "
              "balanced portfolio; 6% is the all-stock record with no bad "
              "luck."),
        pages=((PAGE_TWENTY, "the lump-sum verdict compares the break-even "
                             "against fixed 3% and 5% lines; it should compare "
                             "against this"),
               (PAGE_TSP, "not consumed yet -- the page does not project "
                          "growth"),
               (PAGE_ROTH, "carries its own real_return_* fields "
                           "(engine/roth_profile.py)")),
    ),
    "real_discount_rate_pct": Explanation(
        field="real_discount_rate_pct",
        question="Assume a real discount rate of (%)",
        unit="% per year, above inflation",
        what=("The rate that turns a guaranteed, inflation-indexed income "
              "stream -- your pension, VA compensation, SBP -- into a single "
              "present value. It is the return you could earn above "
              "inflation on money you could rely on the same way: the yield "
              "on inflation-protected Treasuries, or what a conservative "
              "portfolio earns above inflation. A lower rate makes the "
              "pension worth more; a higher one makes it worth less."),
        what_not=("NOT inflation. People reasonably assume it is, and it is "
                  "the most common error in valuing military retired pay. "
                  "The app works in today's dollars and the streams it values "
                  "are COLA'd, so they are level in real terms; discounting a "
                  "level real stream at a nominal rate (say 6.5%) counts "
                  "inflation twice and cuts a 40-year pension's value by "
                  "roughly a third. Also NOT your expected portfolio return: "
                  "a pension is not a stock, and pricing it as one is how a "
                  "lump-sum buyout at DoD's 6.46% comes to look fair."),
        default=3.0, low=0.0, high=5.0,
        reasoning=("Long inflation-protected Treasuries have yielded about "
                   "1.5-2.5% real in recent years; a conservative bond-heavy "
                   "portfolio has earned 2-3% above inflation over long "
                   "windows. 3% sits in the middle and matches the default "
                   "every page has used. 2.5% is the conservative case -- a "
                   "pension is worth more when safe returns are scarce; 3.5% "
                   "leans toward the portfolio side. Above 5% you are "
                   "treating a government-backed, longevity-hedged, indexed "
                   "stream as if it carried equity risk."),
        hint=("NOT inflation. The return you could earn above inflation on "
              "safe money -- about 3%. Higher makes every pension worth "
              "less."),
        pages=((PAGE_WORTH, "own input, widget key 'disc', default 3%"),
               (PAGE_TWENTY, "own input, widget key 'rdisc', default 3%"),
               (PAGE_SURVIVOR, "engine default of 3% (engine/benefits/sbp.py); "
                               "not exposed on the page"),
               (PAGE_MEDICAL, "engine default of 3% (disability_separation.py "
                              "and life_insurance.py); not exposed on the "
                              "page")),
    ),
    "pay_raise_real_pct": Explanation(
        field="pay_raise_real_pct",
        question="Assume pay raises beat inflation by (%)",
        unit="% per year, above inflation",
        what=("How much the annual across-the-board military pay raise runs "
              "above inflation, on average. Zero means raises track prices "
              "and basic pay is flat in real terms. The raises that come "
              "from promotion and longevity steps are modelled separately "
              "from the pay table, and they are far larger than this."),
        what_not=("Not the headline raise (3.8% for 2026 -- that is nominal). "
                  "Not promotion or time-in-service increases, which the "
                  "career page takes from the pay table. And not a BAH or "
                  "BAS assumption: those are set from market rents and the "
                  "USDA food index and are not projected at all."),
        default=0.0, low=-1.0, high=1.0,
        reasoning=("By law the raise defaults to the Employment Cost Index, "
                   "which has tracked the CPI closely over long periods -- "
                   "hence zero. The 2023-26 raises ran a little above "
                   "inflation and the 2014-16 raises ran below it, and "
                   "neither lasted. Half a point either way, sustained, is "
                   "the reasonable band; beyond a point you are forecasting "
                   "a change in the law, not in pay."),
        hint=("Zero means raises track inflation. Promotions and longevity "
              "steps are modelled separately and matter far more."),
        pages=((PAGE_CAREER, "the projection has an annual_raise parameter "
                             "(engine/career/timeline.py) that the page leaves "
                             "at zero"),),
    ),
    "cola_full": Explanation(
        field="cola_full",
        question="Does your retired pay get the full COLA?",
        unit="yes or no",
        what=("Whether retired pay keeps pace with the CPI in full. Final "
              "Pay, High-3 and BRS all pay the full COLA. CSB/REDUX pays CPI "
              "minus one point until age 62, when the pension is recomputed "
              "to what High-3 would have paid and the reduced COLA resumes."),
        what_not=("Not a forecast and not a choice. It is a fact of your "
                  "retirement system, which your DIEMS date and the CSB "
                  "election decided. Switching it off for a full-COLA member "
                  "is a stress test, not a scenario; switching it on for a "
                  "REDUX member overstates the pension by a real point a "
                  "year, compounded for decades."),
        default=True,
        reasoning=("Set from your system. The retirement page derives the "
                   "COLA drift from the system itself; this flag is the "
                   "plan-wide statement of the same fact, and the sanity "
                   "check below says when the two disagree."),
        hint=("Yes for Final Pay, High-3 and BRS. No for CSB/REDUX, which "
              "pays CPI minus one point until 62."),
        pages=((PAGE_TWENTY, "derived from your retirement system, not read "
                             "from this flag"),
               (PAGE_WORTH, "streams are valued as level real annuities; a "
                            "CPI-minus-1 stream should be shaved"),
               (PAGE_SURVIVOR, "SBP itself is always full COLA; a REDUX "
                               "member's own retired pay is not")),
    ),
    "tax_scenario": Explanation(
        field="tax_scenario",
        question="Which tax future should we plan for?",
        unit="scenario",
        what=("Which federal rate schedule the long-range tax comparisons -- "
              "Roth conversion, traditional versus Roth, the taxable share "
              "of retired pay -- assume for the years beyond the next few. "
              "Current law is the 2026 schedule, made permanent in 2025. "
              "TCJA sunset puts the 2017 rates and brackets back. Higher "
              f"adds {HIGHER_POINTS:g} points to every rate as a stress test."),
        what_not=("Not a prediction; nobody has one. Not your bracket today, "
                  "which comes from your actual income and is what the TSP "
                  "page asks for. And not state tax, which follows your "
                  "state of legal residence, not this."),
        default=TAX_CURRENT, choices=tuple(TAX_SCENARIOS),
        reasoning=("Current law is the only scenario with a statute behind "
                   "it. The sunset case matters because it is the direction "
                   "the last big change came from, and because a Roth "
                   "decision is a bet on future rates: if it only pays under "
                   "current law, it is fragile. Higher exists to find out how "
                   "much of a plan survives a five-point rise. It is not a "
                   "forecast."),
        hint=("Current law is the 2026 schedule. TCJA sunset is the 2017 "
              "schedule returning. Higher is a stress test, five points on "
              "every rate."),
        pages=((PAGE_ROTH, "maps onto engine/tax/federal.TaxPolicy through "
                           "tax_scenarios[name].to_tax_policy()"),
               (PAGE_TSP, "asks for your bracket now and in retirement as "
                          "flat rates, widget keys 'marg' and 'expmarg'"),
               (PAGE_SURVIVOR, "asks for flat marginal rates, widget keys "
                               "'myrate', 'sprate' and 'crrate'")),
    ),
    "planning_margin_years": Explanation(
        field="planning_margin_years",
        question="Plan how many years past the median lifespan?",
        unit="years",
        what=("How far past your actuarial life expectancy the plan runs. "
              "Life expectancy is a median: half of people outlive it. A "
              "pension, SBP and a withdrawal plan all have to last as long "
              "as you do, so anything that insures against a long life is "
              "planned to the median plus this margin."),
        what_not=("Not a prediction of your own lifespan, and not a health "
                  "question. It is a margin of safety, in the same sense as "
                  "the fund you keep for a job loss. Not extra years for your "
                  "survivor either -- the SBP page asks about them "
                  "separately."),
        default=5, low=0, high=15,
        reasoning=("Five years takes you from the median to roughly the 80th "
                   "percentile of remaining lifetime at retirement ages, "
                   "which is a common planning convention. Zero plans to the "
                   "coin flip. Ten covers most of the distribution. Beyond "
                   "fifteen you are planning for a centenarian, which is fine "
                   "if that is your family history but costs you spending "
                   "today. Below zero is planning to die early, and the "
                   "sanity check says so."),
        hint=("Half of people outlive the median. Five years takes you to "
              "roughly the 80th percentile."),
        pages=((PAGE_WORTH, "asks how long you expect to live, widget key "
                            "'lifeexp', defaulting to the median with no "
                            "margin"),
               (PAGE_TWENTY, "same question, widget key 'life'"),
               (PAGE_SURVIVOR, "same question for you and your survivor, "
                               "widget keys 'mylife' and 'splife'"),
               (PAGE_MEDICAL, "same question, widget key 'dslife'"),
               (PAGE_HOME_STATE, "asks how many years you will draw retired "
                                 "pay, widget key 'retyrs', fixed at 30")),
    ),
}


def explain(name: str) -> Explanation:
    """The explanation for one field of Assumptions, by field name."""
    try:
        return _EXPLANATIONS[name]
    except KeyError:
        raise KeyError(f"no explanation for assumption {name!r}; known: "
                       f"{', '.join(_EXPLANATIONS)}") from None


def explain_all() -> list[Explanation]:
    """Every explanation, in dataclass field order."""
    return [explain(n) for n in FIELDS]


def pages_moved() -> list[dict]:
    """One row per (assumption, page): what moves, and how it gets there today."""
    rows = []
    for e in explain_all():
        for page, how in e.pages:
            rows.append({"Assumption": e.question, "Page": page,
                         "How the page gets it today": how})
    return rows


# ==========================================================================
# Presets
# ==========================================================================

@dataclass(frozen=True)
class Preset:
    name: str
    rationale: str
    values: dict


# Presets never touch cola_full. It is a fact about the member's retirement
# system, not an outlook, and a preset that flipped it would be wrong for
# everyone on one side of the 1986 DIEMS line.
presets = {
    "Conservative": Preset(
        "Conservative",
        "Bonds do more of the work, safe yields stay low so the pension is "
        "worth more, raises lag prices a little, rates go back to 2017 and "
        "you plan well past the median -- the set to test whether a plan "
        "still works when the tailwinds stop.",
        {"real_return_pct": 3.0, "real_discount_rate_pct": 2.5,
         "inflation_pct": 3.0, "pay_raise_real_pct": -0.5,
         "tax_scenario": TAX_SUNSET, "planning_margin_years": 8}),
    "Baseline": Preset(
        "Baseline",
        "The long-run averages: a balanced portfolio's 4% real, safe money's "
        "3% real, raises that track inflation, the tax law on the books and "
        "five years past the median -- the defaults every page has used.",
        {"real_return_pct": 4.0, "real_discount_rate_pct": 3.0,
         "inflation_pct": 2.5, "pay_raise_real_pct": 0.0,
         "tax_scenario": TAX_CURRENT, "planning_margin_years": 5}),
    "Optimistic": Preset(
        "Optimistic",
        "A stock-heavy portfolio held through every crash, safe yields a "
        "little higher, raises that keep beating inflation and current law "
        "holding -- defensible, but nothing in it is allowed to go wrong.",
        {"real_return_pct": 5.0, "real_discount_rate_pct": 3.5,
         "inflation_pct": 2.0, "pay_raise_real_pct": 0.5,
         "tax_scenario": TAX_CURRENT, "planning_margin_years": 3}),
}
PRESET_NAMES = list(presets)


def apply_preset(a: Assumptions, name: str) -> list[str]:
    """Write a preset onto `a` in place. Returns the fields that changed."""
    p = presets[name]
    changed = []
    for k, v in p.values.items():
        if not _same(getattr(a, k), v):
            setattr(a, k, v)
            changed.append(k)
    return changed


def matching_preset(a: Assumptions) -> str | None:
    """The preset `a` currently equals on every field a preset sets, or None."""
    for name, p in presets.items():
        if all(_same(getattr(a, k), v) for k, v in p.values.items()):
            return name
    return None


def _same(x, y) -> bool:
    if isinstance(x, (int, float)) and isinstance(y, (int, float)) \
       and not isinstance(x, bool) and not isinstance(y, bool):
        return abs(float(x) - float(y)) < 1e-9
    return x == y


# ==========================================================================
# Real <-> nominal
# ==========================================================================

def real_to_nominal(rate_real_pct: float, inflation_pct: float) -> float:
    """
    (1 + real)(1 + inflation) - 1, in percent.

    4% real at 2.5% inflation is 6.6% nominal, not 6.5%. The tenth of a point
    is small; the habit of adding the two is what leads people to subtract
    them, and subtracting is how a 6.5% "safe" nominal rate ends up applied
    to a COLA'd pension.
    """
    r = rate_real_pct / 100.0
    i = inflation_pct / 100.0
    return ((1.0 + r) * (1.0 + i) - 1.0) * 100.0


def nominal_to_real(rate_nominal_pct: float, inflation_pct: float) -> float:
    """(1 + nominal) / (1 + inflation) - 1, in percent. Inverse of real_to_nominal."""
    n = rate_nominal_pct / 100.0
    i = inflation_pct / 100.0
    return ((1.0 + n) / (1.0 + i) - 1.0) * 100.0


# Fields that are real rates and so have a nominal equivalent.
REAL_RATE_FIELDS = ("real_return_pct", "real_discount_rate_pct",
                    "pay_raise_real_pct")


def nominal_equivalent(name: str, a: Assumptions) -> float | None:
    """The nominal figure a real-rate field implies at `a`'s inflation, or None."""
    if name not in REAL_RATE_FIELDS:
        return None
    return real_to_nominal(float(getattr(a, name)), a.inflation_pct)


def as_decimals(a: Assumptions) -> dict:
    """The rates as decimals, the way the engines take them."""
    return {"inflation": a.inflation_pct / 100.0,
            "real_return": a.real_return_pct / 100.0,
            "real_discount_rate": a.real_discount_rate_pct / 100.0,
            "pay_raise_real": a.pay_raise_real_pct / 100.0}


# ==========================================================================
# Tax scenarios
# ==========================================================================

@dataclass(frozen=True)
class TaxScenario:
    """One tax future, as a bracket table and as the TaxPolicy the Roth engine takes."""
    name: str
    federal_scenario: str        # engine.tax.federal.SCENARIO_* constant
    points_added: float          # uniform shift of every marginal rate, in points
    brackets: dict               # {MFJ: [(upper, rate), ...], SINGLE: [...]}, 2026 $
    standard_deduction: dict     # {MFJ: $, SINGLE: $}
    personal_exemption: float    # per person; zero under current law
    summary: str
    note: str
    verify: bool = False         # the dollar lines have not been checked
    stress_test: bool = False    # not a forecast

    def marginal_rate(self, taxable: float, status: str = T.MFJ) -> float:
        return F.marginal_rate(taxable, self.brackets[status])

    def rate_multiplier(self, taxable: float, status: str = T.MFJ) -> float:
        """Marginal rate under this scenario over the current-law rate at the same income."""
        base = F.marginal_rate(taxable, T.FEDERAL_BRACKETS_2026[status])
        return self.marginal_rate(taxable, status) / base if base else 1.0

    def to_tax_policy(self, change_year: int | None = None) -> F.TaxPolicy:
        """
        The engine's TaxPolicy for this scenario.

        `change_year` is when the change lands; the engine's default is kept
        unless you say otherwise, and it is ignored under current law.
        """
        kw = dict(scenario=self.federal_scenario,
                  surcharge_points=self.points_added)
        if change_year is not None:
            kw["change_year"] = change_year
        return F.TaxPolicy(**kw)


def _shift_rates(brackets: Sequence[tuple], points: float) -> list[tuple]:
    p = points / 100.0
    return [(bound, min(0.99, rate + p)) for bound, rate in brackets]


def _upto(x: float) -> str:
    return "and above" if x == float("inf") else f"up to ${x:,.0f}"


def describe_table(brackets: dict, standard_deduction: dict,
                   personal_exemption: float) -> str:
    """The rate table as one sentence per filing status, for a note."""
    parts = []
    for status in (T.MFJ, T.SINGLE):
        bands = "; ".join(f"{rate * 100:g}% {_upto(bound)}"
                          for bound, rate in brackets[status])
        parts.append(f"{status}: {bands}")
    parts.append("Standard deduction "
                 + ", ".join(f"${standard_deduction[s]:,.0f} {s}"
                             for s in (T.MFJ, T.SINGLE))
                 + (f"; personal exemption ${personal_exemption:,.0f} a person"
                    if personal_exemption else "; no personal exemption")
                 + ".")
    return " ".join(parts)


tax_scenarios = {
    TAX_CURRENT: TaxScenario(
        name=TAX_CURRENT,
        federal_scenario=F.SCENARIO_CURRENT,
        points_added=0.0,
        brackets=T.FEDERAL_BRACKETS_2026,
        standard_deduction=T.STANDARD_DEDUCTION_2026,
        personal_exemption=0.0,
        summary=("The 2026 schedule -- 10/12/22/24/32/35/37% -- as made "
                 "permanent by the One Big Beautiful Bill Act of July 2025, "
                 "with the brackets indexed to inflation so they are flat in "
                 "real terms."),
        note=T.TABLE_VINTAGE_NOTE,
    ),
    TAX_SUNSET: TaxScenario(
        name=TAX_SUNSET,
        federal_scenario=F.SCENARIO_PRE_TCJA,
        points_added=0.0,
        brackets=T.PRE_TCJA_BRACKETS_2026,
        standard_deduction=T.PRE_TCJA_STANDARD_DEDUCTION,
        personal_exemption=T.PRE_TCJA_PERSONAL_EXEMPTION,
        verify=True,
        summary=("A future Congress puts the 2017 schedule back: rates of "
                 "10/15/25/28/33/35/39.6%, the 2017 bracket boundaries "
                 "restated in 2026 dollars (about 1.29x), a standard "
                 "deduction of roughly half today's, and a personal "
                 "exemption of about $5,400 a person. Middle incomes pay two "
                 "to three points more at the margin, which is what makes a "
                 "Roth decision that only works under current law fragile."),
        note=("VERIFY. The table is engine/tax/tables.py "
              "PRE_TCJA_BRACKETS_2026: the 2017 marginal rates paired with "
              "the 2017 boundaries inflated to 2026 purchasing power, and "
              "the pre-TCJA standard deduction and personal exemption "
              "likewise restated. The shape is right -- rates rise across "
              "the middle brackets, the standard deduction roughly halves, "
              "exemptions return -- but the dollar lines were restated "
              "without access to the 2017 revenue procedure and have not "
              "been checked against it. Assumed: "
              + describe_table(T.PRE_TCJA_BRACKETS_2026,
                               T.PRE_TCJA_STANDARD_DEDUCTION,
                               T.PRE_TCJA_PERSONAL_EXEMPTION)),
    ),
    TAX_HIGHER: TaxScenario(
        name=TAX_HIGHER,
        federal_scenario=F.SCENARIO_SURCHARGE,
        points_added=HIGHER_POINTS,
        brackets={s: _shift_rates(b, HIGHER_POINTS)
                  for s, b in T.FEDERAL_BRACKETS_2026.items()},
        standard_deduction=T.STANDARD_DEDUCTION_2026,
        personal_exemption=0.0,
        stress_test=True,
        summary=(f"A stress test, not a forecast: every marginal rate "
                 f"{HIGHER_POINTS:g} points above current law, so the 12% "
                 f"bracket becomes {12 + HIGHER_POINTS:g}%, the 22% bracket "
                 f"{22 + HIGHER_POINTS:g}% and the top rate "
                 f"{37 + HIGHER_POINTS:g}%, on today's bracket boundaries and "
                 f"deductions."),
        note=("This is a stress test. No bill proposes a uniform five-point "
              "rise; the point is to see how much of a Roth or conversion "
              "decision survives one. A plan that only works under current "
              "law is a bet; one that still works here is a plan."),
    ),
}


def tax_scenario_for(a: Assumptions) -> TaxScenario:
    """The scenario `a` names, falling back to current law for an unknown name."""
    return tax_scenarios.get(a.tax_scenario, tax_scenarios[TAX_CURRENT])


def bracket_rows(sc: TaxScenario) -> list[dict]:
    """The scenario's table as rows for a dataframe, one per band."""
    rows = []
    for (mb, mr), (sb, sr) in zip(sc.brackets[T.MFJ], sc.brackets[T.SINGLE]):
        rows.append({
            "Marginal rate": f"{mr * 100:g}%" if mr == sr
                             else f"{mr * 100:g}% / {sr * 100:g}%",
            "Married filing jointly, taxable income": _upto(mb),
            "Single, taxable income": _upto(sb),
        })
    return rows


# ==========================================================================
# Sanity
# ==========================================================================

def sanity(a: Assumptions, retirement_system: str = "") -> list[tuple[str, str, str]]:
    """
    (severity, headline, detail) for everything about `a` that does not hang
    together. Empty means nothing to flag. Pass the member's retirement
    system (engine/profile.py ServiceMember.retirement_system) to check the
    COLA flag against it.
    """
    out = []
    r, d, i = a.real_return_pct, a.real_discount_rate_pct, a.inflation_pct
    p, margin = a.pay_raise_real_pct, a.planning_margin_years

    # --- COLA against the retirement system --------------------------------
    if retirement_system == SYS_REDUX and a.cola_full:
        out.append((SEV_BAD, "CSB/REDUX does not get the full COLA",
                    "Your retirement system pays CPI minus one point until the "
                    "recomputation at 62. With the full COLA switched on, every "
                    "pension value in the app is overstated by a real point a "
                    "year, compounding for decades. Switch it off."))
    elif retirement_system not in ("", SYS_NONE, SYS_REDUX) and not a.cola_full:
        out.append((SEV_WARN, "Only CSB/REDUX loses a point of COLA",
                    f"{retirement_system} pays the full CPI adjustment. With "
                    f"the full COLA switched off your pension is understated. "
                    f"Switch it back on unless you are deliberately "
                    f"stress-testing a COLA cut."))

    # --- return against discount rate --------------------------------------
    if r < d:
        out.append((SEV_WARN, "You expect the portfolio to earn less than the "
                              "rate you discount guaranteed income at",
                    f"The discount rate ({d:g}%) is meant to be the return on "
                    f"the safe alternative; the real return ({r:g}%) is what "
                    f"risky money might earn. A return below the discount rate "
                    f"says stocks are a worse deal than the pension's safe "
                    f"yield -- possible for a year, odd as a decades-long "
                    f"assumption. Raise the return or lower the discount rate "
                    f"so each means what it is supposed to."))
    if r > AGGRESSIVE_REAL_RETURN:
        out.append((SEV_WARN, f"A real return of {r:g}% is aggressive",
                    f"{AGGRESSIVE_REAL_RETURN:g}% real is about what an all-"
                    f"stock US portfolio has averaged over a century, with no "
                    f"fees and no bad luck, and the projections apply it every "
                    f"year in a straight line. Planning on more than history's "
                    f"best broad result leaves nothing for the decade that goes "
                    f"wrong. Four is a balanced default."))
    if r < 0:
        out.append((SEV_WARN, "A negative real return is a guaranteed loss of "
                              "purchasing power",
                    "That is what cash under the mattress does. If you hold "
                    "cash, say so on the balance sheet -- a plan-wide negative "
                    "return means never investing, which is a different plan."))

    # --- discount rate on its own ------------------------------------------
    if d > HIGH_DISCOUNT_RATE:
        out.append((SEV_WARN, f"A real discount rate of {d:g}% prices your "
                              f"pension like a stock",
                    "Guaranteed, inflation-indexed, government-backed income is "
                    "the safest asset you own. Discounting it above what safe "
                    "money earns understates it, and is precisely the "
                    "arithmetic that makes a lump-sum buyout look fair. Three "
                    f"is the default; {HIGH_DISCOUNT_RATE:g} is the top of the "
                    "reasonable range. If you meant a nominal rate, take "
                    "inflation out first."))
    if d < 0:
        out.append((SEV_BAD, "A negative real discount rate has no meaning here",
                    "It would say a dollar of pension next year is worth more "
                    "than a dollar today. Use zero for an undiscounted total, "
                    "or a small positive rate."))
    elif d == 0:
        out.append((SEV_INFO, "At 0% you are adding the pension up, not "
                              "valuing it",
                    "Every future dollar counts the same as one today. Fine "
                    "for a total; not a basis for comparing the pension "
                    "against a lump sum or a portfolio."))

    # --- inflation and raises ----------------------------------------------
    if i < 0:
        out.append((SEV_BAD, "Negative inflation is not a planning case",
                    "Sustained deflation has not happened in the US since the "
                    "1930s. Use zero if you want the nominal and real figures "
                    "to coincide."))
    elif i > 6:
        out.append((SEV_WARN, f"{i:g}% inflation, sustained, is a different "
                              f"economy",
                    "It only changes the nominal equivalents and the erosion "
                    "of unindexed tax thresholds here, but check you did not "
                    "mean a one-year figure."))
    if abs(p) > 1.0:
        out.append((SEV_WARN, f"Pay raises {abs(p):g} points {'above' if p > 0 else 'below'} "
                              f"inflation, every year, is a forecast of the law",
                    "Raises default to the Employment Cost Index and have "
                    "tracked prices over long periods. A sustained gap of more "
                    "than a point either way has not happened in the modern "
                    "pay system."))

    # --- planning margin ---------------------------------------------------
    if margin < 0:
        out.append((SEV_BAD, "You are planning to die before the median",
                    "Half of people outlive their life expectancy; a plan that "
                    "ends before it fails more often than not. A margin below "
                    "zero shortens every pension, SBP and insurance "
                    "calculation. Set it to zero at the very least."))
    elif margin > 15:
        out.append((SEV_INFO, f"{margin} years past the median plans for a "
                              f"centenarian",
                    "Reasonable if that is your family history. It costs "
                    "spending today, because everything has to last longer."))

    # --- tax scenario ------------------------------------------------------
    if a.tax_scenario not in TAX_SCENARIOS:
        out.append((SEV_BAD, f"Unknown tax scenario {a.tax_scenario!r}",
                    "Pick one of: " + ", ".join(TAX_SCENARIOS) + "."))
    elif a.tax_scenario == TAX_HIGHER:
        out.append((SEV_INFO, "Higher is a stress test, not a forecast",
                    f"Every marginal rate is {HIGHER_POINTS:g} points above "
                    f"current law. Use it to see what survives, then plan on "
                    f"current law or the sunset case."))
    return out
