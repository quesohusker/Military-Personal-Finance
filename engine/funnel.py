"""
The funnel: one question that settles what the app asks and what it scores.

`docs/ARCHITECTURE.md` §2 gives the axis. It is not demographics -- it is HOW
MUCH OF THE FUTURE IS STILL A DECISION. Someone in uniform can still choose to
stay to 20 or leave at 12; a retiree drawing a pension cannot. Three funnels of
questions, three scorecard framings, one projection spine underneath.

Two things this module is NOT:

  * IT IS NOT A PERMISSIONS SYSTEM (§2, "What the funnel must not do"). Every
    page stays reachable from every funnel. A serving member deciding whether
    to stay to 20 needs the retiree pages to make that decision. The funnel
    sets defaults, ordering and what gets scored -- nothing here hides a page.

  * IT IS NOT A SECOND STATUS FIELD. `ServiceMember.component` remains the
    thing the app's ~30 existing status gates read (§4a), and those gates are
    not being rewritten. `set_funnel()` keeps `component` consistent with the
    chosen funnel so that every one of them behaves without being touched.

Storage: `Household.funnel` holds the key. It round-trips through
`engine/storage.py` for free, because `Household.to_dict()` is `asdict()` and
`_build()` skips keys a file does not carry -- so a plan saved before this
module existed loads with `funnel == FUNNEL_UNSET` and is then resolved by
`funnel_of()`. There is NO versioned migration in this codebase (the
`schema_version` field on Household is written and never read), so none is
added here; tolerating a missing key is the whole mechanism.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Sequence

from engine import mortality as MORT
from engine.profile import (Household, ServiceMember, ACTIVE, RETIRED,
                            VETERAN, CIVILIAN, SERVING)

# --------------------------------------------------------------------------
# The three funnels, and the fourth state
# --------------------------------------------------------------------------
# Stored on the plan as a slug rather than as a label, because the label is
# prose and prose gets rewritten. These strings are in saved plan files and
# must never change.
FUNNEL_SERVING = "serving"
FUNNEL_VETERAN = "veteran"
FUNNEL_RETIRED = "retiree"

# Not an answer. A blank plan and a plan whose owner has not been asked yet
# both read as this, and the landing page must be able to tell that apart from
# a deliberate choice -- which is why it is the empty string and is NOT a
# member of FUNNELS.
FUNNEL_UNSET = ""

#: The three funnels, in the order the landing page offers them.
FUNNELS: tuple[str, ...] = (FUNNEL_SERVING, FUNNEL_VETERAN, FUNNEL_RETIRED)


@dataclass(frozen=True)
class Funnel:
    """
    One funnel, as data. No behaviour: the landing page renders it, the intake
    page filters questions by `key`, and the scorecard reads `frame`.
    """
    key: str
    label: str                      # what the landing page button says
    description: str                # one line, second person, the app's voice
    implies: tuple[str, ...]        # what choosing this does, stated plainly
    default_component: str          # the ServiceMember.component it sets
    frame: str                      # what the scorecard measures for them


FUNNEL_SPECS: tuple[Funnel, ...] = (
    Funnel(
        key=FUNNEL_SERVING,
        label="Currently serving",
        description="You are in uniform now — Active, Guard or Reserve — and "
                    "most of what happens next is still a decision.",
        implies=(
            "Your component stays Active, Guard or Reserve, so every page that "
            "asks about pay, BAH, deployment and the TSP match stays switched on.",
            "Intake asks for your DIEMS date first, because it decides your "
            "retirement system and nothing else does.",
            "Your readiness is not one number. It is one per course of action — "
            "stay to 20, or leave at 12.",
        ),
        default_component=ACTIVE,
        frame="Compare courses of action.",
    ),
    Funnel(
        key=FUNNEL_VETERAN,
        label="Veteran, not retired from the military",
        description="You served and left without a military pension, so your "
                    "retirement is a civilian one built partly on what service "
                    "left you.",
        implies=(
            "Your component is set to Veteran (not retired).",
            "No military retired pay is assumed. VA compensation may be the "
            "only inflation-linked income you have.",
            "The scorecard scores a civilian problem with military assets — the "
            "case this app has historically said least about.",
        ),
        default_component=VETERAN,
        frame="Score a civilian problem with military assets.",
    ),
    Funnel(
        key=FUNNEL_RETIRED,
        label="Retired from the military",
        description="You draw military retired pay, or you are about to. The "
                    "big calls are made; what is left is sequencing.",
        implies=(
            "Your component is set to Military Retiree.",
            "A pension, SBP and TRICARE are assumed to be in play, and intake "
            "asks you for the figures.",
            "The scorecard scores sequencing — when to claim, how much to "
            "convert, and which account to draw first.",
        ),
        default_component=RETIRED,
        frame="Score sequencing.",
    ),
)

SPEC_BY_KEY: dict[str, Funnel] = {f.key: f for f in FUNNEL_SPECS}


def spec(key: str) -> Funnel | None:
    """The Funnel for a key, or None for FUNNEL_UNSET and anything unknown."""
    return SPEC_BY_KEY.get(key or "")


def label_for(key: str) -> str:
    """A display label for a key. Blank plans read as 'Not chosen yet'."""
    f = spec(key)
    return f.label if f else "Not chosen yet"


def is_chosen(key: str) -> bool:
    return key in SPEC_BY_KEY


# --------------------------------------------------------------------------
# Inference -- reading the funnel off a plan that already exists
# --------------------------------------------------------------------------
# Nobody who already has a plan gets sent back through intake to answer a
# question the plan can answer for them. This function is the tie-breaker the
# app has never had.
#
# THE DISAGREEMENT IT SETTLES. §4a of ARCHITECTURE.md counts 30+ status gates
# written independently, and they do not agree on what "retired" means:
#
#   1_Profile      component == RETIRED  OR retired_pay > 0 OR va_monthly > 0
#   9_Survivor     retired_pay_monthly > 0      (else "enter your retired pay")
#   16_Healthcare  component in (VETERAN, CIVILIAN)
#   19_Housing     m.is_serving
#
# The rules below are the app's single answer. Two principles decide every
# ambiguous case, and they are worth stating before the code:
#
#   A. SERVING WINS OVER EVERYTHING. The funnel axis is how much of the future
#      is still a decision. If you are in uniform it is, whatever else is on
#      the plan.
#   B. POSITIVE EVIDENCE BEATS A LABEL; ABSENT EVIDENCE DOES NOT. Retired pay
#      on the plan is proof of a pension and overrides a "Veteran" label. An
#      EMPTY retired-pay field is not proof of anything, so it never overrides
#      a "Military Retiree" label.
#
# Explicitly NOT used as evidence:
#
#   * VA compensation and VA rating. 1_Profile shows its retiree card when
#     va_disability_monthly > 0, which is right for that card and wrong for the
#     funnel: a rated veteran with no pension is squarely the Veteran funnel.
#     §4b makes the same point from the other end -- pension_as_bond() already
#     sums retired pay + VA + CRSC, so a rated veteran has a partial income
#     floor without being a retiree. VA decides healthcare, not the funnel.
#   * The DIEMS date and the retirement system. Everyone who ever served has
#     one; it says nothing about whether they are collecting.

def infer_funnel(h: Household) -> str:
    """
    Best funnel for a plan that predates the question, from what it carries.

    Always returns one of FUNNELS -- never FUNNEL_UNSET. "Has this been asked?"
    is `h.funnel == FUNNEL_UNSET`, and it is a different question from "which
    funnel does this plan look like?", which is this one.
    """
    m = h.member

    # A. Still in uniform: the future is still a decision. Unconditional -- a
    #    Guard member drawing a prior retirement, or someone who typed a figure
    #    into the retiree card while still serving, is still serving.
    if m.component in SERVING:
        return FUNNEL_SERVING

    # B. Retired pay on the plan is a pension, whatever the component says.
    #    This is the one case where the stored component loses.
    if float(m.retired_pay_monthly or 0.0) > 0:
        return FUNNEL_RETIRED

    # The label, where there is one. A Chapter 61 retiree whose pay is fully
    # VA-offset, and a retiree who simply has not typed the figure yet, both
    # land here -- and both are retirees. This is where we part company with
    # 9_Survivor's `retired_pay_monthly > 0` gate.
    if m.component == RETIRED:
        return FUNNEL_RETIRED

    # "Veteran (not retired)" says "not retired" in so many words. With no
    # retired pay to contradict it, take it at its word -- including for the
    # 20-year case below, which is why this test comes first.
    if m.component == VETERAN:
        return FUNNEL_VETERAN

    # CIVILIAN claims nothing either way, so service history is allowed to
    # speak. Twenty years is the retirement cliff: someone with 20 good years
    # and no pay showing is a grey-area Guard or Reserve retiree waiting on 60,
    # or a retiree who left the component field alone. Either way the retiree
    # questions are the ones worth asking them.
    if m.component == CIVILIAN and float(m.years_of_service or 0.0) >= 20.0:
        return FUNNEL_RETIRED

    # Everything else -- a civilian spouse's plan, a short-service veteran, a
    # blank-but-not-military plan. Veteran is the honest default: a civilian
    # problem, with whatever military assets exist. It asks the fewest
    # questions that do not apply.
    return FUNNEL_VETERAN


def funnel_of(h: Household) -> str:
    """
    The funnel to use RIGHT NOW. An answer beats an inference, always.

    This is what pages should call. `infer_funnel()` is only for the plan that
    has never been asked.
    """
    return h.funnel if is_chosen(h.funnel) else infer_funnel(h)


# --------------------------------------------------------------------------
# Setting it -- the integration point with the 30+ existing gates
# --------------------------------------------------------------------------

def set_funnel(h: Household, key: str) -> str:
    """
    Record the funnel and make `member.component` agree with it.

    This is the whole reason the funnel is safe to add to a 23-page app: the
    existing gates keep reading `component` and keep working, because choosing
    a funnel moves `component` underneath them. Nothing downstream learns a new
    field.

    What it will NOT do:

      * It never narrows a serving component. A Guard or Reserve member who
        picks "currently serving" stays Guard or Reserve; only a component
        outside SERVING is moved, and it is moved to Active Duty.
      * It never invents or erases money. Picking the retiree funnel does not
        fabricate a retired-pay figure, so a gate like 9_Survivor's
        `retired_pay_monthly > 0` still shows its "enter your retired pay"
        prompt until the user does. That is correct: the funnel decides which
        questions get asked, not what the answers are.
      * It does not mark the plan dirty or invalidate cached results. The
        engine layer holds no Streamlit state. The CALLING PAGE must call
        `mark_dirty()` and `invalidate()` from `ui.panel`, exactly as the
        `choice()` helper does.

    Passing FUNNEL_UNSET clears the answer and leaves `component` alone, so
    "start over" does not silently rewrite the plan. Returns the key stored.
    """
    if key != FUNNEL_UNSET and key not in SPEC_BY_KEY:
        raise ValueError(f"Not a funnel: {key!r}. Expected one of "
                         f"{FUNNELS} or FUNNEL_UNSET.")

    h.funnel = key
    if key == FUNNEL_UNSET:
        return key

    m = h.member
    if key == FUNNEL_SERVING:
        if m.component not in SERVING:
            m.component = ACTIVE
    else:
        m.component = SPEC_BY_KEY[key].default_component
    return key


def ensure_spouse(h: Household) -> ServiceMember | None:
    """
    Give a married household a spouse record to write into.

    Nothing in the app creates `Household.spouse` today -- every reader guards
    with `h.has_spouse and h.spouse`, and `benefits/healthcare.py` has a branch
    for the married-but-absent case. Intake asks spouse questions, so it needs
    somewhere to put the answers. Idempotent; returns None when not married.
    """
    if not h.has_spouse:
        return None
    if h.spouse is None:
        h.spouse = ServiceMember(component=CIVILIAN, birth_year=h.member.birth_year)
    return h.spouse


def prepare(h: Household) -> Household:
    """
    Normalise a household before a render pass, once, at the top of the page.

    Only one thing so far: a married household gets a spouse record, so the
    spouse questions have a target and `applies()` can stay a pure predicate.
    Call it before evaluating any `Question.applies`.
    """
    ensure_spouse(h)
    return h


# --------------------------------------------------------------------------
# Essential vs discretionary spending
# --------------------------------------------------------------------------
# Step 1 of the build order, and the income-floor component is meaningless
# without it. §8: users will understate it, so the question is phrased as what
# they could not cut rather than as a budget line.

#: Fallback share of total spending treated as essential when the user has not
#: answered. Deliberately high: an understated floor makes the scorecard
#: flatter someone, which is the failure mode that matters. Any rating built on
#: this must say it is an assumption, not an answer -- ask `has_essential_split`.
DEFAULT_ESSENTIAL_SHARE = 0.75


def has_essential_split(h: Household) -> bool:
    """True when the user actually answered the essential-spending question."""
    return float(getattr(h, "essential_monthly_expenses", 0.0) or 0.0) > 0


def essential_monthly(h: Household) -> float:
    """
    Monthly spending that could not be cut, falling back sensibly.

    Order: the answer if there is one; otherwise a share of total spending;
    otherwise zero, because nothing has been entered and a guess on top of a
    guess is worse than a blank.

    The answer is clamped to total spending. An essential figure above the
    total is a contradiction, and letting it through produces a confident,
    wrong income-floor rating -- §8's exact warning. The clamp is visible:
    compare `essential_monthly(h)` with `h.essential_monthly_expenses` to
    detect it and tell the user.
    """
    answered = float(getattr(h, "essential_monthly_expenses", 0.0) or 0.0)
    total = float(h.monthly_expenses or 0.0)
    if answered > 0:
        return min(answered, total) if total > 0 else answered
    if total > 0:
        return total * DEFAULT_ESSENTIAL_SHARE
    return 0.0


def discretionary_monthly(h: Household) -> float:
    """Total spending less the essential floor. Never negative."""
    return max(0.0, float(h.monthly_expenses or 0.0) - essential_monthly(h))


# --------------------------------------------------------------------------
# The question spec
# --------------------------------------------------------------------------
# A Question is a rendering instruction, not a widget. It names a helper in
# ui.panel, the object to write into and the attribute on it; the intake page
# dispatches. Three funnel-specific modules add to the set, so the schema has
# to be complete enough that they never need to reach around it.

KIND_TEXT = "text"
KIND_INTEGER = "integer"
KIND_NUMBER = "number"
KIND_MONEY = "money"
KIND_PCT = "pct"
KIND_TOGGLE = "toggle"
KIND_CHOICE = "choice"

#: Every widget kind, each one exactly a helper in `ui.panel`. There are seven
#: and there will not be an eighth without changing the renderer too.
KINDS: tuple[str, ...] = (KIND_TEXT, KIND_INTEGER, KIND_NUMBER, KIND_MONEY,
                          KIND_PCT, KIND_TOGGLE, KIND_CHOICE)

# Which optional fields each helper actually accepts. The renderer does not
# need to know this -- `Question.widget_kwargs()` does -- but a mismatch here
# is a TypeError at render time, so it is kept next to the kinds it describes
# and checked by `validate()`.
_EXTRAS: dict[str, frozenset[str]] = {
    KIND_TEXT:    frozenset({"placeholder"}),
    KIND_INTEGER: frozenset({"min_value", "max_value", "step"}),
    KIND_NUMBER:  frozenset({"min_value", "max_value", "step", "fmt"}),
    KIND_MONEY:   frozenset({"min_value", "max_value", "step"}),
    KIND_PCT:     frozenset({"min_value", "max_value", "step", "decimals"}),
    KIND_TOGGLE:  frozenset(),
    KIND_CHOICE:  frozenset({"options", "format_func"}),
}


@dataclass(frozen=True)
class Question:
    """
    One question, as data a page can render without knowing what it is about.

        q = Question(key="by", label="What year were you born?",
                     kind=KIND_INTEGER, path="member", attr="birth_year",
                     group="About you", order=10,
                     min_value=1930, max_value=2010)

        obj = q.target(h)
        ui.panel.integer(q.label, obj, q.attr, key=wkey(q.key),
                         **q.widget_kwargs())

    `key` is the widget key STEM. It goes through `wkey()` at render time and
    must be unique across the whole assembled set, common and funnel-specific
    together, or two widgets collide and one silently shows the other's value.
    """
    key: str
    label: str                              # second person, a question
    kind: str
    attr: str
    path: str = ""                          # dotted from Household; "" = h
    help: str = ""
    funnels: tuple[str, ...] = FUNNELS      # which funnels ask it
    group: str = ""                         # the input_card it belongs in
    group_rank: int = 0                     # card order within the funnel
    order: int = 0                          # within the group
    when: Callable[[Household], bool] | None = None

    # Widget extras. Only the ones listed in _EXTRAS for this kind are passed.
    options: tuple = ()
    step: float | None = None
    min_value: float | None = None
    max_value: float | None = None
    placeholder: str = ""
    decimals: int | None = None
    fmt: str | None = None
    format_func: Callable[[object], str] | None = None   # choice only

    # ------------------------------------------------------------------
    def asks(self, funnel: str) -> bool:
        """Is this question part of `funnel`'s set at all?"""
        return funnel in self.funnels

    def applies(self, h: Household) -> bool:
        """
        Should this be on screen for this household right now?

        Both gates: the funnel asks it AND the `when` predicate passes. A
        question with no `when` applies to every household in its funnels.
        """
        if not self.asks(funnel_of(h)):
            return False
        return True if self.when is None else bool(self.when(h))

    def target(self, h: Household):
        """
        The object the widget writes into, walked from the Household.

        `path=""` is the Household itself; `path="member"` is `h.member`;
        `path="investments"` is `h.investments`. Dotted paths work. Returns
        None when a hop is missing -- an unmarried household has no spouse --
        and a None target means DO NOT RENDER, which `applies()` should already
        have told you.
        """
        obj = h
        if not self.path:
            return obj
        for part in self.path.split("."):
            obj = getattr(obj, part, None)
            if obj is None:
                return None
        return obj

    def widget_kwargs(self) -> dict:
        """
        Keyword arguments for this question's `ui.panel` helper.

        Only what the helper accepts and only what was set, so a default in
        `ui.panel` stays the default rather than being overwritten with None.
        Every helper takes `help`, so it is always included when there is one.
        """
        out: dict = {}
        if self.help:
            out["help"] = self.help
        allowed = _EXTRAS.get(self.kind, frozenset())
        for name in ("options", "step", "min_value", "max_value",
                     "placeholder", "decimals", "fmt", "format_func"):
            if name not in allowed:
                continue
            value = getattr(self, name)
            if value is None or value == () or value == "":
                continue
            out[name] = value
        if self.kind == KIND_CHOICE:
            out["options"] = list(self.options)
        return out


