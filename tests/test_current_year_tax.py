"""
Tests for this year's federal return: engine/tax/current_year.py.

The claims being pinned here are the ones that decide whether a military family
files correctly or leaves four figures on the table:

  * Box 1 is basic pay and taxable special pays LESS the traditional TSP
    deferral. BAH and BAS are not in it and never were, so a household living
    on $75,000 files a $45,000 return.
  * A month in a combat zone removes that month's military pay from box 1
    entirely -- all of it for enlisted members and warrant officers.
  * Because of both, the Earned Income Credit reaches junior enlisted families
    whose real compensation looks far too high for it.
  * The combat-pay election (IRC 32(c)(2)(B)(vi)) can raise the credit or
    destroy it. It must be computed both ways and recommended only when it
    wins.
  * VA compensation is outside AGI, in every year, at any rating.
  * The Saver's Credit is an AGI test, and junior enlisted pass it.

The page is rendered headlessly against both sample plans at the bottom.
"""

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

from engine import storage
from engine.profile import Household, ServiceMember, SpouseIncome, CIVILIAN
from engine.tax import current_year as CY
from engine.tax import tables as T
from ui.panel import PROFILE_KEY, VERSION_KEY

ROOT = pathlib.Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "samples"
PAGE = ROOT / "pages" / "22_This_Years_Taxes.py"

E5_BASIC_MONTHLY = 4_110.0      # an E-5 at six years
BAH_MONTHLY = 2_000.0
BAS_MONTHLY = 460.0


def load(name: str) -> Household:
    return storage.from_upload_bytes((SAMPLES / f"{name}.mpfplan.json").read_bytes())


def e5(**kw) -> ServiceMember:
    """An E-5 with every pay figure overridden, so no table lookup is involved."""
    args = dict(grade="E-5", birth_year=1996, years_of_service=6.0,
                basic_pay_monthly_override=E5_BASIC_MONTHLY,
                bah_monthly_override=BAH_MONTHLY,
                bas_monthly_override=BAS_MONTHLY,
                has_dependents=True, tsp_contribution_pct=0.0,
                tsp_roth_share=1.0)
    args.update(kw)
    return ServiceMember(**args)


def household(member: ServiceMember, *, spouse_wages: float = 0.0,
              n_dependents: int = 2) -> Household:
    return Household(member=member, has_spouse=True, n_dependents=n_dependents,
                     spouse_income=SpouseIncome(employed=spouse_wages > 0,
                                                annual_income=spouse_wages),
                     state_of_legal_residence="Texas", current_state="Texas")


# ==========================================================================
# The W-2: what is in box 1 and what never gets there
# ==========================================================================

def test_box_one_is_taxable_pay_less_the_traditional_deferral():
    w = CY.w2_picture(e5(tsp_contribution_pct=0.10, tsp_roth_share=0.0))
    deferral = 0.10 * E5_BASIC_MONTHLY * 12

    assert w.basic_pay == pytest.approx(E5_BASIC_MONTHLY * 12)
    assert w.tsp_traditional == pytest.approx(deferral)
    assert w.tsp_traditional_box1_reduction == pytest.approx(deferral)
    assert w.box1 == pytest.approx(E5_BASIC_MONTHLY * 12 - deferral)


def test_box_one_excludes_bah_and_bas():
    w = CY.w2_picture(e5())
    assert w.bah == pytest.approx(BAH_MONTHLY * 12)
    assert w.bas == pytest.approx(BAS_MONTHLY * 12)
    assert w.box1 == pytest.approx(E5_BASIC_MONTHLY * 12)
    assert w.never_taxed == pytest.approx(w.bah + w.bas)

    # Doubling the housing allowance changes the W-2 not at all.
    richer = CY.w2_picture(e5(bah_monthly_override=BAH_MONTHLY * 2))
    assert richer.box1 == pytest.approx(w.box1)
    assert richer.gross > w.gross


def test_a_roth_contribution_does_not_reduce_box_one():
    roth = CY.w2_picture(e5(tsp_contribution_pct=0.10, tsp_roth_share=1.0))
    trad = CY.w2_picture(e5(tsp_contribution_pct=0.10, tsp_roth_share=0.0))
    assert roth.box1 == pytest.approx(E5_BASIC_MONTHLY * 12)
    assert trad.box1 < roth.box1


