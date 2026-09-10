import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import streamlit as st
import pandas as pd
import altair as alt

from ui.panel import (wkey, get_household, page_header, two_pane, input_card,
                      section, metric_row, money, pct, integer, number, toggle,
                      choice, fmt_money, fmt_pct, esc, md_money, render_findings,
                      mark_dirty, invalidate)
from engine.career import timeline as TL
from engine.income import spouse as SP
from engine.pay import grades as G, bah as BAH

h = get_household()
m = h.member
bah_data = BAH.load()

page_header("📈 Career",
            "Promotions and moves on one line. Pay steps at longevity "
            "boundaries and jumps on orders — it does not grow on a curve.")

# --------------------------------------------------------------------------
if "timeline" not in st.session_state:
    st.session_state["timeline"] = TL.CareerTimeline(
        promotions=TL.default_promotions(m.grade, m.years_of_service),
        separation_at_years_of_service=20.0)
t = st.session_state["timeline"]

START = float(m.years_of_service)
END = float(t.separation_at_years_of_service)
si = h.spouse_income

inputs, results = two_pane()

# ==========================================================================
# Left: the questions, stacked.
# ==========================================================================
with inputs:
    with input_card("When you separate and promote"):
        # Time in grade is what a promotion board actually looks at, and the
        # sliders below are years of service, so say where the member is
        # standing now. Only shown from a Date of Rank -- a typed number of
        # years is stale the moment the plan is reopened, and a stale figure
        # stated this confidently would be worse than saying nothing.
        if m.dor is not None:
            st.caption(f"You have {m.time_in_grade():.1f} years in {m.grade}, "
                       f"from a Date of Rank of {m.date_of_rank}. Set it on "
                       f"Profile.")

        sep = st.slider("When do you separate or retire?", min_value=max(2.0, START + 1),
                        max_value=42.0, value=float(max(END, START + 1)),
                        step=1.0, key=wkey("sepslider"), format="%g yrs")
        if sep != t.separation_at_years_of_service:
            t.separation_at_years_of_service = sep
            END = sep

        st.markdown("###### Promotions")
        new_proms = []
        for i, p in enumerate(t.promotions):
            if p.at_years_of_service > sep:
                continue
            st.markdown(f"**{p.to_grade}**")
            at = st.slider(f"{p.to_grade} at", min_value=float(int(START)),
                           max_value=float(sep), value=float(min(max(p.at_years_of_service, START), sep)),
                           step=0.5, key=wkey(f"prom_{i}"),
                           label_visibility="collapsed", format="%g yrs")
            new_proms.append(TL.Promotion(p.to_grade, at, p.confirmed))
        t.promotions = new_proms

        if st.button("Reset timing", use_container_width=True,
                     key=wkey("resetp")):
            t.promotions = TL.default_promotions(m.grade, m.years_of_service)
            st.rerun()
        if st.button("No more promotions", use_container_width=True,
                     key=wkey("clearp")):
            t.promotions = []
            st.rerun()

    with input_card("Where are you moving next?"):
        move_rows = [{"At YOS": mv.at_years_of_service, "ZIP": mv.destination_zip,
                      "Label": mv.destination_label,
                      "Into quarters": mv.into_government_housing}
                     for mv in t.moves]
        if not move_rows:
            move_rows = [{"At YOS": min(START + 3, END), "ZIP": "", "Label": "",
                          "Into quarters": False}]
        edited = st.data_editor(
            pd.DataFrame(move_rows), num_rows="dynamic", use_container_width=True,
            key=wkey("moves"), height=170,
            column_config={
                "At YOS": st.column_config.NumberColumn(format="%.1f",
                                                        min_value=0.0, max_value=42.0),
                "ZIP": st.column_config.TextColumn(width="small"),
            })
        if st.button("Apply moves", type="primary", use_container_width=True,
                     key=wkey("applymoves")):
            moves = []
            for _, row in edited.iterrows():
                z = str(row.get("ZIP") or "").strip()
                if not z:
                    continue
                moves.append(TL.PCSMove(
                    at_years_of_service=float(row.get("At YOS") or 0),
                    destination_zip=z,
                    destination_label=str(row.get("Label") or ""),
                    into_government_housing=bool(row.get("Into quarters"))))
            t.moves = moves
            mark_dirty(); invalidate(); st.rerun()

    with input_card("Want to compare two ZIP codes?"):
        from_zip = st.text_input("Which ZIP are you moving from?", value=m.duty_zip or "",
                                 key=wkey("fz"), placeholder="73503")
        to_zip = st.text_input("Which ZIP are you moving to?", value="", key=wkey("tz"),
                               placeholder="92134")

    with input_card("About your spouse"):
        toggle("Is your spouse employed?", si, "employed", key=wkey("spemp"))
        toggle("Are you both in the military?", si, "is_dual_military", key=wkey("spdual"),
               help="Both on orders, so a PCS does not stop either income.")
        money("What do they earn, per year?", si, "annual_income", key=wkey("spinc"), step=1000.0)
        choice("What kind of work does your spouse do?", si, "career_type", SP.CAREER_TYPES,
               key=wkey("spcareer"),
               help="How well the work survives a move is the whole question.")
        number("How many months out of work per move?", si, "months_unemployed_per_pcs",
               key=wkey("spmonths"), min_value=0.0, max_value=24.0, step=0.5)
        pct("How far does pay fall on a move? (%)", si, "wage_reset_on_move", key=wkey("spreset"),
            step=1.0, max_value=60.0,
            help="How far pay falls on landing in a new market, before "
                 "rebuilding.")
        pct("How much goes to retirement? (%)", si,
            "retirement_contribution_pct", key=wkey("spret"), step=0.5,
            max_value=50.0)
        pct("What does the employer match? (%)", si, "employer_match_pct", key=wkey("spmatch"),
            step=0.5, max_value=25.0)

