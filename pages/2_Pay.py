import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import streamlit as st
import pandas as pd
st.set_page_config(page_title="Pay", page_icon="💵", layout="wide")

from ui.panel import (wkey, render_save_load, page_header, section, metric_row,
                      money, toggle, fmt_money, fmt_pct, esc, md_money)
from engine.pay import grades as G, bah as BAH, bas as BAS, basepay as BP
from engine.pay import bah_nonlocality as NL
from engine.profile import GUARD, RESERVE

h = render_save_load("pay")
m = h.member

page_header("💵 Pay",
            "What you actually earn, split into what is taxed and what is not. "
            "That split is the biggest structural difference between military "
            "and civilian compensation.")

bah_data = BAH.load()
bp_table = BP.load()
try:
    is_officer = G.is_officer(G.get(m.grade))
except KeyError:
    is_officer = False

# ==========================================================================
with section("Basic pay"):
    c1, c2 = st.columns([1, 2])
    with c1:
        money("Override from your LES (0 = use the table)", m,
              "basic_pay_monthly_override", key=wkey("bpover"), step=50.0,
              help="Your LES is authoritative. The table is a convenience.")
    bp = BP.lookup(m.grade, m.years_of_service, bp_table,
                   override_monthly=m.basic_pay_monthly_override)
    with c2:
        if bp.found:
            metric_row([(f"{bp.grade} at {bp.yos_column}+ years",
                         f"{fmt_money(bp.monthly)}/mo",
                         f"{fmt_money(bp.annual)}/yr")])
            if bp.note:
                st.caption(esc(bp.note))
            elif bp.next_raise_at_years:
                st.caption(f"Next longevity raise at {bp.next_raise_at_years:g} "
                           f"years of service.")
        else:
            st.warning(esc(bp.note), icon="⚠️")

basic = bp.monthly if bp.found else 0.0

# ==========================================================================
with section("Housing allowance"):
    if m.lives_in_government_housing:
        nlp = NL.partial(m.grade)
        bah_monthly = nlp.monthly if nlp.found else 0.0
        st.info(f"You live in government quarters, so you receive **BAH-Partial** "
                f"of {fmt_money(bah_monthly)}/mo rather than a locality rate. "
                f"Housing is provided instead.", icon="🏠")
    else:
        b1, b2 = st.columns([1, 2])
        with b1:
            money("Override from your LES (0 = look it up)", m,
                  "bah_monthly_override", key=wkey("bahover"), step=50.0)
        with b2:
            if m.bah_monthly_override > 0:
                bah_monthly = m.bah_monthly_override
                metric_row([("BAH — from your LES", f"{fmt_money(bah_monthly)}/mo",
                             f"{fmt_money(bah_monthly * 12)}/yr")])
            else:
                r = BAH.lookup_or_average(m.duty_zip, m.grade, m.has_dependents,
                                          bah_data)
                bah_monthly = r.monthly
                if r.found:
                    metric_row([(f"BAH — {r.mha_name}", f"{fmt_money(r.monthly)}/mo",
                                 f"{fmt_money(r.annual)}/yr")])
                    if r.is_average:
                        st.caption("📍 " + esc(r.note))
                else:
                    st.warning(esc(r.note), icon="⚠️")

        if bah_monthly > 0:
            hc1, hc2 = st.columns([1, 2])
            with hc1:
                actual = st.number_input(
                    "Your actual rent/PITI + utilities (0 = estimate)",
                    value=0.0, step=50.0, min_value=0.0, format="%.2f",
                    key=wkey("housecost"))
            pos = BAH.housing_position(bah_monthly, actual)
            with hc2:
                metric_row([
                    ("Housing cost", f"{fmt_money(pos.housing_cost_monthly)}/mo"),
                    ("Left over", f"{fmt_money(pos.surplus_monthly)}/mo"),
                    ("Per year", fmt_money(pos.surplus_annual)),
                ])
            st.caption(esc(pos.note))

