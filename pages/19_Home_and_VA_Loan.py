import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import streamlit as st
import pandas as pd
import altair as alt

from ui.panel import (wkey, get_household, page_header, two_pane, input_card,
                      section, metric_row, money, number, toggle, fmt_money,
                      fmt_pct, esc, render_findings)
from ui import charts as C
from engine.pay import bah as BAH
from engine.housing import va_loan as VL
from engine.housing import rent_vs_buy as RB

h = get_household()
m = h.member
hz = h.housing
asm = h.assumptions

page_header("🏠 Housing & VA Loan",
            "Buy, rent, or keep the house? The VA loan is the best mortgage "
            "product in the country and the one people understand least — "
            "three things here are worth five figures each: the funding-fee "
            "exemption at a 10% rating, the assumability of a low rate, and "
            "knowing that a three-year tour rarely breaks even.")

inputs, results = two_pane()

# ==========================================================================
# Left: the questions, stacked.
# ==========================================================================
with inputs:
    with input_card("The house"):
        toggle("Do you own a home?", hz, "owns_home", key=wkey("hs_owns"),
               help="Off means you are deciding whether to buy at this "
                    "station. Everything below still works — the price is "
                    "what you would pay.")
        money("What is it worth, or what price are you looking at?", h,
              "home_value", key=wkey("hs_value"), step=5_000.0,
              help="Leave it at zero and the page uses a placeholder price "
                   "built from your BAH, so you can see the shape of the "
                   "answer before you have a house in mind.")
        money("What do you owe on the mortgage?", h, "mortgage_balance",
              key=wkey("hs_bal"), step=5_000.0)
        number("What rate are you paying? (%)", hz, "mortgage_rate_pct",
               key=wkey("hs_rate"), min_value=0.0, max_value=20.0, step=0.125,
               fmt="%.3f",
               help="The rate on the note. If you are buying, put the rate "
                    "you have been quoted.")
        number("How many years are left on it?", hz, "mortgage_years_left",
               key=wkey("hs_yrs"), min_value=0.0, max_value=40.0, step=1.0,
               fmt="%.0f")

    with input_card("Your VA entitlement"):
        toggle("Is it a VA loan?", hz, "is_va_loan", key=wkey("hs_isva"))
        toggle("Have you used your VA entitlement before?", hz,
               "used_va_entitlement_before", key=wkey("hs_used"),
               help="A subsequent use costs 3.30% under 5% down instead of "
                    "2.15% — unless you are exempt, in which case both are "
                    "zero.")
        down_pct = st.number_input("What down payment will you make? (%)",
                                   value=0.0, min_value=0.0, max_value=100.0,
                                   step=1.0, format="%.1f", key=wkey("hs_down"),
                                   help="Zero is the normal VA answer. Five "
                                        "percent cuts the funding fee; on a "
                                        "subsequent use it cuts it by more "
                                        "than half.")
        surviving_spouse = st.toggle("Are you a surviving spouse using this benefit?",
                                     value=False, key=wkey("hs_ss"),
                                     help="A surviving spouse of a veteran who "
                                          "died in service or from a "
                                          "service-connected disability pays "
                                          "no funding fee.")
        purple_heart = st.toggle("Do you hold a Purple Heart, on active duty?",
                                 value=False, key=wkey("hs_ph"),
                                 help="A Purple Heart recipient serving on "
                                      "active duty is exempt from the funding "
                                      "fee. This one applies before you are a "
                                      "veteran and is the category most often "
                                      "missed.")

    with input_card("This station"):
        number("How many years will you be at this station?", hz,
               "years_at_this_station", key=wkey("hs_tour"), min_value=0.5,
               max_value=30.0, step=0.5, fmt="%.1f",
               help="Three years is the modal tour, and three years is "
                    "shorter than almost every break-even.")
        money("What would rent cost, per month?", hz, "monthly_rent",
              key=wkey("hs_rent"), step=50.0,
              help="For a comparable place. The comparison caps this at "
                   "105% of your BAH, because that is what the allowance is "
                   "set to cover.")
        money("What is the property tax, per year?", hz, "annual_property_tax",
              key=wkey("hs_tax"), step=100.0,
              help="Leave at zero and the model assumes "
                   f"{RB.DEFAULTS['property_tax_pct']:.1f}% of value a year.")

    with input_card("The market you are in"):
        market_rate = st.number_input("What is the going mortgage rate? (%)",
                                      value=6.5, min_value=0.0, max_value=20.0,
                                      step=0.125, format="%.3f",
                                      key=wkey("hs_mkt"),
                                      help="What a buyer would pay today. The "
                                           "gap between this and your own rate "
                                           "is what your loan is worth to "
                                           "somebody who can assume it.")
        appreciation = st.number_input("What appreciation should we assume? (%)",
                                       value=float(asm.inflation_pct),
                                       min_value=-5.0, max_value=15.0, step=0.25,
                                       format="%.2f", key=wkey("hs_appr"),
                                       help="Defaults to your inflation "
                                            "assumption — that is, no real "
                                            "appreciation. Set it to zero and "
                                            "see what survives.")
        closing_pct = st.number_input("What will closing cost you? (% of price)",
                                      value=float(RB.DEFAULTS["closing_cost_pct"]),
                                      min_value=0.0, max_value=10.0, step=0.25,
                                      format="%.2f", key=wkey("hs_close"),
                                      help="Buyer-side costs, typically 2-3%.")
        selling_pct = st.number_input("What will selling cost you? (% of price)",
                                      value=float(RB.DEFAULTS["selling_cost_pct"]),
                                      min_value=0.0, max_value=15.0, step=0.5,
                                      format="%.2f", key=wkey("hs_sell"),
                                      help="Commission, concessions and title, "
                                           "typically 6-8%. This is the number "
                                           "that decides short horizons.")

