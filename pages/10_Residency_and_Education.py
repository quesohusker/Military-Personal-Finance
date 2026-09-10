import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import streamlit as st
import pandas as pd

from ui.panel import (wkey, get_household, page_header, two_pane, input_card, section, metric_row, money, integer, number, toggle, choice, fmt_money, fmt_pct, esc, md_money)
from engine.tax import domicile as D
from engine.benefits import gi_bill as GI
from engine.pay import bah as BAH
from engine.pay import taxable as TX

h = get_household()
m = h.member
page_header("🗺️ Residency & GI Bill",
            "Where you pay state tax, and what your GI Bill is worth.")

inputs, results = two_pane()

# ==========================================================================
# Left: the questions, stacked.
# ==========================================================================
with inputs:
    with input_card("Where do you pay tax?"):
        slr = st.selectbox("Which state is your legal residence?", D.STATE_NAMES,
                           index=D.STATE_NAMES.index(h.state_of_legal_residence)
                           if h.state_of_legal_residence in D.STATE_NAMES else 0,
                           key=wkey("slr2"))
        h.state_of_legal_residence = slr
        # Compare against where you are actually stationed. Texas is only
        # the fallback for a blank or unrecognised duty state.
        duty = (h.current_state or "").strip().lower()
        alt_default = next((n for n in D.STATE_NAMES if n.lower() == duty),
                           "Texas")
        alt = st.selectbox("Which state do you want to compare with?", D.STATE_NAMES,
                           index=D.STATE_NAMES.index(alt_default),
                           key=wkey("altstate"),
                           help="Defaults to the state you live in now, from "
                                "Profile.")

    with input_card("What you earn, and for how long"):
        # Derived, not typed: the Pay page already knows this number.
        tp = TX.compute(m)
        taxable_pay = tp.annual
        annual_retired = TX.annual_retired_pay(m)
        st.markdown(esc(f"**Taxable military pay: {fmt_money(taxable_pay)} a year**"))
        st.caption(esc(tp.describe())
                   + (" Change any of these on **Income**."
                      if tp.serving else ""))
        for note in tp.notes:
            st.warning(esc(note), icon="⚠️")
        if not m.is_serving and annual_retired <= 0:
            st.warning("Retired pay is not entered. Add it on **Profile** so "
                       "the retirement years can be compared.", icon="⚠️")
        ad_years = st.number_input("How many years will you serve?",
                                   value=20.0 if m.is_serving else 0.0,
                                   min_value=0.0, max_value=42.0, step=1.0,
                                   key=wkey("adyrs"))
        ret_years = st.number_input("How many years will you draw retired pay?", value=30.0,
                                    min_value=0.0, max_value=60.0, step=1.0,
                                    key=wkey("retyrs"))

    with input_card("How the states rank for you"):
        sp_inc = st.number_input("What does your spouse earn, per year?",
                                 value=float(h.spouse_income.annual_income),
                                 min_value=0.0, step=1000.0, format="%.0f",
                                 key=wkey("spincrank"),
                                 help="This is what separates states that merely "
                                      "exempt military pay from states with no "
                                      "income tax at all.")

    with input_card("Where will you study?"):
        school = st.selectbox("What kind of school is it?", GI.SCHOOL_TYPES, key=wkey("school"))
        tuition = st.number_input("What are tuition and fees, per year?", value=12_000.0,
                                  min_value=0.0, step=500.0, format="%.0f",
                                  key=wkey("tuition"))
        school_zip = st.text_input("What is the school ZIP code?", value="", key=wkey("schoolzip"),
                                   placeholder="78712",
                                   help="Housing pays the E-5-with-dependents "
                                        "BAH rate at the SCHOOL's location — not "
                                        "yours, and not your pay grade.")

    with input_card("Who will use the GI Bill?"):
        child_age = st.number_input("How old is your child? (0 for a spouse)",
                                    value=14, min_value=0, max_value=30,
                                    key=wkey("childage"))
        has_degree = st.toggle("Do you already have the degree you need?",
                               value=False, key=wkey("hasdegree"))
        still_in = st.toggle("Are you still serving?", value=m.is_serving, key=wkey("stillin"))

# ==========================================================================
# The maths, once the answers are in.
# ==========================================================================
comp = D.compare_states(slr, alt, taxable_pay,
                        annual_retired,
                        ad_years, ret_years,
                        annual_va_compensation=m.va_disability_monthly * 12)

ranked = D.rank_states(taxable_pay, annual_retired,
                       ad_years, ret_years, spouse_income=sp_inc,
                       spouse_years=ad_years)

