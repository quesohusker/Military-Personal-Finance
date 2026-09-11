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

from dataclasses import MISSING, dataclass, fields as dataclass_fields
from datetime import date
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


def prepare(h: Household, pool: Sequence["Question"] | None = None,
            derived: Sequence["Derived"] | None = None) -> Household:
    """
    Normalise a household before a render pass, once, at the top of the page.

    Two things:

      * a married household gets a spouse record, so the spouse questions have
        a target and `applies()` can stay a pure predicate;
      * every fact the app can work out is filled in, so no page and no engine
        sees a blank where a derivation exists (ARCHITECTURE.md R1).

    `pool` and `derived` default to the COMMON sets only, because this module
    cannot see the funnel-specific ones without an import cycle.
    **`engine.intake.prepare()` passes the assembled sets and is the one every
    page should call.** Call it before evaluating any `Question.applies`.
    """
    ensure_spouse(h)
    apply_derivations(h,
                      QUESTIONS if pool is None else pool,
                      DERIVED if derived is None else derived)
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

    # -- The override mechanism (ARCHITECTURE.md R1) ----------------------
    # A question carrying `derive` IS NOT ASKED IN THE MAIN FLOW. The app
    # works the answer out and the question becomes a correction: it renders
    # in the review card at the end of intake, seeded with the derived figure
    # and captioned with `derived_from`, rather than as a blank field in the
    # primary run. R1: "the question is never 'what is your basic pay?' -- it
    # is an override, asked only when the member wants to correct what the
    # table produced, and it should not be in the main flow at all."
    #
    #   derive        pure function of the Household -> the worked-out value.
    #   derived_from  one line, shown to the user: what it was worked out from.
    #   fills_in      True  -- write the value into the plan, because the rest
    #                          of the app reads the raw field and would
    #                          otherwise see a blank.
    #                 False -- leave the field as a pure OVERRIDE SLOT, because
    #                          the engine already falls back on its own.
    #                          `taxable.resolve_basic_monthly()` and every
    #                          `*_monthly_override` field work this way: blank
    #                          means "use what the app worked out".
    derive: Callable[[Household], object] | None = None
    derived_from: str = ""
    fills_in: bool = False

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
    @property
    def is_derived(self) -> bool:
        """True when the app works this out and only offers a correction."""
        return self.derive is not None

    def derived_value(self, h: Household):
        """
        What the app works this answer out to be, or None when it cannot.

        `derive` is a pure function of the Household, like `when`. It may
        legitimately return None -- a BAH lookup with no duty ZIP and no
        installed rate table has nothing to say -- and the review card then
        renders the stored value with no claim about where it came from.
        """
        return None if self.derive is None else self.derive(h)

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


def not_on_active_duty(h: Household) -> bool:
    """
    True for anyone who can hold a civilian job: out, or Guard or Reserve.

    Active duty is the one component where civilian wages are not a thing, so
    it is the one component that is not asked about them.
    """
    return h.member.component != ACTIVE


# --------------------------------------------------------------------------
# Facts the app works out, so that nobody is asked for them
# --------------------------------------------------------------------------
# ARCHITECTURE.md R1: "A question earns its place only if the answer CANNOT be
# derived. The test is not 'is this useful?' -- it is 'can the app work it
# out?'" There are two shapes of answer to that, and they are different
# objects here because they behave differently:
#
#   Question(derive=...)   A CORRECTABLE figure. Not asked in the main flow;
#                          it renders in the review card at the end of intake,
#                          seeded with what the app worked out. The user may
#                          overrule it and their answer stands for good.
#
#   Derived(...)           A SETTLED fact. No widget anywhere, because there is
#                          no second opinion to have: CRDP is automatic at
#                          twenty years and a 50% rating, a married member
#                          draws BAH at the with-dependents rate. The app
#                          writes it into the plan and the thirty-odd status
#                          gates (§4a) read it exactly as before.
#
# WHY A SETTLED FACT HAS NO WIDGET, stated once. A derivation may only
# overwrite a field that is still at its DECLARED DATACLASS DEFAULT, so a
# typed answer is never stomped. For a boolean whose derivation says True, the
# contrary answer IS the default -- there is no way to hold "no, really,
# False" that the next render pass would not undo. Rather than ship a toggle
# that silently flips back, a fact like that is either settled (no widget) or
# it stays a question. Nothing in between.

def _declared_default(obj, attr: str):
    """
    The value this attribute has on a freshly built object, or a sentinel.

    Read off the dataclass field rather than off a fresh instance, so a
    default_factory (Household.member, .estate) is never invoked.
    """
    for f in dataclass_fields(type(obj)):
        if f.name != attr:
            continue
        if f.default is not MISSING:
            return f.default
        return _NO_DEFAULT
    return _NO_DEFAULT