# --------------------------------------------------------------------------
# Predicates the questions share
# --------------------------------------------------------------------------

def has_spouse(h: Household) -> bool:
    """Married AND there is a spouse record to write into. See ensure_spouse."""
    return bool(h.has_spouse) and h.spouse is not None


def is_deployed(h: Household) -> bool:
    return bool(h.member.is_deployed)


# --------------------------------------------------------------------------
# The common set
# --------------------------------------------------------------------------
# Everything every funnel asks, and NOTHING else. Funnel-specific questions
# live in engine/intake/serving.py, veteran.py and retiree.py -- see
# docs/FUNNEL_CONTRACT.md. Groups are input_card titles; order runs within a
# group. Leave gaps in the numbering so a later insert does not renumber.

GROUP_ABOUT = "About you"
GROUP_HOUSEHOLD = "Your household"
GROUP_WHERE = "Where you live"
GROUP_BALANCES = "What you have saved"
GROUP_SPENDING = "What you spend"
GROUP_PLAN = "When you stop working"

#: The order the common groups are shown in. A funnel module may reuse these
#: names to add to an existing card, or introduce its own.
GROUP_ORDER: tuple[str, ...] = (GROUP_ABOUT, GROUP_HOUSEHOLD, GROUP_WHERE,
                                GROUP_BALANCES, GROUP_SPENDING, GROUP_PLAN)

