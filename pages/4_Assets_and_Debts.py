import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import streamlit as st
import pandas as pd
st.set_page_config(page_title="Assets & Debts", page_icon="🏦", layout="wide")

from ui.panel import (wkey, render_save_load, page_header, money, pct, integer,
                      fmt_money, fmt_pct, esc, md_money, render_findings)
from engine.networth import balance_sheet as BS

h = render_save_load("networth")
m = h.member
page_header("🏦 Assets & Debts",
            "Your balance sheet — including the asset most planning tools leave "
            "off entirely.")

st.markdown("### Cash and investments")
c1, c2, c3 = st.columns(3)
with c1:
    money("Cash and savings", h, "cash_savings", key=wkey("cash"), step=500.0)
    money("Monthly expenses", h, "monthly_expenses", key=wkey("expenses"),
          step=100.0, help="Everything you spend in a month, excluding income "
                           "tax. Used to size your emergency fund.")
with c2:
    money("Taxable brokerage", h, "taxable_brokerage", key=wkey("brok"), step=1000.0)
    money("Other assets", h, "other_assets", key=wkey("otherassets"), step=1000.0)
with c3:
    money("Home value", h, "home_value", key=wkey("home"), step=5000.0)
    money("Vehicles", h, "vehicles_value", key=wkey("vehicles"), step=1000.0)

st.markdown("### Retirement accounts")
r1, r2, r3, r4 = st.columns(4)
with r1:
    money("Traditional TSP", m, "tsp_traditional_balance", key=wkey("tsptrad"),
          step=1000.0)
with r2:
    money("Roth TSP", m, "tsp_roth_balance", key=wkey("tsproth"), step=1000.0)
with r3:
    money("Traditional IRA", m, "ira_traditional_balance", key=wkey("iratrad"),
          step=1000.0)
with r4:
    money("Roth IRA", m, "ira_roth_balance", key=wkey("iraroth"), step=1000.0)

st.caption("Service automatic and matching contributions always land in the "
           "**traditional** balance, regardless of how you designate your own "
           "contributions. A BRS member contributing entirely to Roth TSP still "
           "accumulates a traditional balance from the match.")

st.markdown("### Mortgage")
money("Mortgage balance", h, "mortgage_balance", key=wkey("mortgage"), step=1000.0)
st.caption("Other debts are entered on the **Debt Payoff** page and flow through "
           "to this balance sheet automatically.")

# --------------------------------------------------------------------------
st.markdown("---")
st.markdown("### Assumptions")
a1, a2 = st.columns(2)
with a1:
    life_exp = st.number_input("Life expectancy", value=90, min_value=60,
                               max_value=110, step=1, key=wkey("lifeexp"))
with a2:
    disc = st.number_input("Real discount rate for income streams (%)",
                           value=3.0, min_value=0.0, max_value=10.0, step=0.25,
                           format="%.2f", key=wkey("disc"),
                           help="A REAL rate, because military retired pay and "
                                "VA compensation both keep pace with inflation. "
                                "Discounting a COLA'd stream at a nominal rate "
                                "understates it badly.")

bs = BS.from_household(h, life_expectancy=int(life_exp),
                       real_discount_rate=disc / 100.0)

# --------------------------------------------------------------------------
st.markdown("---")
st.markdown("## Net worth")

k = st.columns(4)
k[0].metric("Total assets", fmt_money(bs.total_assets))
k[1].metric("Total liabilities", fmt_money(bs.total_liabilities))
k[2].metric("Net worth", fmt_money(bs.net_worth))
k[3].metric("After embedded tax", fmt_money(bs.net_worth_after_tax),
            fmt_money(-bs.embedded_tax), delta_color="inverse")

k2 = st.columns(4)
k2[0].metric("Liquid net worth", fmt_money(bs.liquid_net_worth))
k2[1].metric("Investable assets", fmt_money(bs.investable_assets))
k2[2].metric("Home equity", fmt_money(bs.home_equity))
k2[3].metric("Pre-tax share of retirement",
             fmt_pct(bs.pretax_retirement / bs.retirement_assets
                     if bs.retirement_assets else 0, 0))

rows = [
    ("Cash and savings", bs.cash), ("Taxable brokerage", bs.taxable_brokerage),
    ("SDP", bs.sdp_balance), ("Traditional TSP + IRA", bs.pretax_retirement),
    ("Roth TSP + IRA", bs.aftertax_retirement), ("Home", bs.home_value),
    ("Vehicles", bs.vehicles), ("Other assets", bs.other_assets),
    ("Mortgage", -bs.mortgage_balance), ("Consumer debt", -bs.consumer_debt),
    ("Vehicle debt", -bs.vehicle_debt), ("Other debt", -bs.other_debt),
]
df = pd.DataFrame([{"Item": n, "Amount": v} for n, v in rows if abs(v) > 0])
if not df.empty:
    st.dataframe(df.style.format({"Amount": "${:,.0f}"}),
                 use_container_width=True, hide_index=True)

# --------------------------------------------------------------------------
if bs.streams:
    st.markdown("---")
    st.markdown("## Guaranteed income")

    st.warning(BS.VALUATION_CAVEAT, icon="⚠️")

    srows = [{"Stream": s.label,
              "Annual amount": s.annual_amount,
              "Years": round(s.years, 1),
              "Taxable": "Yes" if s.is_taxable else "No — tax-free",
              "Replacement cost": s.present_value} for s in bs.streams]
    st.dataframe(pd.DataFrame(srows).style.format(
        {"Annual amount": "${:,.0f}", "Replacement cost": "${:,.0f}"}),
        use_container_width=True, hide_index=True)

    g = st.columns(3)
    g[0].metric("Total replacement cost", fmt_money(bs.streams_present_value))
    g[1].metric("Investable assets", fmt_money(bs.investable_assets))
    g[2].metric("Net worth + replacement cost",
                fmt_money(bs.net_worth_with_streams))

    with st.expander("How this is calculated, and its limits"):
        st.markdown(f"""
Each stream is valued as a level **real** annuity — the same inflation-adjusted
amount every year from your current age to the life expectancy you set above —
discounted at **{disc:.2f}%** real.

A real discount rate is used deliberately. Military retired pay and VA
compensation are both indexed to inflation, so their purchasing power is level.
Discounting a COLA-adjusted stream at a nominal rate is a common error, and it
is precisely the error that makes lump-sum buyout offers look reasonable when
they are not.

**The number is sensitive to two assumptions you control.** A longer life
expectancy raises it; a higher discount rate lowers it. Move both and see. If
the conclusion you are drawing flips between plausible settings, it was not a
strong conclusion.

**It is not, and does not become:** a spendable balance, an input to a
withdrawal rate, or an estate figure.
        """)

st.markdown("---")
render_findings(BS.findings(bs, h))