def test_the_chart_rows_account_for_every_dollar_of_gross():
    w = CY.w2_picture(e5(tsp_contribution_pct=0.10, tsp_roth_share=0.0,
                         in_combat_zone=True, months_deployed_this_year=4))
    assert sum(r["Amount"] for r in w.rows()) == pytest.approx(w.gross)
    taxed = sum(r["Amount"] for r in w.rows() if r["Treatment"] == "Taxed")
    assert taxed == pytest.approx(w.box1)


# ==========================================================================
# The Combat Zone Tax Exclusion
# ==========================================================================

def test_combat_zone_months_zero_out_military_pay_for_those_months():
    full = CY.w2_picture(e5())
    seven = CY.w2_picture(e5(in_combat_zone=True, months_deployed_this_year=7))

    assert seven.czte_months == 7
    assert seven.czte_excluded == pytest.approx(E5_BASIC_MONTHLY * 7)
    assert seven.box1 == pytest.approx(E5_BASIC_MONTHLY * 5)
    assert seven.combat_pay == pytest.approx(E5_BASIC_MONTHLY * 7)
    # The allowances are untouched: they were never taxable to begin with.
    assert seven.bah == pytest.approx(full.bah)
    assert seven.gross == pytest.approx(full.gross)


def test_a_full_year_in_the_zone_leaves_an_empty_box_one():
    w = CY.w2_picture(e5(in_combat_zone=True, months_deployed_this_year=12))
    assert w.box1 == pytest.approx(0.0)
    assert w.combat_pay == pytest.approx(E5_BASIC_MONTHLY * 12)
    # FICA still applies to excluded pay, so the earnings record keeps building.
    assert w.fica_wages == pytest.approx(E5_BASIC_MONTHLY * 12)


def test_the_page_may_override_the_months_without_touching_the_profile():
    m = e5(in_combat_zone=True, months_deployed_this_year=7)
    assert CY.w2_picture(m, czte_months=2).czte_months == 2
    assert CY.w2_picture(m, czte_months=0).box1 == pytest.approx(E5_BASIC_MONTHLY * 12)
    assert m.months_deployed_this_year == 7      # the profile is not written to

    est = CY.estimate(household(m), czte_months=3)
    assert est.w2.czte_months == 3
    assert est.member_wages == pytest.approx(E5_BASIC_MONTHLY * 9)


def test_only_the_share_of_a_deferral_made_from_taxed_pay_lowers_box_one():
    """A traditional contribution out of combat pay reduces nothing."""
    w = CY.w2_picture(e5(tsp_contribution_pct=0.12, tsp_roth_share=0.0,
                         in_combat_zone=True, months_deployed_this_year=6))
    deferral = 0.12 * E5_BASIC_MONTHLY * 12
    assert w.tsp_traditional == pytest.approx(deferral)
    assert w.tsp_traditional_box1_reduction == pytest.approx(deferral * 0.5)
    assert w.box1 == pytest.approx(E5_BASIC_MONTHLY * 6 - deferral * 0.5)
    assert any("never taxable" in n for n in w.notes)


# ==========================================================================
# The Earned Income Credit
# ==========================================================================

def test_the_credit_phases_in_plateaus_and_phases_out():
    p = CY.EITC_2026
    rate, top = p["credit_rate"][2], p["earned_income_amount"][2]

    small = CY.earned_income_credit(5_000, 5_000, 2, T.MFJ)
    assert small.phase == "phase-in"
    assert small.credit == pytest.approx(rate * 5_000)

    peak = CY.earned_income_credit(top, top, 2, T.MFJ)
    assert peak.phase == "plateau"
    assert peak.credit == pytest.approx(p["max_credit"][2], abs=1.0)

    over = CY.earned_income_credit(50_000, 50_000, 2, T.MFJ)
    assert over.phase == "phase-out"
    assert 0 < over.credit < peak.credit

    gone = CY.earned_income_credit(90_000, 90_000, 2, T.MFJ)
    assert gone.credit == 0 and not gone.eligible


