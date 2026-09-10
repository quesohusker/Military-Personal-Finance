import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import streamlit as st

from ui.panel import (wkey, get_household, page_header, two_pane, input_card,
                      section, metric_row, money, fmt_money, esc,
                      render_findings)
from engine.benefits import disability_separation as DS
from engine.benefits import life_insurance as LI
from engine.coach import prime_directive as PD

h = get_household()
m = h.member
page_header("⚕️ If I am medically separated",
            "The disability evaluation outcome, and what to do about life "
            "insurance before you separate rather than after.")

basic = PD.monthly_basic_pay(m)

inputs, results = two_pane()

# ==========================================================================
# Left: the questions, stacked.
# ==========================================================================
with inputs:
    with input_card("Your rating and your pay"):
        dod = st.slider("What is your DoD disability rating?", 0, 100, 20, step=10,
                        key=wkey("dodr"),
                        help="Only the conditions that make you unfit for "
                             "duty. This is NOT your VA rating and the two "
                             "routinely differ.")
        yos = st.number_input("How many years will you have served?",
                              value=float(m.years_of_service), min_value=0.0,
                              max_value=40.0, step=0.5, key=wkey("dsyos"))
        h3 = st.number_input("What is your High-3 monthly basic pay?",
                             value=float(basic or 4_110.0), min_value=0.0,
                             step=50.0, key=wkey("dsh3"),
                             help="Average of your highest 36 months of basic "
                                  "pay. Basic pay only — no BAH, no BAS.")

    with input_card("Your age and VA compensation"):
        sep_age = st.number_input("How old will you be when you separate?",
                                  value=int(max(20, m.age())),
                                  min_value=17, max_value=70, key=wkey("dsage"))
        life_exp = st.number_input("How long do you expect to live?", value=85, min_value=50,
                                   max_value=105, key=wkey("dslife"))
        va_comp = st.number_input("What VA pay do you expect, per month?",
                                  value=float(m.va_disability_monthly or 1_400.0),
                                  min_value=0.0, step=50.0, key=wkey("dsvac"),
                                  help="Used to work out how many months of VA "
                                       "payments are withheld to recoup a "
                                       "severance.")

    with input_card("About your separation"):
        combat = st.toggle("Is the disability combat-related?", value=False,
                           key=wkey("dscr"),
                           help="A combat-related determination generally "
                                "stops the severance being recouped. It is "
                                "worth the entire severance, so make sure it "
                                "is made and documented.")
        czone = st.toggle("Did it happen in a combat zone?", value=False,
                          key=wkey("dscz"),
                          help="Makes the severance tax-free. It is commonly "
                               "withheld at source anyway and then has to be "
                               "recovered by amending the return.")
        tdrl = st.toggle("Were you placed on the TDRL?", value=False, key=wkey("dstdrl"),
                         help="Temporary list. Retired pay is paid now, but "
                              "the rating is re-evaluated for up to three "
                              "years.")
        brs = st.toggle("Are you in the Blended Retirement System?", value=m.opted_into_brs,
                        key=wkey("dsbrs"))

    with input_card("About your life insurance"):
        cover = st.number_input("How much coverage do you want?", value=float(m.sgli_coverage
                                                                              or LI.SGLI_MAX),
                                min_value=0.0, max_value=LI.VGLI_MAX,
                                step=50_000.0, key=wkey("licov"))
        li_age = st.number_input("How old will you be when you separate?", value=int(sep_age),
                                 min_value=17, max_value=70, key=wkey("liage"))
        to_age = st.number_input("Compare through what age?", value=70, min_value=30,
                                 max_value=100, key=wkey("lito"))
        term_yrs = st.select_slider("How long should the term be?", options=[10, 15, 20, 30],
                                    value=20, key=wkey("literm"))
        insurable = st.toggle("Could you get commercial coverage?",
                              value=True, key=wkey("liins"),
                              help="Turn this off if a health condition would "
                                   "make you uninsurable or rated. It changes "
                                   "the answer completely.")

    with input_card("How much cover do you need?"):
        inc = st.number_input("What income should it replace, per year?", value=80_000.0,
                              min_value=0.0, step=5_000.0, key=wkey("nincome"))
        yrs = st.number_input("For how many years?", value=25.0,
                              min_value=0.0, max_value=60.0, step=1.0,
                              key=wkey("nyears"))
        mort = st.number_input("What mortgage balance would it clear?",
                               value=float(h.mortgage_balance), min_value=0.0,
                               step=10_000.0, key=wkey("nmort"))
        edu = st.number_input("How much education should it fund?", value=0.0, min_value=0.0,
                              step=10_000.0, key=wkey("nedu"))
        surv = st.number_input("What is your survivor guaranteed, per year?",
                               value=0.0, min_value=0.0, step=5_000.0,
                               key=wkey("nsurv"),
                               help="SBP plus DIC plus Social Security "
                                    "survivor benefits. This is the number "
                                    "most needs calculators leave out.")
        liquid = st.number_input("What liquid assets are available?", value=0.0,
                                 min_value=0.0, step=10_000.0, key=wkey("nliq"))
        have = st.number_input("How much coverage do you already have?", value=float(cover),
                               min_value=0.0, step=50_000.0, key=wkey("nhave"))

