import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import streamlit as st
import pandas as pd

from ui.panel import (wkey, get_household, page_header, two_pane, input_card,
                      section, money, pct, integer, fmt_money, fmt_pct, esc,
                      md_money, render_findings, mark_dirty, invalidate)
from engine import mortality as MORT
from engine.debt import payoff as P
from engine.networth import balance_sheet as BS

# A real discount rate is not inflation, and people reasonably assume it is.
DISCOUNT_HELP = (
    "NOT inflation. A real discount rate is the return you could earn ABOVE "
    "inflation \u2014 the opportunity cost of the money. This app works in "
    "today's dollars, and military retired pay and VA compensation both keep "
    "pace with inflation, so inflation is already netted out on both sides. "
    "Discounting a COLA'd stream at a nominal rate double-counts inflation and "
    "understates the pension badly. About 3% is what a conservative portfolio "
    "earns above inflation."
)

h = get_household()
m = h.member
page_header("🏦 What I am worth",
            "Your balance sheet — including the asset most planning tools leave "
            "off entirely.")

# --------------------------------------------------------------------------
# Debts belong on the balance sheet, so they are entered here. A six-column
# editor cannot be worked in a narrow column, so it takes the full width
# above the two-pane split rather than sitting in the input column.
# --------------------------------------------------------------------------
st.markdown("### Your debts")
st.caption("Mark anything you took on **before** you entered active duty — the "
           "SCRA 6% cap applies only to those, and it can change which debt is "
           "worth attacking first.")

rows = [{"Name": d.name, "Balance": d.balance, "APR %": d.apr * 100,
         "Minimum payment": d.minimum_payment, "Kind": d.kind,
         "Pre-service": d.incurred_before_service} for d in h.debts]
if not rows:
    rows = [{"Name": "", "Balance": 0.0, "APR %": 0.0, "Minimum payment": 0.0,
             "Kind": "Credit card", "Pre-service": False}]

edited = st.data_editor(
    pd.DataFrame(rows), num_rows="dynamic", use_container_width=True,
    key=wkey("debt_editor"),
    column_config={
        "Balance": st.column_config.NumberColumn(format="$%.2f", min_value=0.0),
        "APR %": st.column_config.NumberColumn(format="%.2f%%", min_value=0.0,
                                               max_value=99.0),
        "Minimum payment": st.column_config.NumberColumn(format="$%.2f",
                                                        min_value=0.0),
        "Kind": st.column_config.SelectboxColumn(options=P.DEBT_KINDS),
        "Pre-service": st.column_config.CheckboxColumn(
            help="Incurred BEFORE you entered active duty. Only these qualify "
                 "for the SCRA 6% cap."),
    })

if st.button("Save these debts", type="primary", key=wkey("savedebts")):
    new = []
    for _, row in edited.iterrows():
        name = str(row.get("Name") or "").strip()
        bal = float(row.get("Balance") or 0)
        if not name or bal <= 0:
            continue
        new.append(P.Debt(name=name, balance=bal,
                          apr=float(row.get("APR %") or 0) / 100.0,
                          minimum_payment=float(row.get("Minimum payment") or 0),
                          kind=str(row.get("Kind") or "Credit card"),
                          incurred_before_service=bool(row.get("Pre-service"))))
    h.debts = new
    mark_dirty(); invalidate()
    st.success(f"Saved {len(new)} debt(s).")
    st.rerun()


inputs, results = two_pane()

# ==========================================================================
# Left: the questions, stacked.
# ==========================================================================
with inputs:
    with input_card("What you own and what you spend"):
        money("How much is in cash and savings?", h, "cash_savings", key=wkey("cash"), step=500.0)
        money("What do you spend in a month?", h, "monthly_expenses", key=wkey("expenses"),
              step=100.0, help="Everything you spend in a month, excluding income "
                               "tax. Used to size your emergency fund.")
        money("What is in your brokerage?", h, "taxable_brokerage", key=wkey("brok"), step=1000.0)
        money("Any other assets?", h, "other_assets", key=wkey("otherassets"), step=1000.0)
        money("What is your home worth?", h, "home_value", key=wkey("home"), step=5000.0)
        money("What are your cars worth?", h, "vehicles_value", key=wkey("vehicles"), step=1000.0)

    with input_card("What have you saved for retirement?"):
        money("How much is in traditional TSP?", m, "tsp_traditional_balance", key=wkey("tsptrad"),
              step=1000.0)
        money("How much is in Roth TSP?", m, "tsp_roth_balance", key=wkey("tsproth"), step=1000.0)
        money("How much is in traditional IRA?", m, "ira_traditional_balance", key=wkey("iratrad"),
              step=1000.0)
        money("How much is in Roth IRA?", m, "ira_roth_balance", key=wkey("iraroth"), step=1000.0)

    with input_card("Do you have a mortgage?"):
        money("How much do you still owe?", h, "mortgage_balance", key=wkey("mortgage"),
              step=1000.0)

    with input_card("What should we assume?"):
        life_exp = st.number_input("How long do you expect to live?",
                                   value=MORT.life_expectancy(m.age(), m.sex),
                                   min_value=60, max_value=110, step=1,
                                   key=wkey("lifeexp"),
                                   help=MORT.explain(m.age(), m.sex))
        disc = st.number_input("Assume a real discount rate of (%)",
                               value=3.0, min_value=0.0, max_value=10.0, step=0.25,
                               format="%.2f", key=wkey("disc"),
                               help=DISCOUNT_HELP)

# ==========================================================================
# What those answers add up to.
# ==========================================================================
bs = BS.from_household(h, life_expectancy=int(life_exp),
                       real_discount_rate=disc / 100.0)

rows = [
    ("Cash and savings", bs.cash), ("Taxable brokerage", bs.taxable_brokerage),
    ("SDP", bs.sdp_balance), ("Traditional TSP + IRA", bs.pretax_retirement),
    ("Roth TSP + IRA", bs.aftertax_retirement), ("Home", bs.home_value),
    ("Vehicles", bs.vehicles), ("Other assets", bs.other_assets),
    ("Mortgage", -bs.mortgage_balance), ("Consumer debt", -bs.consumer_debt),
    ("Vehicle debt", -bs.vehicle_debt), ("Other debt", -bs.other_debt),
]
df = pd.DataFrame([{"Item": n, "Amount": v} for n, v in rows if abs(v) > 0])

# ==========================================================================
# Right: the balance sheet.
# ==========================================================================
with results:
    with section("Net worth"):
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

        if not df.empty:
            st.dataframe(df.style.format({"Amount": "${:,.0f}"}),
                         use_container_width=True, hide_index=True)

        st.caption("Service automatic and matching contributions always land in "
                   "the **traditional** balance, regardless of how you designate "
                   "your own contributions. A BRS member contributing entirely to "
                   "Roth TSP still accumulates a traditional balance from the "
                   "match.")
        st.caption("Debts entered in the table above flow into this balance "
                   "sheet; the **Getting out of debt** page works from the "
                   "same list.")

    # ----------------------------------------------------------------------
    if bs.streams:
        with section("Guaranteed income"):
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
amount every year from your current age to the life expectancy you set —
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

    # ----------------------------------------------------------------------
    render_findings(BS.findings(bs, h))