def test_the_phase_out_runs_on_the_greater_of_agi_and_earned_income():
    low_agi = CY.earned_income_credit(50_000, 20_000, 2, T.MFJ)
    same = CY.earned_income_credit(50_000, 50_000, 2, T.MFJ)
    assert low_agi.credit == pytest.approx(same.credit)


def test_the_completed_phase_out_is_derived_not_hard_coded():
    p = CY.EITC_2026
    limit = CY.completed_phaseout(2, T.MFJ)
    assert limit == pytest.approx(p["phaseout_threshold"][T.MFJ][2]
                                  + p["max_credit"][2] / p["phaseout_rate"][2])
    assert CY.earned_income_credit(limit + 1, limit + 1, 2, T.MFJ).credit == 0
    assert CY.earned_income_credit(limit - 1_000, limit - 1_000, 2, T.MFJ).credit > 0


def test_investment_income_disqualifies_the_credit_outright():
    r = CY.earned_income_credit(
        30_000, 30_000, 2, T.MFJ,
        investment_income=CY.EITC_2026["investment_income_limit"] + 1)
    assert not r.eligible and r.credit == 0
    assert "Investment income" in r.reason


def test_allowances_keep_a_junior_enlisted_family_inside_the_credit():
    """
    The headline: $78,000 of real compensation, a $49,000 W-2, and a credit.
    """
    est = CY.estimate(household(e5()))
    assert est.received > 75_000
    assert 30_000 < est.member_wages < 55_000
    assert est.agi == pytest.approx(est.member_wages)
    assert est.eitc.credit > 3_000
    assert est.never_on_the_w2 == pytest.approx(est.received - est.member_wages)


# ==========================================================================
# The combat-pay election, both ways
# ==========================================================================

def test_the_election_is_computed_both_ways_and_only_taken_when_it_wins():
    h = load("e5_6yrs_brs")
    est = CY.estimate(h)

    # The sample as saved: married, two dependents, seven months in the zone,
    # $38,000 of spouse wages.
    assert est.status == T.MFJ and est.n_children == 2
    assert est.w2.basic_pay == pytest.approx(E5_BASIC_MONTHLY * 12)
    assert est.w2.czte_months == 7
    assert est.spouse_wages == pytest.approx(38_000.0)

    e = est.eitc
    assert e.combat_pay > 0
    assert e.without_election.credit > 0
    # Electing it in pushes past the completed phase-out and kills the credit.
    assert e.with_election.credit == 0
    assert e.recommend_election is False
    assert e.credit == pytest.approx(e.without_election.credit)
    assert "Leave the combat pay out" in e.note


def test_the_election_is_recommended_when_it_creates_a_credit():
    """Twelve months in the zone: box 1 is empty, so only the election helps."""
    h = load("e5_6yrs_brs")
    est = CY.estimate(h, czte_months=12, spouse_wages=0.0)

    assert est.member_wages == pytest.approx(0.0)
    e = est.eitc
    assert e.without_election.credit == 0
    assert e.with_election.credit > 3_000
    assert e.recommend_election is True
    assert e.gain == pytest.approx(e.with_election.credit)
    assert e.credit == pytest.approx(e.with_election.credit)
    assert "Schedule EIC" in e.note


def test_the_recommendation_always_takes_the_larger_of_the_two():
    h = load("e5_6yrs_brs")
    for months in range(0, 13):
        for spouse in (0.0, 20_000.0, 38_000.0):
            e = CY.estimate(h, czte_months=months, spouse_wages=spouse).eitc
            better = max(e.without_election.credit, e.with_election.credit)
            assert e.credit == pytest.approx(better)
            if e.recommend_election:
                assert e.with_election.credit > e.without_election.credit


def test_the_election_never_moves_agi_or_tax():
    h = load("e5_6yrs_brs")
    est = CY.estimate(h)
    assert est.agi == pytest.approx(est.member_wages + est.spouse_wages)
    assert est.w2.combat_pay > 0
    assert est.w2.combat_pay not in (est.agi,)
    assert est.agi < est.total_compensation - est.w2.combat_pay


# ==========================================================================
# The Child Tax Credit
# ==========================================================================