class _NoDefault:
    """Sentinel: this attribute has no scalar default to compare against."""


_NO_DEFAULT = _NoDefault()


def is_untouched(obj, attr: str) -> bool:
    """
    Is this field still the value a blank plan starts with?

    The Household carries no "unset" marker for a scalar, so this is the only
    test available and `pages/01_Intake.py::_answered` already owns up to the
    same crudeness. It decides one thing and one thing only: whether a
    derivation may write here. An answer that happens to equal the default is
    indistinguishable from an untouched one and will be re-derived; the review
    card shows the figure and where it came from, so that is visible rather
    than silent.
    """
    default = _declared_default(obj, attr)
    if isinstance(default, _NoDefault):
        return False
    return getattr(obj, attr, None) == default


@dataclass(frozen=True)
class Derived:
    """
    One fact the app works out and writes into the plan. Never a widget.

    `compute` is a pure function of the Household, like `when`. Returning None
    means "not enough on the plan to say", and nothing is written.
    """
    key: str
    label: str                              # a noun phrase; this is not a question
    attr: str
    compute: Callable[[Household], object]
    because: str                            # one line: why the app can say this
    path: str = ""
    funnels: tuple[str, ...] = FUNNELS
    when: Callable[[Household], bool] | None = None

    def asks(self, funnel: str) -> bool:
        return funnel in self.funnels

    def applies(self, h: Household) -> bool:
        if not self.asks(funnel_of(h)):
            return False
        return True if self.when is None else bool(self.when(h))

    def target(self, h: Household):
        obj = h
        if not self.path:
            return obj
        for part in self.path.split("."):
            obj = getattr(obj, part, None)
            if obj is None:
                return None
        return obj

    def value(self, h: Household):
        return self.compute(h)


def _fill_one(h: Household, path: str, attr: str, value) -> bool:
    """Write a derived value where the field is untouched. True if written."""
    obj = h
    for part in (path.split(".") if path else []):
        obj = getattr(obj, part, None)
        if obj is None:
            return False
    if value is None or not hasattr(obj, attr):
        return False
    if not is_untouched(obj, attr):
        return False
    current = getattr(obj, attr)
    if current == value:
        return False
    setattr(obj, attr, value)
    return True


def apply_derivations(h: Household,
                      pool: Sequence["Question"] = (),
                      derived: Sequence["Derived"] = ()) -> list[str]:
    """
    Fill in everything this household's funnel can work out. Returns the keys.

    Called by `prepare()`, so every page that prepares a household sees a plan
    with the derivations in place rather than a blank. It writes DIRECTLY --
    no `mark_dirty()`, no `invalidate()` -- because working out a figure the
    user never typed is not an edit the user made, and the engine layer holds
    no Streamlit state anyway. Idempotent: running it twice writes once.
    """
    written: list[str] = []
    for q in pool:
        if not (q.is_derived and q.fills_in and q.applies(h)):
            continue
        if _fill_one(h, q.path, q.attr, q.derived_value(h)):
            written.append(q.key)
    for d in derived:
        if not d.applies(h):
            continue
        if _fill_one(h, d.path, d.attr, d.value(h)):
            written.append(d.key)
    return written


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
GROUP_EARN = "What you earn"
GROUP_BALANCES = "What you have saved"
GROUP_SPENDING = "What you spend"
GROUP_PLAN = "When you stop working"

#: The one card every derived figure sits on, in every funnel: the review step
#: at the end of intake. It is NOT in GROUP_ORDER -- the page renders it after
#: everything else, on its own, because it is a different kind of act. Every
#: funnel module puts its corrections here and repeats RANK_REVIEW.
GROUP_REVIEW = "The figures we worked out"
RANK_REVIEW = 900

#: The order the common groups are shown in. A funnel module may reuse these
#: names to add to an existing card, or introduce its own.
GROUP_ORDER: tuple[str, ...] = (GROUP_ABOUT, GROUP_HOUSEHOLD, GROUP_WHERE,
                                GROUP_EARN, GROUP_BALANCES, GROUP_SPENDING,
                                GROUP_PLAN)


# --------------------------------------------------------------------------
# The derivations the common set runs on
# --------------------------------------------------------------------------

_ZIP_STATES: dict[str, str] = {}


def state_of_duty_zip(zipcode: str) -> str:
    """
    The state a duty ZIP is in, as a full name the tax tables recognise.

    Read off the BAH archive, which maps 40,000-odd ZIPs to a Military Housing
    Area whose name ends in a postal abbreviation -- "FAYETTEVILLE/FORT BRAGG,
    NC". No second table to keep in step, and it is the same file the BAH rate
    itself comes out of. Blank when there is no ZIP, no installed archive, or
    an overseas MHA with no state.
    """
    z = (zipcode or "").strip()[:5]
    if not z.isdigit() or len(z) != 5:
        return ""
    if not _ZIP_STATES:
        from engine.pay import bah as BAH              # local: keeps import cheap
        from engine.retirement.roth_bridge import STATE_ABBREVIATIONS
        data = BAH.load()
        if data is None:
            return ""
        for zc, mha in data.zip_to_mha.items():
            name = data.mha_names.get(mha, "")
            abbr = name.rsplit(",", 1)[-1].strip().upper() if "," in name else ""
            state = STATE_ABBREVIATIONS.get(abbr, "")
            if state:
                _ZIP_STATES[zc] = state
    return _ZIP_STATES.get(z, "")


