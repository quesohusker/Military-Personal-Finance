"""
Overview — why the tool exists, and the two ready-made examples.
"""

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import streamlit as st

from datetime import date
from ui.panel import get_household, set_household, fmt_money
from engine.profile import Household, ServiceMember, ACTIVE, RETIRED
from engine.debt.payoff import Debt
from engine.pay import bah as BAH, basepay as BP


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
    return h


h = get_household()

st.title("🎖️ Military Personal Finance")
st.caption("Financial planning built for the way military pay and benefits "
           "actually work — active duty first, retirees on the same machinery.")

st.markdown("---")

bah_data = BAH.load()
bp_table = BP.load()

st.subheader("Start here")

c1, c2, c3 = st.columns(3)
with c1:
    st.markdown("**Start from scratch**")
    st.caption("A blank plan. Work down the menu from 'Profile'.")
    if st.button("New blank plan", use_container_width=True):
        set_household(Household()); st.rerun()
with c2:
    st.markdown("**Active duty example**")
    st.caption("A BRS E-5 at Fort Bragg with a truck loan and a pre-service "
               "credit card. Good for seeing the waterfall work.")
    if st.button("Load active duty example", use_container_width=True):
        set_household(_example_active()); st.rerun()
with c3:
    st.markdown("**Retiree example**")
    st.caption("A retired O-5 with 26 years, rated 100% permanent and total, "
               "working a civilian job.")
    if st.button("Load retiree example", use_container_width=True):
        set_household(_example_retiree()); st.rerun()

st.markdown("---")
st.subheader("This plan at a glance")

m = h.member
cols = st.columns(5)
cols[0].metric("Component", m.component)
cols[1].metric("Grade", m.grade)
cols[2].metric("Retirement system", m.retirement_system)
cols[3].metric("Years of service", f"{m.years_of_service:g}")
cols[4].metric("Monthly expenses", fmt_money(h.monthly_expenses))

st.markdown("---")

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
