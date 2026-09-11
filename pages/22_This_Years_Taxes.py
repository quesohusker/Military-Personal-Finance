import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import calendar
from datetime import date

import altair as alt
import pandas as pd
import streamlit as st

from ui.panel import (wkey, get_household, page_header, two_pane, input_card,
                      section, metric_row, money, mark_dirty, invalidate,
                      fmt_money, fmt_pct, esc, md_money, render_findings)
from ui import charts as CH
from engine.tax import current_year as CY
from engine.tax import tables as T

h = get_household()
m = h.member

page_header("🧾 Taxes",
            esc("What this year's return will look like: BAH and BAS never "
                "reach a W-2, and pay earned in a combat zone does not either. "
                "That is how a family living on $75,000 files a $30,000 return "
                "— and why credits everyone assumes are for other people are "
                "sitting on this one."))

# Almost nothing on this page is written back into the plan, and that is the
# right answer rather than the §4a defect -- but it has to be VISIBLE, which is
# what it was not. Every answer here except one is a fact about ONE tax year --
# what the LES says today, how many months in the zone, which children are
# under 17 this December -- or a filing scenario the member is trying on. None
# of that belongs in a profile the thirty-year projection reads, so it stays
# page-local and every widget says so (`FUNNEL_CONTRACT.md` §14).
#
# The exception is the spouse's wages. That is not a tax-year figure at all:
# the plan already carries it, `engine/income/spouse.py` projects a career from
# it, and a member correcting it here was correcting nothing.
WHATIF = ("A what-if on this page only. Nothing typed here is saved to your "
          "plan — it moves the figures below and nothing else.")
WHATIF_CARD = "What-if — nothing on this card is saved to your plan."
THIS_YEAR_CARD = ("This tax year only — nothing on this card is saved to your "
                  "plan.")

inputs, results = two_pane()

# ==========================================================================
# Left: the questions, stacked.
# ==========================================================================
with inputs:
    with input_card("Your return"):
        st.caption(THIS_YEAR_CARD)
        status = st.selectbox(
            "How will you file this year?", T.FILING_STATUSES,
            index=T.FILING_STATUSES.index(CY.filing_status_for(h)),
            key=wkey("cy_status"),
            help=WHATIF + " It opens on what your Profile implies — married "
                 "members almost always file jointly, and filing separately "
                 "disqualifies the Earned Income Credit outright — so change it "
                 "here only to see what the other status would do.")

        n_children = st.number_input(
            "How many children will you claim?", min_value=0, max_value=15,
            value=int(h.n_dependents), step=1, key=wkey("cy_kids"),
            help=WHATIF + " It opens at your household's dependants, which is "
                 "a different question and usually a different number: a child "
                 "under 17 at the end of the year counts for the Child Tax "
                 "Credit; the Earned Income Credit reaches to 18, or 23 for a "
                 "full-time student. Anyone else you support is worth $500 as "
                 "an other dependent. Your household's dependant count lives on Intake.")

    with input_card("What has been withheld"):
        st.caption(THIS_YEAR_CARD)
        have_les = st.toggle(
            "Do you have your LES to hand?", value=False, key=wkey("cy_haveles"),
            help=WHATIF + " Without it the page assumes plain W-4 settings at "
                 "every payer, which is what causes most surprise bills in "
                 "April.")
        if have_les:
            withheld_ytd = st.number_input(
                "How much federal income tax has been withheld so far?",
                min_value=0.0, value=0.0, step=100.0, format="%.2f",
                key=wkey("cy_withheld"),
                help=WHATIF + " TAX YTD in the FED TAXES block of your LES — "
                     "not the monthly figure. Add your spouse's year-to-date "
                     "federal withholding from their pay stub. It is true of "
                     "one year and stale by the next, so the plan does not "
                     "carry it.")
            les_month = st.selectbox(
                "Which month does that figure run through?", list(range(1, 13)),
                index=min(12, date.today().month) - 1, key=wkey("cy_month"),
                format_func=lambda i: calendar.month_name[i],
                help=WHATIF + " The year-to-date figure is scaled "
                     "straight-line to twelve months from here.")
        else:
            withheld_ytd, les_month = None, 12

    if status == T.MFJ:
        with input_card("Your spouse"):
            if h.has_spouse:
                # The one fact on this page. It is not a tax-year figure: the
                # plan holds it, the Career page asks it, and
                # `engine/income/spouse.py` builds a whole earnings path from
                # it. So it writes through, like every other shared field.
                _wages_before = float(h.spouse_income.annual_income)
                spouse_wages = money(
                    "What will your spouse earn this year?", h.spouse_income,
                    "annual_income", key=wkey("cy_spousewage"), step=1000.0,
                    help="Gross wages before their own retirement "
                         "contributions — the number that decides the Earned "
                         "Income Credit for most military families. This is "
                         "your plan's figure, shared with the Career page, and "
                         "correcting it here corrects it everywhere.")
                # `income/spouse.py` returns nothing at all unless `employed`
                # is set (line 145), so a figure typed here with the flag off
                # would be read back as zero -- the silent discard this work
                # exists to remove. But the flag is only turned on when the
                # member TYPES a figure on this page, never merely by opening
                # it: a spouse who has stopped working is marked not employed
                # on the Career page while last year's figure is still on the
                # plan, and re-employing them on render would resurrect dead
                # income into every projection without anyone asking.
                if (spouse_wages > 0 and spouse_wages != _wages_before
                        and not h.spouse_income.employed):
                    h.spouse_income.employed = True
                    mark_dirty()
                    invalidate()
            else:
                st.caption(WHATIF_CARD + " Your plan has no spouse on it, so "
                                         "there is nowhere to save this.")
                spouse_wages = st.number_input(
                    "What will your spouse earn this year?", min_value=0.0,
                    value=0.0, step=1000.0, format="%.2f",
                    key=wkey("cy_spousewage"),
                    help=WHATIF + " Add a spouse on Intake and this becomes "
                         "your plan's figure instead.")
    else:
        spouse_wages = 0.0

    if m.is_serving:
        with input_card("Time in the zone"):
            st.caption(WHATIF_CARD)
            czte_months = st.number_input(
                "How many months will you spend in a combat zone this year?",
                min_value=0, max_value=12,
                value=int(m.months_deployed_this_year if m.in_combat_zone else 0),
                step=1, key=wkey("cy_czmonths"),
                help=WHATIF + " Any part of a month in the zone counts as a "
                     "whole month: 1 January to 1 July is SEVEN qualifying "
                     "months, not six. It opens at your plan's deployment "
                     "months — change it here to see the return a deployment "
                     "produces before you take it. Your real deployment months "
                     "live on Intake.")
    else:
        czte_months = 0

