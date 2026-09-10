import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import streamlit as st
import pandas as pd
import altair as alt

from ui.panel import (wkey, get_household, page_header, two_pane, input_card,
                      section, metric_row, money, integer, toggle, fmt_money,
                      fmt_pct, esc, md_money, render_findings)
from engine.income import social_security as SS
from engine.tax import tables as T
from engine import mortality as MORT

BLUE, ORANGE, GREY, AQUA = "#2a78d6", "#eb6834", "#5a6b73", "#1baf7a"
STATEMENT_URL = "ssa.gov/myaccount"

h = get_household()
m = h.member
ss = h.social_security

# A plan saved with a claim age outside 62-70 would crash the number inputs
# below, and nothing happens outside that window anyway.
ss.claim_age = int(min(SS.MAX_CLAIM_AGE, max(SS.MIN_CLAIM_AGE, int(ss.claim_age))))
ss.spouse_claim_age = int(min(SS.MAX_CLAIM_AGE,
                              max(SS.MIN_CLAIM_AGE, int(ss.spouse_claim_age))))

page_header("🧓 When do I claim Social Security?",
            "One figure decides most of this: the monthly benefit at full "
            "retirement age printed on your ssa.gov statement. Go and get it — "
            "everything else on this page is arithmetic around that number.")

inputs, results = two_pane()

# The estimate is only used to seed the civilian-years question; the real one
# is computed once the answers are in.
_seed = SS.estimate_pia_from_career(m)

# ==========================================================================
# Left: the questions, stacked.
# ==========================================================================
with inputs:
    with input_card("What your statement says"):
        st.caption(f"Log in at **{STATEMENT_URL}** and read the benefit at full "
                   f"retirement age off page 1. It is computed from your actual "
                   f"earnings record — no estimate here can match it, and it "
                   f"takes ten minutes.")
        money("What does your statement say you get at full retirement age?",
              ss, "estimated_monthly_at_fra", key=wkey("ss_fra"), step=50.0,
              help="The monthly amount at full retirement age, in today's "
                   "dollars. Not the figure at 62, and not the figure at 70 — "
                   "the app computes those from this one. Leave it at zero and "
                   "the page falls back to a modelled career.")
        integer("At what age do you plan to claim?", ss, "claim_age",
                key=wkey("ss_claim"), min_value=SS.MIN_CLAIM_AGE,
                max_value=SS.MAX_CLAIM_AGE,
                help="62 is the earliest, 70 is the last age at which waiting "
                     "still adds anything. Full retirement age for you is "
                     f"{SS.fra_label(m.birth_year)}.")

    if h.has_spouse:
        with input_card("What your spouse gets"):
            toggle("Is your spouse on SSDI?", ss, "spouse_on_ssdi",
                   key=wkey("ss_spssdi"),
                   help="Social Security Disability Insurance pays their full "
                        "PIA now and converts to a retirement benefit at full "
                        "retirement age at the same amount.")
            if ss.spouse_on_ssdi:
                money("What does your spouse receive from SSDI each month?",
                      ss, "spouse_ssdi_monthly", key=wkey("ss_spssdiamt"),
                      step=50.0,
                      help="This is already their full PIA, so it is also the "
                           "base for any spousal or survivor benefit.")
            else:
                money("What does your spouse's statement say they get at full "
                      "retirement age?", ss, "spouse_estimated_monthly_at_fra",
                      key=wkey("ss_spfra"), step=50.0,
                      help="Leave it at zero if they have little or no record "
                           "of their own — they can still draw up to half of "
                           "yours.")
            integer("At what age will your spouse claim?", ss, "spouse_claim_age",
                    key=wkey("ss_spclaim"), min_value=SS.MIN_CLAIM_AGE,
                    max_value=SS.MAX_CLAIM_AGE,
                    help="Ignored while they are on SSDI: that benefit converts "
                         "at full retirement age on its own, with no claim to "
                         "make and no early-claiming reduction.")

    with input_card("If you have no statement yet"):
        st.caption("Only used while the figure above is zero. Covered earnings "
                   "are basic pay only — BAH and BAS carry no Social Security "
                   "tax — plus whatever you earn after you take the uniform off.")
        civ_years = st.number_input(
            "How many years will you work in a civilian job afterwards?",
            value=min(45, max(0, int(_seed.n_civilian_years))), min_value=0,
            max_value=45, step=1,
            key=wkey("ss_civyrs"),
            help="Years of covered civilian earnings after you separate. Social "
                 "Security averages your highest 35 years, so a 20-year career "
                 "alone leaves 15 zeros in the average — civilian years replace "
                 "them one for one.")
        money("What will you earn in civilian wages, per year?", m,
              "civilian_wages_annual", key=wkey("ss_civwage"), step=1000.0,
              help="Today's dollars. This is the same figure as on the Who I am "
                   "page. Zero here makes the civilian years above count as "
                   "zeros, which is what drags the estimate down.")

    with input_card("Your other income in retirement"):
        other_income = st.number_input(
            "What other taxable income will you have once benefits start?",
            value=float(max(0.0, round(m.retired_pay_monthly * 12.0))), min_value=0.0,
            step=1000.0, format="%.2f", key=wkey("ss_other"),
            help="Retired pay, traditional TSP and IRA withdrawals, wages, "
                 "pensions, interest and dividends. VA compensation does not "
                 "count, and neither does a Roth withdrawal. This is what "
                 "decides how much of the benefit is taxed.")