def derive_current_state(h: Household) -> str:
    """
    Where you live now: your duty station's state, or your legal residence.

    Serving, the duty ZIP says it outright and the app already holds the ZIP
    to price BAH. Out of uniform there is no duty station and SCRA no longer
    applies, so where you live and where you are domiciled are the same place
    until you say otherwise.

    KNOWN LIMIT. A Military Housing Area can straddle a state line -- the
    Washington DC area covers DC, Maryland and Virginia -- and its NAME carries
    only one abbreviation, so a ZIP on the far side of the line resolves to the
    wrong state. That is worth knowing rather than worth refusing to derive:
    the field it replaces held a stale "Texas" for everybody, so the derivation
    is better than the alternative for anyone not in Texas, and it is offered
    back on the review card with the caveat in its help text. A ZIP-to-state
    table would settle it outright and there is not one in this tree.
    """
    if h.member.component in SERVING:
        return state_of_duty_zip(h.member.duty_zip) or h.state_of_legal_residence
    return h.state_of_legal_residence

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
    # DERIVED, not asked. Serving, the duty ZIP already on the plan names the
    # state; out of uniform there is no duty station and no SCRA, so it is the
    # legal residence. Kept as a correction because the two come apart --
    # a Guard member who drills in one state and lives in another, a retiree
    # who has moved and not yet changed domicile.
    Question(key="q_current_state", label="Which state do you live in now?",
             kind=KIND_TEXT, attr="current_state",
             group=GROUP_REVIEW, group_rank=RANK_REVIEW, order=10,
             placeholder="Texas",
             derive=derive_current_state, fills_in=True,
             derived_from="your duty station ZIP code, or your legal residence "
                          "once you are out of uniform",
             help="Where you actually live, which is not necessarily where you "
                  "pay tax — under SCRA you keep your domicile wherever you "
                  "are stationed. Worth checking rather than skipping: it "
                  "decides which state's disabled-veteran property tax "
                  "exemption the Housing page quotes you, and whether the "
                  "spouse-residency election on Taxes is worth making. The app "
                  "reads it off the housing area your duty ZIP sits in, and a "
                  "housing area can straddle a state line — so if you are near "
                  "one, check this."),

    # -- What you earn -----------------------------------------------------
    # THE ONE HOME FOR CIVILIAN WAGES (R3). Profile asked it and the Social
    # Security page asked it again, and the two meant different things: Profile
    # means what you earn NOW -- which is what `tsp.plan_contributions` and
    # `roth_bridge` read it as -- while Social Security was asking what you
    # will earn AFTER you take the uniform off. One field, two facts. It is
    # asked here, once, as current wages; Social Security's version is now a
    # page-local what-if and says so.
    #
    # Not asked on active duty, and only there: a Guard or Reserve member's
    # civilian job is usually their main income, and a veteran's or retiree's
    # second career is the difference between a plan that works and one that
    # does not.
    Question(key="q_civilian_wages",
             label="What do you earn in a civilian job, per year?",
             kind=KIND_MONEY, path="member", attr="civilian_wages_annual",
             group=GROUP_EARN, order=10, step=1_000.0, when=not_on_active_duty,
             help="Gross wages before tax and before anything you divert into "
                  "a retirement plan. Your service years and your civilian "
                  "years are one earnings record as far as Social Security is "
                  "concerned. Leave it at zero if you are not working."),

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

# WHY `estate.n_children` IS NOT DERIVED FROM `n_dependents`, and must not be.
#
# It was, briefly, on the reasoning that `engine/tax/current_year.py` already
# reads `est.n_children = h.n_dependents`. That reading is a fallback INSIDE a
# page that offers its own override widget (`pages/22_This_Years_Taxes.py`),
# and it is not a licence to write the value permanently into the plan.
#
# Two things break when it is:
#
#   1. `n_dependents` INCLUDES A SPOUSE. It is the military pay and tax sense
#      of the word -- it is what BAH's with-dependants rate turns on, and
#      intake asks it two lines below "Are you married?". A married member with
#      no children answers 1.
#   2. `engine/scorecard/components.py::legacy()` is scored ONLY when the user
#      says a legacy is a goal (ARCHITECTURE.md §3), and `n_children > 0` is
#      one of the three things that counts as saying so. Deriving the count
#      turned that component from NOT_APPLICABLE to a rated C-4 for every
#      married member with dependants -- a goal they never stated, scored
#      against a count that includes their spouse. The component's own detail
#      text says "Nothing is assumed from the number of dependants you claim
#      for pay", which the derivation made into a falsehood on screen.
#
# `estate.n_children` has two homes already -- the Estate page and the serving
# funnel's GI Bill question -- and both ask for it in its own words. R1 asks
# for the minimum number of questions, not for a derivation that answers a
# different question from the one the field holds.