# ==========================================================================
# What those answers produce.
# ==========================================================================
marks = []
marks.append({"YOS": START, "Label": f"Now · {m.grade}", "Kind": "Now",
              "Row": 0})
for p in t.promotions:
    marks.append({"YOS": p.at_years_of_service, "Label": p.to_grade,
                  "Kind": "Promotion", "Row": 1})
for mv in t.moves:
    marks.append({"YOS": mv.at_years_of_service,
                  "Label": mv.destination_label or mv.destination_zip,
                  "Kind": "PCS", "Row": 2})
marks.append({"YOS": sep, "Label": "Separate", "Kind": "End", "Row": 0})
dfm = pd.DataFrame(marks)

imp = None
if from_zip and to_zip:
    imp = TL.compare_locations(from_zip, to_zip, m.grade,
                               m.has_dependents, bah_data)

proj = SP.project_spouse_income(si, t.moves, 2026, START, END)

rows = TL.project(m, t, start_year=2026, bah_data=bah_data)
spouse_by_year = {r.year: r.earned for r in proj.years} if proj.years else {}
df = pd.DataFrame([{
    "Year": r.year, "YOS": r.years_of_service, "Grade": r.grade,
    "Location": r.duty_label or r.duty_zip or "—",
    "Basic pay": r.basic_pay_monthly * 12,
    "BAH": r.bah_monthly * 12, "BAS": r.bas_monthly * 12,
    "Spouse": spouse_by_year.get(r.year, 0.0),
    "Household": r.total_annual + spouse_by_year.get(r.year, 0.0),
    "Untaxed %": r.nontaxable_share * 100,
    "Event": ("★ Promotion" if r.promoted_this_year else "")
             + (" ✈ PCS" if r.moved_this_year else ""),
} for r in rows]) if rows else None

