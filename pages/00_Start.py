"""
Start — the front door. One question, asked once: where are you in your service?

`docs/ARCHITECTURE.md` §5: "Question 1 sets the funnel." Everything downstream
hangs off the answer — which questions intake asks, which component the app's
30+ existing status gates read (§4a), and what the scorecard measures. So it is
asked on its own, before anything else, and never asked twice.

WHY THIS PAGE IS NOT `two_pane()`. Every other page in the app is a form with a
result: answers down the left, what they mean down the right. This page has no
result to show — there is nothing to compute until the question is answered, so
a 1 : 2.3 split would put the one thing on the page in the narrow column and
leave the wide one empty. The three funnels are peers and the user is comparing
them, so they get three equal columns and are read across rather than down.
`input_card()` is wrong here for the same reason: these are not inputs writing
into a field, they are three doors.

THE FUNNEL IS NOT A PERMISSIONS SYSTEM (§2). Choosing one hides no page from
anybody; a serving member deciding whether to stay to 20 needs the retiree
pages to make that decision. It sets defaults, ordering and what gets scored.
"""

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import streamlit as st
from streamlit.errors import StreamlitAPIException

from ui.panel import (wkey, get_household, set_household, page_header, esc,
                      mark_dirty, invalidate)
from engine.intake import (FUNNEL_SPECS, FUNNEL_SERVING, FUNNEL_RETIRED,
                           spec, is_chosen, funnel_of, set_funnel)
from engine.profile import Household, ServiceMember, ACTIVE, RETIRED
from engine.debt.payoff import Debt
from engine.pay import bah as BAH, basepay as BP

INTAKE_PAGE = "pages/01_Intake.py"


# ==========================================================================
# The two example plans
# ==========================================================================
# Carried across from pages/0_Overview.py, which keeps its own copies until
# that page is folded into the scorecard. They are duplicated rather than
# imported because a Streamlit page module cannot be imported without running
# it, and `0_Overview` is not a legal module name anyway. If you change one,
# change the other.
#
# Both arrive with the funnel already chosen: an example whose front-door
# question is unanswered is a worked example of nothing.

def _example_active() -> Household:
    """A BRS E-5 at Fort Bragg with a car loan and a pre-service credit card."""
    h = Household(profile_name="Example — E-5, BRS, Fort Bragg")
    h.member = ServiceMember(
        name="", birth_year=1999, component=ACTIVE, branch="Army", grade="E-5",
        years_of_service=6.0, time_in_grade_years=1.5, diems_date="2020-06-01",
        duty_zip="28310", has_dependents=True, tsp_contribution_pct=0.03,
        tsp_traditional_balance=9_000, tsp_roth_balance=14_000,
        ira_roth_balance=4_500, sgli_coverage=500_000)
    h.monthly_expenses = 4_200
    h.cash_savings = 3_500
    h.vehicles_value = 21_000
    h.n_dependents = 2
    h.state_of_legal_residence = "Texas"
    h.current_state = "North Carolina"
    h.debts = [
        Debt("Visa", 6_800, 0.2249, 180, "Credit card", incurred_before_service=True),
        Debt("Truck loan", 24_500, 0.0899, 520, "Auto loan"),
    ]
    set_funnel(h, FUNNEL_SERVING)
    return h


def _example_retiree() -> Household:
    """A retired O-5 with 26 years and a 100% VA rating."""
    h = Household(profile_name="Example — Retired O-5, 100% P&T")
    h.member = ServiceMember(
        birth_year=1975, component=RETIRED, branch="Army", grade="O-5",
        years_of_service=26.0, diems_date="1999-05-15",
        retired_pay_monthly=7_276, va_disability_monthly=4_000, va_rating=100,
        va_rating_permanent_total=True, crdp_applies=True, sbp_elected=True,
        tsp_traditional_balance=700_000, tsp_roth_balance=100_000,
        civilian_wages_annual=95_000)
    h.monthly_expenses = 9_000
    h.cash_savings = 60_000
    h.taxable_brokerage = 250_000
    h.home_value = 420_000
    h.mortgage_balance = 280_000
    h.state_of_legal_residence = "Michigan"
    h.current_state = "Michigan"
    set_funnel(h, FUNNEL_RETIRED)
    return h


# ==========================================================================
# Moving on
# ==========================================================================

def _go_to_intake() -> None:
    """
    Hand the user to intake, and never strand them if that is not possible.

    `st.switch_page` raises a control-flow exception on success, so only the
    genuine failure — the page is not registered, which is what happens when
    this file is rendered on its own outside the router — is caught. The rerun
    then redraws this page in its answered state, which links on.
    """
    try:
        st.switch_page(INTAKE_PAGE)
    except StreamlitAPIException:
        st.rerun()


def _link(path: str, label: str, icon: str) -> None:
    """
    A link to another page, degrading to plain text when there is no menu.

    Both `st.page_link` and `st.switch_page` need their target registered with
    `st.navigation` — always true when the app runs, never true when this file
    is rendered on its own. Neither is worth taking the page down for.
    """
    try:
        st.page_link(path, label=label, icon=icon)
    except StreamlitAPIException:
        st.caption(f"{icon} {esc(label)}")


