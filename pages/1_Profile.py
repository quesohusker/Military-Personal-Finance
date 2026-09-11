import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import streamlit as st

from datetime import date
from ui.panel import (wkey, get_household, page_header, two_pane, input_card,
                      money, pct, integer, number, text, toggle, choice,
                      fmt_money, mark_dirty, invalidate)
from engine.profile import (COMPONENTS, SERVING, ACTIVE, RETIRED,
                            retirement_system_for_diems, has_tsp_match,
                            SYS_BRS, SYS_REDUX, DIEMS_BRS_START)
from engine.pay import grades as G
from engine import mortality as MORT

h = get_household()
m = h.member

page_header("👤 Profile",
            "The DIEMS date matters more than anything else here — it decides "
            "your retirement system, which decides whether a TSP match exists "
            "at all.")

inputs, results = two_pane()

# ==========================================================================
# Left: the questions, stacked.
# ==========================================================================
with inputs:
    with input_card("About your service"):
        choice("What component are you in?", m, "component", COMPONENTS, key=wkey("comp"))
        choice("Which branch?", m, "branch", G.BRANCHES, key=wkey("branch"))
        choice("What is your pay grade?", m, "grade", G.GRADE_LABELS, key=wkey("grade"),
               help="O-1E, O-2E and O-3E are for officers with at least four "
                    "years of prior enlisted or warrant service. They are paid "
                    "on a separate, higher line.")
        number("How many years have you served?", m, "years_of_service", key=wkey("yos"),
               min_value=0.0, max_value=45.0, step=0.5)
        text("What is your Date of Rank? (YYYY-MM-DD)", m, "date_of_rank",
             key=wkey("dor"), placeholder="2023-06-01",
             help="The day you pinned on your current grade. It is on your LES "
                  "and your ORB or ERB. It is NOT your DIEMS date and NOT the "
                  "day you joined — it resets at every promotion. Given it, "
                  "the app works out your time in grade and keeps it right as "
                  "the years pass; leave it blank and it asks you for the "
                  "number instead, which is correct on the day you type it and "
                  "stale every time you open the plan afterwards.")
        if m.dor is not None:
            st.caption(f"Time in grade: {m.time_in_grade():.1f} years.")
        else:
            number("How long in your current grade?", m, "time_in_grade_years",
                   key=wkey("tig"), min_value=0.0, max_value=30.0, step=0.5,
                   help="Only asked because there is no Date of Rank above. "
                        "Enter that instead and this looks after itself.")
        integer("What year were you born?", m, "birth_year", key=wkey("by"),
                min_value=1930, max_value=2010)
        choice("Which sex should we use for life expectancy?", m, "sex",
               MORT.SEXES, key=wkey("sex"),
               format_func=lambda v: v or "Prefer not to say",
               help="Only used to pick a mortality table for the pension, SBP "
                    "and insurance pages. About three years separates the two. "
                    "Leave it unset and the app uses the midpoint.")

    with input_card("When you first joined"):
        text("What is your DIEMS date? (YYYY-MM-DD)", m, "diems_date", key=wkey("diems"),
             help="Date of Initial Entry to Military Service — the day you "
                  "first swore in, including at an academy or in ROTC "
                  "contracted status. It is on your LES and your DD-214. It is "
                  "NOT the date you started your current period of service.")
        if m.diems and m.diems < DIEMS_BRS_START:
            toggle("Did you opt into BRS in the 2018 window?", m, "opted_into_brs",
                   key=wkey("brsopt"))
            toggle("Did you take the CSB/REDUX bonus at 15 years?", m,
                   "took_csb_redux", key=wkey("csb"),
                   help="No new elections have been possible since 2017. This "
                        "is a historical fact to record, not a decision to "
                        "make.")

    with input_card("Your household and where you are"):
        toggle("Are you married?", h, "has_spouse", key=wkey("married"))
        integer("How many dependents?", h, "n_dependents", key=wkey("deps"), max_value=15)
        toggle("Do you have dependents for pay purposes?", m, "has_dependents",
               key=wkey("hasdep"),
               help="BAH is binary: with or without dependents. The number of "
                    "dependents does not change the rate.")
        toggle("Do you live in government housing?", m,
               "lives_in_government_housing", key=wkey("govqtrs"),
               help="On-base or privatized housing. BAH is paid to the housing "
                    "partner rather than to you, so your out-of-pocket is zero "
                    "and so is the allowance you keep.")
        text("What is your duty station ZIP code?", m, "duty_zip", key=wkey("zip"),
             placeholder="28310",
             help="Drives your BAH. Leave blank if you do not know where you "
                  "are going yet — the app will use a national median instead.")
        text("Which state is your legal residence?", h, "state_of_legal_residence",
             key=wkey("slr"),
             help="Where you pay income tax. Under SCRA you do not acquire a "
                  "new domicile just by being stationed somewhere.")
        text("Which state do you live in now?", h, "current_state",
             key=wkey("curstate"))

    with input_card("Are you deployed?"):
        toggle("Are you deployed right now?", m, "is_deployed", key=wkey("deployed"))
        integer("How many months deployed this year?", m, "months_deployed_this_year",
                key=wkey("depmo"), max_value=12)
        toggle("Drawing hostile fire or imminent danger pay?", m,
               "drawing_hostile_fire_pay", key=wkey("hfp"),
               help="This is what gates Savings Deposit Program eligibility, "
                    "not deployment on its own.")
        toggle("Are you in a designated combat zone?", m, "in_combat_zone",
               key=wkey("czte"),
               help="Drives the Combat Zone Tax Exclusion. Any part of a month "
                    "in the zone counts as a full month.")
        money("What is your SDP balance?", m, "sdp_balance", key=wkey("sdp"), step=500.0)

    show_retiree = (m.component in (RETIRED,) or m.retired_pay_monthly > 0
                    or m.va_disability_monthly > 0)
    if show_retiree:
        with input_card("Your retired pay and VA"):
            money("What is your gross retired pay, per month?", m, "retired_pay_monthly",
                  key=wkey("retpay"), step=100.0)
            toggle("Did you elect SBP?", m, "sbp_elected", key=wkey("sbp"))
            money("What is your VA compensation, per month?", m, "va_disability_monthly",
                  key=wkey("va"), step=50.0,
                  help="Tax-free at federal and state level.")
            integer("What is your VA rating? (%)", m, "va_rating", key=wkey("varate"),
                    max_value=100, step=10)
            toggle("Does CRDP apply? (20+ years, 50%+ rating)", m, "crdp_applies",
                   key=wkey("crdp"),
                   help="With concurrent receipt your retired pay is not "
                        "reduced by your VA compensation — you receive both in "
                        "full.")
            money("What CRSC do you receive, per month?", m, "crsc_monthly", key=wkey("crsc"),
                  step=50.0,
                  help="Combat-Related Special Compensation is tax-free and is "
                       "an alternative to CRDP, not an addition.")

    with input_card("Civilian income"):
        money("What do you earn in civilian wages, per year?", m, "civilian_wages_annual",
              key=wkey("civwage"), step=1000.0,
              help="A second career, or your own civilian job if you are Guard "
                   "or Reserve.")

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
