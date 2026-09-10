import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import streamlit as st
import pandas as pd
import altair as alt

from ui.panel import (wkey, get_household, page_header, two_pane, input_card,
                      section, metric_row, number, choice, fmt_money, esc,
                      render_findings)
from ui import charts as C
from engine.investments import tsp_allocation as TA
from engine.networth import balance_sheet as BS
from engine.profile import Investments
from engine import mortality as MORT

h = get_household()
m = h.member
inv = h.investments


def pending(key: str, fallback):
    """
    The value a widget will take this run, before it has been instantiated.

    The lifecycle fund is asked about below the five funds, but its percentage
    counts toward the same 100%, so the running total has to include a change
    the user has just made to a widget further down the page. Streamlit puts
    that new value into session_state before the rerun, so reading it there is
    current where reading the Household is one interaction stale.
    """
    return st.session_state.get(wkey(key), fallback)


page_header("📊 How is my money invested?",
            "The five funds, what they cost, and the reason a military "
            "retiree's portfolio can hold more shares than a civilian's — not "
            "fewer.")

inputs, results = two_pane()

# ==========================================================================
# Left: the questions, stacked.
# ==========================================================================
with inputs:
    with input_card("What is your TSP invested in?"):
        number("How much is in the G Fund? (%)", inv, "tsp_g_pct",
               key=wkey("iv_g"), max_value=100.0, step=5.0, fmt="%.0f",
               help="Special Treasury securities issued to the TSP alone. "
                    "Intermediate-term interest, and the principal cannot "
                    "fall. There is nothing like it outside the TSP.")
        number("How much is in the F Fund? (%)", inv, "tsp_f_pct",
               key=wkey("iv_f"), max_value=100.0, step=5.0, fmt="%.0f",
               help="The broad US investment-grade bond market. A real bond "
                    "fund, so it can lose value when rates rise.")
        number("How much is in the C Fund? (%)", inv, "tsp_c_pct",
               key=wkey("iv_c"), max_value=100.0, step=5.0, fmt="%.0f",
               help="The S&P 500 — large US companies, about 80% of the US "
                    "market by value.")
        number("How much is in the S Fund? (%)", inv, "tsp_s_pct",
               key=wkey("iv_s"), max_value=100.0, step=5.0, fmt="%.0f",
               help="The completion index: everything American outside the "
                    "S&P 500. C plus S in roughly 80/20 is the whole US "
                    "market.")
        number("How much is in the I Fund? (%)", inv, "tsp_i_pct",
               key=wkey("iv_i"), max_value=100.0, step=5.0, fmt="%.0f",
               help="International shares. Since the 2024 index change this "
                    "includes emerging markets, which the old EAFE benchmark "
                    "did not.")

        _snap = Investments(
            tsp_g_pct=inv.tsp_g_pct, tsp_f_pct=inv.tsp_f_pct,
            tsp_c_pct=inv.tsp_c_pct, tsp_s_pct=inv.tsp_s_pct,
            tsp_i_pct=inv.tsp_i_pct,
            tsp_lifecycle_fund=pending("iv_lfund", inv.tsp_lifecycle_fund),
            tsp_lifecycle_pct=pending("iv_lpct", inv.tsp_lifecycle_pct))
        _es = TA.equity_share(_snap)
        st.markdown(f"**Running total: {_es.allocation_total_pct:.0f}%**"
                    + ("  ✅" if _es.sums_to_100 else ""))
        if _es.is_empty:
            st.caption("Nothing entered yet. Your allocation is on the TSP "
                       "website under Account Activity.")
        elif _es.allocation_total_pct > 100.0:
            st.caption(f"That is {_es.allocation_total_pct - 100:.0f} points "
                       f"more than you have — the TSP would reject it.")
        elif not _es.sums_to_100:
            st.caption(f"{_es.unassigned_pct:.0f}% unaccounted for. The total "
                       f"has to reach 100%, counting any L fund below.")

    _l_options = [""] + TA.L_FUNDS
    if inv.tsp_lifecycle_fund and inv.tsp_lifecycle_fund not in _l_options:
        _l_options.append(inv.tsp_lifecycle_fund)

    with input_card("Are you in a lifecycle fund?"):
        choice("Which L fund, if any?", inv, "tsp_lifecycle_fund", _l_options,
               key=wkey("iv_lfund"),
               format_func=lambda v: v or "None — I pick the funds myself",
               help="An L fund is a complete portfolio in one holding: a mix "
                    "of the five funds that grows more conservative as its "
                    "target date approaches, rebalanced for you every day.")
        if TA.is_l_fund(inv.tsp_lifecycle_fund):
            number("How much of your TSP is in it? (%)", inv,
                   "tsp_lifecycle_pct", key=wkey("iv_lpct"), max_value=100.0,
                   step=5.0, fmt="%.0f",
                   help="Counts toward the same 100% as the five funds above.")
            st.caption(f"{inv.tsp_lifecycle_fund} is about "
                       f"{TA.l_fund_equity_pct(inv.tsp_lifecycle_fund):.0f}% "
                       f"shares today, and gets more conservative every year "
                       f"on its own.")
        else:
            st.caption("Holding an L fund next to individual funds is the "
                       "most common way a TSP allocation ends up somewhere "
                       "nobody chose. Pick one approach or the other.")

    with input_card("What are you aiming for?"):
        number("What share of your TSP do you want in shares? (%)", inv,
               "target_equity_pct", key=wkey("iv_target"), max_value=100.0,
               step=5.0, fmt="%.0f",
               help="Your target for the TSP itself. The card on the right "
                    "shows what that same target means once your pension is "
                    "counted as the bond holding it is.")
        number("And in your taxable brokerage? (%)", inv, "taxable_equity_pct",
               key=wkey("iv_taxeq"), max_value=100.0, step=5.0, fmt="%.0f",
               help="Shares held in a taxable account are the most "
                    "tax-efficient thing to put there; bonds throw off "
                    "interest taxed at your full rate every year.")

