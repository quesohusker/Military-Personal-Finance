import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import streamlit as st
import pandas as pd
import altair as alt
import numpy as np

from ui.panel import (wkey, get_household, page_header, two_pane, input_card,
                      section, metric_row, choice, fmt_money, fmt_pct, esc,
                      md_money, render_findings)
from engine.retirement import roth_bridge as RB
from engine.retirement.roth_analysis import (compare, sweep_target_brackets,
                                             sweep_tax_scenarios)
from engine.retirement.montecarlo import run_monte_carlo
from engine.roth_profile import Profile, ConversionPlan, validate
from engine.briefing import (build_briefing, briefing_filename, BriefingOptions,
                             TABLE_MODES)
from engine.tax import tables as T
from engine.tax import federal as FED
from engine import mortality as MORT

BLUE, ORANGE, GREEN, AMBER, GREY = "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#5a6b73"
DONT, DO = "Don't convert", "Convert"
BRACKETS = [0.10, 0.12, 0.22, 0.24, 0.32, 0.35, 0.37]
MC_KEY = "mc_summary"          # reserved in ui.panel.RESULT_KEYS; invalidate() clears it

h = get_household()
m = h.member
d = RB.default_inputs(h)
status = T.MFJ if h.has_spouse else T.SINGLE
age_now = max(0, d.start_year - m.birth_year)

# Bounds for the year and age questions. They live in the bridge, which keeps
# every default it hands back inside them: Streamlit REFUSES a value outside a
# widget's range rather than clamping it, so the two have to agree.
LAST_YEAR = int(d.start_year + RB.MAX_HORIZON_YEARS)
OLDEST = int(RB.MAX_PLANNING_AGE)

page_header("🔁 Roth Conversions",
            "Two futures on the same assumptions — one where you convert part of "
            "the traditional balance each year and pay the tax now, one where you "
            "leave it alone and let the RMDs arrive — compared on lifetime tax and "
            "on what is left after every tax bill: yours, your survivor's and your "
            "heirs'.")


# --------------------------------------------------------------------------
# The engine is fast (a projection is a few milliseconds) but the sweeps run
# a dozen of them, so the deterministic work is cached on the engine profile
# itself. Anything that changes the profile changes the key.
# --------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def _analyse(profile_json: str):
    p = Profile.from_json(profile_json)
    return compare(p), sweep_target_brackets(p)


@st.cache_data(show_spinner=False)
def _sensitivity(profile_json: str, change_year: int, points: float):
    p = Profile.from_json(profile_json)
    return sweep_tax_scenarios(p, RB.scenario_policies(change_year, points))


def _pct_label(v: float) -> str:
    return f"{v * 100:.0f}%"


inputs, results = two_pane()

