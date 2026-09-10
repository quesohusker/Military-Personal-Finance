import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import streamlit as st
import pandas as pd
import altair as alt

from ui.panel import (wkey, get_household, page_header, two_pane, input_card,
                      section, metric_row, money, integer, toggle, fmt_money,
                      fmt_pct, esc, render_findings)
from engine.estate import planning as EP

BLUE, ORANGE, GREEN = "#2a78d6", "#eb6834", "#1baf7a"

REQUIRED = "The gift that reaches your target"
PLANNED = "What you are gifting now"

h = get_household()
e = h.estate

page_header("🎁 Estate",
            "A beneficiary designation beats a will every time. Most of what "
            "you own never reaches the will at all — so the form on file at "
            "the TSP matters more than the document in the safe.")

inputs, results = two_pane()

# ==========================================================================
# Left: the questions, stacked.
# ==========================================================================
with inputs:
    with input_card("Your will and your powers of attorney"):
        toggle("Do you have a current will?", e, "has_will", key=wkey("est_will"),
               help="Free at any installation legal assistance office under "
                    "10 U.S.C. 1044, while you serve and as a retiree on a "
                    "space-available basis. A military testamentary "
                    "instrument is exempt from state formality rules, which "
                    "matters when you sign in Germany and die domiciled in "
                    "Texas.")
        has_poa = st.toggle("Do you have a current power of attorney and "
                            "medical directive?", value=False,
                            key=wkey("est_poa"),
                            help="A will is for after you die. These are for "
                                 "the eleven months you are deployed or the "
                                 "six weeks you are unconscious — the far "
                                 "more likely case. Not saved with the plan.")

    with input_card("Your beneficiary designations"):
        toggle("Is your TSP beneficiary designation current?", e,
               "tsp_beneficiary_current", key=wkey("est_tspben"),
               help="Form TSP-3 by its old name; now made online at tsp.gov "
                    "under My Account. With nothing valid on file the "
                    "statutory order of precedence applies instead.")
        toggle("Is your SGLI beneficiary designation current?", e,
               "sgli_beneficiary_current", key=wkey("est_sgliben"),
               help="Form SGLV 8286, now filed in SOES through milConnect. A "
                    "paper form sitting in a personnel file from 2009 is "
                    "still the one that pays.")
        toggle("Is your IRA beneficiary designation current?", e,
               "ira_beneficiary_current", key=wkey("est_iraben"),
               help="Held by the custodian, not by you. Vanguard, Fidelity "
                    "and Schwab each keep it somewhere different and none of "
                    "them will remind you.")

    with input_card("Your children, and what you want them to have"):
        integer("How many children do you have?", e, "n_children",
                key=wkey("est_kids"), min_value=0, max_value=15)
        money("What do you want each child to end up with?", e,
              "target_legacy_per_child", key=wkey("est_target"), step=25_000.0,
              help="In today's dollars, at your life expectancy. Leave it at "
                   "zero if you have no target — the rest of the page still "
                   "works.")
        money("What are you gifting each child a year now?", e,
              "annual_gift_per_child", key=wkey("est_gift"), step=1_000.0)
        integer("What year do you start gifting?", e, "gifting_start_year",
                key=wkey("est_start"), min_value=2020, max_value=2100)

    with input_card("Your heirs' tax rate"):
        heir_rate = st.select_slider(
            "What tax rate would your children pay?",
            options=[0.10, 0.12, 0.22, 0.24, 0.32, 0.35, 0.37],
            value=EP.DEFAULT_HEIR_MARGINAL_RATE,
            format_func=lambda v: f"{v * 100:.0f}%", key=wkey("est_heirrate"),
            help="Their bracket during the ten years they have to empty an "
                 "inherited traditional account — stacked on top of their own "
                 "salary in their peak earning years, not into the empty "
                 "brackets you get to fill in retirement.")