# ==========================================================================
# The arithmetic, once every answer is in.
# ==========================================================================
kw = dict(is_brs=brs, combat_related=combat,
          incurred_in_combat_zone=czone,
          va_monthly_compensation=va_comp,
          age_at_separation=int(sep_age), life_expectancy=int(life_exp),
          on_tdrl=tdrl)

result = DS.compare_paths(int(dod), float(yos), float(h3), **kw)
o = result["actual"]

c = LI.compare(float(cover), int(li_age), int(to_age),
               term_years=int(term_yrs), insurable=insurable)

n = LI.needs(float(inc), float(yrs), mortgage_balance=float(mort),
             education_cost=float(edu), survivor_annual_income=float(surv),
             liquid_assets=float(liquid), current_coverage=float(have))

# ==========================================================================
# Right: what those answers mean.
# ==========================================================================
with results:
    with section("Medical separation or disability retirement",
                 "The Integrated Disability Evaluation System assigns a DoD "
                 "rating. That number, and your length of service, decide between "
                 "a lifetime pension with TRICARE and a one-time cheque. Nothing "
                 "in between."):

        st.markdown(f"### {esc(o.outcome)}")

        if o.outcome == DS.OUTCOME_SEVERANCE:
            metric_row([
                ("Severance, gross", fmt_money(o.severance_gross)),
                ("After tax", fmt_money(o.severance_after_tax)),
                ("Years credited", f"{o.severance_years_credited:g}"),
                ("Months of VA withheld",
                 f"{o.months_of_va_withheld:.0f}" if o.months_of_va_withheld
                 else "None"),
            ])
        else:
            metric_row([
                ("Retired pay", f"{fmt_money(o.retired_pay_monthly)}/mo"),
                ("Per year", fmt_money(o.retired_pay_annual)),
                ("Multiplier", f"{o.multiplier_used * 100:.1f}%"),
                ("Replacement cost", fmt_money(o.lifetime_present_value)),
            ])

        if result["gap"] > 0:
            alt = result["alternative"]
            st.error(esc(
                f"**The cliff here is about {fmt_money(result['gap'])}.** "
                f"A {DS.RETIREMENT_RATING_THRESHOLD}% DoD rating instead of "
                f"{dod}% turns a {fmt_money(o.severance_after_tax)} cheque into a "
                f"{fmt_money(alt.retired_pay_monthly)} a month pension for life, "
                f"plus TRICARE — worth roughly "
                f"{fmt_money(alt.lifetime_present_value)} to replace."))

        for note in o.notes:
            st.markdown(esc(note))

    with section("What each path is worth"):
        render_findings(DS.findings(o, result))

    with section("SGLI, VGLI and level term",
                 "SGLI costs the same at 22 as it does at 52. VGLI does not — and "
                 "the escalation lands exactly when a fixed retirement income is "
                 "least able to absorb it."):

        metric_row([
            ("SGLI now", f"{fmt_money(c.sgli_monthly)}/mo"),
            (f"VGLI at {li_age}", f"{fmt_money(c.vgli_first_monthly)}/mo"),
            (f"VGLI at {to_age}", f"{fmt_money(c.vgli_final_monthly)}/mo"),
            ("Term, fixed", f"{fmt_money(c.term_monthly)}/mo"),
        ])
        metric_row([
            (f"VGLI total to {to_age}", fmt_money(c.vgli_total)),
            ("Term total", fmt_money(c.term_total)),
            ("Difference", fmt_money(c.saving)),
        ])

        st.success(f"**Recommendation: {esc(c.recommendation)}**")
        for r in c.reasoning:
            st.markdown(esc(r))

        st.caption(esc(
            f"Windows after separation: SGLI continues free for "
            f"{LI.SGLI_FREE_DAYS_AFTER_SEPARATION} days. VGLI is issued with no "
            f"health questions within {LI.VGLI_GUARANTEED_DAYS} days, with proof "
            f"of good health to {LI.VGLI_FINAL_DEADLINE_DAYS} days, and not at all "
            f"after that. VGLI rates here are planning estimates — confirm them at "
            f"va.gov."))

    with section("How much cover you actually need",
                 "A military survivor may already have SBP, DIC and Social "
                 "Security survivor benefits. Sizing a policy without netting "
                 "those off buys insurance against a loss that is already partly "
                 "covered."):

        metric_row([
            ("Gross need", fmt_money(n.gross_need)),
            ("Survivor income offset", f"-{fmt_money(n.survivor_income_offset)}"),
            ("Net need", fmt_money(n.net_need)),
            ("Gap", fmt_money(n.gap)),
        ])
        for note in n.notes:
            st.markdown(esc(note))
