import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import streamlit as st
st.set_page_config(page_title="Profile", page_icon="👤", layout="wide")

from datetime import date
from ui.panel import (wkey, render_save_load, page_header, money, pct, integer,
                      number, text, toggle, choice, fmt_money, mark_dirty,
                      invalidate)
from engine.profile import (COMPONENTS, SERVING, ACTIVE, RETIRED,
                            retirement_system_for_diems, has_tsp_match,
                            SYS_BRS, SYS_REDUX, DIEMS_BRS_START)
from engine.pay import grades as G

h = render_save_load("profile")
m = h.member

page_header("👤 Profile",
            "Who you are. The DIEMS date matters more than anything else on "
            "this page — it decides your retirement system, which decides "
            "whether a TSP match exists at all.")

st.markdown("### Service")
c1, c2, c3 = st.columns(3)
with c1:
    choice("Component", m, "component", COMPONENTS, key=wkey("comp"))
    choice("Branch", m, "branch", G.BRANCHES, key=wkey("branch"))
with c2:
    choice("Pay grade", m, "grade", G.GRADE_LABELS, key=wkey("grade"),
           help="O-1E, O-2E and O-3E are for officers with at least four years "
                "of prior enlisted or warrant service. They are paid on a "
                "separate, higher line.")
    number("Years of service", m, "years_of_service", key=wkey("yos"),
           min_value=0.0, max_value=45.0, step=0.5)
with c3:
    number("Years in current grade", m, "time_in_grade_years", key=wkey("tig"),
           min_value=0.0, max_value=30.0, step=0.5)
    integer("Birth year", m, "birth_year", key=wkey("by"),
            min_value=1930, max_value=2010)

try:
    g = G.get(m.grade)
    st.caption(f"**{g.title(m.branch)}** · {g.category} · age "
               f"{m.age(date.today().year)}")
except KeyError:
    pass

st.markdown("---")
st.markdown("### DIEMS date and retirement system")

d1, d2 = st.columns([1, 2])
with d1:
    text("DIEMS date (YYYY-MM-DD)", m, "diems_date", key=wkey("diems"),
         help="Date of Initial Entry to Military Service — the day you first "
              "swore in, including at an academy or in ROTC contracted status. "
              "It is on your LES and your DD-214. It is NOT the date you "
              "started your current period of service.")
    if m.diems is None:
        st.error("That date could not be read. Use YYYY-MM-DD.", icon="🚨")

with d2:
    system = m.retirement_system
    if system == SYS_BRS:
        st.success(f"**{system}** — you have a TSP match. Contribute at least 5% "
                   f"of basic pay to capture all of it.", icon="✅")
    elif system == SYS_REDUX:
        st.warning(f"**{system}** — you took the $30,000 Career Status Bonus at "
                   f"15 years. Your multiplier is 40% at 20 years rather than "
                   f"50%, and your COLA runs a point below inflation until the "
                   f"recomputation at 62.", icon="⚠️")
    else:
        st.info(f"**{system}** — there is no TSP match under this system. "
                f"Contribute to the TSP on its merits, not to chase a match "
                f"that does not exist.", icon="ℹ️")

o1, o2 = st.columns(2)
with o1:
    if m.diems and m.diems < DIEMS_BRS_START:
        toggle("Opted into BRS during the 2018 window", m, "opted_into_brs",
               key=wkey("brsopt"))
with o2:
    if m.diems and m.diems < DIEMS_BRS_START:
        toggle("Took the CSB/REDUX bonus at 15 years", m, "took_csb_redux",
               key=wkey("csb"),
               help="No new elections have been possible since 2017. This is a "
                    "historical fact to record, not a decision to make.")

st.markdown("---")
st.markdown("### Household and location")

l1, l2, l3 = st.columns(3)
with l1:
    toggle("Married", h, "has_spouse", key=wkey("married"))
    integer("Dependents", h, "n_dependents", key=wkey("deps"), max_value=15)
with l2:
    toggle("Has dependents for pay purposes", m, "has_dependents", key=wkey("hasdep"),
           help="BAH is binary: with or without dependents. The number of "
                "dependents does not change the rate.")
    toggle("Lives in government housing", m, "lives_in_government_housing",
           key=wkey("govqtrs"),
           help="On-base or privatized housing. BAH is paid to the housing "
                "partner rather than to you, so your out-of-pocket is zero and "
                "so is the allowance you keep.")