# ==========================================================================
# The arithmetic, once every answer is in.
# ==========================================================================
bah_data = BAH.load()
bah = BAH.lookup_or_average(m.duty_zip, m.grade, m.has_dependents, bah_data) \
    if m.is_serving else BAH.BAHResult()
bah_monthly = bah.monthly if bah.found else 0.0

rent_used, rent_capped = RB.effective_rent(hz.monthly_rent, bah_monthly)

# A price to work with. If the plan has no home value, build one from the rent
# at a price-to-rent ratio of 15 -- a typical US figure -- so the page still
# shows the shape of the answer.
PRICE_TO_RENT = 15.0
RENT_RULE_PCT = 0.7          # monthly rent as a share of value, when unknown
price_is_placeholder = h.home_value <= 0
price = h.home_value if not price_is_placeholder else rent_used * 12.0 * PRICE_TO_RENT

# And a rent to work with, for a retiree with no BAH who has not entered one.
rent_is_placeholder = rent_used <= 0
if rent_is_placeholder:
    rent_used = price * RENT_RULE_PCT / 100.0
    model_rent, model_bah = rent_used, 0.0
else:
    # Hand the raw answers to the model so it can say for itself whether BAH
    # is what set the rent.
    model_rent, model_bah = hz.monthly_rent, bah_monthly

buy_rate = hz.mortgage_rate_pct if hz.mortgage_rate_pct > 0 else market_rate
years_left = hz.mortgage_years_left if hz.mortgage_years_left > 0 else 30.0

purchase_loan = max(0.0, price * (1.0 - down_pct / 100.0))

fee = VL.funding_fee(purchase_loan, down_payment_pct=down_pct,
                     subsequent_use=hz.used_va_entitlement_before,
                     va_rating=m.va_rating,
                     is_surviving_spouse=surviving_spouse,
                     purple_heart_on_active_duty=purple_heart,
                     finance_it=True, rate_pct=buy_rate, years=30.0)

pmi = VL.pmi_saving(purchase_loan, price, buy_rate, years=30.0)