# ==========================================================================
# Left: the questions, stacked.
# ==========================================================================
with inputs:
    with input_card("The conversion you are testing"):
        strategy = st.selectbox("How would you decide how much to convert each year?",
                                RB.STRATEGIES, index=0, key=wkey("rc_strategy"),
                                help="Filling a bracket is the usual answer: convert "
                                     "exactly enough to reach the top of a chosen "
                                     "federal bracket and no more. The other "
                                     "strategies are here to test against it.")
        target_bracket = d.target_bracket
        fixed_amount = d.fixed_amount
        irmaa_tier = d.irmaa_tier_index
        percent_of_balance = d.percent_of_balance
        target_remaining = d.target_remaining_balance
        if strategy == ConversionPlan.STRATEGY_BRACKET:
            target_bracket = st.select_slider(
                "Which bracket would you fill to the top of?", options=BRACKETS,
                value=d.target_bracket, format_func=_pct_label, key=wkey("rc_bracket"),
                help="Applied to whichever rate schedule is in force that year. "
                     "Under a pre-TCJA schedule there is no 22% band, so a 22% "
                     "target fills the 15% band instead.")
        elif strategy == ConversionPlan.STRATEGY_FIXED:
            fixed_amount = st.number_input("How much would you convert each year?",
                                           value=float(d.fixed_amount), min_value=0.0,
                                           step=5_000.0, format="%.0f",
                                           key=wkey("rc_fixed"))
        elif strategy == ConversionPlan.STRATEGY_IRMAA:
            ceilings = FED.irmaa_tier_ceilings(status)
            irmaa_tier = st.selectbox(
                "Which Medicare IRMAA ceiling would you stay under?",
                options=list(range(len(ceilings))),
                format_func=lambda i: f"Tier {i + 1} — MAGI up to {fmt_money(ceilings[i])}",
                key=wkey("rc_irmaa"),
                help="IRMAA is a cliff assessed on income from two years earlier. "
                     "Within two years of 65 this is the strategy to compare.")
        elif strategy == ConversionPlan.STRATEGY_PERCENT:
            percent_of_balance = st.number_input(
                "What share of the balance would you convert each year? (%)",
                value=float(d.percent_of_balance * 100), min_value=0.0,
                max_value=100.0, step=1.0, format="%.1f", key=wkey("rc_pct")) / 100.0
        else:
            target_remaining = st.number_input(
                "How much would you leave in traditional accounts by the end?",
                value=float(d.target_remaining_balance), min_value=0.0,
                step=25_000.0, format="%.0f", key=wkey("rc_target"))

        c_start = st.number_input("What year would you start converting?",
                                  value=int(d.conversion_start_year),
                                  min_value=int(d.start_year),
                                  max_value=LAST_YEAR, step=1,
                                  key=wkey("rc_cstart"))
        c_end = st.number_input("What year would you stop?",
                                value=int(d.conversion_end_year),
                                min_value=int(d.start_year),
                                max_value=LAST_YEAR, step=1,
                                key=wkey("rc_cend"),
                                help="Defaults to the year before your first RMD. "
                                     "A window that ends before the year it starts "
                                     "is treated as a single year.")
        pay_from_taxable = st.toggle("Would you pay the conversion tax from outside the IRA?",
                                     value=bool(d.pay_tax_from_taxable),
                                     key=wkey("rc_payout"),
                                     help="Paying it from the conversion itself is the "
                                          "most common way a Roth conversion fails to "
                                          "pay off — and before 59½ the withheld tax "
                                          "is itself penalised.")
        annual_cap = st.number_input("Is there a hard cap per year? (0 = none)",
                                     value=float(d.annual_cap), min_value=0.0,
                                     step=10_000.0, format="%.0f", key=wkey("rc_cap"))
        skip_working = st.toggle("Would you skip years you are still earning wages?",
                                 value=bool(d.skip_while_working), key=wkey("rc_skip"))

    with input_card("How long you will work, and live"):
        wages = st.number_input("What taxable wages will you earn this year?",
                                value=float(d.wages_annual), min_value=0.0,
                                step=1_000.0, format="%.0f", key=wkey("rc_wages"),
                                help="Basic pay and taxable special pays if you are "
                                     "still serving — BAH and BAS are not wages — plus "
                                     "any civilian job. Retired pay is separate.")
        work_through = st.number_input("What is the last year you will earn wages?",
                                       value=int(d.work_through_year),
                                       min_value=int(d.start_year - 1),
                                       max_value=LAST_YEAR, step=1,
                                       key=wkey("rc_workthru"),
                                       help="Set it to last year if you have already "
                                            "stopped. The years between the last "
                                            "paycheque and the first RMD are usually "
                                            "the conversion window.")
        death_age = st.number_input("How long do you expect to live?",
                                    value=int(d.death_age),
                                    min_value=min(int(age_now + 1), OLDEST),
                                    max_value=OLDEST, step=1,
                                    key=wkey("rc_death"),
                                    help=MORT.explain(age_now, m.sex)
                                         + f" The default adds the plan's "
                                           f"{h.assumptions.planning_margin_years}-year "
                                           f"margin on top.")
        spouse_birth = d.spouse_birth_year
        spouse_wages = d.spouse_wages_annual
        spouse_work_through = d.spouse_work_through_year
        spouse_death_age = d.spouse_death_age
        if h.has_spouse:
            spouse_birth = st.number_input("What year was your spouse born?",
                                           value=int(d.spouse_birth_year),
                                           min_value=RB.MIN_BIRTH_YEAR,
                                           max_value=RB.MAX_BIRTH_YEAR, step=1,
                                           key=wkey("rc_spbirth"))
            spouse_wages = st.number_input("What will your spouse earn this year?",
                                           value=float(d.spouse_wages_annual),
                                           min_value=0.0, step=1_000.0, format="%.0f",
                                           key=wkey("rc_spwages"),
                                           help="Read from the spouse income on the "
                                                "Career page.")
            spouse_work_through = st.number_input(
                "What is the last year your spouse will earn wages?",
                value=int(d.spouse_work_through_year), min_value=int(d.start_year - 1),
                max_value=LAST_YEAR, step=1, key=wkey("rc_spworkthru"))
            spouse_death_age = st.number_input(
                "How long do you expect your spouse to live?",
                value=int(d.spouse_death_age),
                min_value=min(int(max(1, d.start_year - spouse_birth + 1)), OLDEST),
                max_value=OLDEST, step=1, key=wkey("rc_spdeath"),
                help="The survivor years are where the widow's penalty lives. Move "
                     "this and watch the survivor finding.")

    with input_card("Balances your plan file does not carry"):
        spouse_trad = d.spouse_traditional_balance
        spouse_roth = d.spouse_roth_balance
        if h.has_spouse:
            spouse_trad = st.number_input(
                "How much does your spouse hold in traditional accounts?",
                value=float(d.spouse_traditional_balance), min_value=0.0,
                step=5_000.0, format="%.0f", key=wkey("rc_sptrad"),
                help="A 401(k), a TSP of their own, a traditional IRA. It has RMDs "
                     "of its own.")
            spouse_roth = st.number_input(
                "How much does your spouse hold in Roth accounts?",
                value=float(d.spouse_roth_balance), min_value=0.0, step=5_000.0,
                format="%.0f", key=wkey("rc_sproth"))
        cost_basis = st.number_input("What is the cost basis of your brokerage account?",
                                     value=float(d.taxable_cost_basis), min_value=0.0,
                                     step=5_000.0, format="%.0f", key=wkey("rc_basis"),
                                     help="What you paid for what is in it. The gap "
                                          "between basis and balance is taxed when "
                                          "the account is drawn on to pay conversion "
                                          "tax. Leave it equal to the balance if you "
                                          "do not know.")

    with input_card("Your heirs and your survivor"):
        n_heirs = st.number_input("How many beneficiaries will inherit?",
                                  value=int(d.n_beneficiaries), min_value=1,
                                  max_value=RB.MAX_BENEFICIARIES, step=1,
                                  key=wkey("rc_heirs"))
        heir_rate = st.select_slider("What federal bracket will your heirs be in?",
                                     options=BRACKETS, value=d.heir_marginal_rate,
                                     format_func=_pct_label, key=wkey("rc_heirrate"),
                                     help="They must empty an inherited traditional "
                                          "account within ten years, usually during "
                                          "their own peak earning years.")
        dic = d.dic_applies
        if h.has_spouse:
            dic = st.toggle("Would your survivor qualify for DIC?", value=bool(d.dic_applies),
                            key=wkey("rc_dic"),
                            help="Generally applies if you were rated totally disabled "
                                 "for the qualifying period, or die of a "
                                 "service-connected cause. Tax-free, and since 2023 "
                                 "no longer offset against SBP.")

    with input_card("Future tax law"):
        choice("What happens to federal tax rates?", h.assumptions, "tax_scenario",
               RB.TAX_SCENARIOS, key=wkey("rc_taxscen"),
               help="A plan-wide assumption, shared with every other page. "
                    + RB.TAX_SCENARIO_HELP.get(h.assumptions.tax_scenario, ""))
        change_year = d.tax_change_year
        surcharge = d.surcharge_points
        if h.assumptions.tax_scenario != RB.TAX_CURRENT:
            change_year = st.number_input("In what year would the change take effect?",
                                          value=int(d.tax_change_year),
                                          min_value=int(d.start_year),
                                          max_value=LAST_YEAR, step=1,
                                          key=wkey("rc_chyear"))
        if h.assumptions.tax_scenario == RB.TAX_HIGHER:
            surcharge = st.number_input("How many points would every rate rise by?",
                                        value=float(d.surcharge_points), min_value=0.0,
                                        max_value=20.0, step=0.5, format="%.1f",
                                        key=wkey("rc_points"))

    with input_card("Monte Carlo"):
        n_paths = st.slider("How many market histories should we simulate?",
                            min_value=50, max_value=RB.MAX_MC_PATHS,
                            value=int(d.mc_paths), step=50, key=wkey("rc_paths"),
                            help=f"Both futures run on the same random sequence in "
                                 f"each path, so a few hundred is enough to see "
                                 f"whether converting wins. Capped at "
                                 f"{RB.MAX_MC_PATHS} to keep the page responsive.")
        stdev = st.number_input("How volatile are real returns? (% a year)",
                                value=float(d.return_stdev * 100), min_value=0.0,
                                max_value=40.0, step=1.0, format="%.1f",
                                key=wkey("rc_stdev"),
                                help="Standard deviation of annual real returns. "
                                     "About 14% for a balanced portfolio.")
        run_mc = st.button("▶ Run the Monte Carlo", type="primary",
                           use_container_width=True, key=wkey("rc_runmc"))

    with input_card("Ask an LLM about this"):
        anonymize = st.toggle("Leave names out of the briefing?", value=True,
                              key=wkey("rc_anon"))
        table_mode = st.selectbox("How much of the year-by-year table should it carry?",
                                  TABLE_MODES, index=0, key=wkey("rc_tmode"))
        round_to = st.selectbox("Round the dollar figures?", [0, 1_000, 10_000],
                                format_func=lambda v: "Exact" if v == 0
                                else f"To the nearest {fmt_money(v)}",
                                key=wkey("rc_round"))
        include_json = st.toggle("Append the full engine profile as JSON?", value=False,
                                 key=wkey("rc_json"),
                                 help="Lets the reviewer reload exactly what the "
                                      "engine saw. Also the least anonymous option.")

