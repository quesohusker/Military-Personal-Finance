import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import streamlit as st
from streamlit.errors import StreamlitAPIException

from datetime import date
from ui.panel import (wkey, get_household, page_header, two_pane, input_card,
                      choice, fmt_money, esc, md_money)
from engine.profile import (COMPONENTS, SERVING, ACTIVE, RETIRED,
                            retirement_system_for_diems, has_tsp_match,
                            SYS_BRS, SYS_REDUX, DIEMS_BRS_START)
from engine.pay import grades as G
from engine import mortality as MORT

INTAKE_PAGE = "pages/01_Intake.py"


def _link(path: str, label: str, icon: str) -> None:
    """A link to another page, degrading to text when there is no menu."""
    try:
        st.page_link(path, label=label, icon=icon)
    except StreamlitAPIException:
        st.caption(f"{icon} {esc(label)}")


def _yes_no(value) -> str:
    return "Yes" if value else "No"


def _facts(*rows) -> None:
    """Facts this page reads and does not own. R3: one home, read elsewhere."""
    for label, value in rows:
        st.markdown(f"**{esc(label)}** — {value}")


h = get_household()
m = h.member

page_header("👤 Profile",
            "What your plan says about you, and what it means. The DIEMS date "
            "matters more than anything else here — it decides your retirement "
            "system, which decides whether a TSP match exists at all.")

inputs, results = two_pane()

# ==========================================================================
# Left: the questions, stacked.
# ==========================================================================
with inputs:
    st.info("**Your answers live on Intake now.** Every figure below was "
            "entered there, or worked out from what you entered — one home per "
            "fact, read everywhere else (ARCHITECTURE.md R3). This page shows "
            "what the plan holds and what it means. Change any of it on "
            "Intake.", icon="📝")
    _link(INTAKE_PAGE, "Open Intake", "📝")

    with input_card("What only this page asks"):
        # The two facts intake deliberately does not ask. Answering
        # "currently serving" on the Start page guarantees the component is
        # Active, Guard or Reserve but cannot tell which of the three, and
        # branch changes no number in any projection -- it changes a rank
        # title. So they are asked here, once, and this is their one home.
        choice("What component are you in?", m, "component", COMPONENTS,
               key=wkey("comp"),
               help="Intake does not ask this: choosing 'currently serving' "
                    "leaves Guard and Reserve alone rather than guessing "
                    "between them.")
        choice("Which branch?", m, "branch", G.BRANCHES, key=wkey("branch"),
               help="It sets your rank titles. No projection reads it.")

    with input_card("About your service"):
        _facts(("Pay grade", esc(m.grade)),
               ("Years of service", f"{m.years_of_service:g}"),
               ("Time in grade", f"{m.time_in_grade():.1f} years"
                                 + ("" if m.dor is not None
                                    else " (assumed — no Date of Rank)")),
               ("DIEMS date", esc(m.diems_date or "not set")),
               ("Retirement system", esc(m.retirement_system)),
               ("Year of birth", f"{m.birth_year}"),
               ("Sex, for life expectancy", esc(m.sex or "not set")))
        if m.diems is not None and m.diems < DIEMS_BRS_START:
            _facts(("Opted into BRS in 2018", _yes_no(m.opted_into_brs)),
                   ("Took the CSB/REDUX bonus", _yes_no(m.took_csb_redux)))

    with input_card("Your household and where you are"):
        _facts(("Married", _yes_no(h.has_spouse)),
               ("Dependents", f"{h.n_dependents}"),
               ("Dependents for pay", _yes_no(m.has_dependents)),
               ("Government housing", _yes_no(m.lives_in_government_housing)),
               ("Duty station ZIP", esc(m.duty_zip or "not set")),
               ("Legal residence", esc(h.state_of_legal_residence or "not set")),
               ("Living in", esc(h.current_state or "not set")))

    with input_card("Are you deployed?"):
        _facts(("Deployed", _yes_no(m.is_deployed)),
               ("Months deployed this year", f"{int(m.months_deployed_this_year)}"),
               ("Hostile fire or imminent danger pay",
                _yes_no(m.drawing_hostile_fire_pay)),
               ("In a designated combat zone", _yes_no(m.in_combat_zone)),
               ("SDP balance", md_money(m.sdp_balance)))

    show_retiree = (m.component in (RETIRED,) or m.retired_pay_monthly > 0
                    or m.va_disability_monthly > 0)
    if show_retiree:
        with input_card("Your retired pay and VA"):
            _facts(("Gross retired pay",
                    f"{md_money(m.retired_pay_monthly)} a month"),
                   ("SBP elected", _yes_no(m.sbp_elected)),
                   ("VA compensation",
                    f"{md_money(m.va_disability_monthly)} a month"),
                   ("VA rating", f"{m.va_rating}%"),
                   ("Permanent and total", _yes_no(m.va_rating_permanent_total)),
                   ("CRDP applies", _yes_no(m.crdp_applies)),
                   ("CRSC", f"{md_money(m.crsc_monthly)} a month"))

    with input_card("Civilian income"):
        _facts(("Civilian wages",
                f"{md_money(m.civilian_wages_annual)} a year"))

