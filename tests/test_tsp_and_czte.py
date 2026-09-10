"""
Tests for the TSP contribution engine and the Combat Zone Tax Exclusion.

These pin the mechanics that are most often stated wrongly in general military
finance advice: who gets a match, what the match is computed on, where service
money lands, and how the two TSP limits interact in a combat zone.
"""

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

from engine.retirement import tsp as T
from engine.tax import military as M

BASIC = 4110.0 * 12          # an E-5 at six years


# ==========================================================================
# The BRS match
# ==========================================================================

def test_no_match_exists_outside_brs():
    r = T.service_match(BASIC, 0.05, is_brs=False)
    assert not r.eligible
    assert r.total_service == 0
    assert "no TSP match" in r.note


def test_five_percent_captures_everything():
    r = T.service_match(BASIC, 0.05, is_brs=True)
    assert r.unclaimed == 0
    assert r.automatic == pytest.approx(BASIC * 0.01)
    assert r.matching == pytest.approx(BASIC * 0.04)
    assert r.total_service == pytest.approx(BASIC * 0.05)


def test_contributing_above_five_percent_earns_nothing_extra():
    at_five = T.service_match(BASIC, 0.05, is_brs=True)
    at_twenty = T.service_match(BASIC, 0.20, is_brs=True)
    assert at_twenty.total_service == pytest.approx(at_five.total_service)
    assert "no additional service money" in at_twenty.note


def test_the_match_schedule_is_full_then_half():
    """100% on the first 3%, then 50% on the next 2%."""
    at_three = T.service_match(BASIC, 0.03, is_brs=True)
    assert at_three.matching == pytest.approx(BASIC * 0.03)

    at_four = T.service_match(BASIC, 0.04, is_brs=True)
    assert at_four.matching == pytest.approx(BASIC * 0.035)


def test_contributing_nothing_still_gets_the_automatic_one_percent():
    r = T.service_match(BASIC, 0.0, is_brs=True)
    assert r.automatic == pytest.approx(BASIC * 0.01)
    assert r.matching == 0
    assert r.unclaimed == pytest.approx(BASIC * 0.04)


def test_matching_has_not_begun_before_two_years():
    r = T.service_match(BASIC, 0.05, is_brs=True, years_of_service=1.0)
    assert r.matching == 0
    assert r.automatic > 0
    assert "Matching begins" in r.note


def test_only_the_automatic_contribution_has_a_vesting_cliff():
    early = T.service_match(BASIC, 0.05, is_brs=True, years_of_service=1.0)
    assert not early.vested_automatic
    assert "your own contributions and the matching" in early.note

    later = T.service_match(BASIC, 0.05, is_brs=True, years_of_service=3.0)
    assert later.vested_automatic


def test_the_unclaimed_amount_is_real_money():
    """A 3% contributor under BRS leaves 1% of basic pay behind every year."""
    r = T.service_match(BASIC, 0.03, is_brs=True)
    assert r.unclaimed == pytest.approx(BASIC * 0.01)
    assert "on the table" in r.note


# ==========================================================================
# Contribution limits
# ==========================================================================

def test_elective_limit_rises_at_fifty_and_again_at_sixty():
    L = T.TSPLimits()
    assert T.elective_limit(30, L) == L.elective_deferral
    assert T.elective_limit(52, L) == L.elective_deferral + L.catchup_50
    assert T.elective_limit(61, L) == L.elective_deferral + L.catchup_60_63
    assert T.elective_limit(61, L) > T.elective_limit(52, L)


def test_the_super_catchup_drops_back_at_sixty_four():
    L = T.TSPLimits()
    assert T.elective_limit(64, L) == L.elective_deferral + L.catchup_50


def test_high_earners_must_make_catchup_contributions_as_roth():
    L = T.TSPLimits()
    assert T.catchup_must_be_roth(200_000, L)
    assert not T.catchup_must_be_roth(90_000, L)


def test_the_forced_roth_catchup_is_surfaced_in_the_plan():
    p = T.plan_contributions(BASIC, age=55, is_brs=True, contribution_pct=0.10,
                             prior_year_wages=200_000)
    assert p.catchup_forced_roth
    assert any("must be Roth" in n for n in p.notes)


# ==========================================================================
# The combat zone overflow
# ==========================================================================

def test_combat_zone_raises_total_capacity_but_not_roth_capacity():
    """The mechanic most often misstated: Roth stays capped at the deferral limit."""
    normal = T.plan_contributions(BASIC, 28, True, 0.05, in_combat_zone=False)
    zone = T.plan_contributions(BASIC, 28, True, 0.05, in_combat_zone=True)

    assert zone.total_capacity > normal.total_capacity
    assert zone.roth_capacity == normal.roth_capacity == zone.elective_limit
    assert zone.taxexempt_overflow_capacity > 0


def test_the_overflow_is_the_gap_between_the_two_limits():
    p = T.plan_contributions(BASIC, 28, True, 0.05, in_combat_zone=True)
    expected = (p.annual_addition_limit - p.elective_limit
                - p.service_contributions)
    assert p.taxexempt_overflow_capacity == pytest.approx(expected)


def test_combat_zone_notes_give_the_order_of_operations():
    p = T.plan_contributions(BASIC, 28, True, 0.05, in_combat_zone=True)
    joined = " ".join(p.notes)
    assert "fill Roth TSP" in joined
    assert "TRADITIONAL" in joined
    assert "never taxed again" in joined