ent = VL.entitlement(prior_loan_balance=(h.mortgage_balance
                                         if (hz.is_va_loan and hz.owns_home) else 0.0),
                     used_before=hz.used_va_entitlement_before)

assume = VL.assumability_value(h.mortgage_balance, years_left,
                               hz.mortgage_rate_pct, market_rate,
                               home_value=h.home_value)

prepay = VL.prepay_verdict(hz.mortgage_rate_pct, asm.real_return_pct,
                           asm.inflation_pct, balance=h.mortgage_balance,
                           years_left=years_left, extra_monthly=500.0)

rvb = RB.compare(price, buy_rate, down_payment_pct=down_pct,
                 monthly_rent=model_rent, bah_monthly=model_bah,
                 annual_property_tax=hz.annual_property_tax,
                 appreciation_pct=appreciation,
                 inflation_pct=asm.inflation_pct,
                 real_return_pct=asm.real_return_pct,
                 closing_cost_pct=closing_pct, selling_cost_pct=selling_pct,
                 funding_fee_amount=fee.amount, finance_funding_fee=True,
                 horizon_years=hz.years_at_this_station)

streamline = VL.irrrl(h.mortgage_balance, years_left, hz.mortgage_rate_pct,
                      market_rate, va_rating=m.va_rating,
                      is_surviving_spouse=surviving_spouse,
                      purple_heart_on_active_duty=purple_heart)

exempt_tax = RB.lookup(h.current_state, m.va_rating)
tax_annual = (hz.annual_property_tax if hz.annual_property_tax > 0
              else price * RB.DEFAULTS["property_tax_pct"] / 100.0)