# ==========================================================================
# The arithmetic, once every answer is in.
# ==========================================================================
ri = RB.RothInputs(
    start_year=d.start_year,
    wages_annual=float(wages), work_through_year=int(work_through),
    death_age=int(death_age),
    spouse_birth_year=int(spouse_birth), spouse_wages_annual=float(spouse_wages),
    spouse_work_through_year=int(spouse_work_through),
    spouse_death_age=int(spouse_death_age),
    spouse_traditional_balance=float(spouse_trad), spouse_roth_balance=float(spouse_roth),
    taxable_cost_basis=float(cost_basis),
    strategy=strategy, target_bracket=float(target_bracket),
    fixed_amount=float(fixed_amount), irmaa_tier_index=int(irmaa_tier),
    percent_of_balance=float(percent_of_balance),
    target_remaining_balance=float(target_remaining),
    conversion_start_year=int(c_start), conversion_end_year=int(max(c_start, c_end)),
    pay_tax_from_taxable=bool(pay_from_taxable), annual_cap=float(annual_cap),
    skip_while_working=bool(skip_working),
    n_beneficiaries=int(n_heirs), heir_marginal_rate=float(heir_rate),
    dic_applies=bool(dic),
    tax_change_year=int(change_year), surcharge_points=float(surcharge),
    mc_paths=int(n_paths), return_stdev=float(stdev) / 100.0,
    inflation_stdev=d.inflation_stdev, random_seed=d.random_seed,
)
p = RB.to_roth_profile(h, ri)
pj = p.to_json()
issues = validate(p)
trad_total = p.primary.traditional_balance + (p.spouse.traditional_balance if p.has_spouse else 0.0)

