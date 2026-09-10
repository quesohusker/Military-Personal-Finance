import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import math
from datetime import date

import altair as alt
import pandas as pd
import streamlit as st

from ui.panel import (wkey, get_household, page_header, two_pane, input_card,
                      section, metric_row, money, choice, toggle, fmt_money,
                      fmt_pct, esc, render_findings)
from ui import charts as C
from engine import mortality as MORT
from engine.benefits import healthcare as HC
from engine.profile import VETERAN, CIVILIAN

h = get_household()
m = h.member
hc = h.healthcare
TODAY = date.today().year

# One colour per phase, from the app's categorical palette. Retiree Prime and
# Select share the blue slot because only one of them is ever on the chart.
PHASE_COLOUR = {
    HC.PH_ACTIVE: C.AQUA,
    HC.PH_TRS: C.YELLOW,
    HC.PH_GRAY: C.RED,
    HC.PH_RETIREE_PRIME: C.BLUE,
    HC.PH_RETIREE_SELECT: C.BLUE,
    HC.PH_CIVILIAN: C.MAGENTA,
    HC.PH_TFL: C.ORANGE,
    HC.PH_NO_TFL: C.RED,
    HC.PH_MEDICARE: C.VIOLET,
}

page_header("🏥 What will healthcare cost me?",
            "Until 65 a military family has the cheapest coverage in America. "
            "At 65 it becomes Medicare Part B — and what you convert to Roth "
            "at 63 sets that premium at 65.")

inputs, results = two_pane()

# ==========================================================================
# Left: the questions, stacked.
# ==========================================================================
with inputs:
    with input_card("Your coverage today"):
        if m.component in (VETERAN, CIVILIAN):
            st.caption("Without a military retirement there is no TRICARE at "
                       "any price, so the plan below is ignored and your years "
                       "are costed as civilian coverage. Set your component on "
                       "the Who I am page if that is wrong.")
        choice("Which TRICARE plan are you on?", hc, "tricare_plan",
               HC.plans_for(m.component), key=wkey("hc_plan"),
               help="Prime is the HMO — a primary care manager, referrals, "
                    "near-zero copays, and you must live in a Prime service "
                    "area. Select is the PPO — any TRICARE-authorised "
                    "provider, with copays. Reserve Select is sold to the "
                    "Selected Reserve only, so it appears here only if you "
                    "are Guard or Reserve.")
        money("What do you pay for FEDVIP dental, per month?", hc,
              "fedvip_dental_monthly", key=wkey("hc_dental"), step=5.0,
              help="Dental is not part of TRICARE for retirees. FEDVIP is a "
                   "separate premium you pay yourself through BENEFEDS, and "
                   "it continues for life — so it belongs in the lifetime "
                   "figure. Enter the family rate if you cover a family.")
        money("What do you spend out of pocket on care in a year?", hc,
              "out_of_pocket_annual", key=wkey("hc_oop"), step=100.0,
              help="Copays, deductibles and anything TRICARE does not cover. "
                   "Whatever you enter is capped at your catastrophic cap in "
                   "the years TRICARE covers you, because that is what the cap "
                   "does — and left uncapped in any year it does not.")

    with input_card("Long-term care"):
        money("What do you pay for long-term-care insurance, per month?", hc,
              "ltc_premium_monthly", key=wkey("hc_ltc"), step=25.0,
              help="TRICARE, TRICARE For Life and Medicare all stop at "
                   "custodial care. Leave this at zero and the lifetime figure "
                   "below carries no long-term-care cover at all — which is a "
                   "choice, not an absence.")

    with input_card("Medicare at 65"):
        toggle("Will you take Medicare Part B when you are eligible?", hc,
               "part_b_when_eligible", key=wkey("hc_partb"),
               help="TRICARE For Life is a wraparound to Medicare and exists "
                    "only for people enrolled in Part A AND Part B. Turn this "
                    "off and the model shows your 65-and-over years with no "
                    "coverage, because that is what they would be.")
        part_d = st.toggle("Will you also buy a Part D drug plan?", value=False,
                           key=wkey("hc_partd"),
                           help="Most TFL retirees do not. The TRICARE "
                                "pharmacy benefit is creditable coverage, so "
                                "there is no late penalty for skipping Part D "
                                "— and no Part D IRMAA either.")
        joint = st.toggle("Will you file jointly in retirement?",
                          value=bool(h.has_spouse), key=wkey("hc_joint"),
                          help="The IRMAA brackets for a joint return are "
                               "twice the single ones up to the top tier. A "
                               "widowed survivor files single, on roughly the "
                               "same income, which is how a surviving spouse "
                               "walks into IRMAA without earning a dollar "
                               "more.")
        magi_default = float(round(HC.estimate_retirement_magi(h)))
        magi = st.number_input("What MAGI do you expect in retirement?",
                               value=magi_default, min_value=0.0, step=1_000.0,
                               format="%.0f", key=wkey("hc_magi"),
                               help="Retired pay, the taxable share of Social "
                                    "Security, RMDs, interest, dividends and "
                                    "capital gains — plus any tax-exempt "
                                    "interest. VA compensation, CRSC and Roth "
                                    "withdrawals are NOT in it.")

    with input_card("What if I convert this year?"):
        base_default = float(round(HC.estimate_current_magi(h)))
        base_magi = st.number_input(
            "What is your MAGI this year, before converting?",
            value=base_default, min_value=0.0, step=1_000.0, format="%.0f",
            key=wkey("hc_basemagi"),
            help="This year's income as it stands. The conversion below is "
                 "added on top of it.")
        conversion = st.number_input(
            "How much would you convert to Roth this year?", value=0.0,
            min_value=0.0, step=5_000.0, format="%.0f", key=wkey("hc_conv"),
            help="A conversion raises this year's MAGI, and IRMAA reads that "
                 "MAGI two years later. Nothing else about the conversion is "
                 "priced here — the tax on it lives on the Should I convert to "
                 "Roth? page.")