def test_combat_pay_counts_for_the_refundable_child_credit_with_no_election():
    """IRC 24(d)(1): a zero box 1 still produces the Additional CTC."""
    est = CY.estimate(household(e5(in_combat_zone=True,
                                   months_deployed_this_year=12)))
    assert est.member_wages == pytest.approx(0.0)
    assert est.tax_before_credits == pytest.approx(0.0)
    assert est.child.refundable > 0
    assert est.child.refundable == pytest.approx(
        min(2 * CY.CTC_2026["refundable_max_per_child"],
            CY.CTC_2026["refundable_rate"]
            * (est.w2.combat_pay - CY.CTC_2026["earned_income_floor"])))


def test_the_child_credit_phases_out_only_at_high_income():
    low = CY.child_tax_credit(2, 0, 60_000, T.MFJ, tax_available=5_000,
                              earned_income_for_actc=60_000)
    assert low.phaseout_reduction == 0
    assert low.total_after_phaseout == pytest.approx(2 * CY.CTC_2026["per_child"])

    high = CY.child_tax_credit(2, 0, 450_000, T.MFJ, tax_available=100_000,
                               earned_income_for_actc=450_000)
    assert high.phaseout_reduction == pytest.approx(50 * 50)


# ==========================================================================
# The Saver's Credit
# ==========================================================================

def test_the_savers_credit_applies_at_low_agi_and_not_at_high():
    tiers = CY.SAVERS_CREDIT_2026["tiers"][T.MFJ]
    low = CY.savers_credit(tiers[0][0] - 1_000, T.MFJ, [2_000.0],
                           member_age=27, tax_available=5_000)
    assert low.eligible and low.rate == 0.50
    assert low.credit == pytest.approx(1_000.0)

    middle = CY.savers_credit(tiers[-1][0] - 1_000, T.MFJ, [2_000.0],
                              member_age=27, tax_available=5_000)
    assert middle.eligible and middle.rate == 0.10
    assert middle.credit == pytest.approx(200.0)

    high = CY.savers_credit(tiers[-1][0] + 1_000, T.MFJ, [2_000.0],
                            member_age=27, tax_available=5_000)
    assert not high.eligible and high.credit == 0
    assert "above" in high.note


def test_the_savers_credit_caps_contributions_per_person_and_is_nonrefundable():
    cap = CY.SAVERS_CREDIT_2026["max_contribution_per_person"]
    r = CY.savers_credit(30_000, T.MFJ, [10_000.0, 10_000.0],
                         member_age=30, tax_available=10_000)
    assert r.contributions == [cap, cap]
    assert r.credit_before_limit == pytest.approx(0.50 * 2 * cap)

    poor = CY.savers_credit(30_000, T.MFJ, [10_000.0, 10_000.0],
                            member_age=30, tax_available=150.0)
    assert poor.credit == pytest.approx(150.0)
    assert "nonrefundable" in poor.note


def test_a_junior_enlisted_roth_tsp_contribution_earns_the_credit():
    est = CY.estimate(household(e5(tsp_contribution_pct=0.05, tsp_roth_share=1.0)))
    assert est.w2.tsp_roth > 0
    assert est.savers.eligible
    assert est.savers.credit > 0
    assert any("Saver's Credit" in head for _, head, _ in est.findings)


# ==========================================================================
# The retiree: VA compensation
# ==========================================================================

def test_va_compensation_is_not_in_agi():
    h = load("retired_o5_26yrs")
    est = CY.estimate(h)

    assert est.va_compensation == pytest.approx(4_050.0 * 12)
    assert est.agi == pytest.approx(est.retired_pay + est.spouse_wages
                                    + est.civilian_wages)
    assert est.received - est.taxed == pytest.approx(est.va_compensation)
    assert est.total_compensation > est.agi

    # Raising the rating to the maximum changes AGI and tax not at all.
    h.member.va_disability_monthly = 8_000.0
    richer = CY.estimate(h)
    assert richer.agi == pytest.approx(est.agi)
    assert richer.tax_before_credits == pytest.approx(est.tax_before_credits)
    assert richer.total_compensation > est.total_compensation