# ==========================================================================
# Right: what those answers mean.
# ==========================================================================
with results:

    # ---------------------------------------------------------------- fee
    with section("The funding fee — and whether you owe it at all",
                 "The VA charges a one-time fee instead of mortgage insurance. "
                 "It is waived completely for a veteran rated at 10% or more, "
                 "for a surviving spouse, and for a Purple Heart recipient on "
                 "active duty. That waiver is the finding people miss."):

        metric_row([
            ("Loan amount", fmt_money(purchase_loan)),
            ("Fee rate", fmt_pct(fee.rate, 2)),
            ("Funding fee", fmt_money(fee.amount)),
            ("Exemption worth", fmt_money(fee.exemption_worth)),
        ])
        st.caption(esc(f"Priced on a PURCHASE at {fmt_money(price)} less "
                       f"{down_pct:.0f}% down. If you already own, this is what "
                       f"your next VA purchase would cost — the fee on a loan "
                       f"you already have was settled at closing."))

        if fee.exempt:
            st.success(esc(f"You pay no funding fee. {fee.exempt_detail} On this "
                           f"{fmt_money(purchase_loan)} loan that is "
                           f"{fmt_money(fee.gross_amount)} you keep. On a "
                           f"$400,000 loan the same waiver is worth $8,600 on a "
                           f"first use and $13,200 on a subsequent one."),
                       icon="✅")
        elif m.va_rating > 0:
            st.warning(esc(f"Rated at {m.va_rating}%, which is below the 10% "
                           f"threshold, so the fee applies: "
                           f"{fmt_money(fee.amount)}. Ten percent is the whole "
                           f"test."), icon="⚠️")
        else:
            st.info(esc(f"No rating on file, so the fee applies: "
                        f"{fmt_money(fee.amount)}. A service-connected rating "
                        f"of 10% waives it entirely — as does a Purple Heart "
                        f"while you are still serving. If you have conditions "
                        f"you have never claimed, file before you close."),
                    icon="💡")

        st.markdown("##### What the fee would be, on this loan")
        schedule = pd.DataFrame([
            {"Down payment": label,
             "First use": VL.funding_fee_rate(dp, False) * purchase_loan,
             "Subsequent use": VL.funding_fee_rate(dp, True) * purchase_loan}
            for dp, label in ((0.0, "Under 5%"), (5.0, "5% to under 10%"),
                              (10.0, "10% or more"))])
        st.dataframe(schedule.style.format({"First use": "${:,.0f}",
                                            "Subsequent use": "${:,.0f}"}),
                     use_container_width=True, hide_index=True)
        st.caption("At 5% down the subsequent-use penalty disappears entirely. "
                   "That is the part almost nobody is told.")

        if pmi.total_paid > 0:
            metric_row([
                ("Loan-to-value", fmt_pct(pmi.ltv, 0)),
                ("PMI you would pay", f"{fmt_money(pmi.monthly)}/mo"),
                ("For", f"{pmi.months_until_78_ltv / 12.0:.1f} years"),
                ("Total avoided", fmt_money(pmi.total_paid)),
            ])
        for n in fee.notes:
            st.markdown("- " + esc(n))
        if pmi.note:
            st.markdown("- " + esc(pmi.note))
        if pmi.assumption:
            st.caption(esc(pmi.assumption))
        st.caption(esc("VERIFY every figure on this card at va.gov — "
                       + VL.VERIFY["fee_first_use"]))

    # -------------------------------------------------------- entitlement
    with section("Your entitlement",
                 esc("Basic entitlement is $36,000, plus a bonus tier that "
                     "tracks the conforming loan limit. On full entitlement "
                     "there is no VA loan limit at all — that changed on "
                     "1 January 2020 and a great deal of advice still in "
                     "circulation predates it.")):
        metric_row([
            ("Basic", fmt_money(ent.basic)),
            ("Bonus (Tier 2)", fmt_money(ent.bonus)),
            ("Available guaranty", fmt_money(ent.available)),
            ("Zero down up to",
             "No limit" if ent.max_zero_down_loan is None
             else fmt_money(ent.max_zero_down_loan)),
        ])
        st.markdown(esc(ent.note))
        for n in ent.notes:
            st.markdown("- " + esc(n))
        st.caption(esc(VL.VERIFY["conforming_limit_2026"]))

    # ------------------------------------------------------- rent vs buy
    with section("Rent, or buy — over the tour you actually have",
                 "Two paths with the same starting cash: buy and sell at the "
                 "horizon, or rent at BAH and invest every dollar the "
                 "difference saves. The answer is where the lines cross."):

        if price_is_placeholder:
            st.caption(esc(f"You have not entered a home value, so this uses "
                           f"{fmt_money(price)} — fifteen times a year's rent, "
                           f"a typical US price-to-rent ratio. Put the real "
                           f"price on the left."))
        if rent_is_placeholder:
            st.caption(esc(f"No BAH and no rent entered, so rent is modelled at "
                           f"{fmt_money(rent_used)} a month — {RENT_RULE_PCT:.1f}% "
                           f"of value, a rough landlord's rule. Enter what a "
                           f"comparable place actually rents for."))

        metric_row([
            ("Rent, per month", fmt_money(rvb.rent_monthly)),
            ("Own, all-in per month", fmt_money(rvb.monthly_all_in)),
            ("Cash to close", fmt_money(rvb.upfront_cash)),
            ("Break-even",
             f"{rvb.break_even_years:.1f} years" if rvb.break_even_years
             else f"Never, within {RB.DEFAULTS['max_horizon_years']} years"),
        ])

        if rvb.buy_wins_at_horizon:
            st.success(esc(rvb.verdict), icon="✅")
        else:
            st.warning(esc(rvb.verdict), icon="⚠️")

        if rvb.rows:
            frame = pd.DataFrame(
                [{"year": r.year, "Path": "Buy", "Net position": r.own_net}
                 for r in rvb.rows]
                + [{"year": r.year, "Path": "Rent and invest",
                    "Net position": r.rent_net} for r in rvb.rows])
            st.altair_chart(
                alt.Chart(frame).mark_line(strokeWidth=2.2,
                                           interpolate="monotone")
                .encode(
                    x=alt.X("year:Q",
                            axis=alt.Axis(format="d", title="Years at this station"),
                            scale=alt.Scale(nice=False, zero=False)),
                    y=alt.Y("Net position:Q",
                            axis=alt.Axis(format="$,.0s",
                                          title="Net position, nominal dollars")),
                    color=alt.Color("Path:N",
                                    scale=alt.Scale(
                                        domain=["Buy", "Rent and invest"],
                                        range=[C.BLUE, C.ORANGE]),
                                    legend=alt.Legend(orient="top", title=None)),
                    tooltip=["year:Q", "Path:N",
                             alt.Tooltip("Net position:Q", format="$,.0f")])
                .properties(height=260).configure_view(strokeWidth=0),
                use_container_width=True)

            table = pd.DataFrame([{
                "Year": r.year,
                "Home value": r.home_value,
                "Mortgage left": r.mortgage_balance,
                "Sale proceeds": r.sale_proceeds,
                "Buy, net": r.own_net,
                "Rent, net": r.rent_net,
                "Buying ahead by": r.advantage,
            } for r in rvb.rows])
            st.dataframe(table.style.format({
                "Home value": "${:,.0f}", "Mortgage left": "${:,.0f}",
                "Sale proceeds": "${:,.0f}", "Buy, net": "${:,.0f}",
                "Rent, net": "${:,.0f}", "Buying ahead by": "${:,.0f}"}),
                use_container_width=True, hide_index=True, height=300)
            st.caption("Nominal dollars. Selling costs are charged at every "
                       "horizon, because the question is what you walk away "
                       "with if the orders come that year.")

        for n in rvb.notes:
            st.markdown("- " + esc(n))

    # ------------------------------------------------------ assumability
    with section("What your rate is worth to a buyer",
                 "A VA loan can be assumed at the ORIGINAL rate. In a market "
                 "priced well above your note, that is a saleable asset "
                 "attached to your house — and almost no listing mentions it."):
        if h.mortgage_balance > 0 and hz.mortgage_rate_pct > 0:
            metric_row([
                ("Your rate", f"{hz.mortgage_rate_pct:.3g}%"),
                ("Market rate", f"{market_rate:.3g}%"),
                ("Buyer saves", f"{fmt_money(assume.monthly_saving)}/mo"),
                ("Worth today", fmt_money(assume.value)),
            ])
            if assume.value > 5_000:
                st.success(esc(f"The assumption is worth about "
                               f"{fmt_money(assume.value)} to a buyer — "
                               f"{assume.value_pct_of_balance * 100:.0f}% of the "
                               f"{fmt_money(assume.balance)} balance, and "
                               f"{fmt_money(assume.total_nominal_saving)} of "
                               f"payments over {assume.years_left:.0f} years. "
                               f"Price it into the listing."), icon="✅")
            for n in assume.notes:
                st.markdown("- " + esc(n))
            if not hz.is_va_loan:
                st.info("Assumability is a VA and FHA feature. A conventional "
                        "loan has a due-on-sale clause and cannot be assumed, "
                        "so this figure only applies if the loan really is a "
                        "VA loan.", icon="ℹ️")
        else:
            st.caption("Enter the balance and the rate on your loan to price "
                       "the assumption.")

    # ------------------------------------------------------------- prepay
    with section("Should you pay it down early?",
                 "Paying a mortgage down early earns exactly the mortgage rate, "
                 "risk-free. That is the entire case for it — and it is a bad "
                 "trade whenever the portfolio is expected to earn more."):
        if hz.mortgage_rate_pct > 0:
            metric_row([
                ("Mortgage rate", f"{prepay.mortgage_rate_pct:.3g}%"),
                ("Expected nominal return",
                 f"{prepay.expected_nominal_return_pct:.2f}%"),
                ("Spread", f"{prepay.spread_pct:+.2f} pts"),
                ("Verdict", "Prepay" if prepay.prepay_wins else "Do not prepay"),
            ])
            if prepay.prepay_wins:
                st.info(esc(prepay.verdict), icon="💡")
            else:
                st.success(esc(prepay.verdict), icon="✅")
            for n in prepay.notes:
                st.markdown("- " + esc(n))
        else:
            st.caption("Enter your mortgage rate on the left for the prepay "
                       "verdict.")

    # ------------------------------------------------------------- IRRRL
    if hz.owns_home and hz.is_va_loan and h.mortgage_balance > 0:
        with section("Refinancing later: the IRRRL",
                     "The streamline. No appraisal, no income documentation, "
                     "and a funding fee of 0.5% — waived, like every other VA "
                     "funding fee, for a veteran rated at 10% or more."):
            metric_row([
                ("New rate modelled", f"{market_rate:.3g}%"),
                ("Funding fee", fmt_money(streamline.funding_fee_amount)),
                ("Monthly change", f"{fmt_money(streamline.monthly_saving)}/mo"),
                ("Break-even",
                 f"{streamline.break_even_months:.0f} months"
                 if streamline.break_even_months else "No saving at this rate"),
            ])
            for n in streamline.notes:
                st.markdown("- " + esc(n))

    # ------------------------------------------------------ property tax
    with section("Property tax, if you are rated",
                 "Most states exempt some or all of a disabled veteran's "
                 "property tax, and the exemption almost always has to be "
                 "applied for. This table is deliberately incomplete."):
        if exempt_tax is None:
            st.info(esc(f"This app does not have a verified entry for "
                        f"{h.current_state or 'your state'}. That means 'go and "
                        f"find out', not 'no exemption exists' — almost every "
                        f"state has one. Search "
                        f"'{h.current_state or 'your state'} disabled veteran "
                        f"property tax exemption' and call the county assessor. "
                        f"States covered so far: "
                        f"{', '.join(RB.states_covered())}."), icon="💡")
        else:
            saving = exempt_tax.saving(tax_annual, price)
            metric_row([
                ("State", exempt_tax.state),
                ("Your rating", f"{m.va_rating}%"),
                ("Exemption",
                 "Full homestead" if exempt_tax.full_exemption
                 else (exempt_tax.description if exempt_tax.qualifies else "None")),
                ("Worth, per year", fmt_money(saving)),
            ])
            if exempt_tax.full_exemption:
                st.success(esc(f"At {m.va_rating}% in {exempt_tax.state} the "
                               f"residence homestead is fully exempt — about "
                               f"{fmt_money(tax_annual)} a year, every year, "
                               f"and it survives into a surviving spouse's "
                               f"hands in most states. Apply for it; it is not "
                               f"automatic."), icon="✅")
            elif exempt_tax.qualifies:
                st.info(esc(f"{exempt_tax.description} — about "
                            f"{fmt_money(saving)} a year at this tax bill. "
                            f"Worth filing for, and small enough that most "
                            f"people never do."), icon="💡")
            else:
                st.caption(esc(exempt_tax.description))
            st.caption(esc(exempt_tax.note))
            st.caption(esc(f"{exempt_tax.citation} Confidence "
                           f"{exempt_tax.confidence}. {exempt_tax.verify}"))

    # ----------------------------------------------------------- findings
    with section("What this adds up to"):
        render_findings(
            VL.findings(fee=fee, pmi=pmi, ent=ent, assume=assume,
                        prepay=prepay, is_va_loan=hz.is_va_loan,
                        owns_home=hz.owns_home, va_rating=m.va_rating)
            + RB.findings(rvb, hz.years_at_this_station, owns_home=hz.owns_home))

    st.caption("An estimator, not advice, and not a loan quote. Every VA figure "
               "on this page is marked VERIFY because this machine cannot reach "
               "va.gov — check them at va.gov/housing-assistance or with a VA "
               "Regional Loan Centre before you sign anything. Military "
               "OneSource gives free counselling at 800-342-9647.")
