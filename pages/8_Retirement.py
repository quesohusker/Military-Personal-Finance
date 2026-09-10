import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import streamlit as st
import pandas as pd
st.set_page_config(page_title="Retirement", page_icon="🎖️", layout="wide")

from ui.panel import (wkey, render_save_load, page_header, section, metric_row,
                      money, number, integer, fmt_money, fmt_pct, esc, md_money)
from engine.retirement import systems as S
from engine.pay import basepay as BP, grades as G
from engine.profile import SYS_BRS, SYS_HIGH3, SYS_REDUX, SYS_FINAL_PAY

h = render_save_load("retire")
m = h.member
page_header("🎖️ Retirement",
            "What your pension is worth, what reaching twenty is worth, and "
            "the one election that can undo a career of saving.")

SYS_MAP = {"High-3": S.SYS_HIGH3, "Blended Retirement System": S.SYS_BRS,
           "CSB/REDUX": S.SYS_REDUX, "Final Pay": S.SYS_FINAL_PAY}
system = SYS_MAP.get(m.retirement_system, S.SYS_HIGH3)

bp_table = BP.load()
bp = BP.lookup(m.grade, m.years_of_service, bp_table,
               override_monthly=m.basic_pay_monthly_override)

# ==========================================================================
with section("Your inputs"):
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Retirement system", m.retirement_system)
        st.caption("Set by your DIEMS date on the Profile page.")
    with c2:
        h3 = st.number_input("High-3 monthly basic pay",
                             value=float(bp.monthly if bp.found else 5000.0),
                             min_value=0.0, step=100.0, format="%.2f",
                             key=wkey("h3"),
                             help="The average of your highest 36 months of "
                                  "BASIC pay — not total compensation, and not "
                                  "including BAH or BAS.")
    with c3:
        at_years = st.number_input("Years of service at retirement",
                                   value=float(max(20.0, m.years_of_service)),
                                   min_value=0.0, max_value=42.0, step=1.0,
                                   format="%.1f", key=wkey("retyos"))
    with c4:
        ret_age = st.number_input("Age at retirement",
                                  value=int(max(38, m.age() + max(0, at_years - m.years_of_service))),
                                  min_value=30, max_value=70, step=1,
                                  key=wkey("retage"))

    a1, a2 = st.columns(2)
    with a1:
        life = st.number_input("Life expectancy", value=90, min_value=65,
                               max_value=110, step=1, key=wkey("life"))
    with a2:
        disc = st.number_input("Real discount rate (%)", value=3.0,
                               min_value=0.0, max_value=10.0, step=0.25,
                               format="%.2f", key=wkey("rdisc"))

pay = S.retired_pay(system, at_years, h3)

# ==========================================================================
with section("Your retired pay"):
    metric_row([
        ("Multiplier", fmt_pct(pay.multiplier, 1)),
        ("Monthly", fmt_money(pay.monthly)),
        ("Annual", fmt_money(pay.annual)),
        ("COLA", "Full CPI" if pay.real_cola_drift == 0 else "CPI − 1%"),
    ])
    if pay.note:
        st.caption(esc(pay.note))

# ==========================================================================
if at_years < 20 or m.years_of_service < 20:
    with section("The 20-year cliff"):
        cliff = S.value_of_reaching_twenty(
            system, m.years_of_service, h3, retirement_age=ret_age,
            life_expectancy=int(life), real_discount_rate=disc / 100.0,
            tsp_balance=m.tsp_traditional_balance + m.tsp_roth_balance)
        if cliff.years_remaining > 0:
            metric_row([
                ("Years remaining", f"{cliff.years_remaining:g}"),
                ("Pension if you stay", f"{fmt_money(cliff.pension_if_you_stay)}/yr"),
                ("Present value", fmt_money(cliff.present_value)),
                ("Per year served", fmt_money(cliff.value_per_remaining_year)),
            ])
        if system != S.SYS_BRS and cliff.years_remaining > 0:
            st.error(esc(cliff.note), icon="⛰️")
        else:
            st.info(esc(cliff.note), icon="ℹ️")

# ==========================================================================
if system == S.SYS_BRS:
    with section("The lump-sum election",
                 "At retirement BRS lets you take 25% or 50% of the discounted "
                 "value of your pension up to Social Security full retirement "
                 "age as cash, with a reduced annuity until then. The election "
                 "is irrevocable."):

        l1, l2 = st.columns([1, 3])
        with l1:
            share = st.radio("Share taken as cash", [0.25, 0.50],
                             format_func=lambda v: f"{v * 100:.0f}%",
                             key=wkey("lsshare"))
            tax = st.select_slider(
                "Your marginal rate in the year you take it",
                options=[0.12, 0.22, 0.24, 0.32, 0.35, 0.37], value=0.32,
                format_func=lambda v: f"{v * 100:.0f}%", key=wkey("lstax"),
                help="It arrives fully taxable in a single year, usually on top "
                     "of a first-year civilian salary. That stacking is what "
                     "pushes the rate up.")

        ls = S.brs_lump_sum(pay.annual, int(ret_age), share=share,
                            marginal_tax_rate=tax)
        with l2:
            if ls.verdict == "Not applicable":
                st.info(esc(ls.reasoning[0]), icon="ℹ️")
            else:
                metric_row([
                    ("Lump sum, gross", fmt_money(ls.lump_sum_gross)),
                    ("After tax", fmt_money(ls.lump_sum_after_tax)),
                    ("Payments given up", fmt_money(ls.total_annuity_given_up)),
                    ("Break-even real return",
                     fmt_pct(ls.breakeven_real_return, 1)),
                ])
                if ls.breakeven_real_return > 0.05:
                    st.error(f"### {esc(ls.verdict)}\n\nYou would need to earn "
                             f"**{fmt_pct(ls.breakeven_real_return, 1)} real, "
                             f"every year, with certainty** just to break even.",
                             icon="🚨")
                else:
                    st.warning(f"### {esc(ls.verdict)}", icon="⚠️")

        if ls.verdict != "Not applicable":
            for r in ls.reasoning:
                st.markdown("- " + esc(r))

# ==========================================================================
with section("How the systems compare",
             "Only one of these applies to you — your DIEMS date chose it. This "
             "is here to show what yours is worth relative to the others, not "
             "to offer a choice you do not have."):
    rows = S.compare_systems(at_years, h3, int(ret_age), int(life),
                             disc / 100.0,
                             tsp_balance_brs=m.tsp_traditional_balance
                             + m.tsp_roth_balance)
    df = pd.DataFrame([{
        "System": r["System"] + ("  ← yours" if r["System"] == system else ""),
        "Multiplier": r["Multiplier"], "Monthly": r["Monthly"],
        "Annual": r["Annual"], "Pension value": r["Pension present value"],
        "Plus TSP / bonus": r.get("TSP from match", 0) + r.get("CSB bonus", 0),
        "Total": r["Total"],
    } for r in rows])
    st.dataframe(df.style.format({
        "Multiplier": "{:.1%}", "Monthly": "${:,.0f}", "Annual": "${:,.0f}",
        "Pension value": "${:,.0f}", "Plus TSP / bonus": "${:,.0f}",
        "Total": "${:,.0f}"}), use_container_width=True, hide_index=True)
    st.caption("REDUX is discounted harder than its multiplier suggests, "
               "because CPI-minus-1% is a real loss compounding for decades "
               "before the age-62 recomputation.")

st.caption("Pension values are replacement-cost estimates for an inflation-"
           "adjusted lifetime income, not cash values. See Assets & Debts for "
           "the full caveat.")
