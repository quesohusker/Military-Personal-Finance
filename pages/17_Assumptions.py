import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import streamlit as st
import pandas as pd

from ui.panel import (wkey, get_household, page_header, two_pane, input_card,
                      section, metric_row, number, integer, toggle, choice,
                      esc, render_findings, mark_dirty, invalidate, VERSION_KEY)
from engine import assumptions as A
from engine import mortality as MORT
from engine.tax import tables as T

# The preset the user last applied. Deliberately not a widget key: it has to
# survive the version bump that refreshes every widget after a preset lands.
LAST_PRESET = "mpf_last_preset"

h = get_household()
a = h.assumptions
m = h.member

page_header("🎛️ What should we assume?",
            "Every projection in the app leans on the same handful of rates. "
            "Set them once here, and read what each one means, what it does "
            "not mean, and which pages it moves.")

inputs, results = two_pane()

# ==========================================================================
# Left: the questions, stacked.
# ==========================================================================
with inputs:
    with input_card("Start from a preset"):
        names = A.PRESET_NAMES
        current = A.matching_preset(a) or st.session_state.get(LAST_PRESET, "Baseline")
        picked = st.selectbox("Which outlook do you want to start from?", names,
                              index=names.index(current) if current in names else 1,
                              key=wkey("as_preset"),
                              help="A preset writes one coherent set onto every "
                                   "question below; change any of them afterwards. "
                                   "The COLA question is never touched, because "
                                   "it is a fact about your retirement system, "
                                   "not an outlook.")
        st.caption(esc(A.presets[picked].rationale))
        if st.button(f"Apply {picked}", key=wkey("as_apply"), type="primary",
                     use_container_width=True):
            changed = A.apply_preset(a, picked)
            st.session_state[LAST_PRESET] = picked
            if changed:
                mark_dirty(); invalidate()
                # The bound widgets below keep their own copy of the old value
                # in session_state, and Streamlit protects a widget created in
                # the current run. Versioning the keys is how this app refreshes
                # them (see wkey in ui/panel.py): every widget becomes new and
                # initialises from the plan.
                st.session_state[VERSION_KEY] = st.session_state.get(VERSION_KEY, 0) + 1
                st.rerun()
            else:
                st.caption("Those are the values already on this page.")

    with input_card("Returns and rates, above inflation"):
        number("Assume a real return of (%)", a, "real_return_pct",
               key=wkey("as_return"), min_value=-5.0, max_value=15.0, step=0.25,
               fmt="%.2f", help=A.explain("real_return_pct").hint)
        number("Assume a real discount rate of (%)", a, "real_discount_rate_pct",
               key=wkey("as_disc"), min_value=-2.0, max_value=12.0, step=0.25,
               fmt="%.2f", help=A.explain("real_discount_rate_pct").hint)
        number("Assume inflation of (%)", a, "inflation_pct",
               key=wkey("as_infl"), min_value=-2.0, max_value=15.0, step=0.25,
               fmt="%.2f", help=A.explain("inflation_pct").hint)
        number("Assume pay raises beat inflation by (%)", a, "pay_raise_real_pct",
               key=wkey("as_raise"), min_value=-5.0, max_value=5.0, step=0.25,
               fmt="%.2f", help=A.explain("pay_raise_real_pct").hint)

    with input_card("Thinking in nominal terms?"):
        # Page-local: a converter, not a stored assumption.
        nominal = st.number_input("What nominal return do you have in mind? (%)",
                                  value=round(A.real_to_nominal(a.real_return_pct,
                                                                a.inflation_pct), 2),
                                  min_value=-10.0, max_value=30.0, step=0.25,
                                  format="%.2f", key=wkey("as_nominal"),
                                  help="The figure a fund factsheet or a bank "
                                       "quotes. This takes your inflation "
                                       "assumption out of it properly.")
        st.caption(f"At {a.inflation_pct:.2f}% inflation that is "
                   f"**{A.nominal_to_real(nominal, a.inflation_pct):.2f}% real** — "
                   f"the number to put in the real return above. Not "
                   f"{nominal - a.inflation_pct:.2f}%: it is (1 + nominal) ÷ "
                   f"(1 + inflation) − 1, not a subtraction.")

    with input_card("Your COLA and your taxes"):
        toggle("Does your retired pay get the full COLA?", a, "cola_full",
               key=wkey("as_cola"), help=A.explain("cola_full").hint)
        choice("Which tax future should we plan for?", a, "tax_scenario",
               A.TAX_SCENARIOS, key=wkey("as_tax"),
               help=A.explain("tax_scenario").hint)

    with input_card("How long to plan for"):
        integer("Plan how many years past the median lifespan?", a,
                "planning_margin_years", key=wkey("as_margin"),
                min_value=-10, max_value=30,
                help=A.explain("planning_margin_years").hint)

