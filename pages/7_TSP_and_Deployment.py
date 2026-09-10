import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import streamlit as st
import pandas as pd

from ui.panel import (wkey, get_household, page_header, two_pane, input_card,
                      section, metric_row, money, pct, integer, toggle,
                      fmt_money, fmt_pct, esc, md_money)
from engine.retirement import tsp as T
from engine.tax import military as M
from engine.pay import grades as G, bah as BAH, bas as BAS, basepay as BP
from engine.profile import SYS_BRS, has_tsp_match

h = get_household()
m = h.member
page_header("🪖 Combat-zone pay and the TSP",
            "Contribution limits, the match, and what a combat zone opens up.")

# --------------------------------------------------------------------------
# Standing facts from the profile — not answers given on this page.
# --------------------------------------------------------------------------
bp_table = BP.load()
bah_data = BAH.load()
is_officer = False
try:
    is_officer = G.is_officer(G.get(m.grade))
except KeyError:
    pass

bp = BP.lookup(m.grade, m.years_of_service, bp_table,
               override_monthly=m.basic_pay_monthly_override)
basic_annual = bp.annual if bp.found else 0.0

bah_r = BAH.lookup_or_average(m.duty_zip, m.grade, m.has_dependents, bah_data)
bah_annual = (m.bah_monthly_override or (bah_r.monthly if bah_r.found else 0.0)) * 12
bas_annual = (m.bas_monthly_override or BAS.bas_monthly(is_officer).monthly) * 12

is_brs = has_tsp_match(m.retirement_system)
age = m.age()

inputs, results = two_pane()

# ==========================================================================
# Left: the questions, stacked.
# ==========================================================================
with inputs:
    with input_card("What you put into the TSP"):
        pct("How much do you contribute? (% of basic pay)", m, "tsp_contribution_pct",
            key=wkey("tsppct"), step=1.0, max_value=92.0,
            help="TSP elections are a percentage of BASIC PAY — not of your total "
                 "compensation, and not of BAH or BAS.")
        pct("What share goes to Roth?", m, "tsp_roth_share", key=wkey("rothshare"),
            step=5.0, max_value=100.0)

    with input_card("Traditional or Roth?"):
        marginal = st.select_slider("What is your federal tax bracket now?",
                                    options=[0.10, 0.12, 0.22, 0.24, 0.32, 0.35, 0.37],
                                    value=0.12, format_func=lambda v: f"{v*100:.0f}%",
                                    key=wkey("marg"))
        expected = st.select_slider("What bracket do you expect in retirement?",
                                    options=[0.10, 0.12, 0.22, 0.24, 0.32, 0.35, 0.37],
                                    value=0.22, format_func=lambda v: f"{v*100:.0f}%",
                                    key=wkey("expmarg"))

    with input_card("Are you deployed?"):
        toggle("Are you in a combat zone?", m, "in_combat_zone", key=wkey("cz2"))
        integer("How many qualifying months in the zone?", m, "months_deployed_this_year",
                key=wkey("czmo"), max_value=12,
                help="Any part of a month in the zone counts as a whole month. A "
                     "deployment from 1 January to 1 July is SEVEN qualifying "
                     "months, not six.")
        toggle("Drawing hostile fire or imminent danger pay?", m,
               "drawing_hostile_fire_pay", key=wkey("hfp2"))
        money("What is your SDP balance?", m, "sdp_balance", key=wkey("sdp2"), step=500.0)

# ==========================================================================
# The arithmetic, once every answer is in.
# ==========================================================================
match = T.service_match(basic_annual, m.tsp_contribution_pct, is_brs,
                        m.years_of_service)

plan = T.plan_contributions(basic_annual, age, is_brs, m.tsp_contribution_pct,
                            in_combat_zone=m.in_combat_zone,
                            prior_year_wages=m.civilian_wages_annual,
                            years_of_service=m.years_of_service)

split = M.CompensationSplit(basic_pay=basic_annual, bah=bah_annual, bas=bas_annual,
                            special_pay_taxable=m.special_pay_monthly * 12
                            if m.special_pay_taxable else 0.0)
rec, why = T.traditional_or_roth(marginal, split.nontaxable_share,
                                 m.in_combat_zone, expected)

analysis = M.analyse_czte(
    M.CompensationSplit(basic_pay=basic_annual, bah=bah_annual, bas=bas_annual,
                        special_pay_taxable=m.special_pay_monthly * 12
                        if m.special_pay_taxable else 0.0),
    m.grade, m.months_deployed_this_year if m.in_combat_zone else 0)

