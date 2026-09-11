import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import streamlit as st

from ui.panel import (wkey, get_household, page_header, two_pane, input_card,
                      section, metric_row, money, number, integer, toggle,
                      fmt_money, esc, render_findings)
from engine import mortality as MORT
from engine.benefits import disability_separation as DS
from engine.benefits import life_insurance as LI
from engine.coach import prime_directive as PD
from engine.profile import SYS_BRS

# A page-local knob is not a fact about the member, and the two must not look
# alike. `FUNNEL_CONTRACT.md` §14: a widget seeded from the plan that writes
# nothing back is a defect; a widget exploring a value the member is NOT
# claiming as true is fine, as long as the page says so.
#
# The four disability determinations on this page are on the FACT side and are
# saved: a board assigns the DoD rating, a line-of-duty finding decides whether
# the condition is combat-related, and the TDRL is an order. The insurance
# sizing worksheet below them is on the what-if side and is not.
WHATIF = ("A what-if on this page only. Nothing typed here is saved to your "
          "plan — it moves the figures below and nothing else.")
WHATIF_CARD = "What-if — nothing on this card is saved to your plan."

h = get_household()
m = h.member
t = h.career
a = h.assumptions
page_header("⚕️ Medical Separation",
            "The disability evaluation outcome, and what to do about life "
            "insurance before you separate rather than after.")

basic = PD.monthly_basic_pay(m)
table_h3 = float(basic or 4_110.0)

# The same tidy-up `3_Career.py` does at its slider. A plan nobody has opened
# the Career page on carries the declared default of twenty years, which is
# already behind anyone who has served longer than that -- and this page would
# then price a twenty-year pension for a member with twenty-six. Adopting the
# member's own longevity is the app fixing its own default, not the member
# answering a question, so it does not claim unsaved changes.
if not t.entered and t.separation_at_years_of_service < m.years_of_service:
    t.separation_at_years_of_service = float(m.years_of_service)


def _separation_answered(before: float) -> None:
    """
    Mark the timeline ANSWERED once the member moves the separation point.

    `t.entered` is what stops the tidy-up above from re-adopting the member's
    own longevity over a real answer, and `3_Career.py` sets it at every edit.
    This page writes the same field, so it owes the same flag: without it a
    member who has served 21 years and genuinely means to go at 20 types 20,
    the value is stored, and the next render puts 21 straight back -- silently,
    because the tidy-up is not an edit and says nothing.
    """
    if t.separation_at_years_of_service != before:
        t.entered = True

inputs, results = two_pane()

