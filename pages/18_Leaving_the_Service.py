import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import streamlit as st
import altair as alt
import pandas as pd

from datetime import date

from ui.panel import (wkey, get_household, page_header, two_pane, input_card,
                      section, metric_row, number, fmt_money, esc,
                      render_findings, mark_dirty, invalidate)
from ui import charts as CH
from engine.career import transition as TR
from engine.profile import RETIRED
from engine.benefits import life_insurance as LI

h = get_household()
m = h.member

page_header("🚪 Transition",
            "The ordinary exit — an ETS date or a retirement ceremony, with "
            "nothing going wrong. Money still leaks out of it in five places: "
            "the leave balance, the gap between the last pay and the first "
            "pension, the VA claim you filed too late, the TSP loan, and the "
            "final move you let expire.")

today = date.today()

inputs, results = two_pane()

# ==========================================================================
# Left: the questions, stacked.
# ==========================================================================
with inputs:
    with input_card("Your leave balance"):
        number("How many days of leave will you have left?", m,
               "leave_balance_days", key=wkey("tr_days"),
               min_value=0.0, max_value=120.0, step=1.0,
               help=f"What you expect on the LES for your final month, not "
                    f"today's balance. You keep accruing "
                    f"{TR.FIGURES['leave_accrual_days_per_month']} days a "
                    f"month right up to the end.")
        sold_before = st.number_input(
            "How many days have you already sold in your career?",
            value=0.0, min_value=0.0,
            max_value=float(TR.SELLBACK_CAREER_CAP_DAYS), step=1.0,
            key=wkey("tr_sold"),
            help="The 60-day limit is a CAREER cap. Days sold at a "
                 "re-enlistment years ago still count against it, and people "
                 "forget them.")
        leave_choice = st.radio("What do you plan to do with it?",
                                TR.LEAVE_CHOICES, index=0, key=wkey("tr_choice"))

    with input_card("Your date, and how you are leaving"):
        stored = TR.parse_separation_date(m.planned_separation_date, today=today)
        picked = st.date_input("When do you plan to separate or retire?",
                               value=stored, min_value=date(2000, 1, 1),
                               max_value=date(2060, 12, 31), key=wkey("tr_date"),
                               help="Your ETS or retirement date. Terminal "
                                    "leave does not move it — it is the last "
                                    "stretch of it.")
        if isinstance(picked, (list, tuple)):
            picked = picked[0] if picked else stored
        if picked and picked.isoformat() != (m.planned_separation_date or ""):
            m.planned_separation_date = picked.isoformat()
            mark_dirty()
            invalidate()
        sep_date = picked or stored

        default_kind = (TR.RETIRING
                        if (m.component == RETIRED or m.years_of_service >= 20
                            or m.retired_pay_monthly > 0) else TR.SEPARATING)
        kind = st.radio("Are you retiring or separating?", TR.EXIT_KINDS,
                        index=TR.EXIT_KINDS.index(default_kind),
                        key=wkey("tr_kind"),
                        help="Retiring means a pension from the month after you "
                             "go. Separating means the pay simply stops.")
        involuntary = st.toggle("Is the separation involuntary?", value=False,
                                key=wkey("tr_invol"),
                                help="Force shaping, non-retention, a "
                                     "disestablished billet, the end of a "
                                     "contingency mobilisation. It is what "
                                     "decides whether you get TAMP.")

    with input_card("The VA"):
        va_amt = st.number_input("What VA compensation do you expect, per month?",
                                 value=float(m.va_disability_monthly or 0.0),
                                 min_value=0.0, step=50.0, key=wkey("tr_va"),
                                 help="Your best estimate of the award. It is "
                                      "tax-free, so a dollar of it is worth "
                                      "more than a dollar of retired pay.")
        filed_bdd = st.toggle("Have you filed a BDD claim?", value=False,
                              key=wkey("tr_bdd"),
                              help="Benefits Delivery at Discharge. Filed 180 "
                                   "to 90 days before you separate, the rating "
                                   "is normally decided by the time you leave.")

    with input_card("Your TSP, and tax"):
        tsp_loan = st.number_input("What is your outstanding TSP loan balance?",
                                   value=0.0, min_value=0.0, step=500.0,
                                   key=wkey("tr_loan"),
                                   help="Repayment comes out of military pay, "
                                        "and military pay is about to stop.")
        rate_pct = st.number_input("What marginal tax rate should we use? (%)",
                                   value=22.0, min_value=0.0, max_value=50.0,
                                   step=1.0, key=wkey("tr_rate"),
                                   help="22% is the flat federal withholding "
                                        "rate on a lump payment like a leave "
                                        "sell-back. Your own bracket is the "
                                        "better answer.")