# ==========================================================================
# Right: what those answers mean.
# ==========================================================================
with results:
    try:
        g = G.get(m.grade)
        st.markdown(f"### {g.title(m.branch)}")
        st.caption(f"{g.category} · {m.component} · age "
                   f"{m.age(date.today().year)} · {m.years_of_service:g} years "
                   f"of service")
    except KeyError:
        pass

    if m.diems is None:
        st.error("That DIEMS date could not be read. Use YYYY-MM-DD.", icon="🚨")

    system = m.retirement_system
    if system == SYS_BRS:
        st.success(f"**{system}** — you have a TSP match. Contribute at least "
                   f"5% of basic pay to capture all of it.", icon="✅")
    elif system == SYS_REDUX:
        st.warning(f"**{system}** — you took the $30,000 Career Status Bonus at "
                   f"15 years. Your multiplier is 40% at 20 years rather than "
                   f"50%, and your COLA runs a point below inflation until the "
                   f"recomputation at 62.", icon="⚠️")
    else:
        st.info(f"**{system}** — there is no TSP match under this system. "
                f"Contribute to the TSP on its merits, not to chase a match "
                f"that does not exist.", icon="ℹ️")

    if (h.state_of_legal_residence or "").strip().lower() != \
       (h.current_state or "").strip().lower():
        st.info("Your legal residence differs from where you live. That is "
                "normal and legal for a service member under SCRA — military "
                "pay is taxed only by your state of legal residence regardless "
                "of duty station. It does require a genuine connection to that "
                "state, and states do audit it.", icon="📍")

    if m.is_deployed and m.drawing_hostile_fire_pay:
        st.success("**The Savings Deposit Program is open to you.** 10% "
                   "guaranteed on up to $10,000, compounded monthly, with "
                   "interest continuing for 90 days after you redeploy. "
                   "Nothing else available to you returns that with certainty.",
                   icon="💰")
    if m.in_combat_zone:
        st.success("**Combat Zone Tax Exclusion applies.** Enlisted and warrant "
                   "officers exclude all military pay for the month; "
                   "commissioned officers are capped at the highest enlisted "
                   "basic pay plus hostile fire pay. This is the cheapest year "
                   "you will ever have to fill Roth accounts or convert an old "
                   "traditional balance.", icon="💰")

    if show_retiree and m.va_rating >= 50 and m.years_of_service >= 20 \
       and not m.crdp_applies:
        st.warning("You appear to qualify for CRDP — 20+ years and a rating of "
                   "50% or more. It is automatic and restores retired pay that "
                   "would otherwise be offset. Turn it on.", icon="⚠️")

    if not show_retiree:
        st.caption("Set your component to Military Retiree, or enter a VA "
                   "rating, to see the retired pay and VA questions.")