QUESTIONS: tuple[Question, ...] = (
    # -- About you ---------------------------------------------------------
    Question(key="q_birth_year", label="What year were you born?",
             kind=KIND_INTEGER, path="member", attr="birth_year",
             group=GROUP_ABOUT, order=10,
             min_value=1930, max_value=2015,
             help="Everything dated runs off this — Social Security claiming, "
                  "RMDs, Medicare and how long the plan runs."),
    Question(key="q_sex", label="Which sex should we use for life expectancy?",
             kind=KIND_CHOICE, path="member", attr="sex",
             group=GROUP_ABOUT, order=20, options=tuple(MORT.SEXES),
             format_func=lambda v: v or "Prefer not to say",
             help="Only used to pick a mortality table. About three years "
                  "separates the two, which is enough to move the value of a "
                  "pension or an SBP election by a five-figure sum. Leave it "
                  "unset and the app uses the midpoint."),

    # -- Your household ----------------------------------------------------
    Question(key="q_married", label="Are you married?",
             kind=KIND_TOGGLE, attr="has_spouse",
             group=GROUP_HOUSEHOLD, order=10,
             help="Survivor income, filing status and the widow's penalty all "
                  "turn on this."),
    Question(key="q_spouse_birth_year",
             label="What year was your spouse born?",
             kind=KIND_INTEGER, path="spouse", attr="birth_year",
             group=GROUP_HOUSEHOLD, order=20, when=has_spouse,
             min_value=1930, max_value=2015,
             help="Who is likely to outlive whom decides how much an SBP "
                  "election is worth and how long survivor income has to last."),
    Question(key="q_dependents", label="How many dependents do you have?",
             kind=KIND_INTEGER, attr="n_dependents",
             group=GROUP_HOUSEHOLD, order=30, min_value=0, max_value=15),

    # -- Where you live ----------------------------------------------------
    Question(key="q_slr", label="Which state is your legal residence?",
             kind=KIND_TEXT, attr="state_of_legal_residence",
             group=GROUP_WHERE, order=10, placeholder="Texas",
             help="Where you pay income tax. Under SCRA you do not acquire a "
                  "new domicile just by being stationed somewhere, and several "
                  "states do not tax military retired pay at all."),
    Question(key="q_current_state", label="Which state do you live in now?",
             kind=KIND_TEXT, attr="current_state",
             group=GROUP_WHERE, order=20, placeholder="Texas"),

    # -- What you have saved ----------------------------------------------
    Question(key="q_tsp_trad",
             label="What is in your traditional TSP?",
             kind=KIND_MONEY, path="member", attr="tsp_traditional_balance",
             group=GROUP_BALANCES, order=10, step=1000.0,
             help="Pre-tax money. It is the balance that creates an RMD and a "
                  "tax bill later, so it is the one Roth conversions are about."),
    Question(key="q_tsp_roth", label="What is in your Roth TSP?",
             kind=KIND_MONEY, path="member", attr="tsp_roth_balance",
             group=GROUP_BALANCES, order=20, step=1000.0),
    Question(key="q_ira_trad",
             label="What is in your traditional IRA?",
             kind=KIND_MONEY, path="member", attr="ira_traditional_balance",
             group=GROUP_BALANCES, order=30, step=1000.0),
    Question(key="q_ira_roth", label="What is in your Roth IRA?",
             kind=KIND_MONEY, path="member", attr="ira_roth_balance",
             group=GROUP_BALANCES, order=40, step=1000.0),
    Question(key="q_brokerage",
             label="What do you hold in a taxable brokerage account?",
             kind=KIND_MONEY, attr="taxable_brokerage",
             group=GROUP_BALANCES, order=50, step=1000.0,
             help="Everything outside a retirement account — index funds, "
                  "individual stocks, a money market fund you invest from."),
    Question(key="q_cash", label="How much cash do you keep on hand?",
             kind=KIND_MONEY, attr="cash_savings",
             group=GROUP_BALANCES, order=60, step=500.0,
             help="Checking, savings and anything you could spend this week "
                  "without selling something."),

    # -- What you spend ----------------------------------------------------
    Question(key="q_spend_total", label="What do you spend in a month?",
             kind=KIND_MONEY, attr="monthly_expenses",
             group=GROUP_SPENDING, order=10, step=100.0,
             help="Everything that leaves the account in an ordinary month, "
                  "including the mortgage or rent."),
    Question(key="q_spend_essential",
             label="If your income was cut tomorrow, what would you still have "
                   "to pay every month?",
             kind=KIND_MONEY, attr="essential_monthly_expenses",
             group=GROUP_SPENDING, order=20, step=100.0,
             help="Housing, food, utilities, insurance, healthcare, transport, "
                  "minimum debt payments. Not travel, not eating out, not the "
                  "boat. This is the figure your guaranteed income — pension, "
                  "VA compensation, Social Security — has to cover before the "
                  "portfolio matters at all, so it is worth being honest about "
                  "rather than optimistic. Leave it blank and the app assumes "
                  "three quarters of your total and says so."),

    # -- When you stop working --------------------------------------------
    Question(key="q_target_retire_age",
             label="At what age do you want to stop working for money?",
             kind=KIND_INTEGER, attr="target_retirement_age",
             group=GROUP_PLAN, order=10, min_value=0, max_value=90,
             help="A target, not a commitment — the whole point of the "
                  "scorecard is to tell you whether it holds. Leave it at 0 if "
                  "you have not picked one."),
)


