"""
Military Personal Finance — the router.

Run with:  streamlit run Military_Finance.py

The menu is organised by WHO A PAGE IS FOR. Most of personal finance does not
care whether you are in uniform, so `General` holds the pages everyone uses and
the three status groups hold only what is genuinely particular to that status.

Titles are nouns. The title says the subject, the subtitle says the question —
a sidebar of full sentences is slow to scan, and the eye should land rather
than read. See docs/REORGANIZATION.md for the reasoning and the old-to-new map.
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
    # Status-independent: the money questions that do not care what your DD-214
    # says. Ordered as a new user walks them — who you are, what comes in, what
    # you hold, what the government takes, then the decisions run on top.
    "General": [
        _page("pages/0_Overview.py", "Overview", "🎖️", default=True),
        _page("pages/1_Profile.py", "Profile", "👤"),
        _page("pages/2_Pay.py", "Income", "💵"),
        _page("pages/4_Assets_and_Debts.py", "Accounts", "🏦"),
        _page("pages/21_Investments.py", "Investments", "📊"),
        _page("pages/22_This_Years_Taxes.py", "Taxes", "🧾"),
        _page("pages/6_Prime_Directive.py", "Next Dollar", "🧭"),
        _page("pages/14_Roth_Conversions.py", "Roth Conversions", "🔁"),
        _page("pages/5_Debt_Payoff.py", "Debt Payoff", "💳"),
        _page("pages/20_Estate_and_Gifting.py", "Estate", "🎁"),
        _page("pages/17_Assumptions.py", "Assumptions", "🎛️"),
        _page("pages/12_Upload_LES.py", "Import Pay Statement", "📄"),
        _page("pages/13_Upload_Statement.py", "Import Accounts", "📥"),
    ],
    # In uniform now: the decisions you can only make from inside.
    "Currently Serving": [
        _page("pages/3_Career.py", "Career", "📈"),
        _page("pages/7_TSP_and_Deployment.py", "Deployment", "🪖"),
        _page("pages/8_Retirement.py", "Pension", "🎖️"),
        _page("pages/18_Leaving_the_Service.py", "Transition", "🚪"),
    ],
    # Served and left — with or without twenty years. VA benefits, the GI Bill,
    # and the exit that does not go to plan.
    "Veteran": [
        _page("pages/11_Separation_and_Insurance.py", "Medical Separation", "⚕️"),
        _page("pages/10_Residency_and_Education.py", "Residency & GI Bill", "🗺️"),
        _page("pages/19_Home_and_VA_Loan.py", "Housing & VA Loan", "🏠"),
    ],
    # Drawing retired pay: the streams that start late and the elections that
    # decide what your family keeps.
    "Retiree": [
        _page("pages/15_Social_Security.py", "Social Security", "🧓"),
        _page("pages/16_Healthcare.py", "Healthcare", "🏥"),
        _page("pages/9_Survivor_and_VA.py", "Survivor Benefits", "🛡️"),
    ],
}

# expanded=True: past ten pages Streamlit folds the tail of the menu behind a
# "View N more" button, and the group it hides is the one retirees need.
st.navigation(MENU, expanded=True).run()
