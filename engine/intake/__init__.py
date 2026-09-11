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

THE WHOLE CONTRACT FOR ONE OF THOSE MODULES IS ONE LINE:

    QUESTIONS: tuple[Question, ...]

a module-level tuple of `engine.funnel.Question`, every one of them carrying
`funnels=(FUNNEL_X,)` for its own funnel. No registration call, no import-time
side effect, no mutable registry -- a module either defines the name or it does
not exist yet. `docs/FUNNEL_CONTRACT.md` is the long form.

The three modules are written by other agents and may not exist yet. A missing
one is not an error here: it contributes nothing and the common set still
renders. A module that exists and is BROKEN is a different matter and raises,
because a silently empty funnel is the worse failure.
"""

from __future__ import annotations

import importlib
from typing import Iterable

from engine.funnel import (  # re-exported so a page has one import to make
    FUNNELS, FUNNEL_SERVING, FUNNEL_VETERAN, FUNNEL_RETIRED, FUNNEL_UNSET,
    Funnel, FUNNEL_SPECS, spec, label_for, is_chosen,
    Question, QUESTIONS, KINDS, GROUP_ORDER,
    infer_funnel, funnel_of, set_funnel, prepare, ensure_spouse,
    essential_monthly, discretionary_monthly, has_essential_split,
    questions_for, visible_questions, grouped, validate,
)
from engine.profile import Household

__all__ = [
    "FUNNELS", "FUNNEL_SERVING", "FUNNEL_VETERAN", "FUNNEL_RETIRED",
    "FUNNEL_UNSET", "Funnel", "FUNNEL_SPECS", "spec", "label_for", "is_chosen",
    "Question", "QUESTIONS", "KINDS", "GROUP_ORDER",
    "infer_funnel", "funnel_of", "set_funnel", "prepare", "ensure_spouse",
    "essential_monthly", "discretionary_monthly", "has_essential_split",
    "questions_for", "visible_questions", "grouped", "validate",
    "MODULES", "funnel_questions", "all_questions", "questions_to_ask", "pool",
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


def all_questions(funnel: str) -> tuple[Question, ...]:
    """
    Common plus funnel-specific, unfiltered by household, in render order.

    Use this for the contract test -- `validate(all_questions(f))` for each
    funnel is what catches a duplicate widget key between two agents' modules.
    """
    return questions_for(funnel, tuple(QUESTIONS) + funnel_questions(funnel))


def questions_to_ask(h: Household) -> tuple[Question, ...]:
    """
    What to put on screen for this household, in render order.

    The intake page calls `prepare(h)` and then this, and renders nothing else.
    """
    funnel = funnel_of(h)
    return visible_questions(h, tuple(QUESTIONS) + funnel_questions(funnel))


def pool(funnels: Iterable[str] = FUNNELS) -> tuple[Question, ...]:
    """Every question in the app, across every funnel, deduplicated by key."""
    seen: dict[str, Question] = {}
    for f in funnels:
        for q in all_questions(f):
            seen.setdefault(q.key, q)
    return tuple(seen.values())