# ==========================================================================
# The arithmetic, once every answer is in.
# ==========================================================================
es = TA.equity_share(inv)
drift = TA.versus_target(inv, tsp_balance=TA.tsp_balance(h))
pb = TA.pension_as_bond(h)
cov = TA.expenses_covered(h, portfolio=pb.portfolio if pb.applies else None)
loc = TA.asset_location(h)
fee = TA.rollover_pitch(h)
pick = TA.suggested_l_fund(h)

# ==========================================================================
# Right: what those answers mean.
# ==========================================================================
with results:
    # ----------------------------------------------------------------------
    with section("Your allocation",
                 "Everything below is computed on what you entered on the "
                 "left, including the shares held inside any L fund."):
        metric_row([
            ("In shares", f"{es.equity_pct:.0f}%"),
            ("Your target", f"{drift.target_pct:.0f}%"),
            ("Drift", f"{drift.drift_pts:+.0f} pts"),
            ("Adds to", f"{es.allocation_total_pct:.0f}%"),
        ])

        rows = TA.allocation_rows(inv)
        if rows:
            df = pd.DataFrame(rows)
            kinds = [k for k in TA.KINDS if k in set(df["Kind"])]
            colours = {TA.KIND_STOCKS: C.BLUE, TA.KIND_FIXED: C.AQUA,
                       TA.KIND_LIFECYCLE: C.VIOLET}
            st.altair_chart(
                alt.Chart(df).mark_bar(cornerRadius=3).encode(
                    x=alt.X("Percent:Q", title="% of your TSP",
                            scale=alt.Scale(domain=[0, 100], nice=False),
                            axis=alt.Axis(format="d")),
                    y=alt.Y("Fund:N", sort=None, title=None,
                            axis=alt.Axis(labelLimit=200)),
                    color=alt.Color("Kind:N",
                                    scale=alt.Scale(domain=kinds,
                                                    range=[colours[k] for k in kinds]),
                                    legend=alt.Legend(title=None, orient="top")),
                    tooltip=[alt.Tooltip("Fund:N"),
                             alt.Tooltip("Percent:Q", format=".0f"),
                             alt.Tooltip("What:N", title="What it holds"),
                             alt.Tooltip("Expense ratio:Q", format=".3f")],
                ).properties(height=36 * len(df) + 40).configure_view(strokeWidth=0),
                use_container_width=True)

            gap = pd.DataFrame([
                {"Line": "You hold", "Shares": es.equity_pct},
                {"Line": "You target", "Shares": float(inv.target_equity_pct)},
            ])
            st.altair_chart(
                alt.Chart(gap).mark_bar(cornerRadius=3, height=18).encode(
                    x=alt.X("Shares:Q", title="Share of the TSP in shares (%)",
                            scale=alt.Scale(domain=[0, 100], nice=False),
                            axis=alt.Axis(format="d")),
                    y=alt.Y("Line:N", sort=None, title=None),
                    color=alt.Color("Line:N",
                                    scale=alt.Scale(domain=["You hold", "You target"],
                                                    range=[C.BLUE, C.ORANGE]),
                                    legend=None),
                    tooltip=[alt.Tooltip("Line:N", title=""),
                             alt.Tooltip("Shares:Q", format=".0f")],
                ).properties(height=90).configure_view(strokeWidth=0),
                use_container_width=True)
        else:
            st.info("Enter what you hold on the left and this page fills in.",
                    icon="ℹ️")

        st.markdown(f"**{esc(drift.headline)}**")
        if drift.moves:
            st.markdown(esc(f"Suggested interfund transfer: "
                            f"{TA.describe_moves(drift.moves)}."))
        st.caption(esc(drift.note))
        st.caption(f"Interfund transfers cost nothing. "
                   f"{TA.IFT_UNRESTRICTED_PER_MONTH} a calendar month are "
                   f"unrestricted; after those, the only transfer the system "
                   f"accepts is one moving money INTO the G Fund. You can "
                   f"always de-risk. You cannot always re-risk.")

        with st.expander("What the five funds actually are"):
            for code in TA.FUND_CODES:
                f = TA.FUNDS[code]
                st.markdown(f"**{f.name}** — {esc(f.what)} "
                            f"*({f.expense_ratio_pct:.3f}% a year)*")
                st.caption(esc(f.note))
            st.caption(esc(TA.VERIFY["expense_ratios"]))

        with st.expander("The L funds, and which one matches you"):
            lrows = [{"Fund": n, "Shares": TA.l_fund_equity_pct(n),
                      "Bonds and G": 100 - TA.l_fund_equity_pct(n)}
                     for n in TA.L_FUNDS]
            st.dataframe(pd.DataFrame(lrows).style.format(
                {"Shares": "{:.0f}%", "Bonds and G": "{:.0f}%"}),
                use_container_width=True, hide_index=True)
            st.markdown(f"**For you: {pick.fund}.** {esc(pick.note)}")
            st.caption(esc(TA.VERIFY["l_fund_equity"]))
            st.caption(esc(TA.VERIFY["l_fund_lineup"]))

    # ----------------------------------------------------------------------
    with section("You already own a very large bond",
                 "The finding that reorders this whole page, and the one a "
                 "civilian rule of thumb cannot see."):
        if pb.applies:
            metric_row([
                ("Guaranteed income", f"{fmt_money(pb.guaranteed_annual)}/yr"),
                ("Replacement cost", fmt_money(pb.replacement_cost)),
                ("Investable assets", fmt_money(pb.portfolio)),
                ("Already in bonds", f"{pb.bond_like_pct:.0f}%"),
            ])
            st.markdown(esc(
                f"Your retired pay and VA compensation together pay "
                f"{fmt_money(pb.guaranteed_annual)} a year, indexed to "
                f"inflation, for life. Buying an equivalent income would cost "
                f"about {fmt_money(pb.replacement_cost)} — valued over "
                f"{pb.years_valued:.0f} years to age {pb.life_expectancy} at "
                f"{pb.real_discount_rate * 100:.1f}% real. Set against "
                f"{fmt_money(pb.portfolio)} of investable assets, that is "
                f"{pb.bond_like_pct:.0f}% of the two combined, and it behaves "
                f"like an inflation-protected bond: it pays monthly, it does "
                f"not fall when markets do, and it never runs out."))

            hh = pd.DataFrame([
                {"If your TSP is": f"{p:.0f}% shares",
                 "Your household is": pb.household_equity_pct(p)}
                for p in (100.0, 80.0, 60.0, float(inv.target_equity_pct))])
            st.dataframe(hh.drop_duplicates().style.format(
                {"Your household is": "{:.0f}% shares"}),
                use_container_width=True, hide_index=True)

            need = pb.portfolio_equity_for(float(inv.target_equity_pct))
            if need > 100:
                st.markdown(esc(
                    f"To make the WHOLE balance sheet "
                    f"{inv.target_equity_pct:.0f}% shares you would have to "
                    f"hold {need:.0f}% of the portfolio in shares — which is "
                    f"not possible, and is the point. Your pension is holding "
                    f"the other end of the see-saw down. Even 100% of the TSP "
                    f"in C, S and I leaves the household at "
                    f"{pb.household_equity_pct(100.0):.0f}% shares."))
            st.markdown(
                "**This is why your investable assets can carry more shares "
                "than a civilian's at the same age, not fewer.** A 60-year-old "
                "civilian holding 40% bonds is buying protection against "
                "having to sell shares in a bad year. You already bought that "
                "protection with twenty years of service, and you are paid for "
                "it monthly. Holding a second, smaller version of it inside "
                "the TSP is paying twice.")
            st.warning(esc(BS.SHORT_CAVEAT), icon="⚠️")
            with st.expander("Why putting a pension on a balance sheet is contested"):
                st.markdown(BS.VALUATION_CAVEAT)
        else:
            st.info("You have no retired pay or VA compensation entered, so "
                    "there is no guaranteed income to value yet. If you serve "
                    "to twenty this becomes the largest number in your plan — "
                    "the **Do I stay to twenty?** page prices it. Until then, "
                    "your allocation question is the ordinary one: how long "
                    "until you need the money.", icon="ℹ️")

    # ----------------------------------------------------------------------
    with section("Sequence-of-returns risk, and the floor under it"):
        metric_row([
            ("Guaranteed, monthly", fmt_money(cov.guaranteed_monthly)),
            ("You spend", f"{fmt_money(cov.monthly_expenses)}/mo"),
            ("Covered", f"{cov.covered_pct:.0f}%" if cov.monthly_expenses else "—"),
            ("Ratio", f"{cov.ratio:.2f}" if cov.monthly_expenses else "—"),
        ])
        st.markdown(f"**{esc(cov.headline)}**")
        st.markdown(esc(cov.detail))
        st.caption("Sequence-of-returns risk is the risk of selling units at "
                   "the bottom to pay the bills. It is not a fact about "
                   "shares; it is a fact about withdrawals. Where guaranteed "
                   "income pays the bills there are no withdrawals, so there "
                   "is no sequence to get wrong.")

    # ----------------------------------------------------------------------
    with section("Where to hold what",
                 "Same allocation, different accounts, different tax bill."):
        metric_row([
            ("Roth (TSP + IRA)", fmt_money(loc.roth)),
            ("Traditional (TSP + IRA)", fmt_money(loc.traditional)),
            ("Taxable brokerage", fmt_money(loc.taxable)),
            (f"Worth over {loc.years} years", fmt_money(loc.gain)),
        ])
        st.markdown("**The rule: C and S in Roth, G and F in traditional.** "
                    "The assets you expect to grow most belong where the "
                    "growth is never taxed.")
        for line in loc.lines:
            st.markdown(esc(line))
        if loc.taxable > 0:
            st.caption(esc(
                f"Your {fmt_money(loc.taxable)} taxable brokerage sits outside "
                f"the TSP and follows the same logic from the other end: "
                f"shares are the tax-efficient thing to hold there, because "
                f"qualified dividends and long-term gains are taxed at "
                f"preferential rates and unrealised growth is not taxed at "
                f"all — while bond interest is taxed at your full rate every "
                f"year. You have it at {inv.taxable_equity_pct:.0f}% shares."))

    # ----------------------------------------------------------------------
    with section("What the TSP's fees save you",
                 "And what the offer every retiring member receives costs."):
        if fee.balance > 0:
            metric_row([
                ("Your TSP + IRA", fmt_money(fee.balance)),
                ("TSP cost", f"{fee.tsp_expense_pct:.2f}%/yr"),
                ("Advisor-managed IRA", f"{fee.advisor_pct:.2f}%/yr"),
                (f"Cost over {fee.years} years", fmt_money(fee.cost)),
            ])
            frows = []
            for yrs in (10, 20, 30):
                f2 = TA.fee_drag(fee.balance, yrs, fee.real_return_pct,
                                 fee.advisor_pct, fee.tsp_expense_pct)
                frows.append({"After": f"{yrs} years",
                              "Left in the TSP": f2.tsp_value,
                              "In a 1% IRA": f2.advisor_value,
                              "The fee took": f2.cost})
            st.dataframe(pd.DataFrame(frows).style.format({
                "Left in the TSP": "${:,.0f}", "In a 1% IRA": "${:,.0f}",
                "The fee took": "${:,.0f}"}),
                use_container_width=True, hide_index=True)
            st.markdown(esc(
                f"Every retiring member is offered this: roll the TSP into an "
                f"IRA a firm manages for {fee.advisor_pct:.0f}% of assets a "
                f"year. On your {fmt_money(fee.balance)} at "
                f"{fee.real_return_pct:.1f}% real, that is "
                f"{fmt_money(fee.first_year_fee)} in the first year and about "
                f"{fmt_money(fee.cost)} over {fee.years} — roughly "
                f"{fee.cost_as_pct_of_balance:.0f}% of everything you have "
                f"today. The fee is charged on the whole balance every year, "
                f"so it compounds against you exactly as returns compound for "
                f"you."))
            st.caption(esc(
                f"The comparison is deliberately conservative: it assumes the "
                f"managed account holds funds as cheap as the TSP's — "
                f"{fee.multiple_of_tsp_cost:.0f} times cheaper than the "
                f"advisory fee alone — and ignores loads, commissions and "
                f"surrender charges entirely. The real gap is wider. None of "
                f"which says advice is worthless: it says advice priced as a "
                f"permanent percentage of your whole balance, for as long as "
                f"you hold it, is a different product from advice priced by "
                f"the hour — and that the G Fund does not exist outside the "
                f"TSP at any price."))
            st.caption(esc(TA.VERIFY["advisor_fee"]))
        else:
            st.info("Enter your TSP and IRA balances on the **What I am "
                    "worth** page and this becomes a dollar figure on your "
                    "own money.", icon="ℹ️")

    # ----------------------------------------------------------------------
    st.markdown("### What to look at, biggest dollars first")
    render_findings(TA.findings(h))

    st.caption("An estimator, not advice, and it names no investment outside "
               "the TSP's own funds. Life expectancy: "
               + MORT.explain(m.age(), m.sex))