def test_a_retiree_has_no_w2_but_still_has_a_return():
    est = CY.estimate(load("retired_o5_26yrs"))
    assert est.w2.serving is False
    assert est.w2.gross == 0
    assert est.member_wages == 0
    assert est.retired_pay > 0
    assert any("1099-R" in n for n in est.w2.notes)
    assert any(r["Component"] == "Retired pay (1099-R)" for r in est.picture_rows())
    assert any(r["Component"] == "VA compensation" for r in est.picture_rows())
    assert est.taxed == pytest.approx(est.retired_pay + est.civilian_wages)


def test_a_high_income_retiree_gets_no_earned_income_credit():
    est = CY.estimate(load("retired_o5_26yrs"))
    assert est.eitc.credit == 0
    assert est.savers.credit == 0


# ==========================================================================
# Withholding and the refund
# ==========================================================================

def test_the_refund_estimate_changes_sign_with_withholding():
    h = load("retired_o5_26yrs")
    thin = CY.estimate(h, withheld_ytd=1_000.0, les_month=12)
    fat = CY.estimate(h, withheld_ytd=60_000.0, les_month=12)

    assert thin.refund < 0 < fat.refund
    assert fat.refund - thin.refund == pytest.approx(59_000.0)
    assert any(sev == "bad" and "OWE" in head for sev, head, _ in thin.findings)
    assert any("refund" in head for _, head, _ in fat.findings)


def test_a_year_to_date_figure_is_scaled_straight_line_to_the_year():
    assert CY.project_withholding(3_000.0, 6) == pytest.approx(6_000.0)
    assert CY.project_withholding(3_000.0, 12) == pytest.approx(3_000.0)
    assert CY.project_withholding(3_000.0, 0) == pytest.approx(3_000.0)

    h = load("retired_o5_26yrs")
    half = CY.estimate(h, withheld_ytd=8_000.0, les_month=6)
    assert half.withholding_projected == pytest.approx(16_000.0)
    assert half.withholding_is_estimate is False

    guessed = CY.estimate(h)
    assert guessed.withholding_is_estimate is True
    assert guessed.withholding_projected == pytest.approx(guessed.typical_withholding)


def test_a_bonus_is_withheld_at_the_flat_supplemental_rate():
    """And does not disturb the withholding on regular pay."""
    plain = CY.estimate(household(e5()))
    with_bonus = CY.estimate(household(e5(bonus_annual_taxable=20_000.0)))
    assert (with_bonus.typical_withholding - plain.typical_withholding
            == pytest.approx(20_000.0 * CY.SUPPLEMENTAL_WITHHOLDING_RATE))


# ==========================================================================
# Filing status and the household
# ==========================================================================

def test_filing_status_and_spouse_wages_come_from_the_household():
    h = household(e5(), spouse_wages=38_000.0)
    assert CY.filing_status_for(h) == T.MFJ
    assert CY.spouse_wages_for(h) == pytest.approx(38_000.0)

    h.has_spouse = False
    assert CY.filing_status_for(h) == T.SINGLE
    assert CY.spouse_wages_for(h) == 0.0


def test_filing_single_drops_the_spouse_wages_from_the_return():
    h = household(e5(), spouse_wages=38_000.0)
    joint = CY.estimate(h)
    single = CY.estimate(h, status=T.SINGLE)
    assert joint.spouse_wages == pytest.approx(38_000.0)
    assert single.spouse_wages == 0.0
    assert single.deductions < joint.deductions
    assert any("head of household" in head.lower() for _, head, _ in single.findings)


def test_dependents_beyond_the_children_are_worth_the_other_dependent_credit():
    h = household(e5(), n_dependents=3)
    est = CY.estimate(h, n_children=2)
    assert est.n_children == 2 and est.n_other_dependents == 1
    assert est.child.total_after_phaseout == pytest.approx(
        2 * CY.CTC_2026["per_child"] + CY.CTC_2026["other_dependent"])