# --------------------------------------------------------------------------
# Assembling a set
# --------------------------------------------------------------------------
# `engine/intake/__init__.py` pulls the funnel-specific modules in and hands
# the combined pool to these. They are here because they are schema behaviour,
# not intake wiring.

def questions_for(funnel: str,
                  pool: Iterable[Question] = QUESTIONS) -> tuple[Question, ...]:
    """Every question `funnel` asks, in group then order. No household needed."""
    picked = [q for q in pool if q.asks(funnel)]
    return tuple(sorted(picked, key=_sort_key))


def visible_questions(h: Household,
                      pool: Iterable[Question] = QUESTIONS) -> tuple[Question, ...]:
    """
    Every question to put on screen for this household, in render order.

    Call `prepare(h)` first: a married household needs its spouse record before
    the spouse questions can pass `applies()`.
    """
    picked = [q for q in pool if q.applies(h) and q.target(h) is not None]
    return tuple(sorted(picked, key=_sort_key))


def grouped(questions: Iterable[Question]) -> tuple[tuple[str, tuple[Question, ...]], ...]:
    """
    Questions bundled into their input cards, cards in GROUP_ORDER first.

        for title, qs in grouped(visible_questions(h)):
            with input_card(title):
                for q in qs: render(q)
    """
    out: dict[str, list[Question]] = {}
    for q in sorted(questions, key=_sort_key):
        out.setdefault(q.group, []).append(q)
    return tuple((title, tuple(qs)) for title, qs in out.items())


