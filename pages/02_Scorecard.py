"""
Scorecard — the app's answer, and the front door's reason to exist.

`docs/ARCHITECTURE.md` §1: the app assesses READINESS TO RETIRE, and the
diagnosis it opens with is that there is no answer — the app was a set of
calculators. This page is the answer. §3 specifies it: eight components, each
rated C-1 to C-5, each stating the two or three figures that produced it, each
linking to the page that moves it.

WHY IT IS A DASHBOARD AND NOT A FORM. Every other page in the app is inputs
down the left and results down the right, because every other page is a
calculator. This one computes nothing the user can steer from here; it reads
what the rest of the app already holds. So the summary comes first at full
width, the detail comes underneath, and the only controls are how to order the
cards and whether to spend three seconds on the market test.

STATE IS ENCODED IN FORM, NOT ONLY COLOUR. Every band carries three redundant
encodings — a four-cell bar that fills left to right, the C-code as text, and a
distinct glyph. The page is readable in greyscale, and it is readable to
someone who cannot separate red from green.

IT IS NOT A PERMISSIONS SYSTEM. A C-4 hides nothing, unlocks nothing and gates
nothing. Every link on this page goes to a page that was already reachable.

DOLLAR SIGNS. Streamlit reads the span between two unescaped dollar signs as
LaTeX and silently eats both, so every figure on this page goes through esc()
or md_money(), and no `help=` string contains one at all — a help string cannot
be escaped at render time.
"""

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import streamlit as st
from streamlit.errors import StreamlitAPIException

from ui.panel import (wkey, get_household, page_header, section, metric_row,
                      esc, fmt_pct, render_findings)
from engine import scorecard as SC
from engine.scorecard import bands as B
from engine.intake import prepare

START_PAGE = "pages/00_Start.py"
INTAKE_PAGE = "pages/01_Intake.py"

#: Reserved in `ui.panel.RESULT_KEYS`, and shared with the Roth Conversions
#: page: same summary, same key, same `invalidate()` clearing both. Keyed on
#: `Profile.to_json()` so any change to the plan retires the stored result
#: rather than showing it against inputs it was not computed from.
MC_KEY = "mc_summary"


def _link(path: str, label: str, icon: str) -> None:
    """A page link that degrades to text when the router is not running."""
    try:
        st.page_link(path, label=label, icon=icon)
    except StreamlitAPIException:
        st.caption(f"{icon} {esc(label)}")


def _band_block(rating: int, status_label: str = "") -> None:
    """The three redundant encodings, stacked. Never colour alone."""
    st.markdown(
        f"<div style='font-family:ui-monospace,monospace;font-size:1.9rem;"
        f"line-height:1.1;letter-spacing:0.08em'>{B.bar(rating)}</div>"
        f"<div style='font-size:1.35rem;font-weight:700;margin-top:.15rem'>"
        f"{B.icon(rating)} {B.code(rating)}</div>"
        f"<div style='font-size:.82rem;opacity:.75'>{esc(B.label(rating))}</div>"
        + (f"<div style='font-size:.78rem;opacity:.6;margin-top:.2rem'>"
           f"{esc(status_label)}</div>" if status_label else ""),
        unsafe_allow_html=True)


# ==========================================================================
# The page
# ==========================================================================

h = prepare(get_household())

page_header("🎯 Scorecard",
            "One question, answered: are you ready to retire? Eight components, "
            "each rated C-1 to C-5, each showing the figures it was rated from, "
            "each linked to the page that moves it.")

# --------------------------------------------------------------------------
# The front door comes first. An empty card is not an answer, it is a reproach.
#
# This page renders a Scorecard and knows nothing about how the question at
# the front door is routed — that knowledge stays in the engine, where it
# cannot quietly turn into a gate. `needs_front_door()` is the whole of the
# page's interest in it.
# --------------------------------------------------------------------------
if SC.needs_front_door(h):
    st.info(
        "**This plan has not been through the front door yet.** One question — "
        "where you are in your service — decides what the app asks you and what "
        "it scores. Answer it and the scorecard fills in.", icon="🎖️")
    _link(START_PAGE, "Start here", "🎖️")
    reading = SC.front_door_reading(h)
    if reading:
        st.caption(esc(f"From what this plan already carries it reads as "
                       f"{reading}, but that is a reading, not your answer."))
    st.stop()

