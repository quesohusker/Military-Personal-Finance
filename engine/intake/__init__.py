"""
Intake: the funnel-specific question sets, assembled.

`engine/funnel.py` owns the schema and the questions EVERY funnel asks. This
package owns the three sets that only one funnel asks, one module each:

    engine/intake/serving.py    DIEMS, grade, years of service, duty ZIP,
                                deployment, TSP election, separation plan
    engine/intake/veteran.py    separation date, years served, VA rating,
                                GI Bill remaining, VGLI, employer plan
    engine/intake/retiree.py    retired pay, retirement system, SBP, VA
                                rating, CRDP/CRSC, TRICARE plan

THE WHOLE CONTRACT FOR ONE OF THOSE MODULES IS TWO NAMES:

    QUESTIONS: tuple[Question, ...]
    DERIVED:   tuple[Derived, ...]        # optional; () when a module has none

and two optional callables, for a funnel that wants to SHOW its arithmetic
rather than only offer it back as a widget:

    statement(h) -> [(label, figure), ...]            read-only rows
    findings(h)  -> [(severity, headline, detail)]    what to say about them

module-level tuples of `engine.funnel.Question` and `engine.funnel.Derived`,
every one of them carrying `funnels=(FUNNEL_X,)` for its own funnel. No
registration call, no import-time side effect, no mutable registry -- a module
either defines the name or it does not. `docs/FUNNEL_CONTRACT.md` is the long
form.

A `Question` carrying `derive` is not asked: the app works the answer out and
offers it back for correction on the review card. A `Derived` is not even
that -- it is a fact with no second opinion, filled straight into the plan.
Both are ARCHITECTURE.md R1: ask only what cannot be worked out.

The three modules are written by other agents and may not exist yet. A missing
one is not an error here: it contributes nothing and the common set still
renders. A module that exists and is BROKEN is a different matter and raises,
because a silently empty funnel is the worse failure.
"""

from __future__ import annotations

import importlib
from typing import Iterable

from engine import funnel as _funnel
from engine.funnel import (  # re-exported so a page has one import to make
    FUNNELS, FUNNEL_SERVING, FUNNEL_VETERAN, FUNNEL_RETIRED, FUNNEL_UNSET,
    Funnel, FUNNEL_SPECS, spec, label_for, is_chosen,
    Question, Derived, QUESTIONS, DERIVED, KINDS, GROUP_ORDER,
    GROUP_REVIEW, RANK_REVIEW,
    KIND_TEXT, KIND_INTEGER, KIND_NUMBER, KIND_MONEY, KIND_PCT, KIND_TOGGLE,
    KIND_CHOICE,
    infer_funnel, funnel_of, set_funnel, ensure_spouse, apply_derivations,
    essential_monthly, discretionary_monthly, has_essential_split,
    questions_for, visible_questions, review_questions, settled_facts,
    grouped, validate,
)
from engine.profile import Household

__all__ = [
    "FUNNELS", "FUNNEL_SERVING", "FUNNEL_VETERAN", "FUNNEL_RETIRED",
    "FUNNEL_UNSET", "Funnel", "FUNNEL_SPECS", "spec", "label_for", "is_chosen",
    "Question", "Derived", "QUESTIONS", "DERIVED", "KINDS", "GROUP_ORDER",
    "GROUP_REVIEW", "RANK_REVIEW",
    "KIND_TEXT", "KIND_INTEGER", "KIND_NUMBER", "KIND_MONEY", "KIND_PCT",
    "KIND_TOGGLE", "KIND_CHOICE",
    "infer_funnel", "funnel_of", "set_funnel", "prepare", "ensure_spouse",
    "apply_derivations",
    "essential_monthly", "discretionary_monthly", "has_essential_split",
    "questions_for", "visible_questions", "review_questions", "settled_facts",
    "grouped", "validate",
    "MODULES", "funnel_questions", "funnel_derived", "all_questions",
    "derived_pool", "review_statement", "review_findings",
    "all_derived", "questions_to_ask", "figures_to_check", "facts_settled",
    "pool",
]

#: The module that owns each funnel's extra questions. The extension point:
#: write the module, define QUESTIONS in it, and it is live.
MODULES: dict[str, str] = {
    FUNNEL_SERVING: "engine.intake.serving",
    FUNNEL_VETERAN: "engine.intake.veteran",
    FUNNEL_RETIRED: "engine.intake.retiree",
}


def funnel_questions(funnel: str) -> tuple[Question, ...]:
    """
    The extra questions `funnel` asks. Empty until its module lands.

    A ModuleNotFoundError for the module itself is the not-written-yet case and
    is swallowed. Anything else -- a syntax error, a bad import inside it, a
    module with no QUESTIONS -- is a real defect and is not hidden.
    """
    name = MODULES.get(funnel)
    if not name:
        return ()
    try:
        mod = importlib.import_module(name)
    except ModuleNotFoundError as e:
        if (e.name or "") == name:
            return ()
        raise
    return tuple(getattr(mod, "QUESTIONS", ()))