a = SS.analyse(h, civilian_years=int(civ_years),
               other_income_annual=float(other_income))

# ==========================================================================
# Right: what those answers mean.
# ==========================================================================
with results:
    if a.pia_source != SS.SOURCE_STATEMENT:
        st.warning(esc(f"No statement figure yet, so everything below runs off a "
                       f"modelled career. Get the real number at {STATEMENT_URL} "
                       f"and type it into the first box — it is the single most "
                       f"valuable ten minutes on this page."), icon="⚠️")

    with section("What you would get, 62 to 70",
                 "One decision, nine answers. The benefit is indexed to "
                 "inflation, so every figure here is in today's dollars and "
                 "stays that way for life."):

        if a.pia <= 0:
            st.info(esc("Enter the benefit at full retirement age from your "
                        "ssa.gov statement to see the comparison. Without it, "
                        "and without a pay table to model a career from, there "
                        "is nothing to compare."), icon="ℹ️")
        else:
            metric_row([
                (f"At {a.fra_label} (your PIA)", f"{fmt_money(a.pia)}/mo"),
                ("At 62", f"{fmt_money(a.benefit_at_62)}/mo",
                 f"{fmt_pct(a.benefit_at_62 / a.pia - 1, 0)} for life"),
                ("At 70", f"{fmt_money(a.benefit_at_70)}/mo",
                 f"+{fmt_pct(a.benefit_at_70 / a.pia - 1, 0)} for life"),
                (f"At {a.claim_age}, as planned", f"{fmt_money(a.benefit_at_claim)}/mo"),
            ])
            st.caption(esc(f"Source: {a.pia_source.lower()}. Full retirement age "
                           f"is {a.fra_label} for someone born in "
                           f"{a.birth_year}."))

            table = pd.DataFrame([{
                "Claim age": r.age,
                "Share of full": r.factor,
                "Monthly": r.monthly,
                "Annual": r.annual,
                f"Total by {a.life_expectancy}": r.total_by_life_expectancy,
                f"Worth today at {a.real_discount_rate * 100:.1f}%": r.pv_by_life_expectancy,
                "Catches 62 at": ("—" if r.breakeven_vs_62 is None
                                  else f"{r.breakeven_vs_62:.0f}"),
            } for r in a.rows])
            st.dataframe(table.style.format({
                "Claim age": "{:d}", "Share of full": "{:.0%}",
                "Monthly": "${:,.0f}", "Annual": "${:,.0f}",
                f"Total by {a.life_expectancy}": "${:,.0f}",
                f"Worth today at {a.real_discount_rate * 100:.1f}%": "${:,.0f}",
            }), use_container_width=True, hide_index=True)

            picks = sorted({SS.MIN_CLAIM_AGE, int(round(a.fra_years)), SS.MAX_CLAIM_AGE})
            last_age = max(a.planning_age, a.life_expectancy) + 2
            curve = pd.DataFrame([
                {"Age": age, "Claim": f"Claim at {p}",
                 "Received": SS.cumulative_benefit(
                     SS.benefit_at(a.pia, a.birth_year, p), p, age)}
                for p in picks for age in range(SS.MIN_CLAIM_AGE, last_age + 1)])
            marks = pd.DataFrame([
                {"Age": a.life_expectancy, "Label": f"Life expectancy {a.life_expectancy}"},
                {"Age": a.planning_age, "Label": f"Plan to {a.planning_age}"},
            ])
            lines = alt.Chart(curve).mark_line(strokeWidth=2.2, interpolate="monotone").encode(
                x=alt.X("Age:Q", axis=alt.Axis(format="d", title="Your age"),
                        scale=alt.Scale(nice=False, zero=False)),
                y=alt.Y("Received:Q",
                        axis=alt.Axis(format="$,.0s",
                                      title="Benefits received, today's dollars")),
                color=alt.Color("Claim:N",
                                scale=alt.Scale(domain=[f"Claim at {p}" for p in picks],
                                                range=[BLUE, GREY, ORANGE][:len(picks)]),
                                legend=alt.Legend(orient="top", title=None)),
                tooltip=[alt.Tooltip("Age:Q", format="d"), "Claim:N",
                         alt.Tooltip("Received:Q", title="Received so far",
                                     format="$,.0f")])
            rules = alt.Chart(marks).mark_rule(color=AQUA, strokeWidth=1.4,
                                               strokeDash=[4, 4]).encode(x="Age:Q")
            labels = alt.Chart(marks).mark_text(align="left", dx=4, dy=-6,
                                                fontSize=11, color=AQUA).encode(
                x="Age:Q", y=alt.value(10), text="Label:N")
            st.altair_chart((lines + rules + labels).properties(height=280)
                            .configure_view(strokeWidth=0),
                            use_container_width=True)
            st.caption(esc("Where the lines cross is the breakeven. Left of it "
                           "the early claim is ahead; right of it the later one "
                           "is, and stays ahead for the rest of a long life. " +
                           a.life_expectancy_note))

            if a.pia_source == SS.SOURCE_ESTIMATE and a.estimate is not None:
                with st.expander("How that estimate was built", expanded=False):
                    st.markdown(esc(a.estimate.note))
                    for line in a.estimate.assumptions:
                        st.markdown("- " + esc(line))
                    st.caption(esc(
                        f"An AIME of {fmt_money(a.estimate.aime)} a month runs "
                        f"through the bend-point formula — 90% of the first "
                        f"${SS.BEND_POINT_1:,.0f}, 32% to "
                        f"${SS.BEND_POINT_2:,.0f}, 15% above — to give the PIA. "
                        f"Replace all of it with your statement figure."))

    if a.pia > 0:
        with section("When the wait pays off",
                     "The claiming decision is not an investment question. It is "
                     "insurance against living a long time — the outcome that "
                     "actually costs money."):
            edge = a.edge_70_over_62_at_life_expectancy
            if edge >= 0:
                st.success(f"**At your life expectancy of {a.life_expectancy}, "
                           f"claiming at 70 beats 62 by {md_money(edge)}.**",
                           icon="✅")
            else:
                st.info(f"**At your life expectancy of {a.life_expectancy}, "
                        f"claiming at 62 beats 70 by {md_money(-edge)}.**",
                        icon="💡")

            be = a.breakeven_62_vs_70
            bed = a.breakeven_62_vs_70_discounted
            metric_row([
                ("Breakeven, 62 vs 70", f"{be:.0f}" if be else "never"),
                (f"Discounted at {a.real_discount_rate * 100:.1f}%",
                 f"{bed:.0f}" if bed else "never"),
                (f"Gap by {a.planning_age}",
                 fmt_money(a.edge_70_over_62_at_planning_age)),
                ("Best age on total dollars", f"{a.best_age_by_life_expectancy}"),
            ])
            metric_row([
                (f"62, total by {a.life_expectancy}",
                 fmt_money(a.rows[0].total_by_life_expectancy)),
                (f"{a.fra_label}, total by {a.life_expectancy}",
                 fmt_money(SS.cumulative_benefit(a.pia, a.fra_years, a.life_expectancy))),
                (f"70, total by {a.life_expectancy}",
                 fmt_money(a.rows[-1].total_by_life_expectancy)),
                ("70 vs 62, discounted", fmt_money(a.edge_70_over_62_pv)),
            ])
            st.caption(esc(
                f"The undiscounted breakeven is the honest headline; the "
                f"discounted one is the same comparison after charging your "
                f"{a.real_discount_rate * 100:.1f}% real discount rate for "
                f"having to wait, which is why it lands later. Neither is a "
                f"forecast of your death. Delaying buys an inflation-indexed "
                f"lifetime income for less than any insurer will sell it, and "
                f"it pays out precisely in the case you cannot otherwise "
                f"afford — a very long retirement."))
            st.caption(esc(MORT.explain(a.conditioning_age, m.sex)))

    with section("Your spouse, and whoever outlives the other",
                 "A married couple has two benefits while both are alive and one "
                 "afterwards. That second fact is what the higher earner's claim "
                 "age really decides."):
        if not h.has_spouse:
            st.caption("You are not recorded as married, so there is no spousal "
                       "or survivor benefit to show. Set it on the Who I am page "
                       "if that is wrong.")
        elif a.pia <= 0 and a.spouse_pia <= 0:
            st.caption("Enter a statement figure for at least one of you to see "
                       "the spousal and survivor picture.")
        else:
            sp = a.spousal_for_spouse
            metric_row([
                ("Your benefit at " + str(a.claim_age), f"{fmt_money(a.benefit_at_claim)}/mo"),
                ("Their own benefit", f"{fmt_money(sp.own_benefit)}/mo"),
                ("Spousal top-up", f"{fmt_money(sp.spousal_excess_paid)}/mo"),
                ("They receive", f"{fmt_money(sp.total)}/mo"),
            ])
            if a.pia > 0:
                st.markdown(esc(
                    f"A spouse can draw up to half of your benefit at full "
                    f"retirement age — {fmt_money(SS.SPOUSAL_SHARE * a.pia)} a "
                    f"month here — whether or not they ever paid in, which is "
                    f"the floor under a military spouse whose own record was cut "
                    f"short by every PCS. {sp.note}"))
            else:
                st.markdown(esc(f"There is no benefit of your own recorded yet, "
                                f"so there is nothing for them to be topped up "
                                f"from. {sp.note}"))
            you = a.spousal_for_you
            if you is not None and you.spousal_excess_paid > 0:
                st.markdown(esc(
                    f"It runs the other way too: your spouse out-earns you here, "
                    f"so your own benefit is topped up by "
                    f"{fmt_money(you.spousal_excess_paid)} a month on their "
                    f"record, to {fmt_money(you.total)} in all."))

            sv = a.survivor
            if sv is not None:
                st.divider()
                metric_row([
                    ("Household, both alive", f"{fmt_money(sv.household_before)}/mo"),
                    ("After the first death", f"{fmt_money(sv.household_after)}/mo",
                     f"-{fmt_money(sv.monthly_drop)}/mo"),
                    ("Survivor, higher earner claims 62",
                     f"{fmt_money(a.survivor_if_higher_claims_62)}/mo"),
                    ("Survivor, higher earner waits to 70",
                     f"{fmt_money(a.survivor_if_higher_claims_70)}/mo"),
                ])
                st.markdown(esc(
                    f"The higher earner here is {a.higher_earner}. The survivor "
                    f"keeps the larger of the two benefits and loses the "
                    f"smaller — two checks become one — and they inherit it "
                    f"including any delayed credits, for life. Waiting is "
                    f"therefore worth "
                    f"{fmt_money(a.survivor_if_higher_claims_70 - a.survivor_if_higher_claims_62)} "
                    f"a month to the survivor, who is usually the one who lives "
                    f"longest. {sv.note}"))

    with section("What gets taxed",
                 "Up to 85% of the benefit is subject to federal income tax, "
                 "decided by 'provisional income': your other income plus half "
                 "the benefit."):
        tx = a.taxation
        if tx is None or tx.ss_annual <= 0:
            st.caption("No benefit figure yet, so there is nothing to tax.")
        else:
            metric_row([
                ("Household benefit", f"{fmt_money(tx.ss_annual)}/yr"),
                ("Other income", f"{fmt_money(tx.other_income)}/yr"),
                ("Provisional income", fmt_money(tx.provisional_income)),
                ("Taxable share", fmt_pct(tx.taxable_share, 0),
                 f"{fmt_money(tx.taxable_amount)} taxed"),
            ])
            st.markdown(esc(tx.note))

            ramp = pd.DataFrame([{
                "Other income": other,
                "Provisional income": t.provisional_income,
                "Share of benefit taxed": t.taxable_share,
                "Benefit taxed": t.taxable_amount,
            } for other, t in a.ramp])
            st.dataframe(ramp.style.format({
                "Other income": "${:,.0f}", "Provisional income": "${:,.0f}",
                "Share of benefit taxed": "{:.0%}", "Benefit taxed": "${:,.0f}",
            }), use_container_width=True, hide_index=True)
            st.caption(esc(
                f"Thresholds are ${SS.PROVISIONAL_TIER1[T.SINGLE]:,.0f} and "
                f"${SS.PROVISIONAL_TIER2[T.SINGLE]:,.0f} filing single, "
                f"${SS.PROVISIONAL_TIER1[T.MFJ]:,.0f} and "
                f"${SS.PROVISIONAL_TIER2[T.MFJ]:,.0f} filing jointly. They were "
                f"written in 1984 and 1993 and have never been indexed, so "
                f"inflation alone pulls more retirees over them every year."))

            st.divider()
            st.markdown(f"**🔁 Roth conversions and this benefit.** "
                        f"{esc(SS.ROTH_NOTE)}")
            st.caption(esc(
                "In short: converting before you claim is cheap, converting "
                "after you claim is taxed twice over — once on the conversion "
                "and again through the extra slice of benefit it drags into "
                "tax. Spending from Roth later is invisible to this "
                "calculation; spending the same money from a traditional TSP is "
                "not. See the Should I convert to Roth? page."))

    with section("What your service does — and does not — do to this benefit",
                 "Almost everything a civilian tool tells a service member about "
                 "Social Security is wrong in one of these ways."):
        for fact in a.facts:
            st.markdown("- " + esc(fact))

    with section("Findings"):
        render_findings(a.findings)

    st.caption(esc(
        f"An estimator, not advice, and not an application. The bend points and "
        f"the taxable maximum built into the fallback estimate are the "
        f"{SS.PARAMETER_YEAR} figures and have not been verified against "
        f"ssa.gov from this machine; the taxation thresholds are statutory and "
        f"unindexed. Your statement figure is the number to trust. Free "
        f"counselling through Military OneSource at 800-342-9647."))