# ==========================================================================
# The arithmetic, once every answer is in.
# ==========================================================================
lc = HC.lifetime_cost(h, retirement_magi=magi, filing_joint=joint,
                      part_d_enrolled=part_d, today_year=TODAY)

age_now = m.age(TODAY)
n_medicare = 2 if h.has_spouse else 1
tier = lc.irmaa_tier
headroom = HC.irmaa_headroom(magi, joint)
# The surcharge lands as soon as the FIRST of you is on Medicare, so the probe
# runs on the older of the two. A spouse with no birth year is assumed your age.
spouse_by = h.spouse.birth_year if (h.has_spouse and h.spouse) else m.birth_year
oldest_now = max(age_now, TODAY - spouse_by) if h.has_spouse else age_now
probe = HC.probe_conversion(base_magi, conversion, joint,
                            n_enrolled=n_medicare, include_part_d=part_d,
                            conversion_year=TODAY,
                            age_in_conversion_year=oldest_now)

phases_present = [p for p in HC.PHASE_ORDER
                  if p in {r.phase for r in lc.rows}]
phase_scale = alt.Scale(domain=phases_present,
                        range=[PHASE_COLOUR[p] for p in phases_present])

medicare_rows = [r for r in lc.rows if r.age >= HC.MEDICARE_AGE]
at_65_cost = medicare_rows[0].total if medicare_rows else 0.0