with l3:
    text("Duty station ZIP code", m, "duty_zip", key=wkey("zip"),
         placeholder="28310",
         help="Drives your BAH. Leave blank if you do not know where you are "
              "going yet — the app will use a national median instead.")

s1, s2 = st.columns(2)
with s1:
    text("State of legal residence", h, "state_of_legal_residence", key=wkey("slr"),
         help="Where you pay income tax. Under SCRA you do not acquire a new "
              "domicile just by being stationed somewhere. Establishing "
              "residence in a no-income-tax state — at a genuine PCS to it — "
              "can follow you for an entire career and into retirement.")
with s2:
    text("State where you currently live", h, "current_state", key=wkey("curstate"))

if (h.state_of_legal_residence or "").strip().lower() != (h.current_state or "").strip().lower():
    st.info("Your legal residence differs from where you live. That is normal "
            "and legal for a service member under SCRA — military pay is taxed "
            "only by your state of legal residence regardless of duty station. "
            "It does require a genuine connection to that state, and states do "
            "audit it.", icon="📍")

st.markdown("---")
st.markdown("### Deployment")

d1, d2, d3 = st.columns(3)
with d1:
    toggle("Currently deployed", m, "is_deployed", key=wkey("deployed"))
    integer("Months deployed this year", m, "months_deployed_this_year",
            key=wkey("depmo"), max_value=12)
with d2:
    toggle("Drawing hostile fire / imminent danger pay", m,
           "drawing_hostile_fire_pay", key=wkey("hfp"),
           help="This is what gates Savings Deposit Program eligibility, not "
                "deployment on its own.")
    toggle("In a designated combat zone", m, "in_combat_zone", key=wkey("czte"),
           help="Drives the Combat Zone Tax Exclusion. Any part of a month in "
                "the zone counts as a full month.")
with d3:
    money("SDP balance", m, "sdp_balance", key=wkey("sdp"), step=500.0)

if m.is_deployed and m.drawing_hostile_fire_pay:
    st.success("**The Savings Deposit Program is open to you.** 10% guaranteed "
               "on up to $10,000, compounded monthly, with interest continuing "
               "for 90 days after you redeploy. Nothing else available to you "
               "returns that with certainty.", icon="💰")
if m.in_combat_zone:
    st.success("**Combat Zone Tax Exclusion applies.** Enlisted and warrant "
               "officers exclude all military pay for the month; commissioned "
               "officers are capped at the highest enlisted basic pay plus "
               "hostile fire pay. This is the cheapest year you will ever have "
               "to fill Roth accounts or convert an old traditional balance.",
               icon="💰")

st.markdown("---")
st.markdown("### Retiree and VA")

if m.component in (RETIRED,) or m.retired_pay_monthly > 0 or m.va_disability_monthly > 0:
    r1, r2, r3 = st.columns(3)
    with r1:
        money("Retired pay, per month (gross)", m, "retired_pay_monthly",
              key=wkey("retpay"), step=100.0)
        toggle("SBP elected", m, "sbp_elected", key=wkey("sbp"))
    with r2:
        money("VA compensation, per month", m, "va_disability_monthly",
              key=wkey("va"), step=50.0,
              help="Tax-free at federal and state level.")
        integer("VA rating (%)", m, "va_rating", key=wkey("varate"),
                max_value=100, step=10)
    with r3:
        toggle("CRDP applies (20+ years and 50%+ rating)", m, "crdp_applies",
               key=wkey("crdp"),
               help="With concurrent receipt your retired pay is not reduced by "
                    "your VA compensation — you receive both in full.")
        money("CRSC, per month", m, "crsc_monthly", key=wkey("crsc"), step=50.0,
              help="Combat-Related Special Compensation is tax-free and is an "
                   "alternative to CRDP, not an addition.")
    if m.va_rating >= 50 and m.years_of_service >= 20 and not m.crdp_applies:
        st.warning("You appear to qualify for CRDP — 20+ years and a rating of "
                   "50% or more. It is automatic and restores retired pay that "
                   "would otherwise be offset. Turn it on.", icon="⚠️")
else:
    st.caption("Set your component to Military Retiree, or enter a VA rating, "
               "to see retiree fields.")

st.markdown("---")
st.markdown("### Civilian income")
money("Civilian wages, per year", m, "civilian_wages_annual", key=wkey("civwage"),
      step=1000.0, help="A second career, or your own civilian job if you are "
                        "Guard or Reserve.")