# ==========================================================================
if m.component in (GUARD, RESERVE):
    with section("Guard and Reserve"):
        dp = BP.drill_pay(m.grade, m.years_of_service, bp_table,
                          override_monthly=m.basic_pay_monthly_override)
        rc = NL.rc_transit(m.grade, m.has_dependents)
        if dp.found:
            metric_row([("One drill", fmt_money(dp.per_drill)),
                        ("A drill weekend", fmt_money(dp.per_weekend)),
                        ("48 drills a year", fmt_money(dp.annual_48_drills)),
                        ("BAH RC/Transit", f"{fmt_money(rc.monthly)}/mo"
                         if rc.found else "—")])
            st.caption(esc(dp.note))

# ==========================================================================
with section("Subsistence and special pays"):
    s1, s2, s3 = st.columns(3)
    bas_r = BAS.bas_monthly(is_officer)
    with s1:
        metric_row([("BAS — " + ("officer" if is_officer else "enlisted"),
                     f"{fmt_money(bas_r.monthly)}/mo",
                     f"{fmt_money(bas_r.annual)}/yr")])
    with s2:
        money("Special and incentive pays, per month", m, "special_pay_monthly",
              key=wkey("spay"), step=50.0,
              help="Flight pay, sea pay, hazardous duty, language pay, medical "
                   "special pays. Most are taxable, and none count toward "
                   "retired pay.")
    with s3:
        toggle("Special pays are taxable", m, "special_pay_taxable",
               key=wkey("spaytax"))

bas_monthly = m.bas_monthly_override or bas_r.monthly
taxable = basic + (m.special_pay_monthly if m.special_pay_taxable else 0.0)
nontaxable = (bah_monthly + bas_monthly
              + (0.0 if m.special_pay_taxable else m.special_pay_monthly))
total = taxable + nontaxable

# ==========================================================================
with section("Total compensation"):
    metric_row([
        ("Taxable", f"{fmt_money(taxable)}/mo", f"{fmt_money(taxable * 12)}/yr"),
        ("Non-taxable", f"{fmt_money(nontaxable)}/mo",
         f"{fmt_money(nontaxable * 12)}/yr"),
        ("Total", f"{fmt_money(total)}/mo", f"{fmt_money(total * 12)}/yr"),
        ("Untaxed share", fmt_pct(nontaxable / total if total else 0, 0)),
    ])

    if total > 0:
        df = pd.DataFrame([
            {"Component": "Basic pay", "Monthly": basic, "Annual": basic * 12,
             "Taxed": "Yes"},
            {"Component": "BAH", "Monthly": bah_monthly,
             "Annual": bah_monthly * 12, "Taxed": "No"},
            {"Component": "BAS", "Monthly": bas_monthly,
             "Annual": bas_monthly * 12, "Taxed": "No"},
            {"Component": "Special pays", "Monthly": m.special_pay_monthly,
             "Annual": m.special_pay_monthly * 12,
             "Taxed": "Yes" if m.special_pay_taxable else "No"},
        ])
        df = df[df["Monthly"] > 0]
        st.dataframe(df.style.format({"Monthly": "${:,.2f}", "Annual": "${:,.0f}"}),
                     use_container_width=True, hide_index=True)

    if nontaxable > 0 and total > 0:
        st.success(
            f"**{fmt_pct(nontaxable / total, 0)} of your compensation is never "
            f"taxed.** A civilian earning {md_money(total * 12)} pays federal "
            f"tax on all of it; you pay on {md_money(taxable * 12)}. Your "
            f"marginal bracket is lower than your standard of living suggests, "
            f"which makes **Roth** the default rather than a close call — and a "
            f"lender will happily qualify you on gross pay that includes "
            f"allowances you lose the moment you move into quarters or PCS "
            f"somewhere cheaper.", icon="💡")

    if m.in_combat_zone:
        st.info("**In a combat zone this changes again.** See the TSP & "
                "Deployment page — enlisted members and warrant officers "
                "exclude all military pay for any month with a day in the zone.",
                icon="🎖️")

if bah_data:
    st.caption(f"BAH {bah_data.year} · {bah_data.n_mhas} housing areas · "
               f"basic pay {bp_table.year if bp_table else 'not installed'} · "
               f"BAS {bas_r.year}. Rates change 1 January.")
