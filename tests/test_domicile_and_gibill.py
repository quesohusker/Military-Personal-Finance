import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

from engine.tax import domicile as D
from engine.benefits import gi_bill as GI


# ==========================================================================
# Domicile
# ==========================================================================

def test_no_tax_states_tax_nothing():
    for s in D.NO_TAX_STATES:
        p = D.profile(s)
        assert p.rate == 0
        assert not p.taxes_active_duty_pay
        assert not p.taxes_retired_pay


def test_va_compensation_is_never_taxed_by_any_state():
    for s in ("California", "Oregon", "Texas", "Michigan"):
        assert not D.profile(s).taxes_va_compensation


def test_california_taxes_both_active_and_retired_pay():
    p = D.profile("California")
    assert p.taxes_active_duty_pay
    assert p.taxes_retired_pay


def test_michigan_exempts_both():
    p = D.profile("Michigan")
    assert not p.taxes_active_duty_pay
    assert not p.taxes_retired_pay


def test_a_career_in_california_costs_six_figures_against_texas():
    c = D.compare_states("California", "Texas", 60_000, 87_000, 20, 30)
    assert c.lifetime_saving > 300_000
    assert c.active_saving > 0 and c.retired_saving > 0


def test_two_exempt_states_are_worth_the_same():
    c = D.compare_states("Michigan", "Texas", 60_000, 87_000, 20, 30)
    assert abs(c.lifetime_saving) < 1_000
    assert "almost identically" in " ".join(c.notes)


def test_va_compensation_is_excluded_from_the_comparison():
    with_va = D.compare_states("California", "Texas", 60_000, 87_000, 20, 30,
                               annual_va_compensation=48_000)
    without = D.compare_states("California", "Texas", 60_000, 87_000, 20, 30)
    assert with_va.lifetime_saving == pytest.approx(without.lifetime_saving)
    assert any("tax-free in every state" in n for n in with_va.notes)


def test_a_move_to_a_worse_state_reports_a_cost_not_a_saving():
    c = D.compare_states("Texas", "California", 60_000, 87_000, 20, 30)
    assert c.lifetime_saving < 0
    assert "MORE than" in " ".join(c.notes)


def test_a_reversal_in_retirement_is_flagged():
    """A state good while serving may be bad to retire to."""
    c = D.compare_states("Michigan", "California", 60_000, 87_000, 20, 30)
    assert any("reversal in retirement" in n for n in c.notes)
    assert any("SCRA no longer protects" in n for n in c.notes)


def test_every_comparison_warns_that_domicile_needs_real_connection():
    c = D.compare_states("California", "Texas", 60_000, 87_000, 20, 30)
    joined = " ".join(c.notes)
    assert "genuine connection, not preference" in joined
    assert "States audit this" in joined


def test_many_more_states_than_the_no_tax_nine_cost_nothing():
    """
    24 states cost a member nothing on MILITARY income -- the nine with no
    income tax plus fifteen that exempt both active duty and retired pay.
    """
    ranked = D.rank_states(60_000, 87_000, 20, 30)
    free = [r for r in ranked if r["Military income tax"] == 0]
    assert len(free) > 20
    names = {r["State"] for r in free}
    assert {"Texas", "Florida", "Michigan", "New York", "Pennsylvania"} <= names


def test_ranking_is_sorted_and_covers_every_state():
    ranked = D.rank_states(60_000, 87_000, 20, 30)
    assert ranked[0]["Lifetime"] <= ranked[-1]["Lifetime"]
    assert len(ranked) == len(D.STATE_NAMES)


def test_spouse_income_separates_states_that_look_identical():
    """
    On military pay alone, Texas and Michigan tie at zero. Add a spouse's
    salary and they do not -- Michigan taxes it, Texas does not.
    """
    ranked = {r["State"]: r for r in
              D.rank_states(60_000, 87_000, 20, 30,
                            spouse_income=55_000, spouse_years=20)}
    assert ranked["Texas"]["Lifetime"] == 0
    assert ranked["Michigan"]["Lifetime"] > 0
    assert ranked["Michigan"]["Military income tax"] == 0


def test_ties_break_toward_states_with_no_income_tax_at_all():
    ranked = D.rank_states(60_000, 87_000, 20, 30)
    zero = [r for r in ranked if r["Lifetime"] == 0]
    first_taxing = next(i for i, r in enumerate(zero)
                        if not r["No income tax at all"])
    last_no_tax = max(i for i, r in enumerate(zero) if r["No income tax at all"])
    assert last_no_tax < first_taxing


def test_exempt_but_taxing_states_are_identifiable():
    states = D.exempt_but_taxing_states()
    assert "Michigan" in states and "Pennsylvania" in states
    assert "Texas" not in states and "Florida" not in states


def test_comparing_a_no_tax_state_to_an_exempt_one_flags_the_difference():
    c = D.compare_states("Texas", "Michigan", 60_000, 87_000, 20, 30)
    joined = " ".join(c.notes)
    assert "not a no-income-tax state" in joined
    assert "spouse" in joined


def test_ranking_covers_every_state():
    assert len(D.rank_states(60_000, 87_000, 20, 30)) == len(D.STATE_NAMES)


