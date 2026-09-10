import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import streamlit as st

from ui.panel import (wkey, get_household, page_header, two_pane, input_card,
                      section, metric_row, money, integer, toggle, fmt_money,
                      fmt_pct, esc, md_money, render_findings)
from engine.benefits import sbp as SBP
from engine.benefits import concurrent_receipt as CR

h = get_household()
m = h.member
page_header("🛡️ Survivors, SBP and the VA",
            "The Survivor Benefit Plan, and the concurrent-receipt election "
            "where the default choice can be the wrong one.")

inputs, results = two_pane()

# ==========================================================================
# Left: the questions, stacked.
# ==========================================================================
with inputs:
    with input_card("Survivor Benefit Plan"):
        toggle("SBP elected", m, "sbp_elected", key=wkey("sbpel"))
        money("Retired pay, per month", m, "retired_pay_monthly",
              key=wkey("rp"), step=100.0)
        base = st.number_input("Base amount elected (0 = full retired pay)",
                               value=0.0, min_value=0.0, step=100.0,
                               format="%.2f", key=wkey("sbpbase"))

    with input_card("Ages and life expectancy"):
        ret_age = st.number_input("Age at retirement", value=int(max(38, m.age())),
                                  min_value=30, max_value=70, key=wkey("sra"))
        my_life = st.number_input("Your life expectancy", value=82,
                                  min_value=60, max_value=105, key=wkey("mylife"))
        sp_life = st.number_input("Survivor's life expectancy", value=90,
                                  min_value=60, max_value=110, key=wkey("splife"),
                                  help="SBP's value is concentrated in the case "
                                       "where your survivor lives a long time — "
                                       "which is exactly what insurance is for. "
                                       "Move this and watch the ratio.")
        sp_age = st.number_input("Survivor's age at your retirement",
                                 value=int(max(30, ret_age - 2)),
                                 min_value=20, max_value=90, key=wkey("spage"))

    with input_card("Tax rates and DIC"):
        my_rate = st.select_slider("Your marginal rate",
                                   options=[0.10, 0.12, 0.22, 0.24, 0.32, 0.35],
                                   value=0.22, format_func=lambda v: f"{v*100:.0f}%",
                                   key=wkey("myrate"))
        sp_rate = st.select_slider("Survivor's marginal rate",
                                   options=[0.10, 0.12, 0.22, 0.24, 0.32],
                                   value=0.12, format_func=lambda v: f"{v*100:.0f}%",
                                   key=wkey("sprate"),
                                   help="Filing single after your death, so "
                                        "brackets are roughly half as wide.")
        dic = st.toggle("Survivor would qualify for DIC", value=False,
                        key=wkey("dicq"),
                        help="Generally applies if you were rated totally "
                             "disabled for the qualifying period, or die of a "
                             "service-connected cause.")

    with input_card("VA rating"):
        integer("VA rating (%)", m, "va_rating", key=wkey("var2"), max_value=100,
                step=10)
        combat = st.toggle("Some disabilities may be combat-related", value=False,
                           key=wkey("combatrel"),
                           help="Armed conflict, hazardous service, an "
                                "instrumentality of war, or training simulating "
                                "war. Your branch makes the determination, not "
                                "you — if in doubt, apply.")
        ch61 = st.toggle("Chapter 61 medical retirement", value=False,
                         key=wkey("ch61"))

    with input_card("CRDP and CRSC estimates"):
        crdp_amt = st.number_input("Estimated CRDP, per month", value=0.0,
                                   min_value=0.0, step=50.0, format="%.2f",
                                   key=wkey("crdpamt"))
        crsc_amt = st.number_input("Estimated CRSC, per month", value=0.0,
                                   min_value=0.0, step=50.0, format="%.2f",
                                   key=wkey("crscamt"))
        combined = st.select_slider(
            "Your combined federal + state marginal rate",
            options=[0.10, 0.15, 0.22, 0.24, 0.27, 0.29, 0.32, 0.37],
            value=0.24, format_func=lambda v: f"{v*100:.0f}%",
            key=wkey("crrate"))

# ==========================================================================
# The arithmetic, once every answer is in.
# ==========================================================================
a = None
if m.retired_pay_monthly > 0:
    a = SBP.analyse(retired_pay_monthly=m.retired_pay_monthly,
                    retirement_age=int(ret_age),
                    base_amount_monthly=base,
                    member_life_expectancy=int(my_life),
                    survivor_life_expectancy=int(sp_life),
                    survivor_age_at_retirement=int(sp_age),
                    marginal_tax_rate=my_rate,
                    survivor_marginal_rate=sp_rate,
                    dic_applies=dic)

elig = CR.eligibility(m.years_of_service, m.va_rating, combat, ch61)

comp = None
if crdp_amt > 0 and crsc_amt > 0:
    comp = CR.compare(crdp_amt, crsc_amt, marginal_tax_rate=combined)

# ==========================================================================
# Right: what those answers mean.
# ==========================================================================
with results:
    with section("Survivor Benefit Plan",
                 "SBP pays your survivor 55% of an elected base amount, for life, "
                 "indexed to inflation. The election is effectively irrevocable and "
                 "you make it before you retire."):

        if a is not None:
            metric_row([
                ("Premium", f"{fmt_money(a.premium_monthly)}/mo",
                 f"{fmt_money(a.premium_after_tax_monthly)}/mo after tax"),
                ("Survivor receives", f"{fmt_money(a.survivor_total_monthly)}/mo"),
                ("You pay for", f"{a.years_paying:.0f} years"),
                ("Then", "Nothing, for life"),
            ])
            metric_row([
                ("Premiums, present value", fmt_money(a.premiums_present_value)),
                ("Benefit, present value", fmt_money(a.annuity_present_value)),
                ("Ratio",
                 f"{a.annuity_present_value / a.premiums_present_value:.1f}x"
                 if a.premiums_present_value else "—"),
                ("Equivalent insurance", fmt_money(a.equivalent_term_face)),
            ])

            for n in a.notes:
                st.markdown("- " + esc(n))

            st.divider()
            render_findings(SBP.findings(a, m.sbp_elected, h.has_spouse))
        else:
            st.info("Enter your retired pay on the left to price SBP.", icon="ℹ️")

    with section("CRDP or CRSC",
                 "Both restore retired pay that your VA compensation would "
                 "otherwise offset. You cannot have both. DFAS pays whichever is "
                 "larger on GROSS — which is not always the better outcome for you."):

        if comp is not None:
            metric_row([
                ("CRDP gross", f"{fmt_money(comp.crdp_gross_annual)}/yr"),
                ("CRDP after tax", f"{fmt_money(comp.crdp_after_tax)}/yr"),
                ("CRSC (tax-free)", f"{fmt_money(comp.crsc_after_tax)}/yr"),
                ("Better after tax", comp.better_by_after_tax),
            ])
            if comp.mismatch:
                st.error(esc(comp.notes[0]), icon="🚨")
            else:
                st.success(esc(comp.notes[0]), icon="✅")
            for n in comp.notes[1:]:
                st.caption("• " + esc(n))
        else:
            st.caption("Enter both estimated amounts to compare them after tax. "
                       "DFAS can tell you what each would pay; the comparison "
                       "against your own bracket is the part they do not do.")

        st.divider()
        render_findings(CR.findings(elig, comp, m.va_rating, m.years_of_service, ch61))

    st.caption("Estimates only. Your branch determines CRSC eligibility, and DFAS "
               "computes the actual amounts. Free help is available through "
               "Military OneSource at 800-342-9647 and from your installation's "
               "legal assistance office.")