# ==========================================================================
# The arithmetic, once every answer is in.
# ==========================================================================
est = CY.estimate(h, status=status, n_children=int(n_children),
                  spouse_wages=float(spouse_wages), withheld_ytd=withheld_ytd,
                  les_month=int(les_month), czte_months=int(czte_months))

w = est.w2
e = est.eitc
s = est.savers

# One colour per component, held steady so the two bars line up by eye.
COMPONENT_COLOUR = {
    "Box 1 wages": CH.BLUE,
    "Retired pay (1099-R)": CH.VIOLET,
    "Traditional TSP": CH.MAGENTA,
    "Combat-zone pay": CH.ORANGE,
    "BAH": CH.AQUA,
    "BAS": CH.YELLOW,
    "Other allowances": "#7d8b95",
    "VA compensation": "#0f766e",
    "Civilian wages": CH.BLUE,
}
PAID = "What you are paid"
FILED = "What the return sees"

# ==========================================================================
# Right: what those answers mean.
# ==========================================================================
with results:
    with section("The W-2 picture",
                 "Everything you are paid, and the slice of it a tax return "
                 "ever sees."):
        rows = est.picture_rows()
        # For a serving member with nothing else coming in, what a return sees
        # IS box 1, and saying so is the point of the panel. A retiree or a
        # Reservist with a civilian job has more in it than box 1, and the
        # label has to say that or the four figures stop adding up.
        only_a_w2 = est.retired_pay <= 0.5 and est.civilian_wages <= 0.5
        metric_row([
            ("Your total compensation", fmt_money(est.received)),
            ("On the W-2 (box 1)" if only_a_w2 else "What a return sees",
             fmt_money(est.member_wages if only_a_w2 else est.taxed)),
            ("Never taxed", fmt_money(est.never_on_the_w2)),
            ("Share never taxed",
             fmt_pct(est.never_on_the_w2 / est.received if est.received else 0.0, 0)),
        ])

        if rows:
            recs = []
            for i, r in enumerate(rows):
                recs.append({"View": PAID, "Order": i, **r})
                if r["Treatment"] == "Taxed":
                    recs.append({"View": FILED, "Order": i, **r})
            df = pd.DataFrame(recs)
            present = [r["Component"] for r in rows]

            st.altair_chart(
                alt.Chart(df)
                .mark_bar(stroke="#fcfcfb", strokeWidth=2, cornerRadius=2)
                .encode(
                    y=alt.Y("View:N", sort=[PAID, FILED],
                            axis=alt.Axis(title=None, labelFontSize=12,
                                          labelColor=CH.TEXT_PRIMARY,
                                          domainColor=CH.GRID, tickColor=CH.GRID)),
                    x=alt.X("Amount:Q", stack="zero",
                            axis=alt.Axis(format="$,.0s", title="A year",
                                          grid=True, gridColor=CH.GRID,
                                          domainColor=CH.GRID, tickColor=CH.GRID,
                                          labelColor=CH.TEXT_SECONDARY,
                                          titleColor=CH.TEXT_SECONDARY)),
                    color=alt.Color(
                        "Component:N",
                        scale=alt.Scale(domain=present,
                                        range=[COMPONENT_COLOUR.get(c, CH.RED)
                                               for c in present]),
                        legend=alt.Legend(orient="top", title=None, columns=4,
                                          labelColor=CH.TEXT_PRIMARY,
                                          labelFontSize=11)),
                    order=alt.Order("Order:Q"),
                    tooltip=[alt.Tooltip("Component:N", title="Component"),
                             alt.Tooltip("Amount:Q", title="A year", format="$,.0f"),
                             alt.Tooltip("Treatment:N", title="Tax treatment")])
                .properties(height=165).configure_view(strokeWidth=0),
                use_container_width=True)

            if est.never_on_the_w2 > 0.5:
                st.caption(esc(
                    f"The gap is {fmt_money(est.never_on_the_w2)} a year that "
                    f"no tax return ever sees"
                    + ("" if only_a_w2 else
                       f", against {fmt_money(est.member_wages)} in box 1 of "
                       f"your W-2")
                    + f". A civilian would need {fmt_money(est.received)} of "
                    f"salary to live the same way, and would be taxed on all "
                    f"of it. Every credit below is measured against the lower "
                    f"number, not the one you live on."))
            else:
                st.caption("Every dollar you are paid this year is taxable "
                           "income: no allowances, no exclusion, no VA "
                           "compensation.")
        else:
            st.caption("No military pay, retired pay or VA compensation is "
                       "recorded, so there is no W-2 picture to draw. Set your "
                       "grade and component on the Profile page.")

        for note in w.notes:
            st.caption("• " + esc(note))

    with section("Your return, line by line"):
        metric_row([
            ("Adjusted gross income", fmt_money(est.agi)),
            ("Standard deduction", fmt_money(est.deductions)),
            ("Taxable income", fmt_money(est.taxable_income)),
            ("Tax before credits", fmt_money(est.tax_before_credits)),
        ])
        metric_row([
            ("Credits against tax", fmt_money(est.nonrefundable_credits)),
            ("Tax after credits", fmt_money(est.tax_after_credits)),
            ("Refundable credits", fmt_money(est.refundable_credits)),
            ("Withheld, full year", fmt_money(est.withholding_projected)),
        ])

        if est.refund >= 0:
            st.success(f"**Refund of about {md_money(est.refund)}.**", icon="✅")
        else:
            st.error(f"**Balance due of about {md_money(-est.refund)}.** "
                     f"Fix it in myPay with a new W-4 before December.",
                     icon="🚨")

        table = pd.DataFrame([{"Line": lbl, "Amount": fmt_money(v)}
                              for lbl, v in est.lines()])
        st.dataframe(table, use_container_width=True, hide_index=True)

        st.caption(esc(
            f"Federal only, filing {est.status.lower()}, at a marginal rate of "
            f"{fmt_pct(est.marginal_rate, 0)}. "
            + ("Withholding is an estimate from plain W-4 settings — turn on "
               "the LES question to replace it. "
               if est.withholding_is_estimate else
               f"Withholding is {fmt_money(est.withheld_ytd)} through "
               f"{calendar.month_name[est.les_month]}, scaled straight-line to "
               f"the year. ")
            + (f"{est.state.state}: {fmt_money(est.state.tax)} of state tax on "
               f"top." if est.state.tax > 0 else f"{est.state.note}")))

    with section("The Earned Income Credit, computed both ways",
                 "Nontaxable combat pay may be elected into earned income for "
                 "this credit — and only this credit. It is all or nothing, it "
                 "never touches your AGI, and it can just as easily destroy the "
                 "credit as create it."):
        metric_row([
            ("Without the election", fmt_money(e.without_election.credit)),
            ("With the election", fmt_money(e.with_election.credit)),
            ("Combat pay in play", fmt_money(e.combat_pay)),
            ("What to do",
             "Elect it" if e.recommend_election else
             ("Leave it out" if e.combat_pay > 0 else "Nothing to elect")),
        ])

        both = pd.DataFrame([
            {"Combat pay": "Left out of earned income",
             "Earned income": fmt_money(e.without_election.earned_income),
             "AGI": fmt_money(est.agi),
             "Credit": fmt_money(e.without_election.credit),
             "Where you are": e.without_election.phase or "none"},
            {"Combat pay": "Elected into earned income",
             "Earned income": fmt_money(e.with_election.earned_income),
             "AGI": fmt_money(est.agi),
             "Credit": fmt_money(e.with_election.credit),
             "Where you are": e.with_election.phase or "none"},
        ])
        st.dataframe(both, use_container_width=True, hide_index=True)

        if e.recommend_election:
            st.success(esc(e.note), icon="✅")
        elif e.combat_pay > 0 and e.gain > 0:
            st.warning(esc(e.note), icon="⚠️")
        else:
            st.info(esc(e.note), icon="ℹ️")

        st.caption(esc(
            f"Earned income for this credit starts at box 1: "
            f"{fmt_money(est.member_wages)} of wages"
            + (f" plus {fmt_money(est.spouse_wages)} from your spouse"
               if est.spouse_wages else "")
            + f". BAH, BAS and every other allowance are outside it, which is "
            f"why the credit reaches military families whose real "
            f"{fmt_money(est.total_compensation)} of household compensation "
            f"looks far too high for it. The credit dies at "
            f"{fmt_money(CY.completed_phaseout(est.n_children, est.status))} of "
            f"AGI for {est.n_children if est.n_children else 'no'} "
            f"{'child' if est.n_children == 1 else 'children'}. Claim it on "
            f"Schedule EIC — the free VITA preparers on most installations know "
            f"this rule cold."))

    with section("The Saver's Credit",
                 "Money back for retirement contributions you are already "
                 "making. Roth TSP counts, and almost nobody eligible claims "
                 "it."):
        metric_row([
            ("Your AGI", fmt_money(est.agi)),
            ("Your tier", fmt_pct(s.rate, 0) if s.rate else "None"),
            ("Contributions counted", fmt_money(sum(s.contributions))),
            ("Credit", fmt_money(s.credit)),
        ])
        if s.credit > 0:
            st.success(esc(s.note), icon="✅")
        elif s.eligible:
            st.warning(esc(s.note), icon="⚠️")
        else:
            st.info(esc(s.note), icon="ℹ️")
        st.caption(esc(
            f"Up to "
            f"{fmt_money(CY.SAVERS_CREDIT_2026['max_contribution_per_person'])} "
            f"of contributions per person, at 50%, 20% or 10% by AGI, claimed "
            f"on Form 8880. The AGI ceiling is "
            f"{fmt_money(s.ceiling)} filing {est.status.lower()}. It is "
            f"nonrefundable, so it can only wipe out tax you owe — and "
            f"{CY.SAVERS_CREDIT_2026['last_year_as_credit']} is its last year "
            f"as a credit before SECURE 2.0 turns it into a match paid straight "
            f"into the account."))

    with section("What to do about it",
                 "Ordered by what each one is worth on this return."):
        render_findings(est.findings)

    st.caption(esc(
        f"An estimate of the {CY.TAX_YEAR} federal return, not a filed one: it "
        f"assumes the standard deduction, no itemising, no self-employment and "
        f"no state credits. Rates and credit amounts are {CY.TAX_YEAR} figures. "
        f"Free tax preparation for service members is at Military OneSource, "
        f"800-342-9647, and at the VITA site on your installation."))