def test_the_return_lines_balance():
    for name in ("e5_6yrs_brs", "retired_o5_26yrs"):
        est = CY.estimate(load(name))
        lines = dict(est.lines())
        assert lines["Adjusted gross income"] == pytest.approx(est.agi)
        assert lines["Taxable income"] == pytest.approx(
            max(0.0, est.agi - est.deductions))
        assert lines["Tax after credits"] == pytest.approx(est.tax_after_credits)
        label = "Refund" if est.refund >= 0 else "Balance due"
        assert lines[label] == pytest.approx(abs(est.refund))


def test_a_civilian_with_nothing_entered_does_not_blow_up():
    est = CY.estimate(Household(member=ServiceMember(component=CIVILIAN)))
    assert est.picture_rows() == []
    assert est.received == 0 and est.agi == 0
    assert est.refund >= 0


# ==========================================================================
# The page
# ==========================================================================

def render(plan: str | None = None):
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(PAGE), default_timeout=120)
    if plan:
        at.session_state[PROFILE_KEY] = load(plan)
        at.session_state[VERSION_KEY] = 0
    at.run()
    assert not at.exception, at.exception
    return at


def body(at) -> str:
    return " ".join([el.value for el in at.markdown]
                    + [el.value for el in at.caption]
                    + [el.value for el in at.success]
                    + [el.value for el in at.warning]
                    + [el.value for el in at.info]
                    + [el.value for el in at.error])


def test_the_page_renders_for_a_deployed_e5():
    at = render("e5_6yrs_brs")
    assert "Taxes" in at.title[0].value
    text = body(at)
    assert "Earned Income Credit" in text
    assert "Saver's Credit" in text
    assert "Leave the combat pay out" in text
    # Dollars in prose are escaped, or Streamlit reads a pair of them as LaTeX.
    assert "\\$" in text
    # The W-2 chart compiled: an invalid Altair spec raises on serialisation.
    assert len(at.get("vega_lite_chart")) == 1

    labels = {mtr.label: mtr.value for mtr in at.metric}
    assert labels["On the W-2 (box 1)"] == "$20,550"
    assert labels["Your total compensation"] == "$84,815"
    assert labels["What to do"] == "Leave it out"


def test_the_page_renders_for_a_retiree():
    at = render("retired_o5_26yrs")
    text = body(at)
    assert "Balance due" in text or "OWE" in text
    assert len(at.get("vega_lite_chart")) == 1
    labels = {mtr.label: mtr.value for mtr in at.metric}
    # No W-2 at all, so the panel says what a return sees instead of box 1.
    assert "On the W-2 (box 1)" not in labels
    assert labels["What to do"] == "Nothing to elect"
    assert labels["Never taxed"] == "$48,600"      # the VA compensation


def test_the_page_renders_with_an_empty_plan():
    at = render()
    assert not at.exception
    assert at.session_state[PROFILE_KEY] is not None


def test_the_page_reads_the_plan_as_defaults_and_lets_them_be_overridden():
    at = render("e5_6yrs_brs")
    assert at.selectbox(key="cy_status__v0").value == T.MFJ
    assert at.number_input(key="cy_kids__v0").value == 2
    assert at.number_input(key="cy_czmonths__v0").value == 7
    assert at.number_input(key="cy_spousewage__v0").value == pytest.approx(38_000.0)

    at.number_input(key="cy_czmonths__v0").set_value(0).run()
    assert not at.exception, at.exception
    # The override is page-local: the plan itself is untouched.
    assert at.session_state[PROFILE_KEY].member.months_deployed_this_year == 7
    assert "nothing to elect" in body(at)


def test_the_page_takes_a_withholding_figure_from_the_les():
    at = render("e5_6yrs_brs")
    assert "estimate from plain W-4 settings" in body(at)

    at.toggle(key="cy_haveles__v0").set_value(True).run()
    assert not at.exception, at.exception
    at.number_input(key="cy_withheld__v0").set_value(1_200.0).run()
    assert not at.exception, at.exception
    at.selectbox(key="cy_month__v0").set_value(6).run()
    assert not at.exception, at.exception
    assert "through June" in body(at)


def test_the_page_switches_to_single_and_hides_the_spouse():
    at = render("e5_6yrs_brs")
    at.selectbox(key="cy_status__v0").select(T.SINGLE).run()
    assert not at.exception, at.exception
    assert "cy_spousewage__v0" not in [w.key for w in at.number_input]