def _choose(h: Household, key: str) -> None:
    """
    Record the answer.

    `set_funnel()` is a pure engine function and holds no Streamlit state, so
    the dirty flag and the cached results are this page's job — exactly as the
    `ui.panel` input helpers do it for a widget (FUNNEL_CONTRACT §7).
    """
    set_funnel(h, key)
    mark_dirty()
    invalidate()
    _go_to_intake()


def _funnel_cards(h: Household, current: str) -> None:
    """
    The three doors, side by side, rendered from FUNNEL_SPECS in its own order.

    Nothing here names a funnel: add a fourth to `FUNNEL_SPECS` and it appears.
    """
    cols = st.columns(len(FUNNEL_SPECS), gap="large")
    for col, f in zip(cols, FUNNEL_SPECS):
        mine = (f.key == current)
        with col, st.container(border=True):
            st.markdown(f"#### {esc(f.label)}")
            st.caption(esc(f.description))
            st.markdown("\n".join(f"- {esc(line)}" for line in f.implies))
            st.caption(f"**What it scores:** {esc(f.frame)}")
            if st.button("Keep this one" if mine else "This is me",
                         key=wkey(f"pick_{f.key}"), use_container_width=True,
                         type="secondary" if mine else "primary"):
                _choose(h, f.key)


# ==========================================================================
# The page
# ==========================================================================

h = get_household()

page_header("🎖️ Start here",
            "One question decides what this app asks you and what it scores: "
            "where are you in your service?")

if is_chosen(h.funnel):
    # ANSWERED. Nobody with a plan gets made to answer this again. Show what
    # they picked, point at the work, and put the change out of the way but
    # within reach.
    chosen = spec(h.funnel)
    st.success(f"**{esc(chosen.label)}** — {esc(chosen.description)}", icon="✅")
    st.caption(f"Plan: **{esc(h.profile_name)}**")
    _link(INTAKE_PAGE, "Continue to your answers", "➡️")

    with st.expander("Change where you are in your service", expanded=False):
        st.caption("Changing this changes which questions intake asks you and "
                   "which component the rest of the app reads. It never erases "
                   "a figure you have already entered.")
        _funnel_cards(h, current=h.funnel)
else:
    # NEVER ASKED — including every plan saved before this question existed.
    # `funnel_of()` already has an answer for those, so the honest thing is to
    # show it as a reading of the plan, with the evidence it was read from,
    # rather than either hiding it or pretending it was a choice.
    m = h.member
    guess = spec(funnel_of(h))
    st.info(
        f"This plan has not been asked yet. From what it carries — "
        f"{esc(m.component)}, {m.years_of_service:g} years of service — it "
        f"reads as **{esc(guess.label)}**. Pick the one that is actually true.",
        icon="🧭")
    _funnel_cards(h, current="")

st.markdown("---")

# ==========================================================================
# Somewhere to start from
# ==========================================================================
st.subheader("Or start from something")
st.caption("Each of these replaces the plan you have open.")

c1, c2, c3 = st.columns(3)
with c1:
    st.markdown("**Start from scratch**")
    st.caption("A blank plan, with the question above still to answer.")
    if st.button("New blank plan", key=wkey("new_blank"),
                 use_container_width=True):
        set_household(Household())
        st.rerun()
with c2:
    st.markdown("**Active duty example**")
    st.caption("A BRS E-5 at Fort Bragg with a truck loan and a pre-service "
               "credit card. Good for seeing the waterfall work.")
    if st.button("Load active duty example", key=wkey("ex_active"),
                 use_container_width=True):
        set_household(_example_active())
        st.rerun()
with c3:
    st.markdown("**Retiree example**")
    st.caption("A retired O-5 with 26 years, rated 100% permanent and total, "
               "working a civilian job.")
    if st.button("Load retiree example", key=wkey("ex_retiree"),
                 use_container_width=True):
        set_household(_example_retiree())
        st.rerun()

st.markdown("---")

# ==========================================================================
# What a front door owes the person standing at it
# ==========================================================================
bah_data = BAH.load()
bp_table = BP.load()

f1, f2 = st.columns([1, 1])
with f1:
    st.info("**Nothing you enter leaves this machine.** No account, no server, "
            "no analytics. Plans save as plain JSON.", icon="🔒")
with f2:
    st.markdown(
        f"**Rate data** — "
        f"{'BAH ' + str(bah_data.year) + f' ({bah_data.n_mhas} housing areas, {bah_data.n_zips:,} ZIP codes)' if bah_data else 'BAH ❌ not installed'}"
        f" · "
        f"{'basic pay ' + str(bp_table.year) if bp_table else 'basic pay ❌ not installed'}"
    )

st.caption(
    "An estimator and a planning tool. Not tax, legal or investment advice, and "
    "no substitute for your LES, your Retiree Account Statement, or a "
    "conversation with a financial counsellor — Military OneSource provides "
    "those free at 800-342-9647."
)