# ==========================================================================
# Right: what those answers mean.
# ==========================================================================
with results:
    with section("The match"):
        if not is_brs:
            st.info(f"**{m.retirement_system} — there is no TSP match.** "
                    f"{esc(match.note)}", icon="ℹ️")
        else:
            k = st.columns(4)
            k[0].metric("You contribute", f"{fmt_money(match.member_contribution)}/yr")
            k[1].metric("Automatic 1%", f"{fmt_money(match.automatic)}/yr")
            k[2].metric("Matching", f"{fmt_money(match.matching)}/yr")
            k[3].metric("Unclaimed", f"{fmt_money(match.unclaimed)}/yr",
                        delta_color="inverse")
            if match.unclaimed > 0:
                st.error(esc(match.note), icon="🚨")
            else:
                st.success(esc(match.note), icon="✅")

        if is_brs and basic_annual > 0:
            rows = []
            for p_ in (0.0, 0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.10):
                r = T.service_match(basic_annual, p_, True, m.years_of_service)
                rows.append({"You contribute": f"{p_ * 100:.0f}%",
                             "Your dollars": r.member_contribution,
                             "Service adds": r.total_service,
                             "Total into TSP": r.member_contribution + r.total_service,
                             "Left behind": r.unclaimed})
            st.dataframe(pd.DataFrame(rows).style.format({
                "Your dollars": "${:,.0f}", "Service adds": "${:,.0f}",
                "Total into TSP": "${:,.0f}", "Left behind": "${:,.0f}"}),
                use_container_width=True, hide_index=True)
            st.caption("The service contribution stops rising at 5%. Contributing more "
                       "is often still right — but not for the match.")

        st.info("**Service automatic and matching contributions always go to the "
                "TRADITIONAL balance**, however you designate your own. A member "
                "contributing 100% Roth still accumulates a traditional balance from "
                "the match, and will have required distributions on it later.", icon="📌")

    with section("Your limits this year"):
        metric_row([
            ("Your contribution limit", fmt_money(plan.elective_limit)),
            ("On track to contribute", fmt_money(plan.member_regular)),
            ("Annual addition limit", fmt_money(plan.annual_addition_limit)),
            ("Age", str(age)),
        ])
        for n in plan.notes:
            st.caption("• " + esc(n))

    with section("Traditional or Roth"):
        if rec == "Roth":
            st.success(f"### {rec}\n{esc(why)}", icon="✅")
        elif rec == "Traditional":
            st.info(f"### {rec}\n{esc(why)}", icon="ℹ️")
        else:
            st.warning(f"### {rec}\n{esc(why)}", icon="⚖️")

        if split.gross > 0:
            st.caption(esc(M.effective_tax_rate_note(split)))

    with section("Deployment"):
        if analysis.months > 0:
            metric_row([
                ("Taxable without CZTE", fmt_money(analysis.taxable_without)),
                ("Taxable with CZTE", fmt_money(analysis.taxable_with),
                 fmt_money(-analysis.excluded)),
                ("Excluded", fmt_money(analysis.excluded)),
            ])
            if analysis.is_capped:
                st.warning(esc(analysis.cap_note), icon="⚠️")
            else:
                st.success(esc(analysis.cap_note), icon="✅")
        else:
            st.caption("Turn on the combat zone toggle and enter qualifying months "
                       "to see what the exclusion is worth.")

    if analysis.months > 0:
        with section("What this year unlocks, in order"):
            for i, (title, detail) in enumerate(analysis.opportunities, start=1):
                with st.container(border=True):
                    st.markdown(f"**{i}. {esc(title)}**")
                    st.markdown(esc(detail))

            if m.drawing_hostile_fire_pay:
                remaining = max(0.0, h.limits.sdp_cap - m.sdp_balance)
                if remaining > 0:
                    st.error(f"**Fund the SDP first: {md_money(remaining)} of room "
                             f"left.** A guaranteed 10% has no substitute here.",
                             icon="💰")
                else:
                    st.success("SDP is funded to the cap.", icon="✅")
            else:
                st.caption("SDP requires hostile fire or imminent danger pay, not "
                           "merely deployment. Turn that on in the Deployment card "
                           "if it applies.")

        if m.in_combat_zone and plan.taxexempt_overflow_capacity > 0:
            with section("The combat zone TSP overflow"):
                st.markdown(
                    f"""
Normally your own contributions stop at **{md_money(plan.elective_limit)}**.
In a combat zone, total additions are bounded by the much higher annual
addition limit of **{md_money(plan.annual_addition_limit)}** instead.

But **Roth TSP is still capped at {md_money(plan.elective_limit)}**. So:

1. Fill **Roth TSP** to {md_money(plan.elective_limit)} with tax-free pay.
2. Overflow up to **{md_money(plan.taxexempt_overflow_capacity)}** more into
   **traditional** TSP as tax-exempt contributions.

Those overflow dollars are contributed with pay that was never taxed, and are
never taxed again on withdrawal — only their earnings are. It is the closest
thing to a mega backdoor Roth available to a service member.

One caution: a tax-exempt traditional balance cannot be cleanly rolled into a
traditional IRA, so it needs deliberate handling at separation rather than a
default rollover.
                    """)

    st.caption("Rates and limits are 2026. Free financial counselling is available "
               "through Military OneSource at 800-342-9647.")