# --------------------------------------------------------------------------
# The expensive part, and only on request.
# --------------------------------------------------------------------------
# Built once. The profile and the projection are milliseconds; the Monte
# Carlo is attached only if the session already holds one for THIS plan.
engines = SC.inputs.for_household(h)
pkey = engines.key
stored = st.session_state.get(MC_KEY)
mc = stored["summary"] if (stored and stored.get("key") == pkey) else None
engines.mc = mc

card = SC.evaluate(h, engines=engines)

# --------------------------------------------------------------------------
# The answer, before any detail.
# --------------------------------------------------------------------------
head, meta = st.columns([1, 3], gap="large")
with head:
    with st.container(border=True):
        _band_block(card.rating)
        st.caption(esc("Overall readiness" if card.established
                       else "Overall readiness — not established"))

with meta:
    with st.container(border=True):
        st.markdown(f"### {esc(B.gloss(card.rating))}")
        if card.frame:
            st.caption(esc(f"{card.audience_label}. {card.frame}"))
        metric_row([
            ("Weighted readiness", f"{card.score:.0f}/100"),
            ("Components rated", f"{card.n_rated} of {card.n_total}"),
            ("Scorecard weight rated", fmt_pct(card.coverage, 0)),
        ])
        st.progress(min(1.0, max(0.0, card.readiness)))

if not card.established:
    st.warning(esc(card.established_note), icon="⚠️")
elif card.limiting is not None and card.limiting.rating >= B.C3:
    st.warning(
        esc(f"What is holding you back: {card.limiting.title} — "
            f"{B.code(card.limiting.rating)}. {card.limiting.headline}"),
        icon="⚠️")
elif card.limiting is not None:
    st.success(
        esc(f"Nothing rated below {B.code(card.limiting.rating)}. "
            f"{card.limiting.headline}"), icon="✅")

# --------------------------------------------------------------------------
# The eight, at a glance, before any of them is read in full.
# --------------------------------------------------------------------------
with section("The eight components",
             "Band, and what it is waiting on. The bar fills left to right: "
             "four cells is C-1, none is C-5."):
    cols = st.columns(4, gap="medium")
    for i, c in enumerate(card.components):
        with cols[i % 4], st.container(border=True):
            st.markdown(
                f"<div style='font-family:ui-monospace,monospace;"
                f"letter-spacing:.08em'>{B.bar(c.rating)} "
                f"<strong>{B.code(c.rating)}</strong></div>"
                f"<div style='font-weight:600;margin-top:.15rem'>"
                f"{c.icon} {esc(c.title)}</div>"
                f"<div style='font-size:.78rem;opacity:.65'>"
                f"{esc(c.status_label)} · weight {c.weight:g}</div>",
                unsafe_allow_html=True)

# --------------------------------------------------------------------------
# The two controls this page has.
# --------------------------------------------------------------------------
c1, c2, c3 = st.columns([2, 2, 3], gap="medium")
with c1:
    order_by = st.selectbox(
        "How should the components be ordered?",
        ["What needs attention first", "Scorecard order"],
        key=wkey("sc_order"),
        help="Attention order puts the lowest band at the top, heaviest "
             "component first when two share a band.")
with c2:
    show_unrated = st.toggle("Show what could not be rated?", value=True,
                             key=wkey("sc_unrated"),
                             help="A component that does not apply to you, or "
                                  "that the app cannot compute yet, is excluded "
                                  "from the overall rating rather than scored "
                                  "zero. The reasons are often the most useful "
                                  "thing on this page.")
with c3:
    if card.needs_longevity:
        st.caption("The market test runs 300 futures and takes a few seconds. "
                   "It is the only slow thing on this page, so it is never run "
                   "on its own.")
        if st.button("▶️  Run the market test", key=wkey("sc_run_mc"),
                     use_container_width=True, type="primary"):
            bar = st.progress(0.0, text="Running 300 futures…")
            try:
                summary = SC.run_longevity(
                    engines.profile,
                    progress=lambda f: bar.progress(
                        min(1.0, float(f)),
                        text=f"Running… {int(min(1.0, float(f)) * 100)}%"))
                st.session_state[MC_KEY] = {"key": pkey, "summary": summary}
            finally:
                bar.empty()
            st.rerun()
    elif mc is not None:
        st.caption(esc(f"Market test: {mc.n_paths:,} futures, run against this "
                       f"plan. It clears itself whenever you change a figure."))