def test_combat_zone_notes_warn_about_the_rollover_complication():
    p = T.plan_contributions(BASIC, 28, True, 0.05, in_combat_zone=True)
    assert any("cannot be cleanly rolled" in n for n in p.notes)


def test_no_overflow_outside_a_combat_zone():
    p = T.plan_contributions(BASIC, 28, True, 0.05, in_combat_zone=False)
    assert p.taxexempt_overflow_capacity == 0
    assert p.total_capacity == p.elective_limit


# ==========================================================================
# Traditional vs Roth
# ==========================================================================

def test_a_combat_zone_always_argues_for_roth():
    rec, why = T.traditional_or_roth(0.24, 0.10, in_combat_zone=True)
    assert rec == "Roth"
    assert "never taxed at any point" in why


def test_a_low_bracket_argues_for_roth():
    assert T.traditional_or_roth(0.12, 0.30)[0] == "Roth"


def test_a_large_untaxed_share_argues_for_roth_even_at_22_percent():
    assert T.traditional_or_roth(0.22, 0.40)[0] == "Roth"


def test_a_high_bracket_with_little_untaxed_pay_argues_for_traditional():
    rec, why = T.traditional_or_roth(0.35, 0.05, expected_retirement_rate=0.22)
    assert rec == "Traditional"
    assert "deferring" in why


def test_a_close_call_recommends_splitting():
    assert T.traditional_or_roth(0.24, 0.10, expected_retirement_rate=0.22)[0] == "Split"


# ==========================================================================
# The compensation split
# ==========================================================================

def make_split() -> M.CompensationSplit:
    return M.CompensationSplit(basic_pay=BASIC, bah=1806 * 12, bas=476.95 * 12)


def test_allowances_never_enter_taxable_income():
    s = make_split()
    assert s.taxable_before_czte == pytest.approx(BASIC)
    assert s.allowances > 0
    assert s.gross > s.federal_taxable


def test_the_untaxed_share_is_substantial():
    s = make_split()
    assert 0.25 < s.nontaxable_share < 0.45


def test_the_note_frames_it_against_a_civilian():
    note = M.effective_tax_rate_note(make_split())
    assert "A civilian earning" in note
    assert "Roth the default" in note
    assert "lender" in note


# ==========================================================================
# CZTE
# ==========================================================================

def test_enlisted_and_warrant_officers_have_no_cap():
    for grade in ("E-1", "E-5", "E-9", "W-1", "W-5"):
        amount, note = M.czte_monthly_exclusion(grade, 20_000.0)
        assert amount == 20_000.0, grade
        assert "no cap" in note


def test_commissioned_officers_are_capped():
    amount, note = M.czte_monthly_exclusion("O-5", 12_394.80)
    assert amount == pytest.approx(M.CZTE_OFFICER_MONTHLY_CAP_2026)
    assert amount < 12_394.80
    assert "capped" in note


def test_an_officer_below_the_cap_excludes_everything():
    amount, note = M.czte_monthly_exclusion("O-2", 6_617.70)
    assert amount == pytest.approx(6_617.70)
    assert "Below the" in note


def test_prior_enlisted_officers_are_capped_like_other_officers():
    """O-3E is a commissioned officer, not a warrant officer."""
    amount, _ = M.czte_monthly_exclusion("O-3E", 20_000.0)
    assert amount == pytest.approx(M.CZTE_OFFICER_MONTHLY_CAP_2026)


def test_partial_year_exclusion_scales_with_months():
    seven = M.analyse_czte(make_split(), "E-5", 7)
    twelve = M.analyse_czte(make_split(), "E-5", 12)
    assert 0 < seven.excluded < twelve.excluded


def test_a_full_year_in_the_zone_excludes_all_enlisted_pay():
    a = M.analyse_czte(make_split(), "E-5", 12)
    assert a.taxable_with == pytest.approx(0.0, abs=1.0)


def test_exclusion_never_exceeds_taxable_pay():
    a = M.analyse_czte(make_split(), "E-5", 12)
    assert a.excluded <= a.taxable_without + 0.01


def test_months_are_clamped_to_a_year():
    a = M.analyse_czte(make_split(), "E-5", 99)
    assert a.months == 12


def test_no_months_in_zone_changes_nothing():
    a = M.analyse_czte(make_split(), "E-5", 0)
    assert a.excluded == 0
    assert a.taxable_with == a.taxable_without
    assert a.opportunities == []


def test_czte_pay_still_counts_for_social_security():
    """Excluded from income tax, NOT from FICA. The earnings record still builds."""
    s = make_split()
    M.apply_czte(s, "E-5", 12)
    assert s.federal_taxable == pytest.approx(0.0, abs=1.0)
    assert s.fica_wages == pytest.approx(BASIC)


def test_the_opportunity_list_leads_with_sdp_then_roth():
    a = M.analyse_czte(make_split(), "E-5", 6)
    titles = [t for t, _ in a.opportunities]
    assert "Savings Deposit Program" in titles[0]
    assert "Roth" in titles[1]
    assert any("Convert old traditional" in t for t in titles)
    assert any("reenlistment" in t for t in titles)


def test_the_vesting_note_reaches_the_member_who_needs_it():
    """
    Under two years of service is exactly when someone worries about forfeiting
    their TSP on separation. The reassurance must survive the early return for
    members whose matching has not yet begun.
    """
    for yos in (0.5, 1.0, 1.9):
        note = T.service_match(BASIC, 0.05, is_brs=True, years_of_service=yos).note
        assert "vests at" in note, yos
        assert "yours immediately" in note, yos
        assert "keep them" in note, yos
