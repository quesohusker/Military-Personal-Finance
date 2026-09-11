"""
Intake — every question the chosen funnel asks, rendered from data.

THIS FILE KNOWS NOTHING ABOUT ANY FUNNEL. It asks `engine.intake` what to put
on screen and renders it. There is no `if funnel == ...` here and there must
never be one: the three funnel-specific question sets live in
`engine/intake/serving.py`, `veteran.py` and `retiree.py`, they are written
independently, and this page renders a set it has never seen — including a set
whose module did not exist when this page was written.

IT RENDERS TWO THINGS, and the difference between them is ARCHITECTURE.md R1.

  * THE QUESTIONS — `questions_to_ask()`. Only what the app cannot work out.
  * THE REVIEW CARD — `figures_to_check()` and `facts_settled()`. Everything
    the app DID work out, last, on one card: the correctable figures as
    widgets seeded with what was computed, and under them the facts that were
    simply settled. Nothing here is a blank field, and every row says what it
    came from, because §8 is explicit that a number with no visible derivation
    is worse than no number.

The whole renderer is the four lines inside the two loops below. Everything
else on the page is telling the user where they are in it.

`docs/FUNNEL_CONTRACT.md` §4 is the specification; §8 rule 5 is the shape.
"""

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import streamlit as st
import pandas as pd
from streamlit.errors import StreamlitAPIException

import ui.panel as panel
from ui.panel import (wkey, get_household, page_header, two_pane, input_card,
                      esc, md_money, render_findings)
from engine.intake import (KINDS, KIND_MONEY, KIND_PCT, KIND_TOGGLE, prepare,
                           questions_to_ask, figures_to_check, facts_settled,
                           review_statement, review_findings,
                           grouped, spec, funnel_of, is_chosen, GROUP_REVIEW,
                           essential_monthly, has_essential_split)

START_PAGE = "pages/00_Start.py"

#: Widget kind -> the `ui.panel` helper of the same name. Built from KINDS
#: rather than written out, so the vocabulary stays defined in exactly one
#: place. An eighth kind means a new helper in `ui.panel`, and then this picks
#: it up for free.
RENDERERS = {kind: getattr(panel, kind) for kind in KINDS}


def _link(path: str, label: str, icon: str) -> None:
    """
    A link to another page, degrading to plain text when there is no menu.

    `st.page_link` needs its target registered with `st.navigation` — always
    true when the app runs, never true when this file is rendered on its own.
    Not worth taking the page down for.
    """
    try:
        st.page_link(path, label=label, icon=icon)
    except StreamlitAPIException:
        st.caption(f"{icon} {esc(label)}")


def _answered(q, h) -> bool:
    """
    Has this question been answered?

    Deliberately crude, and the caption on the progress panel says so. The
    Household carries no "unset" marker for a scalar -- `0.0` for a balance and
    `False` for a toggle are what a blank plan starts with -- so a considered
    zero cannot be told from an untouched one. Counting it as unanswered
    understates progress, which is the safe direction: it nags rather than
    reassures.
    """
    obj = q.target(h)
    if obj is None:
        return False
    value = getattr(obj, q.attr, None)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return float(value) != 0.0
    return bool(str(value or "").strip())


def _plain(value) -> str:
    """A settled value as the user should read it. No widget, no kind."""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (int, float)):
        return f"{value:g}"
    return esc(str(value))


def _shown(q, value) -> str:
    """The derived value as the user should read it, escaped for markdown."""
    if q.kind == KIND_TOGGLE:
        return "Yes" if value else "No"
    if q.kind == KIND_MONEY:
        return md_money(float(value))
    if q.kind == KIND_PCT:
        return f"{float(value) * 100:.0f}%"
    if isinstance(value, float):
        return f"{value:g}"
    return esc(str(value))


def _derived_note(q, h) -> str:
    """
    The one line under a derived widget: what the app is using, and why.

    Two shapes, because there are two kinds of derived question. One has been
    written into the plan and the widget above is already showing it. The
    other is a pure override slot — blank, with the engine falling back on its
    own — so the note has to say what the fallback is, or the figure would be
    invisible.
    """
    value = q.derived_value(h)
    if value is None:
        return f"The app could not work this out from {esc(q.derived_from)}."
    if q.fills_in:
        return f"Worked out from {esc(q.derived_from)}. Change it if it is wrong."
    keep = ("Leave it at zero to keep it." if q.kind in (KIND_MONEY, KIND_PCT)
            else "Leave it blank to keep it.")
    return (f"The app is using {_shown(q, value)}, from {esc(q.derived_from)}. "
            f"{keep}")


h = get_household()

# Once, at the top, before anything evaluates `applies()` or `target()`: a
# married household needs its spouse record created or the spouse questions
# have nowhere to write and vanish instead (FUNNEL_CONTRACT §5).
prepare(h)

page_header("📝 Intake",
            "Everything your plan needs, in the order it makes sense to ask "
            "it. Answers write straight into the plan as you type.")

# ==========================================================================
# No funnel, no form
# ==========================================================================
# `funnel_of()` would happily infer one and this page would render, but then
# the user answers fifteen common questions and never gets asked the one that
# decides the other ten. Send them to the front door instead.
#
# Told rather than bounced: a silent redirect out of a page the user just
# clicked in the menu reads as the click having done nothing.
if not is_chosen(h.funnel):
    st.warning("**One question comes first.** Where you are in your service "
               "decides which of these questions are yours, so intake does not "
               "open until it is answered.", icon="🎖️")
    _link(START_PAGE, "Answer it on the Start page", "🎖️")
    st.stop()