# ==========================================================================
# Left: the questions, stacked.
# ==========================================================================
with inputs:
    with input_card("Your rating and your pay"):
        dod = integer("What is your DoD disability rating?", m,
                      "dod_disability_rating", key=wkey("dodr"),
                      min_value=0, max_value=100, step=10,
                      help="Only the conditions that make you unfit for duty. "
                           "This is NOT your VA rating and the two routinely "
                           "differ, so it has its own place on your plan. "
                           "Leave it at zero until a board has rated you.")
        if not dod:
            st.caption(f"No rating recorded, so the figures below are what your "
                       f"length of service alone produces. The cliff panel "
                       f"shows what a "
                       f"{DS.RETIREMENT_RATING_THRESHOLD}% finding would do.")
        _sep_before = float(t.separation_at_years_of_service)
        yos = number("How many years will you have served?", t,
                     "separation_at_years_of_service", key=wkey("dsyos"),
                     min_value=0.0, max_value=42.0, step=0.5, fmt="%.1f",
                     help="Your separation point — the same answer as the "
                          "slider on the Career page and the Pension page, "
                          "saved with your plan.")
        _separation_answered(_sep_before)
        money("What is your High-3 monthly basic pay? (0 = use the table)", m,
              "high_3_monthly_override", key=wkey("dsh3"), step=50.0,
              help="Average of your highest 36 months of basic pay. Basic pay "
                   "only — no BAH, no BAS. Leave it at zero and the published "
                   "table is used. The Pension page reads the same figure.")
        h3 = m.high_3_monthly(table_h3)
        st.caption(esc(f"The table gives {fmt_money(table_h3)} a month for "
                       f"{m.grade} at {m.years_of_service:g} years."))

    with input_card("Your age and VA compensation"):
        # R1: separating at `yos` years, from `m.years_of_service` today, fixes
        # the age. Asking it as well would let the two disagree.
        sep_age = int(min(70, max(17, round(
            m.age() + max(0.0, yos - m.years_of_service)))))
        st.caption(f"You would be **{sep_age}** when you separate — today's age "
                   f"plus the {max(0.0, yos - m.years_of_service):g} years "
                   f"still to serve.")
        life_exp = st.number_input("How long do you expect to live?",
                                   value=MORT.life_expectancy(m.age(), m.sex),
                                   min_value=50, max_value=105,
                                   key=wkey("dslife"),
                                   help=WHATIF + " " + MORT.explain(m.age(), m.sex))
        st.caption("Life expectancy is an assumption you are trying on, not a "
                   "fact about you, so it is not saved.")
        va_comp = money("What VA compensation do you receive, or expect, each "
                        "month?", m, "va_disability_monthly", key=wkey("dsvac"),
                        step=50.0,
                        help="The same figure Intake and Survivor Benefits "
                             "carry — correcting it here corrects it "
                             "everywhere. Used to work out how many months of "
                             "VA payments are withheld to recoup a severance.")

    with input_card("What the board decided"):
        combat = toggle("Is the disability combat-related?", m,
                        "disability_combat_related", key=wkey("dscr"),
                        help="A combat-related determination generally stops "
                             "the severance being recouped. It is worth the "
                             "entire severance, so make sure it is made and "
                             "documented — and recorded here.")
        czone = toggle("Did it happen in a combat zone?", m,
                       "disability_incurred_in_combat_zone", key=wkey("dscz"),
                       help="Makes the severance tax-free. It is commonly "
                            "withheld at source anyway and then has to be "
                            "recovered by amending the return.")
        tdrl = toggle("Were you placed on the TDRL?", m, "on_tdrl",
                      key=wkey("dstdrl"),
                      help="Temporary list. Retired pay is paid now, but the "
                           "rating is re-evaluated for up to three years.")

        # R1 again, and a defect closed: this used to be asked, seeded from
        # `opted_into_brs`, which is only the 2018 opt-in flag. Anyone with a
        # DIEMS date of 2018 or later is in BRS without ever opting in, so the
        # widget told them they were not. The DIEMS date decides and nothing
        # else does.
        brs = (m.retirement_system == SYS_BRS)
        st.caption(f"Your retirement system is **{esc(m.retirement_system)}**, "
                   f"from your DIEMS date. Set it on Profile.")

    with input_card("About your life insurance"):
        cover = money("How much SGLI coverage do you carry?", m,
                      "sgli_coverage", key=wkey("licov"), step=50_000.0,
                      max_value=LI.VGLI_MAX,
                      help="What your LES shows as SGLI. It is what VGLI would "
                           "continue, so it is the coverage priced below. Saved "
                           "with your plan.")
        if cover <= 0:
            st.caption("Your plan records no SGLI coverage, so there is nothing "
                       "for VGLI to continue and the comparison below is empty.")
        st.caption("The three questions below are what-ifs — they set up the "
                   "comparison and nothing typed in them is saved.")
        to_age = st.number_input("Compare through what age?", value=70, min_value=30,
                                 max_value=100, key=wkey("lito"), help=WHATIF)
        term_yrs = st.select_slider("How long should the term be?", options=[10, 15, 20, 30],
                                    value=20, key=wkey("literm"), help=WHATIF)
        insurable = st.toggle("Could you get commercial coverage?",
                              value=True, key=wkey("liins"),
                              help=WHATIF + " Turn it off if a health condition "
                                   "would make you uninsurable or rated. It "
                                   "changes the answer completely — but it is a "
                                   "guess about an underwriter, not a "
                                   "determination anyone has made, so the plan "
                                   "does not carry it.")

    with input_card("How much cover do you need?"):
        # One saved field on an otherwise page-local card, so the exception is
        # stated BEFORE the blanket denial rather than after it. A member who
        # reads only the first clause must not come away believing the
        # mortgage figure is a scratch pad.
        st.caption("A sizing worksheet. **Your mortgage balance is saved to "
                   "your plan** and shared with Accounts and Housing; "
                   "everything else on this card is a what-if and is not "
                   "saved.")
        inc = st.number_input("What income should it replace, per year?", value=80_000.0,
                              min_value=0.0, step=5_000.0, key=wkey("nincome"),
                              help=WHATIF)
        yrs = st.number_input("For how many years?", value=25.0,
                              min_value=0.0, max_value=60.0, step=1.0,
                              key=wkey("nyears"), help=WHATIF)
        # FUNNEL_CONTRACT.md §14: a second widget on a shared fact is a
        # drill-down when it asks the SAME question, and a defect when it asks
        # a different one. "What would it clear?" is a hypothetical and this
        # writes the real balance sheet -- a member modelling partial cover
        # would have silently rewritten their net worth. So it asks for the
        # balance, and the help says what the worksheet does with it.
        mort = money("What is your mortgage balance?", h,
                     "mortgage_balance", key=wkey("nmort"), step=10_000.0,
                     help="Your plan's mortgage balance, shared with Accounts "
                          "and Housing & VA Loan — correcting it here corrects "
                          "it everywhere, and it is the one figure on this card "
                          "that is saved. The worksheet assumes the payout "
                          "clears it in full; to size cover that clears only "
                          "part of it, read the shortfall off the result rather "
                          "than lowering this.")
        edu = st.number_input("How much education should it fund?", value=0.0, min_value=0.0,
                              step=10_000.0, key=wkey("nedu"), help=WHATIF)
        surv = st.number_input("What is your survivor guaranteed, per year?",
                               value=0.0, min_value=0.0, step=5_000.0,
                               key=wkey("nsurv"),
                               help=WHATIF + " SBP plus DIC plus Social "
                                    "Security survivor benefits. This is the "
                                    "number most needs calculators leave out.")
        liquid = st.number_input("What liquid assets are available?",
                                 value=float(h.cash_savings + h.taxable_brokerage),
                                 min_value=0.0, step=10_000.0, key=wkey("nliq"),
                                 help=WHATIF + " Opened at your plan's cash plus "
                                      "brokerage; change it to whatever a "
                                      "survivor could actually reach.")
        have = st.number_input("How much coverage do you already have?", value=float(cover),
                               min_value=0.0, step=50_000.0, key=wkey("nhave"),
                               help=WHATIF + " Opened at your SGLI above — add "
                                    "any commercial policy on top.")

# ==========================================================================
# The arithmetic, once every answer is in.
# ==========================================================================
kw = dict(is_brs=brs, combat_related=combat,
          incurred_in_combat_zone=czone,
          va_monthly_compensation=va_comp,
          age_at_separation=int(sep_age), life_expectancy=int(life_exp),
          real_discount_rate=float(a.real_discount_rate_pct) / 100.0,
          on_tdrl=tdrl)

result = DS.compare_paths(int(dod), float(yos), float(h3), **kw)
o = result["actual"]

c = LI.compare(float(cover), int(sep_age), int(to_age),
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
            (f"VGLI at {sep_age}", f"{fmt_money(c.vgli_first_monthly)}/mo"),
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
