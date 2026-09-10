import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import streamlit as st
import pandas as pd
st.set_page_config(page_title="Career", page_icon="📈", layout="wide")

from ui.panel import (wkey, render_save_load, page_header, fmt_money, fmt_pct,
                      esc, md_money)
from engine.career import timeline as TL
from engine.pay import grades as G, bah as BAH

h = render_save_load("career")
m = h.member
page_header("📈 Career",
            "Promotions and moves over time. Military pay does not grow on a "
            "curve — it steps at longevity boundaries, jumps at promotion, and "
            "can swing thousands a month on a single set of orders.")

bah_data = BAH.load()

# --------------------------------------------------------------------------
st.markdown("### What a move would do to your pay")
st.caption("If you know where you are going next, this is the first number you "
           "want. It is invisible in any civilian planning tool.")

c1, c2, c3 = st.columns(3)
with c1:
    from_zip = st.text_input("Current ZIP", value=m.duty_zip or "",
                             key=wkey("fromzip"), placeholder="73503")
with c2:
    to_zip = st.text_input("Next duty station ZIP", value="",
                           key=wkey("tozip"), placeholder="92134")
with c3:
    st.write("")
    st.write("")
    compare = st.button("Compare", type="primary", use_container_width=True,
                        key=wkey("cmp"))

if to_zip and from_zip:
    impact = TL.compare_locations(from_zip, to_zip, m.grade, m.has_dependents,
                                  bah_data)
    if impact.found:
        k = st.columns(3)
        k[0].metric(impact.from_label or from_zip,
                    f"{fmt_money(impact.from_bah)}/mo")
        k[1].metric(impact.to_label or to_zip, f"{fmt_money(impact.to_bah)}/mo")
        k[2].metric("Change", f"{fmt_money(impact.monthly_change)}/mo",
                    f"{fmt_money(impact.annual_change)}/yr")
        st.info(esc(impact.note), icon="📍")
        st.caption("Remember that a higher allowance reflects higher local "
                   "housing costs. It is not a raise in real terms, and housing "
                   "typically consumes slightly more than the allowance either "
                   "way.")
    elif impact.note:
        st.warning(esc(impact.note), icon="⚠️")

# --------------------------------------------------------------------------
st.markdown("---")
st.markdown("### Promotion timeline")

note = TL.promotion_note(m.grade)
if note:
    st.caption(esc(note))

if "timeline" not in st.session_state:
    st.session_state["timeline"] = TL.CareerTimeline(
        promotions=TL.default_promotions(m.grade, m.years_of_service),
        separation_at_years_of_service=20.0)
t = st.session_state["timeline"]

if st.button("Reset to typical timing for my grade", key=wkey("resetpromo")):
    st.session_state["timeline"] = TL.CareerTimeline(
        promotions=TL.default_promotions(m.grade, m.years_of_service),
        moves=t.moves, separation_at_years_of_service=t.separation_at_years_of_service)
    st.rerun()

prom_rows = [{"Promote to": p.to_grade, "At years of service": p.at_years_of_service,
              "Have orders / sequence number": p.confirmed} for p in t.promotions]
if not prom_rows:
    prom_rows = [{"Promote to": "", "At years of service": 0.0,
                  "Have orders / sequence number": False}]

edited_p = st.data_editor(
    pd.DataFrame(prom_rows), num_rows="dynamic", use_container_width=True,
    key=wkey("promo_editor"),
    column_config={
        "Promote to": st.column_config.SelectboxColumn(options=G.GRADE_LABELS),
        "At years of service": st.column_config.NumberColumn(
            format="%.1f", min_value=0.0, max_value=45.0),
    })

st.markdown("### Planned moves")
move_rows = [{"At years of service": mv.at_years_of_service,
              "Destination ZIP": mv.destination_zip,
              "Label": mv.destination_label, "Tour type": mv.tour_type,
              "Into government housing": mv.into_government_housing}
             for mv in t.moves]
if not move_rows:
    move_rows = [{"At years of service": 0.0, "Destination ZIP": "", "Label": "",
                  "Tour type": "CONUS", "Into government housing": False}]

edited_m = st.data_editor(
    pd.DataFrame(move_rows), num_rows="dynamic", use_container_width=True,
    key=wkey("move_editor"),
    column_config={
        "At years of service": st.column_config.NumberColumn(
            format="%.1f", min_value=0.0, max_value=45.0),
        "Tour type": st.column_config.SelectboxColumn(options=TL.TOUR_TYPES),
    })

sep = st.number_input("Separate or retire at years of service",
                      value=float(t.separation_at_years_of_service),
                      min_value=1.0, max_value=45.0, step=1.0, format="%.1f",
                      key=wkey("sepyos"))

if st.button("Apply timeline", type="primary", key=wkey("applytl")):
    proms = []
    for _, row in edited_p.iterrows():
        gname = str(row.get("Promote to") or "").strip()
        if not gname:
            continue
        proms.append(TL.Promotion(to_grade=gname,
                                  at_years_of_service=float(row.get("At years of service") or 0),
                                  confirmed=bool(row.get("Have orders / sequence number"))))
    moves = []
    for _, row in edited_m.iterrows():
        z = str(row.get("Destination ZIP") or "").strip()
        if not z:
            continue
        moves.append(TL.PCSMove(at_years_of_service=float(row.get("At years of service") or 0),
                                destination_zip=z,
                                destination_label=str(row.get("Label") or ""),
                                tour_type=str(row.get("Tour type") or "CONUS"),
                                into_government_housing=bool(row.get("Into government housing"))))
    st.session_state["timeline"] = TL.CareerTimeline(
        promotions=proms, moves=moves, separation_at_years_of_service=sep)
    st.rerun()

# --------------------------------------------------------------------------
st.markdown("---")
st.markdown("### Projected pay")

rows = TL.project(m, t, start_year=2026, bah_data=bah_data)
if rows:
    df = pd.DataFrame([{
        "Year": r.year, "YOS": r.years_of_service, "Grade": r.grade,
        "Location": r.duty_label or r.duty_zip or "—",
        "Basic pay": r.basic_pay_monthly, "BAH": r.bah_monthly,
        "BAS": r.bas_monthly, "Total /mo": r.total_monthly,
        "Total /yr": r.total_annual, "Untaxed %": r.nontaxable_share * 100,
        "Event": ("Promotion" if r.promoted_this_year else "") +
                 (" · PCS" if r.moved_this_year else ""),
    } for r in rows])

    st.dataframe(df.style.format({
        "Basic pay": "${:,.0f}", "BAH": "${:,.0f}", "BAS": "${:,.0f}",
        "Total /mo": "${:,.0f}", "Total /yr": "${:,.0f}",
        "Untaxed %": "{:.0f}%", "YOS": "{:.0f}"}),
        use_container_width=True, hide_index=True, height=420)

    st.line_chart(df, x="Year", y=["Basic pay", "BAH", "Total /mo"], height=300)

    first, last = rows[0], rows[-1]
    k = st.columns(3)
    k[0].metric("Now", f"{fmt_money(first.total_annual)}/yr")
    k[1].metric(f"At {last.years_of_service:.0f} years",
                f"{fmt_money(last.total_annual)}/yr")
    k[2].metric("Untaxed share now", fmt_pct(first.nontaxable_share, 0))

    st.caption("BAH is not inflated forward — it is a market-set rate and "
               "guessing its trajectory would add error rather than remove it. "
               "Basic pay steps at longevity boundaries and at promotion, which "
               "is why the line is not smooth.")
