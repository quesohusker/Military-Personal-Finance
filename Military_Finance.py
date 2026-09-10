"""
Military Personal Finance — the router.

Run with:  streamlit run Military_Finance.py

The menu is organised around the DECISIONS a service member has to make and the
EVENTS they will meet, not around the software's features. Nobody wakes up
wanting to visit a "benefits module"; they wake up with orders in hand, or a
medical board convening, or twelve years in and a choice about staying.
"""

import streamlit as st

st.set_page_config(page_title="Military Personal Finance", page_icon="🎖️",
                   layout="wide", initial_sidebar_state="expanded")

from ui.panel import inject_css, render_sidebar  # noqa: E402

inject_css()
render_sidebar()


def _page(path, title, icon, default=False):
    return st.Page(path, title=title, icon=icon, default=default)


MENU = {
    "Where I stand": [
        _page("pages/0_Overview.py", "Overview", "🎖️", default=True),
        _page("pages/12_Upload_LES.py", "Read my LES or RAS", "📄"),
        _page("pages/13_Upload_Statement.py", "Read a bank or brokerage statement", "🏦"),
        _page("pages/1_Profile.py", "Who I am", "👤"),
        _page("pages/2_Pay.py", "What I actually get paid", "💵"),
        _page("pages/4_Assets_and_Debts.py", "What I am worth", "🏦"),
    ],
    "Decisions I make now": [
        _page("pages/6_Prime_Directive.py", "What to do with my next dollar", "🧭"),
        _page("pages/5_Debt_Payoff.py", "Getting out of debt", "💳"),
        _page("pages/10_Residency_and_Education.py",
              "My home state, and the GI Bill", "🗺️"),
    ],
    "When I get orders": [
        _page("pages/3_Career.py", "Promotions and PCS moves", "📈"),
    ],
    "When I deploy": [
        _page("pages/7_TSP_and_Deployment.py", "Combat-zone pay and the TSP", "🪖"),
    ],
    "When I leave the service": [
        _page("pages/8_Retirement.py", "Do I stay to twenty?", "🎖️"),
        _page("pages/11_Separation_and_Insurance.py",
              "If I am medically separated", "⚕️"),
        _page("pages/9_Survivor_and_VA.py", "Survivors, SBP and the VA", "🛡️"),
    ],
}

# expanded=True: past ten pages Streamlit folds the tail of the menu behind a
# "View N more" button, and the group it hides is the one retirees need.
st.navigation(MENU, expanded=True).run()