def funnel_derived(funnel: str) -> tuple[Derived, ...]:
    """
    The settled facts `funnel` works out. Empty for a module that has none.

    Same rules as `funnel_questions`: a module that does not exist yet
    contributes nothing, a module that is broken raises.
    """
    name = MODULES.get(funnel)
    if not name:
        return ()
    try:
        mod = importlib.import_module(name)
    except ModuleNotFoundError as e:
        if (e.name or "") == name:
            return ()
        raise
    return tuple(getattr(mod, "DERIVED", ()))


def all_questions(funnel: str) -> tuple[Question, ...]:
    """
    Common plus funnel-specific, unfiltered by household, in render order.

    Everything the funnel holds -- asked and derived alike. Use this for the
    contract test: `validate(all_questions(f), derived=all_derived(f))` for
    each funnel is what catches a duplicate widget key between two agents'
    modules, and a field that is both asked and worked out.
    """
    return questions_for(funnel, tuple(QUESTIONS) + funnel_questions(funnel))


def all_derived(funnel: str) -> tuple[Derived, ...]:
    """Every settled fact `funnel` works out, common plus funnel-specific."""
    return tuple(DERIVED) + funnel_derived(funnel)


def _funnel_module(funnel: str):
    """The module behind a funnel, or None while it does not exist yet."""
    name = MODULES.get(funnel)
    if not name:
        return None
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as e:
        if (e.name or "") == name:
            return None
        raise


def review_statement(h: Household) -> tuple[tuple[str, str], ...]:
    """
    The read-only rows a funnel wants shown at the top of the review card.

    The optional half of a funnel module's contract: define `statement(h)` and
    it renders, define nothing and the card is just the corrections. The
    serving funnel uses it for the pay packet -- Paul's rule is that basic pay,
    BAS and BAH are shown back as a CONFIRMATION, not asked as a form.
    """
    mod = _funnel_module(funnel_of(h))
    fn = getattr(mod, "statement", None)
    return tuple(fn(h)) if callable(fn) else ()


def review_findings(h: Household) -> tuple[tuple[str, str, str], ...]:
    """
    What a funnel wants said about the figures on the review card.

    `(severity, headline, detail)` triples, rendered by
    `ui.panel.render_findings` like every other finding in the app (HANDOFF
    rule 6). The serving funnel uses it to name the gap between a confirmed
    gross or net and the one the tables produce.
    """
    mod = _funnel_module(funnel_of(h))
    fn = getattr(mod, "findings", None)
    return tuple(fn(h)) if callable(fn) else ()


def prepare(h: Household) -> Household:
    """
    Normalise a household before a render pass. THE ONE EVERY PAGE CALLS.

    `engine.funnel.prepare()` can only see the common set, because the funnel
    modules import it and the other direction would be a cycle. This one hands
    it the assembled set, so a serving member's BAH rate, a retiree's CRDP and
    everything else the funnel can work out are on the plan before any page
    reads it -- including the thirty-odd status gates of §4a, which go on
    reading `member.component` and friends and never learn a new field.
    """
    funnel = funnel_of(h)
    return _funnel.prepare(h, tuple(QUESTIONS) + funnel_questions(funnel),
                           all_derived(funnel))


def questions_to_ask(h: Household) -> tuple[Question, ...]:
    """
    What to ASK this household, in render order. The main flow, and no more.

    The intake page calls `prepare(h)` and then this. Nothing the app can work
    out is in it -- see `figures_to_check()`.
    """
    funnel = funnel_of(h)
    return visible_questions(h, tuple(QUESTIONS) + funnel_questions(funnel))


def figures_to_check(h: Household) -> tuple[Question, ...]:
    """
    What the app worked out and is offering to have corrected.

    The review card at the end of intake. R1: basic pay, BAH and BAS are never
    questions -- they are overrides of a published table, and they belong here.
    """
    funnel = funnel_of(h)
    return review_questions(h, tuple(QUESTIONS) + funnel_questions(funnel))


def facts_settled(h: Household) -> tuple[Derived, ...]:
    """What the app worked out and does not offer to have corrected."""
    return settled_facts(h, all_derived(funnel_of(h)))


def pool(funnels: Iterable[str] = FUNNELS) -> tuple[Question, ...]:
    """Every question in the app, across every funnel, deduplicated by key."""
    seen: dict[str, Question] = {}
    for f in funnels:
        for q in all_questions(f):
            seen.setdefault(q.key, q)
    return tuple(seen.values())


def derived_pool(funnels: Iterable[str] = FUNNELS) -> tuple[Derived, ...]:
    """Every settled fact in the app, across every funnel, deduplicated."""
    seen: dict[str, Derived] = {}
    for f in funnels:
        for d in all_derived(f):
            seen.setdefault(d.key, d)
    return tuple(seen.values())
