import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import streamlit as st
import pandas as pd

from ui.panel import (wkey, get_household, page_header, two_pane, input_card,
                      section, metric_row, fmt_money, esc, md_money,
                      render_findings)
from engine.debt import payoff as P
from engine.profile import SERVING

h = get_household()
m = h.member
page_header("💳 Getting out of debt",
            "Avalanche against snowball, with the SCRA interest cap priced in.")

# --------------------------------------------------------------------------
# Debts are entered on "What I am worth", because that is where they belong on
# a balance sheet. This page consumes them.
# --------------------------------------------------------------------------
if h.debts:
    with st.expander(f"Your {len(h.debts)} debt(s) — edit them on "
                     f"'What I am worth'", expanded=False):
        st.dataframe(
            pd.DataFrame([{"Name": d.name, "Balance": d.balance,
                           "APR %": d.apr * 100,
                           "Minimum payment": d.minimum_payment,
                           "Kind": d.kind,
                           "Pre-service": d.incurred_before_service}
                          for d in h.debts]),
            hide_index=True, use_container_width=True,
            column_config={
                "Balance": st.column_config.NumberColumn(format="$%.2f"),
                "APR %": st.column_config.NumberColumn(format="%.2f%%"),
                "Minimum payment": st.column_config.NumberColumn(format="$%.2f"),
            })

if not h.debts:
    st.info("No debts recorded. Add them on the **What I am worth** page, "
            "under Your debts.", icon="ℹ️")
    st.stop()

inputs, results = two_pane()

# ==========================================================================
# Left: how much you can put against the debt.
# ==========================================================================
with inputs:
    with input_card("How much can you pay?"):
        extra = st.number_input("What can you pay above the minimums, per month?", value=200.0,
                                step=50.0, min_value=0.0, format="%.2f",
                                key=wkey("extra"))
        scra_on = st.toggle("Have you invoked the SCRA 6% cap?", value=False, key=wkey("scraon"),
                            help="Turn on to see what capping your pre-service debt "
                                 "at 6% is worth. It is not automatic — you must "
                                 "request it in writing with a copy of your orders.")

minimums = sum(d.minimum_payment for d in h.debts)
comparison = P.compare_strategies(h.debts, extra, scra_active=scra_on)

# ==========================================================================
# Right: what that budget buys.
# ==========================================================================
with results:
    metric_row([("Minimum payments", f"{fmt_money(minimums)}/mo"),
                ("Total budget", f"{fmt_money(minimums + extra)}/mo")])

    with section("Avalanche against snowball"):
        cols = st.columns(2)
        for col, strategy in zip(cols, (P.STRATEGY_AVALANCHE, P.STRATEGY_SNOWBALL)):
            res = comparison.results[strategy]
            with col:
                with st.container(border=True):
                    st.markdown(f"**{esc(strategy)}**")
                    if not res.is_solvable:
                        st.error("At this payment level these debts never get paid off.",
                                 icon="🚨")
                        continue
                    st.metric("Debt-free in", f"{res.months} months",
                              f"{res.years:.1f} years")
                    st.metric("Interest paid", fmt_money(res.total_interest))
                    order = P.order_debts(h.debts, strategy, scra_on)
                    st.caption("Attack order: " + esc(" → ".join(d.name for d in order)))

        if comparison.best_by_interest:
            gap, months = comparison.interest_gap, comparison.months_gap
            if gap < 200:
                st.info(f"The two methods are within {md_money(gap)} of each other here. "
                        f"Pick the one you will actually stick to — snowball's early win "
                        f"is worth more than a rounding error.", icon="💡")
            else:
                st.success(f"**{esc(comparison.best_by_interest)}** saves "
                           f"{md_money(gap)} and {months} month(s).", icon="🏆")

        if comparison.scra_savings > 0:
            st.success(f"**Invoking SCRA is worth {md_money(comparison.scra_savings)} "
                       f"and {comparison.scra_months_saved} month(s) off your payoff "
                       f"date.** Write to each lender with a copy of your orders. They "
                       f"must apply the 6% cap retroactively to the start of your active "
                       f"duty and forgive the excess interest — not defer it.", icon="⚖️")

    with section("Balance over time"):
        best = comparison.results.get(comparison.best_by_interest
                                      or P.STRATEGY_AVALANCHE)
        if best and best.is_solvable and best.schedule:
            frames = []
            for strategy, res in comparison.results.items():
                if not res.is_solvable:
                    continue
                for row in res.schedule:
                    frames.append({"Month": row.month, "Balance": row.total_balance,
                                   "Strategy": strategy})
            if frames:
                df = pd.DataFrame(frames)
                st.line_chart(df, x="Month", y="Balance", color="Strategy", height=320)

            st.markdown("**When each debt clears**")
            payoff = [{"Debt": name, "Month": month,
                       "Years": round(month / 12.0, 1)}
                      for name, month in sorted(best.payoff_month.items(),
                                                key=lambda kv: kv[1])]
            if payoff:
                st.dataframe(pd.DataFrame(payoff), use_container_width=True,
                             hide_index=True)

    render_findings(P.payoff_findings(h.debts, comparison, scra_on))