rows = list(card.components)
if order_by == "What needs attention first":
    rows.sort(key=lambda c: (0 if c.applies else 1, -c.rating, -c.weight, c.order))

# --------------------------------------------------------------------------
# Each component in full: the band, the evidence, and the way out.
# --------------------------------------------------------------------------
for c in rows:
    if not c.applies and not show_unrated:
        continue
    with st.container(border=True):
        band, body = st.columns([1, 4], gap="large")
        with band:
            _band_block(c.rating, c.status_label)
            st.caption(esc(f"Component {c.order} · weight {c.weight:g}"))
            if not c.applies:
                st.caption("Excluded from the overall rating.")

        with body:
            st.markdown(f"#### {c.icon} {esc(c.title)}")
            st.caption(esc(c.question))
            st.markdown(f"**{esc(c.headline)}**")

            if c.evidence:
                st.markdown("")
                ev_cols = st.columns(min(3, len(c.evidence)), gap="medium")
                for i, ev in enumerate(c.evidence):
                    with ev_cols[i % len(ev_cols)]:
                        st.markdown(
                            f"<div style='font-size:.78rem;opacity:.7'>"
                            f"{esc(ev.label)}</div>"
                            f"<div style='font-size:1.1rem;font-weight:600'>"
                            f"{esc(ev.value)}</div>", unsafe_allow_html=True)
                        if ev.note:
                            st.caption(esc(ev.note))

            if c.detail:
                st.markdown("")
                st.markdown(esc(c.detail))

            st.markdown("")
            links = st.columns(1 + len(c.also), gap="small")
            with links[0]:
                _link(c.page, f"Fix this: {c.page_label}", c.page_icon)
            for col, (path, label, icon) in zip(links[1:], c.also):
                with col:
                    _link(path, label, icon)

            if c.findings:
                with st.expander(
                        f"What the engine found ({len(c.findings)})"):
                    render_findings([(getattr(f, "severity", f[0]),
                                      getattr(f, "headline", f[1]),
                                      getattr(f, "detail", f[2]))
                                     for f in c.findings])

# --------------------------------------------------------------------------
# The vocabulary, once, at the bottom where it does not cost the first screen.
# --------------------------------------------------------------------------
with st.expander("What the C-ratings mean"):
    st.markdown(
        "Unit readiness has been rated C-1 to C-5 for as long as any of us has "
        "been in, and every member reads it without a key. The same five bands "
        "are used here for the same reason a unit uses them: a band admits what "
        "a score cannot.")
    for r in B.RATINGS:
        st.markdown(
            f"<div style='font-family:ui-monospace,monospace;"
            f"letter-spacing:.08em;display:inline-block;width:5.5rem'>"
            f"{B.bar(r)}</div> <strong>{B.code(r)}</strong> — "
            f"{esc(B.label(r))}. {esc(B.gloss(r))}", unsafe_allow_html=True)
    st.markdown("---")
    st.markdown(
        "**C-5 is not the same as failing.** It is also where the app puts "
        "*you have not entered this yet* and *this does not apply to you*, "
        "because a 0–100 score cannot say either without lying. A component "
        "that does not apply, or that the app cannot compute yet, is left out "
        "of the overall rating entirely rather than counted as a zero — which "
        "is what lets a veteran rated on five components and a retiree rated "
        "on eight produce numbers that mean the same thing.")
    st.markdown(
        "**Every band states its evidence.** A number with no visible "
        "derivation is worse than no number, so each component shows the two "
        "or three figures it was read from. If you disagree with a band, "
        "disagree with those.")

st.caption(
    "An estimator and a planning tool, not advice, and not a permission "
    "system — nothing on this page unlocks or hides anything. Military "
    "OneSource gives free financial counselling at 800-342-9647."
)