c, bracket_sweep = _analyse(pj)
scenario_sweep = _sensitivity(pj, ri.tax_change_year, ri.surcharge_points)
base, conv = c.base, c.conv


def _frame(res, label: str) -> pd.DataFrame:
    df = pd.DataFrame([{
        "Year": r.year, "Age": r.age_primary, "Future": label,
        "Filing": "Joint" if r.filing_status == T.MFJ else "Single",
        "Wages": r.wages, "Retired pay": r.military_retired_pay,
        "SBP annuity": r.sbp_annuity, "Social Security": r.social_security,
        "Other pension": r.civilian_pension + r.other_taxable,
        "RMD": r.rmd, "Conversion": r.conversion, "AGI": r.agi,
        "Marginal rate": r.marginal_rate, "Tax": r.total_tax,
        "IRMAA surcharge": r.irmaa_surcharge_only,
        "Traditional": r.traditional_balance, "Roth": r.roth_balance,
        "Taxable + cash": r.taxable_balance + r.cash_balance,
    } for r in res.rows])
    if len(df):
        df["Cumulative tax"] = df["Tax"].cumsum()
    return df


dfb, dfc = _frame(base, DONT), _frame(conv, DO)
both = pd.concat([dfb, dfc], ignore_index=True)
future_scale = alt.Scale(domain=[DONT, DO], range=[GREY, BLUE])
year_axis = alt.X("Year:Q", axis=alt.Axis(format="d", title=None),
                  scale=alt.Scale(nice=False, zero=False))