#: Settled facts every funnel derives. None, in the common set: every fact the
#: common questions cover is either asked or genuinely funnel-specific.
DERIVED: tuple[Derived, ...] = ()


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
    Every question ASKED of this household, in render order. The main flow.

    Derived questions are not in it -- the app works those out, and they come
    back in `review_questions()` as corrections rather than as blanks.

    Call `prepare(h)` first: a married household needs its spouse record before
    the spouse questions can pass `applies()`.
    """
    picked = [q for q in pool
              if not q.is_derived and q.applies(h) and q.target(h) is not None]
    return tuple(sorted(picked, key=_sort_key))


def review_questions(h: Household,
                     pool: Iterable[Question] = QUESTIONS) -> tuple[Question, ...]:
    """
    The figures the app worked out and is offering to have corrected.

    The other half of `visible_questions()`: same household, same gates, the
    derived ones instead of the asked ones. They render in one card at the END
    of intake, after everything that was actually asked, because correcting a
    computed figure is a different act from answering a question.
    """
    picked = [q for q in pool
              if q.is_derived and q.applies(h) and q.target(h) is not None]
    return tuple(sorted(picked, key=_sort_key))


def settled_facts(h: Household,
                  derived: Iterable["Derived"] = ()) -> tuple["Derived", ...]:
    """The facts the app worked out and does not offer a widget for."""
    picked = [d for d in derived if d.applies(h) and d.target(h) is not None]
    return tuple(picked)


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
             household: Household | None = None,
             derived: Sequence[Derived] = ()) -> list[str]:
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
        for name in ("label", "help", "placeholder", "derived_from"):
            text = getattr(q, name) or ""
            if text.count("$") >= 2:
                problems.append(
                    f"{q.key}: {name} contains two unescaped '$' — Streamlit "
                    f"will parse the text between them as LaTeX and silently "
                    f"eat both dollar signs. Rephrase so at most one appears.")

        # A derived question is a CORRECTION, and a correction the user cannot
        # trace is worse than a blank field (§8: "A number with no visible
        # derivation is worse than no number"). So every one of them has to
        # say what it was worked out from, and has to sit on the review card
        # rather than in the middle of the main flow.
        if q.is_derived:
            if not q.derived_from.strip():
                problems.append(
                    f"{q.key}: derives its answer and does not say what from. "
                    f"Set derived_from — the review card prints it.")
            if q.group != GROUP_REVIEW:
                problems.append(
                    f"{q.key}: a derived question belongs on the "
                    f"{GROUP_REVIEW!r} card, not {q.group!r} — R1 keeps it out "
                    f"of the main flow.")
        elif q.derived_from or q.fills_in:
            problems.append(f"{q.key}: sets derived_from or fills_in with no "
                            f"derive, so nothing works anything out.")

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

    # The settled facts. They never render a widget, so the label and group
    # rules do not apply to them -- but a key collision with a question is
    # still a collision, and a field that is both asked and derived would have
    # the derivation fighting the answer.
    for d in derived:
        if not d.key:
            problems.append(f"{d.label!r} has no key.")
        elif d.key in seen:
            problems.append(f"Duplicate key {d.key!r} — a derived fact and a "
                            f"question cannot share one.")
        else:
            seen[d.key] = d
        if not d.because.strip():
            problems.append(f"{d.key}: a derived fact must say why the app can "
                            f"claim it. Set `because`.")
        for f in d.funnels:
            if f not in SPEC_BY_KEY:
                problems.append(f"{d.key}: {f!r} is not a funnel.")
        obj = d.target(h)
        if obj is None:
            problems.append(f"{d.key}: path {d.path!r} does not resolve.")
        elif not hasattr(obj, d.attr):
            problems.append(f"{d.key}: {type(obj).__name__} has no attribute "
                            f"{d.attr!r}.")
        for funnel in FUNNELS:
            if not d.asks(funnel):
                continue
            clash = [q for q in pool
                     if q.asks(funnel) and q.path == d.path and q.attr == d.attr]
            for q in clash:
                problems.append(
                    f"{d.key} derives {d.path or 'h'}.{d.attr} and {q.key} asks "
                    f"for it in the {funnel!r} funnel. A field is asked or "
                    f"derived, never both.")
    return problems
