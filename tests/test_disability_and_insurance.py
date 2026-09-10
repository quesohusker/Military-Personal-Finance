import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

from engine.benefits import disability_separation as DS
from engine.benefits import life_insurance as LI


# ==========================================================================
# Which side of the cliff you land on
# ==========================================================================

def test_thirty_percent_qualifies_for_retirement_at_any_length_of_service():
    o = DS.evaluate(30, 4.0, 4_110.0)
    assert o.outcome == DS.OUTCOME_RETIREMENT
    assert o.keeps_tricare
    assert o.retired_pay_monthly > 0


def test_twenty_years_qualifies_regardless_of_rating():
    """Length of service is the other door into Chapter 61 retirement."""
    o = DS.evaluate(10, 20.0, 4_110.0)
    assert o.outcome == DS.OUTCOME_RETIREMENT


def test_under_thirty_percent_and_under_twenty_years_is_severance():
    o = DS.evaluate(20, 8.0, 4_110.0)
    assert o.outcome == DS.OUTCOME_SEVERANCE
    assert not o.keeps_tricare
    assert o.retired_pay_monthly == 0


def test_ten_points_of_rating_decides_everything():
    """
    The 20-to-30 step is the steepest cliff in military compensation. Same
    member, same service, one rating band apart.
    """
    low = DS.evaluate(20, 8.0, 4_110.0, age_at_separation=30)
    high = DS.evaluate(30, 8.0, 4_110.0, age_at_separation=30)
    assert low.outcome == DS.OUTCOME_SEVERANCE
    assert high.outcome == DS.OUTCOME_RETIREMENT
    assert high.lifetime_present_value > low.severance_gross * 4


# ==========================================================================
# Severance arithmetic
# ==========================================================================

def test_severance_is_two_times_monthly_pay_times_years():
    o = DS.evaluate(20, 8.0, 4_110.0, marginal_tax_rate=0.0)
    assert o.severance_years_credited == 8.0
    assert o.severance_gross == pytest.approx(2 * 4_110.0 * 8.0)


def test_severance_has_a_three_year_floor():
    o = DS.evaluate(10, 1.5, 4_000.0)
    assert o.severance_years_credited == DS.SEVERANCE_MIN_YEARS


def test_combat_related_severance_has_a_six_year_floor():
    o = DS.evaluate(10, 2.0, 4_000.0, combat_related=True)
    assert o.severance_years_credited == DS.SEVERANCE_MIN_YEARS_COMBAT


def test_severance_credit_is_capped_at_nineteen_years():
    """Nobody under 20 years can credit 20, and 20+ years is not this path."""
    o = DS.evaluate(10, 19.9, 4_000.0)
    assert o.severance_years_credited == DS.SEVERANCE_MAX_YEARS


def test_combat_zone_injury_makes_the_severance_tax_free():
    taxed = DS.evaluate(20, 8.0, 4_110.0, marginal_tax_rate=0.22)
    free = DS.evaluate(20, 8.0, 4_110.0, marginal_tax_rate=0.22,
                       incurred_in_combat_zone=True)
    assert free.severance_after_tax == free.severance_gross
    assert taxed.severance_after_tax < taxed.severance_gross


# ==========================================================================
# Recoupment -- the surprise that wrecks separation budgets
# ==========================================================================

def test_va_withholds_until_the_severance_is_recovered():
    o = DS.evaluate(20, 8.0, 4_110.0, va_monthly_compensation=1_400.0)
    assert o.severance_recouped
    assert o.months_of_va_withheld == pytest.approx(o.severance_gross / 1_400.0)
    assert o.months_of_va_withheld > 40


def test_combat_related_severance_is_not_recouped():
    o = DS.evaluate(20, 8.0, 4_110.0, combat_related=True,
                    va_monthly_compensation=1_400.0)
    assert not o.severance_recouped
    assert o.months_of_va_withheld == 0


def test_recoupment_warning_names_the_months():
    o = DS.evaluate(20, 8.0, 4_110.0, va_monthly_compensation=1_400.0)
    assert any("recoup" in n.lower() and "months" in n for n in o.notes)


# ==========================================================================
# Retired pay multiplier
# ==========================================================================

def test_the_greater_of_rating_and_length_of_service_is_used():
    short = DS.evaluate(70, 4.0, 5_000.0)      # 70% beats 10% length
    assert short.multiplier_used == pytest.approx(0.70)

    long = DS.evaluate(30, 24.0, 5_000.0)      # 60% length beats 30% rating
    assert long.multiplier_used == pytest.approx(0.60)


def test_the_multiplier_is_capped_at_seventy_five_percent():
    o = DS.evaluate(100, 10.0, 5_000.0)
    assert o.multiplier_used == pytest.approx(DS.MAX_RETIRED_PAY_MULTIPLIER)


def test_brs_length_of_service_multiplier_is_two_percent_a_year():
    brs = DS.evaluate(10, 30.0, 5_000.0, is_brs=True)
    legacy = DS.evaluate(10, 30.0, 5_000.0, is_brs=False)
    assert brs.multiplier_used == pytest.approx(0.60)
    assert legacy.multiplier_used == pytest.approx(DS.MAX_RETIRED_PAY_MULTIPLIER)