# ==========================================================================
# The arithmetic, once every answer is in.
# ==========================================================================
checklist = EP.beneficiary_checklist(h)
comp = EP.inheritance_comparison(h, heir_rate)
tax = EP.estate_tax_check(h)
plan = EP.gifting_plan(h, heir_rate)
all_findings = EP.findings(h, heir_rate, has_poa=has_poa)

# ==========================================================================
# Right: what those answers mean.
# ==========================================================================
with results:

    # ---------------------------------------------------------------- 1
    with section("What overrides your will",
                 "The TSP, SGLI and an IRA each pay whoever is named on their "
                 "own form. A probate court never sees them, and a divorce "
                 "decree does not change them."):
        accounts = EP.designated_accounts(h)
        designated_total = sum(a.balance for a in accounts)
        stale_total = sum(a.balance for a in accounts if not a.designated)
        metric_row([
            ("Passes by designation", fmt_money(designated_total)),
            ("With no current form", fmt_money(stale_total)),
            ("Gross estate", fmt_money(tax.gross_estate)),
            ("Reaches your will",
             fmt_money(max(0.0, tax.taxable_estate - designated_total))),
        ])

        if stale_total > 0:
            st.error(esc(
                f"{fmt_money(stale_total)} would pass to whoever is named on "
                f"a form you have not confirmed. In Ridgway v. Ridgway (1981) "
                f"the Supreme Court held that SGLI goes to the named "
                f"beneficiary even against a state divorce decree ordering "
                f"otherwise — federal law preempts the decree, and the person "
                f"on the form is paid."), icon="🚨")
        elif designated_total > 0:
            st.success(esc(
                f"{fmt_money(designated_total)} is designated and you have "
                f"confirmed the forms are current. Re-confirm after every "
                f"marriage, divorce, birth and death — and read the form "
                f"rather than remembering what you put on it."), icon="✅")

        render_findings(checklist)

        with st.expander("If no valid form is on file"):
            st.markdown("**The TSP**, under 5 U.S.C. 8424(d):")
            for i, who in enumerate(EP.TSP_ORDER_OF_PRECEDENCE, 1):
                st.markdown(f"{i}. {esc(who)}")
            st.markdown("**SGLI**, under 38 U.S.C. 1970(a):")
            for i, who in enumerate(EP.SGLI_ORDER_OF_PRECEDENCE, 1):
                st.markdown(f"{i}. {esc(who)}")
            st.caption("That order pays your parents before a long-term "
                       "partner, and pays a minor child directly — into a "
                       "court-supervised guardianship, released to them in "
                       "full at the age of majority, which is eighteen in "
                       "most states. A trust named as beneficiary is how you "
                       "avoid handing a teenager a lump sum.")

        st.caption(esc(EP.LEGAL_ASSISTANCE))

    # ---------------------------------------------------------------- 2
    with section("Traditional or Roth, in your heirs' hands",
                 "The same balance delivers very different amounts depending "
                 "on which wrapper it dies in. These are your actual "
                 "balances."):
        metric_row([
            ("Traditional", fmt_money(comp.traditional_balance),
             f"{fmt_money(-comp.heir_tax_on_traditional)} to tax"),
            ("Roth", fmt_money(comp.roth_after_tax), "passes whole"),
            ("Taxable", fmt_money(comp.taxable_after_tax), "basis steps up"),
            ("Life insurance", fmt_money(comp.insurance_after_tax),
             "tax-free"),
        ])

        rows = [
            {"Where it sits": "Traditional TSP + IRA",
             "Balance": fmt_money(comp.traditional_balance),
             "Heir's tax": fmt_money(comp.heir_tax_on_traditional),
             "They receive": fmt_money(comp.traditional_after_tax),
             "Why": f"SECURE Act {EP.SECURE_DRAIN_YEARS}-year rule; ordinary "
                    f"income at {fmt_pct(heir_rate)}"},
            {"Where it sits": "Roth TSP + IRA",
             "Balance": fmt_money(comp.roth_balance),
             "Heir's tax": fmt_money(0.0),
             "They receive": fmt_money(comp.roth_after_tax),
             "Why": f"same {EP.SECURE_DRAIN_YEARS}-year deadline, no tax"},
            {"Where it sits": "Taxable brokerage",
             "Balance": fmt_money(comp.taxable_balance),
             "Heir's tax": fmt_money(0.0),
             "They receive": fmt_money(comp.taxable_after_tax),
             "Why": "step-up in basis at death, IRC 1014"},
            {"Where it sits": "SGLI / life insurance",
             "Balance": fmt_money(comp.insurance_proceeds),
             "Heir's tax": fmt_money(0.0),
             "They receive": fmt_money(comp.insurance_after_tax),
             "Why": "not income to the beneficiary, IRC 101(a)"},
        ]
        st.dataframe(pd.DataFrame(rows), use_container_width=True,
                     hide_index=True)

        if comp.gap_if_converted > 0:
            st.warning(esc(
                f"Converting today's {fmt_money(comp.traditional_balance)} of "
                f"traditional money to Roth would hand your heirs "
                f"{fmt_money(comp.gap_if_converted)} more, before counting "
                f"what you would pay in tax to do it. That is the estate "
                f"argument for conversions — the Roth Conversions page "
                f"weighs it against your own lifetime tax bill, which is the "
                f"other half of the decision."), icon="⚠️")

        for n in comp.notes:
            st.markdown("- " + esc(n))

        st.caption("A surviving SPOUSE is the exception to all of it: they "
                   "may roll an inherited IRA into their own and restart the "
                   "clock, and they are the only person who can keep money "
                   "inside the TSP.")

    # ---------------------------------------------------------------- 3
    with section("Gifting now, or a bequest later",
                 "What it takes to hand each child a target sum, against what "
                 "dying would deliver instead. Real terms, today's dollars, "
                 "throughout."):
        if plan.n_children <= 0:
            st.info("Enter how many children you have on the left to build a "
                    "gifting plan. The annual exclusion is per RECIPIENT, and "
                    "a recipient does not have to be a child.", icon="ℹ️")
        elif plan.years <= 0:
            st.warning(esc(
                f"Your start year of {plan.start_year} is past the planning "
                f"horizon of {plan.end_year}, so there is no window to gift "
                f"in. Move the start year earlier."), icon="⚠️")
        else:
            metric_row([
                ("Needed per child, a year",
                 fmt_money(plan.required_annual_gift_per_child)),
                ("Across all children",
                 fmt_money(plan.required_annual_gift_total)),
                ("Annual exclusion, per child",
                 fmt_money(plan.exclusion_per_child),
                 "married couple" if plan.married else "single donor"),
                ("Years of gifting", f"{plan.years}",
                 f"{plan.start_year}–{plan.end_year}"),
            ])
            metric_row([
                ("Target per child", fmt_money(plan.target_per_child)),
                ("Your current gift reaches",
                 fmt_money(plan.planned_value_per_child),
                 fmt_money(-plan.shortfall_per_child)
                 if plan.shortfall_per_child > 0 else "on target"),
                ("A bequest would deliver",
                 fmt_money(plan.bequest_per_child_after_tax),
                 f"after {fmt_money(plan.heir_tax_at_death)} of heirs' tax"),
                ("Total you would gift",
                 fmt_money(plan.required_total_gifted_per_child
                           * plan.n_children)),
            ])

            if plan.cap_binds:
                st.warning(esc(
                    f"The annual exclusion binds in {len(plan.capped_years)} "
                    f"of the {plan.years} years, by "
                    f"{fmt_money(plan.excess_per_child_per_year)} per child a "
                    f"year. Nothing is owed — you file Form 709 with your tax "
                    f"return and the excess is charged against your lifetime "
                    f"exemption of "
                    f"{fmt_money(EP.FEDERAL_ESTATE_EXEMPTION)} per person. "
                    f"That is reporting, not tax."), icon="⚠️")
            elif plan.target_per_child > 0:
                st.success(esc(
                    f"The whole schedule sits inside the "
                    f"{fmt_money(plan.exclusion_per_child)} annual exclusion, "
                    f"so there is no Form 709, no reporting, and no use of "
                    f"your lifetime exemption."), icon="✅")

            # ---- The chart: each child's account, year by year ----------
            chart_rows = []
            for r in plan.rows:
                chart_rows.append({"Year": r.year, "Series": REQUIRED,
                                   "Value": r.required_value_per_child})
                if plan.planned_annual_gift_per_child > 0:
                    chart_rows.append({"Year": r.year, "Series": PLANNED,
                                       "Value": r.planned_value_per_child})
            cdf = pd.DataFrame(chart_rows)
            if len(cdf):
                # Only colour the series that are actually drawn, or the
                # legend advertises a line that is not there.
                domain = [s for s in (REQUIRED, PLANNED)
                          if s in set(cdf["Series"])]
                colours = [{REQUIRED: BLUE, PLANNED: ORANGE}[s] for s in domain]
                lines = alt.Chart(cdf).mark_line(
                    strokeWidth=2.2, interpolate="monotone").encode(
                    x=alt.X("Year:Q",
                            axis=alt.Axis(format="d", title=alt.Undefined),
                            scale=alt.Scale(nice=False, zero=False)),
                    y=alt.Y("Value:Q",
                            axis=alt.Axis(format="$,.0s",
                                          title="One child's account, "
                                                "today's dollars")),
                    # Vega-Lite reads a null legend title as "no title";
                    # alt.Undefined would fall back to the field name here.
                    color=alt.Color("Series:N",
                                    scale=alt.Scale(domain=domain,
                                                    range=colours),
                                    legend=alt.Legend(orient="top",
                                                      title=None)),
                    tooltip=["Year:Q", "Series:N",
                             alt.Tooltip("Value:Q", format="$,.0f")])
                layers = [lines]
                if plan.target_per_child > 0:
                    target_df = pd.DataFrame({"Target": [plan.target_per_child]})
                    layers.append(
                        alt.Chart(target_df).mark_rule(
                            color=GREEN, strokeDash=[6, 4], strokeWidth=2)
                        .encode(y=alt.Y("Target:Q"),
                                tooltip=[alt.Tooltip("Target:Q",
                                                     format="$,.0f")]))
                st.altair_chart(
                    alt.layer(*layers).properties(height=260)
                    .configure_view(strokeWidth=0),
                    use_container_width=True)
                st.caption(esc(
                    f"The dashed line is your {fmt_money(plan.target_per_child)} "
                    f"target. Money given early does the compounding; money "
                    f"given at death does none of it."))

            # ---- The table ----------------------------------------------
            step = max(1, plan.years // 12)
            keep = [r for i, r in enumerate(plan.rows)
                    if i % step == 0 or r is plan.rows[-1]]
            trows = [{
                "Year": str(r.year),
                "Your age": str(r.donor_age),
                "Gift per child": fmt_money(r.required_gift_per_child),
                "Their account": fmt_money(r.required_value_per_child),
                "At your current gift": fmt_money(r.planned_value_per_child),
                "Target": fmt_money(r.target_per_child),
                "Over the exclusion?": "Form 709" if r.over_exclusion else "no",
            } for r in keep]
            st.dataframe(pd.DataFrame(trows), use_container_width=True,
                         hide_index=True)

            for n in plan.notes:
                st.markdown("- " + esc(n))

        with st.expander("Two gifts worth more than the cash"):
            st.markdown(esc(
                f"**Superfund a 529.** The five-year election under IRC "
                f"529(c)(2)(B) lets you put "
                f"{fmt_money(EP.superfund_529(bool(h.has_spouse)))} into one "
                f"beneficiary's 529 in a single contribution — five years of "
                f"annual exclusion at once — by electing on Form 709 to "
                f"spread it. No further exclusion-covered gifts to that "
                f"child are available until it runs out, and if you die "
                f"inside the five years the unused part comes back into your "
                f"estate. So make the election early, not as a deathbed "
                f"manoeuvre."))
            st.markdown(esc(
                f"**Fund a Roth IRA for a child with a real job.** The "
                f"contribution is capped by the child's own EARNED income, "
                f"not by whose money it is — a teenager who makes "
                f"{fmt_money(4_000)} lifeguarding can have "
                f"{fmt_money(EP.roth_ira_for_a_child(4_000, h.limits.ira_contribution))} "
                f"put in by you, up to the "
                f"{fmt_money(h.limits.ira_contribution)} IRA limit. It is a "
                f"gift covered many times over by the annual exclusion, in "
                f"the lowest bracket they will ever be in, with fifty years "
                f"of tax-free compounding ahead of it."))

    # ---------------------------------------------------------------- 4
    with section("Federal estate tax, and the one that might actually apply",
                 "Almost no military family owes federal estate tax. The "
                 "state you are domiciled in when you die is the real thing "
                 "to check."):
        metric_row([
            ("Gross estate", fmt_money(tax.gross_estate)),
            ("Less debts", fmt_money(tax.debts)),
            ("Exemption", fmt_money(tax.exemption_applied),
             "two, with portability" if tax.married else "one person"),
            ("Federal estate tax", fmt_money(tax.federal_tax)),
        ])

        if tax.owes_federal_estate_tax:
            st.error(esc(
                f"{fmt_money(tax.amount_over_exemption)} sits above the "
                f"exemption, which at {fmt_pct(EP.ESTATE_TAX_TOP_RATE)} is "
                f"{fmt_money(tax.federal_tax)} of federal estate tax. At this "
                f"size see a specialist estate attorney, not an installation "
                f"legal assistance office — they do simple wills, and they do "
                f"them well, but this is not that."), icon="🚨")
        else:
            st.success(esc(
                f"You are {fmt_money(tax.headroom)} below the exemption. "
                f"Federal estate tax is not your problem, and advice that "
                f"opens with it is selling you something."), icon="✅")

        for n in tax.notes:
            st.markdown("- " + esc(n))

        with st.expander("States with their own estate or inheritance tax"):
            srows = [{"State": s, "Kind": "Estate tax",
                      "Applies from about": fmt_money(v[0]),
                      "Note": v[1] or "—"}
                     for s, v in sorted(EP.STATE_ESTATE_TAX.items())]
            srows += [{"State": s, "Kind": "Inheritance tax",
                       "Applies from about": "any amount",
                       "Note": note}
                      for s, note in sorted(EP.STATE_INHERITANCE_TAX.items())]
            st.dataframe(pd.DataFrame(srows), use_container_width=True,
                         hide_index=True)
            st.caption("VERIFY before relying on any of it — the list moves, "
                       "and the unindexed thresholds drift in real terms "
                       "every year. An estate tax is paid by the estate; an "
                       "inheritance tax is paid by the person receiving, at a "
                       "rate set by how closely related they were.")

    # ---------------------------------------------------------------- 5
    with section("What to do first",
                 "Ordered by the money at stake, not by subject. Everything "
                 "at the top is fixable in an afternoon and free."):
        render_findings(all_findings)

        with st.expander("Where these figures come from"):
            st.caption(f"Statutory figures are {EP.FIGURE_YEAR} values, stated "
                       f"from knowledge and marked VERIFY. This machine "
                       f"cannot reach irs.gov.")
            for name, note in EP.VERIFY.items():
                st.markdown(f"**{name}** — {esc(note)}")

    st.caption("An estimator, not legal advice. A will, a general or special "
               "power of attorney and an advance medical directive are free "
               "at any installation legal assistance office, and Military "
               "OneSource gives free counselling at 800-342-9647.")