# ==========================================================================
# The arithmetic, once every answer is in.
# ==========================================================================
median_age = MORT.life_expectancy(m.age(), m.sex)
plan_age = MORT.planning_age(m.age(), m.sex, margin=a.planning_margin_years)
findings = A.sanity(a, m.retirement_system)
scenario = A.tax_scenario_for(a)


def value_text(name: str) -> str:
    """The current value of one assumption, with its nominal twin if it has one."""
    v = getattr(a, name)
    if isinstance(v, bool):
        return "Yes" if v else "No"
    if isinstance(v, str):
        return v
    if name == "planning_margin_years":
        return f"{int(v)} years → plan to age {plan_age}"
    nominal = A.nominal_equivalent(name, a)
    if nominal is None:
        return f"{float(v):.2f}%"
    return f"{float(v):.2f}% real ≈ {nominal:.2f}% nominal"


# ==========================================================================
# Right: what those answers mean.
# ==========================================================================
with results:
    with section("The numbers you are running on"):
        match = A.matching_preset(a)
        st.caption(f"These are the **{match}** preset values." if match
                   else "A custom set — edited from a preset.")
        metric_row([
            ("Real return", f"{a.real_return_pct:.2f}%"),
            ("Real discount rate", f"{a.real_discount_rate_pct:.2f}%"),
            ("Inflation", f"{a.inflation_pct:.2f}%"),
            ("Pay raises, real", f"{a.pay_raise_real_pct:+.2f}%"),
        ])
        metric_row([
            ("Nominal return",
             f"{A.real_to_nominal(a.real_return_pct, a.inflation_pct):.2f}%"),
            ("Nominal discount rate",
             f"{A.real_to_nominal(a.real_discount_rate_pct, a.inflation_pct):.2f}%"),
            ("Plan to age", f"{plan_age}", f"median {median_age}"),
            ("Tax future", a.tax_scenario),
        ])
        st.caption("Real is above inflation; nominal is the figure you see "
                   "quoted. They are related by (1 + real) × (1 + inflation) "
                   "− 1, so 4% real at 2.5% inflation is 6.6% nominal, not "
                   "6.5%. Every page in the app works in real terms.")

    with section("Do these hang together?"):
        if findings:
            render_findings(findings)
        else:
            st.success("Nothing to flag. The return sits above the discount "
                       "rate, both are inside the historical range, the COLA "
                       "matches your retirement system and you plan past the "
                       "median.", icon="✅")

    with section("What each assumption means"):
        for e in A.explain_all():
            with st.container(border=True):
                st.markdown(f"**{esc(e.question)}** &nbsp;·&nbsp; "
                            f"{esc(value_text(e.field))}")
                if not e.in_range(getattr(a, e.field)):
                    st.warning(f"Outside the reasonable range "
                               f"({esc(e.range_text)}).", icon="⚠️")
                st.markdown(esc(e.what))
                st.markdown("**What it is not.** " + esc(e.what_not))
                st.caption(esc(f"Default {e.default_text}; reasonable range "
                               f"{e.range_text}. {e.reasoning}"))
                st.caption("Moves: " + esc(", ".join(p for p, _ in e.pages)))

    with section("Which pages this moves",
                 "The last column says how each page gets the number today: "
                 "its own input, an engine default, or nothing yet. Until a "
                 "page reads from here, set the same number in both places."):
        st.dataframe(pd.DataFrame(A.pages_moved()), use_container_width=True,
                     hide_index=True)

    with section(f"The tax future in numbers: {scenario.name}"):
        st.markdown(esc(scenario.summary))
        if scenario.verify:
            st.warning(esc(scenario.note), icon="⚠️")
        elif scenario.stress_test:
            st.info(esc(scenario.note), icon="🧪")
        else:
            st.caption(esc(scenario.note))
        st.dataframe(pd.DataFrame(A.bracket_rows(scenario)),
                     use_container_width=True, hide_index=True)
        probe = 80_000.0
        metric_row([
            ("Marginal rate at $80,000, joint",
             f"{scenario.marginal_rate(probe, T.MFJ) * 100:g}%",
             f"current law {A.tax_scenarios[A.TAX_CURRENT].marginal_rate(probe, T.MFJ) * 100:g}%"),
            ("Marginal rate at $80,000, single",
             f"{scenario.marginal_rate(probe, T.SINGLE) * 100:g}%",
             f"current law {A.tax_scenarios[A.TAX_CURRENT].marginal_rate(probe, T.SINGLE) * 100:g}%"),
            ("Engine scenario", scenario.federal_scenario),
        ])
        st.caption("Taxable income, in 2026 dollars, after the standard "
                   "deduction. The Roth conversion engine takes this scenario "
                   "as a TaxPolicy; the flat rates the TSP and SBP pages ask "
                   "for are your bracket today, which this does not change.")