# ==========================================================================
# Right: the career, drawn.
# ==========================================================================
with results:
    with section("Career timeline",
                 "Drag each marker to the year of service you expect it. "
                 "Defaults are service averages — officer timing follows DOPMA "
                 "zones and is fairly predictable; enlisted timing swings widely "
                 "by branch and specialty."):

        base_line = alt.Chart(pd.DataFrame({"x": [START], "x2": [sep], "y": [0]})).mark_rule(
            strokeWidth=3, color="#d5dde0").encode(
            x=alt.X("x:Q", scale=alt.Scale(domain=[START - 0.5, sep + 0.5]),
                    axis=alt.Axis(title="Years of service", grid=True,
                                  tickMinStep=1, gridColor="#eef1f2")),
            x2="x2:Q", y=alt.Y("y:Q", scale=alt.Scale(domain=[-0.6, 2.6]),
                               axis=None))

        colors = alt.Scale(domain=["Now", "Promotion", "PCS", "End"],
                           range=["#5a6b73", "#2a78d6", "#eb6834", "#1baf7a"])
        points = alt.Chart(dfm).mark_point(size=190, filled=True, opacity=1,
                                           stroke="white", strokeWidth=2).encode(
            x="YOS:Q", y=alt.Y("Row:Q", axis=None),
            color=alt.Color("Kind:N", scale=colors,
                            legend=alt.Legend(orient="top", title=None)),
            tooltip=[alt.Tooltip("Label:N"), alt.Tooltip("Kind:N"),
                     alt.Tooltip("YOS:Q", title="Years of service", format=".1f")])
        labels = alt.Chart(dfm).mark_text(dy=-16, fontSize=11,
                                          color="#16232b").encode(
            x="YOS:Q", y=alt.Y("Row:Q", axis=None), text="Label:N")
        stems = alt.Chart(dfm).mark_rule(strokeWidth=1, color="#c3ccd0").encode(
            x="YOS:Q", y=alt.Y("Row:Q", axis=None), y2=alt.datum(0))

        st.altair_chart((base_line + stems + points + labels)
                        .properties(height=210).configure_view(strokeWidth=0),
                        use_container_width=True)

    with section("Planned moves",
                 "If you know where you are going next, this is the first number "
                 "you want. A move can be worth more than a promotion."):
        st.caption("BAH impact")
        if imp is not None:
            if imp.found:
                metric_row([
                    (imp.from_label or from_zip, f"{fmt_money(imp.from_bah)}/mo"),
                    (imp.to_label or to_zip, f"{fmt_money(imp.to_bah)}/mo"),
                    ("Change", f"{fmt_money(imp.monthly_change)}/mo",
                     f"{fmt_money(imp.annual_change)}/yr"),
                ])
                st.caption(esc(imp.note))
            elif imp.note:
                st.caption("⚠️ " + esc(imp.note))

    with section("Spouse income",
                 "A military spouse's earnings are not a continuous career. They "
                 "stop at every move and restart in a new labour market. This is "
                 "usually the largest uncosted item in a military family's finances."):
        if proj.years:
            metric_row([
                ("Spouse earns", fmt_money(proj.total_earned)),
                ("Uninterrupted career", fmt_money(proj.total_uninterrupted)),
                ("Cost of the moves", fmt_money(proj.total_lost),
                 f"-{fmt_pct(proj.lost_share, 0)}"),
                ("Retirement never saved", fmt_money(proj.total_retirement_lost)),
            ])
            dfs = pd.DataFrame([{"Year": r.year, "Earned": r.earned,
                                 "Uninterrupted career": r.uninterrupted}
                                for r in proj.years])
            st.line_chart(dfs, x="Year", y=["Earned", "Uninterrupted career"],
                          height=200)

        render_findings(SP.findings(si, proj))

    if rows:
        with section("Projected household pay"):
            first, last = df.iloc[0], df.iloc[-1]
            metric_row([
                ("Household now", fmt_money(first["Household"])),
                (f"At {last['YOS']:.0f} years", fmt_money(last["Household"])),
                ("Untaxed share now", f"{first['Untaxed %']:.0f}%"),
                ("Spouse share now",
                 fmt_pct(first["Spouse"] / first["Household"] if first["Household"] else 0, 0)),
            ])

            st.altair_chart(
                alt.Chart(df.melt(id_vars="Year",
                                  value_vars=["Basic pay", "BAH", "BAS", "Spouse"],
                                  var_name="Component", value_name="Amount"))
                .mark_area(interpolate="monotone", stroke="white", strokeWidth=1)
                .encode(x=alt.X("Year:Q", axis=alt.Axis(format="d", title=None),
                                scale=alt.Scale(nice=False, zero=False)),
                        y=alt.Y("Amount:Q", stack="zero",
                                axis=alt.Axis(format="$,.0s", title="Annual")),
                        color=alt.Color("Component:N",
                                        scale=alt.Scale(range=["#2a78d6", "#eb6834",
                                                               "#eda100", "#1baf7a"]),
                                        legend=alt.Legend(orient="top", title=None)),
                        tooltip=["Year:Q", "Component:N",
                                 alt.Tooltip("Amount:Q", format="$,.0f")])
                .properties(height=250).configure_view(strokeWidth=0),
                use_container_width=True)

            with st.expander("Year by year"):
                st.dataframe(df.style.format({
                    "Basic pay": "${:,.0f}", "BAH": "${:,.0f}", "BAS": "${:,.0f}",
                    "Spouse": "${:,.0f}", "Household": "${:,.0f}",
                    "Untaxed %": "{:.0f}%", "YOS": "{:.0f}"}),
                    use_container_width=True, hide_index=True, height=360)

            st.caption("BAH is not inflated forward — it is a market rate, and "
                       "guessing its trajectory adds error rather than removing "
                       "it.")