def _group_rank(group: str) -> int:
    try:
        return GROUP_ORDER.index(group)
    except ValueError:
        return len(GROUP_ORDER)      # unknown groups sort after the common ones


def _sort_key(q: Question) -> tuple:
    """
    Cards in order, then questions within a card.

    Common groups come first, in GROUP_ORDER. A funnel module's own cards come
    after them, ordered by the `group_rank` its questions declare -- and only
    by the card TITLE where nothing declares one.

    `group_rank` exists because the title fallback is a trap. All three funnel
    modules ended up choosing card titles to force an alphabetical order, and
    said so in their docstrings: "renaming a card here silently reorders the
    page". A title is prose and prose gets rewritten. Worse, the fallback is
    case-sensitive -- "Your VA benefits" sorts before "Your civilian life" only
    because an uppercase V sorts below a lowercase c -- so a capitalisation fix
    could reorder the page too. Declare `group_rank` and the order is stated
    rather than smuggled.
    """
    return (_group_rank(q.group), q.group_rank, q.group, q.order, q.key)


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------

#: A label must open with one of these. HANDOFF.md: labels are second-person
#: QUESTIONS -- "What year were you born?", not "Birth year" -- and the reliable
#: test for a noun label that has had a question mark stapled on is the first
#: word, not the last character.
QUESTION_OPENERS: frozenset[str] = frozenset({
    "what", "which", "how", "are", "do", "does", "did", "when", "where", "at",
    "if", "have", "has", "is", "was", "will", "would", "can", "could", "should",
})