bah_data = BAH.load()
school_bah = 0.0
school_bah_lookup = None
if school_zip:
    school_bah_lookup = BAH.lookup(school_zip, "E-5", True, bah_data)
    if school_bah_lookup.found:
        school_bah = school_bah_lookup.monthly

mine = GI.value_benefit(school, tuition, school_bah, on_active_duty=True)
theirs = GI.value_benefit(school, tuition, school_bah, on_active_duty=False)

analysis = GI.analyse_transfer(
    m.years_of_service, mine, theirs, already_has_degree=has_degree,
    still_serving=still_in,
    child_age=int(child_age) if child_age > 0 else None)

# ==========================================================================
# Right: what those answers are worth.
# ==========================================================================
with results:
    with section("State of legal residence",
                 "Under SCRA your military pay is taxed only by your state of legal "
                 "residence, whatever your duty station. Over a career and into "
                 "retirement that choice is routinely worth six figures."):

        metric_row([
            (f"{slr} while serving", fmt_money(comp.from_active_tax)),
            (f"{alt} while serving", fmt_money(comp.to_active_tax)),
            (f"{slr} in retirement", fmt_money(comp.from_retired_tax)),
            ("Lifetime difference", fmt_money(comp.lifetime_saving)),
        ])

        if comp.lifetime_saving > 1_000:
            st.success(esc(comp.notes[0] if "tax-free in every state" not in comp.notes[0]
                           else comp.notes[1]), icon="💰")
        for n in comp.notes:
            st.caption("• " + esc(n))

        with st.expander("What establishing domicile actually requires"):
            st.markdown("You cannot simply pick a state. Domicile is intent plus "
                        "objective acts, and states audit it:")
            for a in D.DOMICILE_ACTS:
                st.markdown(f"- {a}")
            st.caption("The practical route is to establish it at a genuine PCS to "
                       "that state, not to declare it from somewhere else.")

        with st.expander("Every state, ranked"):
            df = pd.DataFrame(ranked)[["State", "Rate", "Active duty pay",
                                       "Retired pay", "Military income tax",
                                       "Tax on spouse income", "Lifetime"]]
            st.dataframe(df.style.format({
                "Rate": "{:.2%}", "Military income tax": "${:,.0f}",
                "Tax on spouse income": "${:,.0f}", "Lifetime": "${:,.0f}"}),
                use_container_width=True, hide_index=True, height=340)
            st.info(f"**{len(D.exempt_but_taxing_states()) + len(D.NO_TAX_STATES)} "
                    f"states cost you nothing on military income** — the "
                    f"{len(D.NO_TAX_STATES)} with no income tax, plus "
                    f"{len(D.exempt_but_taxing_states())} more that exempt both "
                    f"active duty and retired pay. They are not equivalent for a "
                    f"household: only the no-income-tax states also leave a "
                    f"spouse's salary, a second career and investment income "
                    f"untaxed.", icon="ℹ️")

        if h.has_spouse:
            st.markdown(esc(D.spouse_residency_note(
                slr, h.current_state, h.current_state)))

    with section("GI Bill — use it or transfer it",
                 "36 months of tuition, housing and books. Transferring requires "
                 "six years of service and four more in obligation."):

        if school_bah_lookup is not None:
            if school_bah_lookup.found:
                st.caption(f"E-5 with dependents at {esc(school_bah_lookup.mha_name)}: "
                           f"{esc(fmt_money(school_bah))}/mo housing allowance.")
            else:
                st.caption("⚠️ " + esc(school_bah_lookup.note))

        metric_row([
            ("If you use it while serving", fmt_money(mine.total)),
            ("If transferred", fmt_money(theirs.total)),
            ("Difference", fmt_money(theirs.total - mine.total)),
            ("Housing component", fmt_money(theirs.housing)),
        ])

        if analysis.recommendation == "Too late to transfer":
            st.error(f"### {esc(analysis.recommendation)}", icon="🚨")
        elif analysis.recommendation == "Not yet eligible":
            st.info(f"### {esc(analysis.recommendation)}", icon="ℹ️")
        else:
            st.success(f"### {esc(analysis.recommendation)}", icon="🎓")

        for r in analysis.reasoning:
            st.markdown("- " + esc(r))

        for n in theirs.notes:
            st.caption("• " + esc(n))

    st.caption("Estimates. VA determines entitlement and school certifying "
               "officials determine tuition. Confirm Yellow Ribbon participation "
               "with the school before enrolling.")