# ==========================================================================
# Right: what those answers mean.
# ==========================================================================
with results:
    with section(f"From {age_now} to {lc.death_age}, phase by phase",
                 "Every figure on this page is in today's dollars. The present "
                 "value discounts future years at the real rate on the "
                 "assumptions page; the plain total does not."):

        metric_row([
            ("Lifetime cost, today's dollars", fmt_money(lc.total_today_dollars)),
            (f"Present value at {fmt_pct(h.assumptions.real_discount_rate_pct / 100, 1)}",
             fmt_money(lc.present_value)),
            ("This year", fmt_money(lc.first_year_cost)),
            ("First year at 65", fmt_money(at_65_cost)),
        ])
        metric_row([
            ("TRICARE group", lc.group),
            ("Part B starts",
             f"age {lc.first_part_b_age} in {m.birth_year + lc.first_part_b_age}"
             if lc.first_part_b_age else "never — declined"),
            ("Life expectancy", f"{lc.death_age}"),
            ("Covered at 65", "TRICARE For Life" if lc.tfl_covered else "Nothing"),
        ])

        spans = pd.DataFrame([
            {"Phase": p, "From": a, "To": b + 1, "Ages": f"{a} to {b}",
             "Years": b - a + 1}
            for p, a, b in lc.phase_spans])
        st.altair_chart(
            alt.Chart(spans).mark_bar(cornerRadius=3).encode(
                x=alt.X("From:Q", title="Your age",
                        scale=alt.Scale(nice=False, zero=False),
                        axis=alt.Axis(format="d")),
                x2="To:Q",
                y=alt.Y("Phase:N", sort=phases_present, title=None,
                        axis=alt.Axis(labelLimit=330)),
                color=alt.Color("Phase:N", scale=phase_scale, legend=None),
                tooltip=[alt.Tooltip("Phase:N"), alt.Tooltip("Ages:N"),
                         alt.Tooltip("Years:Q", format="d")],
            ).properties(height=34 * max(1, len(spans)) + 30)
            .configure_view(strokeWidth=0),
            use_container_width=True)

        years = pd.DataFrame([
            {"Age": r.age, "Year": r.year, "Phase": r.phase,
             "Premiums": r.premiums, "IRMAA": r.irmaa, "Dental": r.dental,
             "Long-term care": r.ltc, "Out of pocket": r.out_of_pocket,
             "Cost": r.total}
            for r in lc.rows])
        st.altair_chart(
            alt.Chart(years).mark_bar().encode(
                x=alt.X("Age:Q", title="Your age",
                        scale=alt.Scale(nice=False, zero=False),
                        axis=alt.Axis(format="d")),
                y=alt.Y("Cost:Q", title="Cost that year, today's dollars",
                        axis=alt.Axis(format="$,.0s")),
                color=alt.Color("Phase:N", scale=phase_scale,
                                legend=alt.Legend(orient="top", title=None,
                                                  direction="vertical",
                                                  labelLimit=440)),
                tooltip=[alt.Tooltip("Age:Q", format="d"),
                         alt.Tooltip("Year:Q", format="d"),
                         alt.Tooltip("Phase:N"),
                         alt.Tooltip("Premiums:Q", format="$,.0f"),
                         alt.Tooltip("IRMAA:Q", format="$,.0f"),
                         alt.Tooltip("Dental:Q", format="$,.0f"),
                         alt.Tooltip("Long-term care:Q", format="$,.0f"),
                         alt.Tooltip("Out of pocket:Q", format="$,.0f"),
                         alt.Tooltip("Cost:Q", format="$,.0f")],
            ).properties(height=250).configure_view(strokeWidth=0),
            use_container_width=True)
        st.caption("The step up at 65 is Medicare Part B. It is not a TRICARE "
                   "bill and there is no way to opt out of it and keep TRICARE "
                   "For Life.")

        rows = []
        for p, a, b in lc.phase_spans:
            n = b - a + 1
            rows.append({
                "Phase": p, "Ages": f"{a} to {b}", "Years": n,
                "Per year": fmt_money(lc.by_phase_undiscounted.get(p, 0.0) / n),
                "Total, today's dollars": fmt_money(
                    lc.by_phase_undiscounted.get(p, 0.0)),
                "Present value": fmt_money(lc.by_phase.get(p, 0.0)),
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True,
                     hide_index=True)

    # ----------------------------------------------------------------------
    with section("The cliff at 65: IRMAA",
                 "Medicare premiums are set by your MAGI from two years "
                 "earlier, in steps. Every step is a cliff: one dollar over a "
                 "bracket costs the whole step, for the whole year."):

        if math.isinf(headroom):
            cliff_cost = 0.0
        else:
            cliff_cost = HC.conversion_irmaa_cost(magi, headroom + 1.0, joint,
                                                  n_medicare, part_d)
        metric_row([
            ("Your IRMAA tier", tier.label),
            ("Part B, per person", f"{fmt_money(tier.part_b_monthly)}/mo"),
            ("Headroom to the next cliff",
             "top tier — no cliff above" if math.isinf(headroom)
             else fmt_money(headroom)),
            ("What one dollar over costs",
             "—" if math.isinf(headroom) else fmt_money(cliff_cost)),
        ])
        st.caption(esc(
            f"Your {'joint' if joint else 'single'} MAGI of {fmt_money(magi)} "
            f"is read from the return you file two years before the premium "
            f"year, so income at {HC.CONVERSION_WINDOW_CLOSES_AT} sets the "
            f"premium at {HC.MEDICARE_AGE}. The figures below are "
            f"{HC.FIGURES['year']} amounts for "
            f"{'two people' if n_medicare == 2 else 'one person'} where a "
            f"total is shown."))

        tiers = HC.irmaa_tiers(joint)
        table = pd.DataFrame([{
            "": "◀ you" if t.index == tier.index else "",
            "Tier": t.label,
            "MAGI two years earlier": t.magi_range_text(),
            "Part B, per person": f"{fmt_money(t.part_b_monthly)}/mo",
            "Part D surcharge": f"{fmt_money(t.part_d_surcharge_monthly)}/mo",
            "Surcharge a year, per person": fmt_money(t.surcharge_annual_per_person),
            f"A year for {'the two of you' if n_medicare == 2 else 'you'}":
                fmt_money(t.part_b_annual_per_person * n_medicare
                          + (t.part_d_surcharge_monthly * 12.0 * n_medicare
                             if part_d else 0.0)),
        } for t in tiers])

        def _highlight(row):
            hit = bool(row.iloc[0])
            return ["background-color: #dfe9f2; font-weight: 700" if hit else ""
                    for _ in row]

        st.dataframe(table.style.apply(_highlight, axis=1),
                     use_container_width=True, hide_index=True)
        st.caption("Part D surcharges are only charged if you hold a Part D "
                   "plan. With TRICARE For Life most retirees do not, and the "
                   "column is there so you can see what skipping it saves.")

    # ----------------------------------------------------------------------
    with section("What a conversion this year would trigger",
                 f"A conversion in {TODAY} is read by Medicare in "
                 f"{TODAY + HC.FIGURES['irmaa_lookback_years']}. Nothing else "
                 f"about the conversion is priced here."):

        metric_row([
            ("MAGI after converting", fmt_money(probe.magi_after)),
            ("Tier", f"{probe.before.label} → {probe.after.label}"),
            (f"Extra premiums in {probe.year_paid}",
             fmt_money(probe.extra_annual_cost) if probe.applies else "$0",
             None if probe.applies else "nobody is on Medicare that year"),
            ("Effective surcharge",
             fmt_pct(probe.effective_rate, 1)
             if (probe.conversion > 0 and probe.applies) else "—"),
        ])

        if conversion <= 0:
            st.info(esc(
                f"Enter a conversion amount on the left. You have "
                f"{fmt_money(HC.irmaa_headroom(base_magi, joint))} of room "
                f"below your next cliff this year."
                if not math.isinf(HC.irmaa_headroom(base_magi, joint)) else
                "Enter a conversion amount on the left. You are already in the "
                "top IRMAA tier, so no further conversion raises the premium."),
                icon="ℹ️")
        elif probe.tiers_crossed > 0 and probe.applies:
            st.error(esc(
                f"This crosses {probe.tiers_crossed} cliff"
                f"{'s' if probe.tiers_crossed > 1 else ''}. The last "
                f"{fmt_money(probe.overshoot)} of the conversion is what buys "
                f"the whole step: convert {fmt_money(probe.headroom_before)} "
                f"instead and the surcharge is zero."), icon="🚨")
        elif probe.tiers_crossed > 0:
            st.warning(esc(
                f"This crosses {probe.tiers_crossed} cliff"
                f"{'s' if probe.tiers_crossed > 1 else ''}, but nobody in the "
                f"household is on Medicare in {probe.year_paid}, so it costs "
                f"nothing. From age {HC.CONVERSION_WINDOW_CLOSES_AT} on, the "
                f"same conversion would cost "
                f"{fmt_money(probe.extra_annual_cost)}."), icon="⚠️")
        else:
            st.success(esc(
                f"This stays inside {probe.after.label}. There is no Medicare "
                f"surcharge to pay in {probe.year_paid} for it."), icon="✅")

        # The step function itself. Nothing argues the cliff like drawing it.
        span = max(conversion * 1.6, 120_000.0)
        if not math.isinf(probe.headroom_before):
            span = max(span, probe.headroom_before * 1.6)
        step = max(250.0, span / 400.0)
        sweep = pd.DataFrame([
            {"Conversion": x,
             "Cost": HC.conversion_irmaa_cost(base_magi, x, joint,
                                              n_medicare, part_d)}
            for x in [i * step for i in range(int(span / step) + 1)]])
        line = alt.Chart(sweep).mark_line(
            interpolate="step-after", strokeWidth=2.2, color=C.ORANGE).encode(
            x=alt.X("Conversion:Q", title="Amount converted this year",
                    axis=alt.Axis(format="$,.0s"),
                    scale=alt.Scale(nice=False, zero=True)),
            y=alt.Y("Cost:Q",
                    title=f"Extra Medicare cost in {probe.year_paid}",
                    axis=alt.Axis(format="$,.0s")),
            tooltip=[alt.Tooltip("Conversion:Q", format="$,.0f"),
                     alt.Tooltip("Cost:Q", format="$,.0f")])
        marks = [line]
        if conversion > 0:
            marks.append(
                alt.Chart(pd.DataFrame({"Conversion": [conversion]}))
                .mark_rule(color=C.TEXT_SECONDARY, strokeWidth=1.5,
                           strokeDash=[4, 3])
                .encode(x="Conversion:Q"))
        st.altair_chart(
            alt.layer(*marks).properties(height=230)
            .configure_view(strokeWidth=0), use_container_width=True)
        st.caption("A staircase, not a ramp. The flat stretches are free; the "
                   "risers cost the same whether you step over them by a "
                   "dollar or by twenty thousand.")

    # ----------------------------------------------------------------------
    with section("Two things this page will not soften"):
        st.markdown(esc(
            f"**TRICARE For Life requires Medicare Part B.** TFL is not a plan "
            f"you enrol in — it is TRICARE paying second to Medicare, and it "
            f"exists only for people enrolled in Part A and Part B. Decline "
            f"Part B and you forfeit TFL: at 65 you would have no TRICARE at "
            f"all, and no Medigap or Medicare Advantage either, because both "
            f"require Part B as well. The premium — "
            f"{fmt_money(HC.FIGURES['part_b_standard_monthly'])} a month per "
            f"person in {HC.FIGURES['year']} — is the price of TFL, and there "
            f"is no version of this where you keep the coverage and skip the "
            f"premium. Enrol late and the premium carries a "
            f"{HC.FIGURES['part_b_late_penalty_per_year'] * 100:.0f}% penalty "
            f"for every full year you waited, for life."))
        st.markdown(esc(
            "**VA care is a parallel system, not family coverage.** A rated "
            "veteran can use the VA for service-connected conditions at no "
            "cost, and that is worth having — but it covers the veteran and "
            "nobody else. Your spouse and children are not VA patients. "
            "CHAMPVA covers the dependants of a 100% permanent and total "
            "veteran only when they are NOT TRICARE-eligible, which a "
            "retiree's family is. So the VA is a supplement to TRICARE for "
            "one person in the house; it is never a reason to drop the plan "
            "that covers the rest of them, and at 65 it is never a reason to "
            "decline Part B."))

    # ----------------------------------------------------------------------
    with section("What we found"):
        render_findings(HC.findings(h, lc, probe))

    # ----------------------------------------------------------------------
    with section("What this assumes, and where the numbers come from"):
        for a in lc.assumptions:
            st.markdown("- " + esc(a))
        st.caption(esc(MORT.explain(age_now, m.sex)))

        with st.expander(f"Every {HC.FIGURES['year']} figure on this page, and "
                         f"how far to trust it"):
            st.caption("This machine cannot reach tricare.mil, cms.gov or "
                       "ssa.gov, so none of these has been checked against the "
                       "published document. Each one says where to check it "
                       "and how much confidence it carries.")
            prov = []
            for key, note in HC.VERIFY.items():
                value = HC.FIGURES[key]
                if key == "irmaa_share_of_cost":
                    shown = ", ".join(fmt_pct(v) for v in value)
                elif isinstance(value, dict):
                    shown = ", ".join(f"{k}: {fmt_money(v)}"
                                      for k, v in value.items())
                elif isinstance(value, list):
                    shown = ", ".join(fmt_money(v) for v in value)
                elif key == "part_b_late_penalty_per_year":
                    shown = fmt_pct(value)
                elif key == "irmaa_lookback_years":
                    shown = f"{value} years"
                else:
                    shown = fmt_money(value)
                prov.append({"Figure": key, "As modelled": shown,
                             "Where to check it, and confidence": note})
            st.dataframe(pd.DataFrame(prov), use_container_width=True,
                         hide_index=True)

    st.caption("An estimator, not advice. TRICARE costs change every January "
               "and the Medicare figures change every November — check both "
               "against the published notices before you act on a number here. "
               "Military OneSource gives free counselling at 800-342-9647.")