def test_the_spouse_election_is_described_as_annual_and_three_way():
    note = D.spouse_residency_note("Texas", "Virginia", "North Carolina")
    assert "each tax year" in note
    assert "Texas" in note and "Virginia" in note and "North Carolina" in note
    assert "re-electable every year" in note


def test_the_spouse_note_distinguishes_vaeia_from_the_older_msrra():
    note = D.spouse_residency_note("Texas", "Virginia", "Texas")
    assert "not the old Military Spouses Residency Relief Act" in note


def test_domicile_acts_list_is_concrete():
    assert any("DD Form 2058" in a for a in D.DOMICILE_ACTS)
    assert any("Voter registration" in a for a in D.DOMICILE_ACTS)


# ==========================================================================
# GI Bill
# ==========================================================================

def test_no_housing_allowance_while_on_active_duty():
    """The reason using it in service is usually the wrong call."""
    v = GI.value_benefit(GI.SCHOOL_PUBLIC_IN_STATE, 12_000, 2_400,
                         on_active_duty=True)
    assert v.housing == 0
    assert v.tuition_covered > 0
    assert any("No housing allowance" in n for n in v.notes)


def test_transferring_beats_using_it_in_service_because_of_housing():
    mine = GI.value_benefit(GI.SCHOOL_PUBLIC_IN_STATE, 12_000, 2_400,
                            on_active_duty=True)
    kid = GI.value_benefit(GI.SCHOOL_PUBLIC_IN_STATE, 12_000, 2_400,
                           on_active_duty=False)
    assert kid.total > mine.total
    assert kid.total - mine.total == pytest.approx(kid.housing)


def test_housing_follows_the_school_zip_not_the_member():
    cheap = GI.value_benefit(GI.SCHOOL_PUBLIC_IN_STATE, 12_000, 1_500)
    dear = GI.value_benefit(GI.SCHOOL_PUBLIC_IN_STATE, 12_000, 3_500)
    assert dear.total > cheap.total
    assert any("SCHOOL's" in n for n in dear.notes)


def test_online_study_pays_half_the_national_average():
    v = GI.value_benefit(GI.SCHOOL_ONLINE, 8_000, 3_500,
                         national_average_bah=2_100)
    assert v.monthly_housing == pytest.approx(1_050)
    assert any("single in-person class" in n for n in v.notes)


def test_a_public_in_state_school_has_no_tuition_cap():
    v = GI.value_benefit(GI.SCHOOL_PUBLIC_IN_STATE, 40_000, 2_000)
    assert v.tuition_shortfall == 0
    assert not v.yellow_ribbon_needed


def test_an_expensive_private_school_needs_yellow_ribbon():
    v = GI.value_benefit(GI.SCHOOL_PRIVATE, 62_000, 3_200)
    assert v.yellow_ribbon_needed
    assert v.tuition_shortfall > 0
    assert any("Yellow Ribbon" in n for n in v.notes)


def test_thirty_six_months_is_four_academic_years():
    v = GI.value_benefit(GI.SCHOOL_PUBLIC_IN_STATE, 10_000, 2_000)
    assert v.academic_years == pytest.approx(4.0)


# ==========================================================================
# The transfer decision
# ==========================================================================

def mine() -> GI.BenefitValue:
    return GI.value_benefit(GI.SCHOOL_PUBLIC_IN_STATE, 12_000, 2_400,
                            on_active_duty=True)


def kid() -> GI.BenefitValue:
    return GI.value_benefit(GI.SCHOOL_PUBLIC_IN_STATE, 12_000, 2_400)


def test_transfer_needs_six_years_of_service():
    a = GI.analyse_transfer(4, mine(), kid())
    assert not a.eligible_to_transfer
    assert a.recommendation == "Not yet eligible"


def test_transfer_cannot_be_started_after_separation():
    a = GI.analyse_transfer(12, mine(), kid(), still_serving=False)
    assert a.recommendation == "Too late to transfer"
    joined = " ".join(a.reasoning)
    assert "cannot be initiated after separation" in joined
    assert "submit the request now" in joined


def test_the_four_year_obligation_is_priced_as_a_real_cost():
    a = GI.analyse_transfer(12, mine(), kid())
    assert a.total_service_required == 16
    joined = " ".join(a.reasoning)
    assert "it is not free" in joined
    assert "removes your option to separate" in joined


def test_a_member_with_a_degree_is_told_to_transfer():
    a = GI.analyse_transfer(12, mine(), kid(), already_has_degree=True)
    assert a.recommendation == "Transfer"
    assert "already have the degree" in " ".join(a.reasoning)


def test_the_child_deadline_is_stated_with_years_remaining():
    a = GI.analyse_transfer(12, mine(), kid(), child_age=14)
    joined = " ".join(a.reasoning)
    assert "before turning 26" in joined
    assert "12 years from now" in joined
    assert "spouse has no such deadline" in joined


def test_a_close_call_defers_to_the_obligation_not_the_arithmetic():
    same = GI.value_benefit(GI.SCHOOL_PUBLIC_IN_STATE, 12_000, 2_400)
    a = GI.analyse_transfer(12, same, same)
    assert a.recommendation == "Close — decide on the obligation"


def test_the_benefit_is_framed_as_a_balance_sheet_asset():
    joined = " ".join(GI.analyse_transfer(12, mine(), kid()).reasoning)
    assert "capital allocation decision" in joined
    assert "529 contributions" in joined