def test_tdrl_pays_now_but_is_not_settled_income():
    o = DS.evaluate(50, 6.0, 4_500.0, on_tdrl=True)
    assert o.outcome == DS.OUTCOME_TDRL
    assert o.retired_pay_monthly > 0
    assert any("re-evaluated" in n for n in o.notes)


# ==========================================================================
# Sizing the cliff
# ==========================================================================

def test_compare_paths_sizes_the_gap_for_a_severance_case():
    r = DS.compare_paths(20, 8.0, 4_110.0, age_at_separation=30,
                         va_monthly_compensation=1_400.0)
    assert r["alternative"] is not None
    assert r["gap"] > 300_000


def test_compare_paths_returns_no_gap_when_already_retired():
    r = DS.compare_paths(50, 8.0, 4_110.0)
    assert r["alternative"] is None
    assert r["gap"] == 0


def test_findings_flag_severance_as_bad_and_retirement_as_good():
    sev = DS.findings(DS.evaluate(20, 8.0, 4_110.0))
    ret = DS.findings(DS.evaluate(50, 8.0, 4_110.0))
    assert sev[0][0] == "bad"
    assert ret[0][0] == "good"


def test_findings_always_explain_that_dod_and_va_rate_independently():
    for rating in (10, 30, 80):
        texts = " ".join(h + d for _, h, d in DS.findings(DS.evaluate(rating, 8.0, 4_110.0)))
        assert "independently" in texts


# ==========================================================================
# SGLI / VGLI / term
# ==========================================================================

def test_sgli_costs_the_same_at_every_age():
    """This is what makes it such a bargain late in a career."""
    assert LI.sgli_monthly(500_000) == pytest.approx(26.0)


def test_sgli_coverage_is_capped_at_the_maximum():
    assert LI.sgli_monthly(900_000) == LI.sgli_monthly(LI.SGLI_MAX)


def test_vgli_premiums_escalate_hard_with_age():
    at_42 = LI.vgli_monthly(42, 500_000)
    at_70 = LI.vgli_monthly(70, 500_000)
    assert at_70 > at_42 * 10


def test_vgli_rate_bands_never_go_down():
    rates = [LI.vgli_monthly(a, 100_000) for a in range(20, 85)]
    assert rates == sorted(rates)


def test_term_is_cheaper_than_vgli_at_the_same_issue_age():
    assert LI.term_monthly(42, 500_000) < LI.vgli_monthly(42, 500_000)


def test_term_beats_vgli_by_a_wide_margin_over_a_full_period():
    c = LI.compare(500_000, separation_age=42, compare_to_age=70)
    assert c.saving > 70_000
    assert c.recommendation.startswith("Level term")


def test_an_uninsurable_member_should_take_vgli():
    c = LI.compare(500_000, 42, 70, insurable=False)
    assert c.recommendation == "Take VGLI"
    assert any("guaranteed acceptance" in r for r in c.reasoning)


def test_the_ordering_trap_is_stated_for_insurable_members():
    """Approved for term BEFORE separating, while the VGLI window is open."""
    c = LI.compare(500_000, 42, 70)
    text = " ".join(c.reasoning)
    assert "240-day" in text
    assert "APPROVED" in text


def test_comparison_reports_the_term_expiry_age():
    c = LI.compare(400_000, 44, 70, term_years=20)
    assert c.term_expires_at_age == 64


def test_term_cost_stops_accruing_at_the_end_of_the_term():
    short = LI.compare(500_000, 42, 55, term_years=20)
    assert short.term_total == pytest.approx(short.term_monthly * 12 * 13)


def test_vgli_coverage_is_capped_at_five_hundred_thousand():
    c = LI.compare(1_000_000, 42, 70)
    assert c.coverage == LI.VGLI_MAX


# ==========================================================================
# Needs analysis
# ==========================================================================

def test_survivor_benefits_are_netted_off_the_need():
    with_sbp = LI.needs(80_000, 25, survivor_annual_income=45_000)
    without = LI.needs(80_000, 25)
    assert with_sbp.net_need < without.net_need
    assert with_sbp.survivor_income_offset > 0


def test_ignoring_survivor_income_overstates_the_need_substantially():
    """The military/civilian divergence this module exists to capture."""
    with_sbp = LI.needs(80_000, 25, survivor_annual_income=45_000)
    without = LI.needs(80_000, 25)
    assert without.net_need > with_sbp.net_need * 1.5


def test_existing_coverage_closes_the_gap():
    n = LI.needs(80_000, 25, survivor_annual_income=45_000,
                 current_coverage=5_000_000)
    assert n.gap == 0
    assert any("meets the need" in note for note in n.notes)


def test_gross_need_sums_its_components():
    n = LI.needs(50_000, 10, mortgage_balance=200_000, education_cost=150_000,
                 final_expenses=25_000)
    assert n.gross_need == pytest.approx(
        n.income_replacement + 200_000 + 150_000 + 25_000)


def test_the_need_shrinks_over_time_and_the_note_says_so():
    n = LI.needs(80_000, 25, mortgage_balance=300_000)
    assert n.gap > 0
    assert any("SHRINKS" in note for note in n.notes)


def test_liquid_assets_reduce_the_need():
    poor = LI.needs(60_000, 20)
    rich = LI.needs(60_000, 20, liquid_assets=500_000)
    assert rich.net_need == pytest.approx(max(0.0, poor.net_need - 500_000))