funnel = spec(funnel_of(h))
questions = questions_to_ask(h)
figures = figures_to_check(h)
settled = facts_settled(h)
statement = review_statement(h)

inputs, results = two_pane()

# ==========================================================================
# Left: the questions, whatever they turn out to be.
# ==========================================================================
def _render(q) -> None:
    """One question, the only way any question is ever rendered."""
    target = q.target(h)
    if target is None:
        # A missing hop -- an unmarried household has no spouse. A None target
        # means do not render (§3).
        return
    render = RENDERERS.get(q.kind)
    if render is None:
        # Only reachable if a funnel module ships a kind that is not in KINDS,
        # which `validate()` catches in its own test. One broken question
        # should not take the page down.
        st.warning(f"No widget for a question of kind "
                   f"{esc(q.kind)!r} ({esc(q.key)}).", icon="⚠️")
        return
    render(q.label, target, q.attr, key=wkey(q.key), **q.widget_kwargs())


with inputs:
    for title, qs in grouped(questions):
        with input_card(title):
            for q in qs:
                _render(q)

    # ======================================================================
    # The review step: everything the app worked out, offered for correction.
    # ======================================================================
    # ARCHITECTURE.md R1. None of this was asked in the flow above, and none
    # of it is blank: the widgets arrive carrying the computed figure and the
    # line under each one says where it came from. The pay overrides are the
    # case R1 names outright — "the question is never 'what is your basic
    # pay?' — it is an override" — and this card is where they live.
    if figures or settled or statement:
        with input_card(GROUP_REVIEW):
            st.caption("Nothing here was asked, because the app could work it "
                       "out from what you have already entered. Read down it "
                       "and correct anything that is wrong; leave the rest "
                       "alone.")

            # The funnel's own arithmetic, shown back rather than asked for.
            # For someone serving this is the pay packet: what the published
            # tables say they are paid, line by line, down to a gross and an
            # estimated net. It is READ-ONLY on purpose — a confirmation, not
            # a form. The two widgets that follow are where they confirm it.
            if statement:
                st.dataframe(
                    pd.DataFrame(statement, columns=["", "Per month"]),
                    hide_index=True, use_container_width=True)

            for q in figures:
                _render(q)
                st.caption(_derived_note(q, h))
            if settled:
                st.markdown("**Settled from your answers**")
                for d in settled:
                    # The value as well as the rule. A rule on its own reads
                    # as a claim about this household -- "your household has
                    # dependants" -- which is wrong half the time.
                    st.markdown(f"- {esc(d.label)}: **{_plain(d.value(h))}** "
                                f"— {esc(d.because)}.")

# ==========================================================================
# Right: where you are in it.
# ==========================================================================
with results:
    st.markdown(f"### {esc(funnel.label)}")
    st.caption(esc(funnel.description))
    st.caption(f"**What the scorecard measures for you:** {esc(funnel.frame)}")
    _link(START_PAGE, "Change where you are in your service", "🎖️")

    with st.container(border=True):
        done = [q for q in questions if _answered(q, h)]
        total = len(questions)
        n = len(done)
        st.markdown("#### Progress")
        st.progress(n / total if total else 0.0,
                    text=f"{n} of {total} answered")

        for title, qs in grouped(questions):
            got = sum(1 for q in qs if _answered(q, h))
            mark = "✅" if got == len(qs) else ("◻️" if got == 0 else "▪️")
            st.markdown(f"{mark} **{esc(title)}** — {got} of {len(qs)}")

        st.caption("A toggle you left off on purpose, and a balance that "
                   "really is zero, both count as unanswered here — nothing on "
                   "the plan tells the difference between a considered zero "
                   "and an untouched one. Nothing is required; the app says "
                   "what it assumed wherever you leave a gap.")

    # What the funnel wants said about the figures it worked out. Findings
    # go on the right, like every other page's (HANDOFF rule 5), and they are
    # `(severity, headline, detail)` triples like every other page's (rule 6).
    # For someone serving these are the gap between the gross and net they
    # confirmed off their LES and the ones the tables produce.
    notes = review_findings(h)
    if notes:
        st.markdown("### Your pay")
        render_findings(notes)

    worked_out = len(figures) + len(settled)
    if worked_out:
        st.caption(f"The app worked out {worked_out} more "
                   f"{'figure' if worked_out == 1 else 'figures'} for you "
                   f"rather than asking — your pay, your allowances and what "
                   f"follows from the answers above. They are at the bottom of "
                   f"the form, with what each one came from.")

    # The spending split is the one gap the app fills in silently, so it is the
    # one it has to own up to here (FUNNEL_CONTRACT §9).
    if h.monthly_expenses > 0 and not has_essential_split(h):
        st.info(f"You have not said what you could not cut, so the app assumes "
                f"three quarters of your total — {md_money(essential_monthly(h))} "
                f"a month. Anything built on it will say it is an assumption "
                f"rather than an answer.", icon="💡")
    elif (has_essential_split(h)
          and essential_monthly(h) < h.essential_monthly_expenses - 1e-9):
        st.warning(f"What you could not cut is more than you spend in total, "
                   f"so the app is using the total — "
                   f"{md_money(essential_monthly(h))} a month. Check both "
                   f"figures.", icon="⚠️")