# ==========================================================================
# The arithmetic, once every answer is in.
# ==========================================================================
t = TR.analyze(h, is_retiring=(kind == TR.RETIRING),
               days_already_sold=float(sold_before),
               leave_choice=leave_choice, separation_date=sep_date,
               expected_va_monthly=float(va_amt), filed_bdd=bool(filed_bdd),
               tsp_loan_balance=float(tsp_loan), involuntary=bool(involuntary),
               marginal_rate=rate_pct / 100.0, today=today)

lv, flow, va = t.leave, t.flow, t.va

# ==========================================================================
# Right: what those answers mean.
# ==========================================================================
with results:
    with section("Sell the leave, or take it",
                 "Sold leave pays basic pay only — no BAH, no BAS — and it is "
                 "taxable. The same day taken as terminal leave pays all three, "
                 "and two of them are untaxed."):

        metric_row([
            ("Terminal leave, after tax", fmt_money(lv.take.after_tax)),
            ("Sold, after tax", fmt_money(lv.sell.after_tax)),
            ("Hybrid, after tax", fmt_money(lv.hybrid.after_tax)),
            ("Taking is worth", f"+{fmt_money(lv.advantage_of_taking)}"),
        ])
        metric_row([
            ("A day sold", fmt_money(lv.basic_daily)),
            ("A day taken", fmt_money(lv.basic_daily + lv.allowance_daily)),
            ("Days you may still sell", f"{lv.cap_remaining:,.0f}"),
            ("Lump at settlement", fmt_money(lv.sell.cash_at_separation)),
        ])

        if lv.days > 0:
            rows = pd.DataFrame([
                {"Option": o.label,
                 "Days sold": round(o.days_sold, 1),
                 "Days taken": round(o.days_taken, 1),
                 "Basic pay": fmt_money(o.sold_gross + o.terminal_basic),
                 "BAH + BAS": fmt_money(o.terminal_allowances),
                 "Tax": f"-{fmt_money(o.tax)}",
                 "After tax": fmt_money(o.after_tax)}
                for o in lv.options])
            st.dataframe(rows, hide_index=True, use_container_width=True)

        if lv.days <= 0:
            st.info("Enter a leave balance on the left and this becomes a "
                    "number rather than a principle.")
        elif lv.advantage_of_taking > 0:
            st.success(esc(f"**{lv.best.label}** — about "
                           f"{fmt_money(lv.best.after_tax)} against "
                           f"{fmt_money(lv.sell.after_tax)} for selling the lot."))
        else:
            st.info(esc(f"All three come to about "
                        f"{fmt_money(lv.take.after_tax)}, because no BAH or BAS "
                        f"is showing for you."))
        for note in lv.notes:
            st.markdown(esc(note))

    with section("The gap between the last pay and the first",
                 f"Military pay stops on {sep_date:%d %B %Y}. Everything else "
                 f"arrives later — and this shows only military and government "
                 f"income, not a civilian salary."):

        metric_row([
            ("Cash to set aside", fmt_money(flow.reserve_needed)),
            ("Months short", f"{flow.months_short}"),
            ("Worst month",
             f"{flow.worst_month.label}" if flow.worst_month else "—"),
            ("Monthly expenses", fmt_money(flow.monthly_expenses)),
        ])

        when = {r.offset: r.label for r in flow.rows}
        metric_row([
            ("Last military pay", when.get(0, "—")),
            ("Final settlement", when.get(flow.settlement_offset, "later")),
            ("First retired pay",
             when.get(flow.retired_pay_offset, "later") if t.is_retiring
             else "No pension"),
            ("First VA payment",
             when.get(flow.va_offset, "later") if va.expected_monthly > 0
             else "None entered"),
        ])

        recs = []
        for r in flow.rows:
            for label, amount in (("Military pay", r.military_pay),
                                  ("Leave settlement", r.leave_settlement),
                                  ("Retired pay", r.retired_pay),
                                  ("VA compensation", r.va_pay)):
                if amount > 0:
                    recs.append({"Month": r.label, "Order": r.offset,
                                 "Source": label, "Amount": amount})

        if recs:
            df = pd.DataFrame(recs)
            order = [r.label for r in flow.rows]
            present = [s for s in ("Military pay", "Leave settlement",
                                   "Retired pay", "VA compensation")
                       if s in set(df["Source"])]
            palette = {"Military pay": CH.BLUE, "Leave settlement": CH.YELLOW,
                       "Retired pay": CH.VIOLET, "VA compensation": CH.AQUA}

            bars = alt.Chart(df).mark_bar(
                cornerRadiusTopLeft=3, cornerRadiusTopRight=3,
                stroke="#fcfcfb", strokeWidth=1).encode(
                x=alt.X("Month:N", sort=order,
                        axis=alt.Axis(title=None, labelAngle=-45)),
                y=alt.Y("Amount:Q", stack="zero",
                        axis=alt.Axis(format="$,.0s", title="Income in the month")),
                color=alt.Color("Source:N",
                                scale=alt.Scale(domain=present,
                                                range=[palette[s] for s in present]),
                                legend=alt.Legend(orient="top", title=None)),
                tooltip=["Month:N", "Source:N",
                         alt.Tooltip("Amount:Q", format="$,.0f")])

            layers = [bars]
            if flow.monthly_expenses > 0:
                rule = alt.Chart(
                    pd.DataFrame({"Expenses": [flow.monthly_expenses]})
                ).mark_rule(color=CH.RED, strokeWidth=2,
                            strokeDash=[5, 4]).encode(
                    y=alt.Y("Expenses:Q"),
                    tooltip=[alt.Tooltip("Expenses:Q", title="Monthly expenses",
                                         format="$,.0f")])
                layers.append(rule)

            st.altair_chart(alt.layer(*layers).properties(height=300),
                            use_container_width=True)
            if flow.monthly_expenses > 0:
                st.caption(esc(f"The dashed line is {fmt_money(flow.monthly_expenses)} "
                               f"a month of expenses. Every bar below it is a "
                               f"month you fund from savings."))
        else:
            st.info("No pay figures could be resolved for your grade, so there "
                    "is nothing to chart. Check your grade and years of "
                    "service on Profile, or enter basic pay from your LES on "
                    "Income.")

        for note in flow.notes:
            st.markdown(esc(note))

    with section("The VA clock",
                 "Retired pay starts the month after you retire, whatever you "
                 "do. VA compensation starts only when the rating is decided — "
                 "and that date is the one you control."):
        metric_row([
            ("Expected award", f"{fmt_money(va.expected_monthly)}/mo"),
            ("Months with no VA payment", f"{va.gap_months:g}"),
            ("Cash delayed", fmt_money(va.gap_dollars)),
            ("Days to separation", f"{t.days_until_separation:,}"),
        ])
        for note in va.notes:
            st.markdown(esc(note))
        if not va.notes:
            st.markdown("Enter the monthly award you expect on the left and "
                        "this page will time it for you.")

    with section("The countdown",
                 "Four dates, working backwards. The BDD window and the CHCBP "
                 "election are the two that close for good."):
        milestones = TR.countdown(t)
        months_out = max(0, round(t.days_until_separation / 30))
        # The tightest bracket that has not already passed is the live one.
        live = next((ms for ms in reversed(milestones)
                     if ms.months_out >= months_out), milestones[-1])
        st.caption(f"You are about {months_out} months out.")
        for i, ms in enumerate(milestones):
            with st.expander(ms.label, expanded=(ms is live)):
                for j, item in enumerate(ms.items):
                    st.checkbox(esc(item), key=wkey(f"tr_cd_{i}_{j}"))

    with section("What is at stake, largest first"):
        render_findings(TR.findings(t))

    with section("Where these numbers come from"):
        st.caption(esc(
            f"Basic pay {fmt_money(t.basic_monthly)}, BAH "
            f"{fmt_money(t.bah_monthly)}, BAS {fmt_money(t.bas_monthly)} a "
            f"month, from your LES overrides where you have entered them and "
            f"from the published tables otherwise. A leave day is one thirtieth "
            f"of monthly pay."))
        if t.is_retiring:
            st.caption(esc(
                f"Retired pay is modelled at {fmt_money(t.retired_pay_monthly)} "
                f"a month"
                + (", estimated from your multiplier because none is entered on "
                   "Profile." if t.retired_pay_is_estimate else ".")))
        st.caption(esc(
            f"SGLI runs free for {LI.SGLI_FREE_DAYS_AFTER_SEPARATION} days after "
            f"you separate, VGLI is guaranteed-issue for "
            f"{LI.VGLI_GUARANTEED_DAYS} days and gone after "
            f"{LI.VGLI_FINAL_DEADLINE_DAYS}. The VGLI-against-term comparison "
            f"itself lives on the medical separation and insurance page; this "
            f"page only holds the clock."))
        for note in t.notes:
            st.caption(esc(note))
        st.caption("Intervals here — when the settlement lands, how long DFAS "
                   "takes to open a retired pay account, how long a VA claim "
                   "runs — are planning estimates with their sources noted in "
                   "engine/career/transition.py. Check them against your own "
                   "orders and your own branch.")