# ==========================================================================
# Right: what those answers mean.
# ==========================================================================
with results:
    with section("Two futures, side by side",
                 "Same household, same returns, same tax law. The only difference "
                 "is whether the conversion plan on the left is carried out."):

        for issue in issues:
            st.warning(esc(issue), icon="⚠️")
        if p.state and not RB.state_is_known(p.state):
            st.warning(esc(f"'{p.state}' is not in the state tax table, so state tax "
                           f"is modelled as zero. Set the state of legal residence "
                           f"to a full state name on the Profile page."), icon="⚠️")

        if trad_total <= 0 and conv.lifetime_conversions <= 0:
            st.info("There is no traditional balance to convert, so the two futures "
                    "are identical. Enter your traditional TSP or IRA balance on the "
                    "Accounts page, or read a statement in.", icon="ℹ️")
        elif c.converting_wins:
            st.success(
                f"**Converting leaves {md_money(c.legacy_gain)} more after every tax "
                f"bill — yours, your survivor's and your heirs'.** Lifetime tax "
                f"{'falls' if c.tax_saved >= 0 else 'rises'} by "
                f"{md_money(abs(c.tax_saved))} in today's dollars"
                + (f", and the conversion path pulls ahead in {c.breakeven_year}."
                   if c.breakeven_year else
                   "; the gain comes from what is left at death rather than from "
                   "a lower tax bill in life."), icon="✅")
        else:
            st.error(
                f"**On these settings converting loses {md_money(-c.legacy_gain)}.** "
                f"Lifetime tax {'rises' if c.tax_saved < 0 else 'falls'} by "
                f"{md_money(abs(c.tax_saved))}. Do not convert on faith — try a "
                f"different target bracket, a later window, or paying the tax from "
                f"outside the IRA, and look at the sweep below.", icon="🚨")

        metric_row([
            ("Lifetime tax — don't convert", fmt_money(base.lifetime_total_tax)),
            ("Lifetime tax — convert", fmt_money(conv.lifetime_total_tax)),
            ("Difference in tax", fmt_money(conv.lifetime_total_tax - base.lifetime_total_tax)),
            ("Discounted at " + fmt_pct(p.assumptions.discount_rate, 1),
             fmt_money(conv.lifetime_total_tax_discounted - base.lifetime_total_tax_discounted)),
        ])
        metric_row([
            ("To heirs after tax — don't convert", fmt_money(base.heir_value_total)),
            ("To heirs after tax — convert", fmt_money(conv.heir_value_total),
             fmt_money(c.legacy_gain)),
            ("Total converted", fmt_money(conv.lifetime_conversions)),
            ("Pre-tax balance at death", fmt_money(conv.ending_traditional),
             f"{fmt_money(conv.ending_traditional - base.ending_traditional)} vs. not converting"),
        ])

        if len(both):
            bal = both.melt(id_vars=["Year", "Future"], value_vars=["Traditional", "Roth"],
                            var_name="Account", value_name="Balance")
            st.altair_chart(
                alt.Chart(bal).mark_line(strokeWidth=2.2, interpolate="monotone")
                .encode(x=year_axis,
                        y=alt.Y("Balance:Q", axis=alt.Axis(format="$,.0s", title="Balance, today's dollars")),
                        color=alt.Color("Future:N", scale=future_scale,
                                        legend=alt.Legend(orient="top", title=None)),
                        strokeDash=alt.StrokeDash("Account:N",
                                                  legend=alt.Legend(orient="top", title=None)),
                        tooltip=["Year:Q", "Future:N", "Account:N",
                                 alt.Tooltip("Balance:Q", format="$,.0f")])
                .properties(height=240).configure_view(strokeWidth=0),
                use_container_width=True)

            st.altair_chart(
                alt.Chart(both).mark_line(strokeWidth=2.2)
                .encode(x=year_axis,
                        y=alt.Y("Cumulative tax:Q",
                                axis=alt.Axis(format="$,.0s", title="Cumulative tax paid")),
                        color=alt.Color("Future:N", scale=future_scale,
                                        legend=alt.Legend(orient="top", title=None)),
                        tooltip=["Year:Q", "Future:N",
                                 alt.Tooltip("Cumulative tax:Q", format="$,.0f"),
                                 alt.Tooltip("Tax:Q", title="Tax this year", format="$,.0f")])
                .properties(height=200).configure_view(strokeWidth=0),
                use_container_width=True)
            st.caption("Converting pays tax early to avoid it later. The lines "
                       "crossing — or never crossing — is the whole decision in one "
                       "picture. All figures are real, today's dollars.")

        with st.expander("What the engine read from your plan"):
            st.dataframe(pd.DataFrame(RB.describe(p), columns=["Item", "As modelled"]),
                         use_container_width=True, hide_index=True)
            st.caption("Everything above comes from the other pages. Anything the "
                       "plan does not hold is a question on the left.")

    with section("The RMD you are probably underestimating",
                 "Required minimum distributions do not start in an empty bracket. "
                 "They stack on top of retired pay and Social Security that are "
                 "already there, so every RMD dollar is taxed at the rate ABOVE "
                 "everything else you receive."):
        rmd_rows = [r for r in base.rows if r.rmd > 0]
        if rmd_rows:
            first = rmd_rows[0]
            peak = max(rmd_rows, key=lambda r: r.rmd)
            floor_income = (first.military_retired_pay + first.social_security
                            + first.civilian_pension + first.wages + first.sbp_annuity)
            metric_row([
                (f"First RMD, {first.year} (age {first.age_primary})", fmt_money(first.rmd)),
                ("Already taxable that year", fmt_money(floor_income)),
                ("Rate the RMD is taxed at", fmt_pct(first.marginal_rate, 0)),
                (f"Peak RMD, {peak.year}", fmt_money(peak.rmd)),
            ])
            metric_row([
                ("Lifetime RMDs — don't convert", fmt_money(base.lifetime_rmds)),
                ("Lifetime RMDs — convert", fmt_money(conv.lifetime_rmds),
                 fmt_money(conv.lifetime_rmds - base.lifetime_rmds)),
                ("Pre-tax left to heirs — don't convert", fmt_money(base.ending_traditional)),
                ("Tax your heirs pay on it", fmt_money(base.heir_tax_paid),
                 f"{fmt_money(conv.heir_tax_paid - base.heir_tax_paid)} if you convert"),
            ])
        else:
            st.info("No RMDs are projected in your lifetime on these settings — the "
                    "traditional balance is small or is spent down first. The case "
                    "for converting then rests on the survivor and heir numbers, not "
                    "on RMDs.", icon="ℹ️")

        sources = ["Wages", "Retired pay", "SBP annuity", "Social Security",
                   "Other pension", "RMD"]
        stack = dfb.melt(id_vars=["Year"], value_vars=sources, var_name="Source",
                         value_name="Amount") if len(dfb) else pd.DataFrame()
        if len(stack):
            present = [s for s in sources if stack.loc[stack["Source"] == s, "Amount"].sum() > 0]
            stack = stack[stack["Source"].isin(present)].copy()
            stack["Order"] = stack["Source"].map({s: i for i, s in enumerate(sources)})
            palette = {"Wages": "#9db0be", "Retired pay": GREY, "SBP annuity": "#7f8f97",
                       "Social Security": AMBER, "Other pension": "#c3ccd0", "RMD": ORANGE}
            st.altair_chart(
                alt.Chart(stack).mark_area(interpolate="monotone", stroke="white",
                                           strokeWidth=0.8)
                .encode(x=year_axis,
                        y=alt.Y("Amount:Q", stack="zero",
                                axis=alt.Axis(format="$,.0s", title="Taxable income if you do not convert")),
                        color=alt.Color("Source:N",
                                        scale=alt.Scale(domain=present,
                                                        range=[palette[s] for s in present]),
                                        legend=alt.Legend(orient="top", title=None)),
                        order=alt.Order("Order:Q"),
                        tooltip=["Year:Q", "Source:N", alt.Tooltip("Amount:Q", format="$,.0f")])
                .properties(height=230).configure_view(strokeWidth=0),
                use_container_width=True)

            rate = both[["Year", "Future", "Marginal rate"]]
            st.altair_chart(
                alt.Chart(rate).mark_line(interpolate="step-after", strokeWidth=2.2)
                .encode(x=year_axis,
                        y=alt.Y("Marginal rate:Q",
                                axis=alt.Axis(format=".0%", title="Marginal federal rate"),
                                scale=alt.Scale(domain=[0, max(0.4, float(both["Marginal rate"].max()) + 0.02)])),
                        color=alt.Color("Future:N", scale=future_scale,
                                        legend=alt.Legend(orient="top", title=None)),
                        tooltip=["Year:Q", "Future:N",
                                 alt.Tooltip("Marginal rate:Q", format=".0%")])
                .properties(height=170).configure_view(strokeWidth=0),
                use_container_width=True)
            st.caption("The orange band is the RMD. Where it appears, the marginal "
                       "rate is what each of those dollars is taxed at — not your "
                       "average rate. Watch the step up when the survivor files single.")

    with section("The bracket sweep — what each conversion amount does",
                 "Each row is a complete re-run of both futures with the conversion "
                 "filled to a different bracket ceiling, ranked by what is left to "
                 "your heirs after all taxes. Converting nothing is the baseline."):
        sw = pd.DataFrame(bracket_sweep)
        if len(sw):
            sw["Strategy"] = sw["target_bracket"].map(
                lambda b: "Convert nothing" if b == 0 else f"Fill to {_pct_label(b)}")
            order = [r["Strategy"] for _, r in sw.sort_values("target_bracket").iterrows()]
            best = sw.iloc[0]
            metric_row([
                ("Best target", best["Strategy"]),
                ("Converts in total", fmt_money(best["total_converted"])),
                ("Extra to heirs vs. nothing", fmt_money(best["legacy_gain"])),
                ("Lifetime tax at that target", fmt_money(best["lifetime_tax"])),
            ])
            st.altair_chart(
                alt.Chart(sw).mark_bar()
                .encode(x=alt.X("Strategy:N", sort=order,
                                axis=alt.Axis(title=None, labelAngle=0)),
                        y=alt.Y("legacy_gain:Q",
                                axis=alt.Axis(format="$,.0s",
                                              title="Extra value to heirs vs. converting nothing")),
                        color=alt.condition(alt.datum.legacy_gain >= 0,
                                            alt.value(GREEN), alt.value(ORANGE)),
                        tooltip=[alt.Tooltip("Strategy:N"),
                                 alt.Tooltip("total_converted:Q", title="Total converted", format="$,.0f"),
                                 alt.Tooltip("lifetime_tax:Q", title="Lifetime tax", format="$,.0f"),
                                 alt.Tooltip("irmaa:Q", title="IRMAA surcharges", format="$,.0f"),
                                 alt.Tooltip("ending_traditional:Q", title="Pre-tax at death", format="$,.0f"),
                                 alt.Tooltip("legacy_gain:Q", title="Extra to heirs", format="$,.0f")])
                .properties(height=220).configure_view(strokeWidth=0),
                use_container_width=True)
            table = sw[["Strategy", "total_converted", "lifetime_tax", "irmaa",
                        "ending_traditional", "legacy", "legacy_gain"]].rename(columns={
                "total_converted": "Total converted", "lifetime_tax": "Lifetime tax",
                "irmaa": "IRMAA surcharges", "ending_traditional": "Pre-tax at death",
                "legacy": "To heirs after tax", "legacy_gain": "vs. nothing"})
            st.dataframe(table.style.format({
                "Total converted": "${:,.0f}", "Lifetime tax": "${:,.0f}",
                "IRMAA surcharges": "${:,.0f}", "Pre-tax at death": "${:,.0f}",
                "To heirs after tax": "${:,.0f}", "vs. nothing": "${:,.0f}"}),
                use_container_width=True, hide_index=True)
            st.caption("A higher target converts MORE per year but often LESS in "
                       "total, because the balance is emptied before it can compound. "
                       "That is why the totals do not rise with the bracket.")

    with section("Does it hold up if rates rise?",
                 "The same comparison under each of the plan-wide tax scenarios. "
                 "The one you have chosen is marked."):
        rows = []
        for s in scenario_sweep:
            rows.append({
                "Scenario": s["scenario"]
                            + ("  ← your plan" if s["scenario"] == h.assumptions.tax_scenario else ""),
                "Lifetime tax — don't": s["tax_no_convert"],
                "Lifetime tax — convert": s["tax_convert"],
                "Tax saved": s["tax_saved"],
                "Extra to heirs": s["legacy_gain"],
                "Verdict": "Convert" if s["legacy_gain"] > 0 else "Do not convert",
            })
        wins = sum(1 for s in scenario_sweep if s["legacy_gain"] > 0)
        st.dataframe(pd.DataFrame(rows).style.format({
            "Lifetime tax — don't": "${:,.0f}", "Lifetime tax — convert": "${:,.0f}",
            "Tax saved": "${:,.0f}", "Extra to heirs": "${:,.0f}"}),
            use_container_width=True, hide_index=True)
        if wins == len(scenario_sweep):
            st.success(f"Converting wins in all {wins} scenarios, so the decision "
                       f"does not depend on predicting Congress.", icon="✅")
        elif wins == 0:
            st.error("Converting loses under every scenario on these settings. "
                     "Change the target or the window before concluding anything.",
                     icon="🚨")
        else:
            st.warning(f"Converting wins in {wins} of {len(scenario_sweep)} scenarios. "
                       f"The answer depends on future tax law — size the conversion "
                       f"for the case you can live with.", icon="⚠️")
        st.caption(esc(f"Rate changes take effect in {ri.tax_change_year}. A "
                       f"bracket target is applied to whichever schedule is in force, "
                       f"so under the pre-TCJA schedule a {_pct_label(ri.target_bracket)} "
                       f"target fills the 15% band and converts less — the sweep "
                       f"tests the plan, not just the tax rate."))

    with section("Monte Carlo — does the answer survive bad markets?",
                 "Both futures are run on the SAME random sequence of returns in "
                 "every path. The question is not how much you will have; it is "
                 "whether converting beats not converting, path by path."):
        if run_mc:
            bar = st.progress(0.0, text="Running both futures on the same random markets…")
            summary = run_monte_carlo(
                p, progress=lambda f: bar.progress(
                    min(1.0, float(f)), text=f"Running… {int(min(1.0, float(f)) * 100)}%"))
            bar.empty()
            st.session_state[MC_KEY] = {"key": pj, "summary": summary}

        stored = st.session_state.get(MC_KEY)
        if stored and getattr(stored.get("summary"), "n_paths", 0) > 0:
            mc = stored["summary"]
            if stored.get("key") != pj:
                st.warning("These results were computed for earlier inputs. Run it "
                           "again to refresh them.", icon="⚠️")
            med = float(np.median(mc.legacy_delta))
            metric_row([
                ("Paths", f"{mc.n_paths:,}"),
                ("Converting leaves heirs more in", fmt_pct(mc.win_rate(), 0) + " of paths"),
                ("Lower lifetime tax in", fmt_pct(mc.tax_win_rate(), 0) + " of paths"),
                ("Median extra value from converting", fmt_money(med)),
            ])
            pct5 = mc.percentiles(mc.legacy_delta)
            metric_row([
                ("Worst 5% of paths", fmt_money(pct5[5])),
                ("Lower quartile", fmt_money(pct5[25])),
                ("Upper quartile", fmt_money(pct5[75])),
                ("Best 5% of paths", fmt_money(pct5[95])),
            ])
            dfm = pd.DataFrame({"Extra value to heirs": mc.legacy_delta})
            hist = alt.Chart(dfm).mark_bar(color=BLUE).encode(
                x=alt.X("Extra value to heirs:Q", bin=alt.Bin(maxbins=40),
                        axis=alt.Axis(format="$,.0s",
                                      title="Extra after-tax value to heirs from converting, per path")),
                y=alt.Y("count():Q", axis=alt.Axis(title="Paths")),
                tooltip=[alt.Tooltip("count():Q", title="Paths")])
            zero = alt.Chart(pd.DataFrame({"x": [0.0]})).mark_rule(
                color=ORANGE, strokeWidth=2).encode(x="x:Q")
            st.altair_chart((hist + zero).properties(height=200).configure_view(strokeWidth=0),
                            use_container_width=True)
            ruin_n, ruin_c = mc.ruin_rate(False), mc.ruin_rate(True)
            if max(ruin_n, ruin_c) > 0:
                st.warning(f"Spending went unfunded in {fmt_pct(ruin_n, 1)} of paths "
                           f"without conversions and {fmt_pct(ruin_c, 1)} with. A "
                           f"conversion that raises that number is buying a tax "
                           f"result with spending security.", icon="⚠️")
            st.caption(f"Real return volatility {fmt_pct(mc.return_stdev, 0)} a year, "
                       f"inflation volatility {fmt_pct(mc.inflation_stdev, 1)}. The "
                       f"bar at zero separates the paths where converting won from "
                       f"the ones where it lost.")
        else:
            st.info(f"Press **Run the Monte Carlo** on the left. {n_paths} paths take "
                    f"a few seconds; the deterministic answer above is the mean "
                    f"path, so this only tells you how robust it is.", icon="🎲")

    with section("What is driving this",
                 "The findings the engine flags on this plan, strongest signal "
                 "first: the RMD stack, the conversion window, the survivor's "
                 "bracket, and the military-specific facts a civilian planner "
                 "gets wrong."):
        weight = {"bad": 0, "warn": 1, "good": 2, "info": 3}
        findings = sorted(c.findings, key=lambda f: weight.get(f.severity, 9))
        render_findings([(f.severity, f.headline, f.detail) for f in findings])

    with section("Year by year"):
        with st.expander("Both futures, every year", expanded=False):
            if len(dfb) and len(dfc):
                yb = dfb.set_index("Year")
                yc = dfc.set_index("Year")
                table = pd.DataFrame({
                    "Age": yb["Age"], "Filing": yb["Filing"],
                    "Retired pay": yb["Retired pay"], "Social Security": yb["Social Security"],
                    "RMD (don't)": yb["RMD"], "Conversion": yc["Conversion"],
                    "AGI (don't)": yb["AGI"], "AGI (convert)": yc["AGI"],
                    "Marginal (don't)": yb["Marginal rate"], "Marginal (convert)": yc["Marginal rate"],
                    "Tax (don't)": yb["Tax"], "Tax (convert)": yc["Tax"],
                    "Pre-tax (don't)": yb["Traditional"], "Pre-tax (convert)": yc["Traditional"],
                }).reset_index()
                st.dataframe(table.style.format({
                    "Retired pay": "${:,.0f}", "Social Security": "${:,.0f}",
                    "RMD (don't)": "${:,.0f}", "Conversion": "${:,.0f}",
                    "AGI (don't)": "${:,.0f}", "AGI (convert)": "${:,.0f}",
                    "Marginal (don't)": "{:.0%}", "Marginal (convert)": "{:.0%}",
                    "Tax (don't)": "${:,.0f}", "Tax (convert)": "${:,.0f}",
                    "Pre-tax (don't)": "${:,.0f}", "Pre-tax (convert)": "${:,.0f}"}),
                    use_container_width=True, hide_index=True, height=380)

    with section("Ask an LLM about this",
                 "A briefing another model can review — the inputs, the "
                 "assumptions, both futures year by year, the sweeps, and a list of "
                 "what this engine deliberately does not model. It asks for a "
                 "critic, not a validator."):
        stored = st.session_state.get(MC_KEY)
        mc_for_brief = stored["summary"] if (stored and stored.get("key") == pj) else None
        md = build_briefing(
            p, c,
            BriefingOptions(anonymize=bool(anonymize), round_to=int(round_to),
                            table_mode=table_mode, include_json=bool(include_json)),
            scenario_sweep=scenario_sweep, bracket_sweep=bracket_sweep,
            monte_carlo=mc_for_brief)
        st.download_button("⬇️  Download the briefing (Markdown)", data=md,
                           file_name=briefing_filename(p), mime="text/markdown",
                           key=wkey("rc_download"), use_container_width=True)
        st.caption(f"{len(md):,} characters"
                   + (", including the Monte Carlo summary" if mc_for_brief else
                      "; run the Monte Carlo to include it")
                   + ". Paste it into any capable model and ask it to find what "
                     "this analysis gets wrong. Nothing is sent anywhere by this app.")
        with st.expander("Preview the briefing"):
            st.code(md[:6000] + ("\n\n… (truncated in the preview; the download is complete)"
                                 if len(md) > 6000 else ""), language="markdown")

    st.caption("An estimator, not tax advice. Tax tables are 2026 figures; state tax "
               "is a single effective rate per state; itemised deductions, QCDs and "
               "AMT are not modelled. Verify with a tax professional before "
               "converting a dollar.")