def validate(pool: Sequence[Question] = QUESTIONS,
             household: Household | None = None) -> list[str]:
    """
    Everything wrong with a question set, as plain sentences. Empty is good.

    Three agents write into this schema independently, so the failure this
    guards against is a duplicate widget key -- two widgets sharing a key show
    each other's value and neither page looks broken. Run it over the assembled
    pool in a test, not at import time.
    """
    problems: list[str] = []
    h = household
    if h is None:
        h = Household(has_spouse=True)
        ensure_spouse(h)

    seen: dict[str, Question] = {}
    for q in pool:
        if not q.key:
            problems.append(f"{q.label!r} has no key.")
        elif q.key in seen:
            problems.append(f"Duplicate question key {q.key!r} — widget keys "
                            f"must be unique across every funnel.")
        else:
            seen[q.key] = q

        if q.kind not in KINDS:
            problems.append(f"{q.key}: unknown widget kind {q.kind!r}. "
                            f"Expected one of {KINDS}.")
        if q.kind == KIND_CHOICE and not q.options:
            problems.append(f"{q.key}: a choice question needs options.")
        if not q.funnels:
            problems.append(f"{q.key}: asked by no funnel.")
        for f in q.funnels:
            if f not in SPEC_BY_KEY:
                problems.append(f"{q.key}: {f!r} is not a funnel.")
        label = q.label.strip()
        if not label.endswith("?"):
            problems.append(f"{q.key}: labels are second-person questions and "
                            f"end in a question mark — {q.label!r}.")
        opener = (label.split() or [""])[0].lower().strip("(\u201c\"'")
        if opener and opener not in QUESTION_OPENERS:
            problems.append(f"{q.key}: a label must open with a question word "
                            f"— {sorted(QUESTION_OPENERS)[:4]}… — not "
                            f"{opener!r}. {q.label!r} reads as a field name.")
        if not q.group:
            problems.append(f"{q.key}: no group, so it has no input card.")

        # Streamlit reads a PAIR of unescaped "$" as LaTeX and eats both dollar
        # signs, and a widget's help text is rendered as markdown like anything
        # else. The renderer passes `help` straight through, so the escaping has
        # to happen here -- which means it has to not be needed. Write "50,000"
        # or spell it, or split the figures across two sentences.
        for name in ("label", "help", "placeholder"):
            text = getattr(q, name) or ""
            if text.count("$") >= 2:
                problems.append(
                    f"{q.key}: {name} contains two unescaped '$' — Streamlit "
                    f"will parse the text between them as LaTeX and silently "
                    f"eat both dollar signs. Rephrase so at most one appears.")

        obj = q.target(h)
        if obj is None:
            problems.append(f"{q.key}: path {q.path!r} does not resolve.")
        elif not hasattr(obj, q.attr):
            problems.append(f"{q.key}: {type(obj).__name__} has no attribute "
                            f"{q.attr!r}.")

    # A card is ranked once, not once per question -- two questions on one card
    # disagreeing about `group_rank` would split it in two.
    #
    # Checked PER FUNNEL, because a card only ever renders inside one. Two
    # funnels may reuse a title and rank it differently, and "Leaving the
    # service" does exactly that: for someone serving it is a date they have
    # not picked yet and comes last, for a veteran it is the DD-214 and comes
    # first. Only questions that appear on screen together have to agree.
    for funnel in FUNNELS:
        ranks: dict[str, set[int]] = {}
        for q in pool:
            if q.group and q.asks(funnel):
                ranks.setdefault(q.group, set()).add(q.group_rank)
        for group, values in ranks.items():
            if len(values) > 1:
                problems.append(
                    f"Card {group!r} carries more than one group_rank "
                    f"({sorted(values)}) in the {funnel!r} funnel. Every "
                    f"question on a card must declare the same one.")
    return problems
