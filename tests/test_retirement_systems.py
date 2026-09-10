import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

from engine.retirement import systems as S

H3 = 11_193.75      # a retiring O-5's high-three average


# ==========================================================================
# Multipliers
# ==========================================================================

def test_legacy_multiplier_is_two_and_a_half_percent_a_year():
    assert S.multiplier(S.SYS_HIGH3, 20) == pytest.approx(0.50)
    assert S.multiplier(S.SYS_HIGH3, 26) == pytest.approx(0.65)
    assert S.multiplier(S.SYS_FINAL_PAY, 30) == pytest.approx(0.75)


def test_brs_multiplier_is_two_percent_a_year():
    assert S.multiplier(S.SYS_BRS, 20) == pytest.approx(0.40)
    assert S.multiplier(S.SYS_BRS, 30) == pytest.approx(0.60)


def test_redux_costs_one_point_for_every_year_under_thirty():
    assert S.multiplier(S.SYS_REDUX, 20) == pytest.approx(0.40)
    assert S.multiplier(S.SYS_REDUX, 26) == pytest.approx(0.61)
    # At 30 years REDUX converges with High-3.
    assert S.multiplier(S.SYS_REDUX, 30) == pytest.approx(
        S.multiplier(S.SYS_HIGH3, 30))


def test_the_multiplier_is_capped_at_seventy_five_percent():
    assert S.multiplier(S.SYS_HIGH3, 40) == pytest.approx(0.75)


# ==========================================================================
# Retired pay
# ==========================================================================

def test_redux_pays_less_than_high_three_at_twenty():
    high3 = S.retired_pay(S.SYS_HIGH3, 20, H3)
    redux = S.retired_pay(S.SYS_REDUX, 20, H3)
    assert redux.monthly < high3.monthly
    assert redux.monthly / high3.monthly == pytest.approx(0.8, rel=0.01)


def test_only_redux_loses_purchasing_power():
    assert S.retired_pay(S.SYS_REDUX, 20, H3).real_cola_drift < 0
    for s in (S.SYS_HIGH3, S.SYS_BRS, S.SYS_FINAL_PAY):
        assert S.retired_pay(s, 20, H3).real_cola_drift == 0


def test_the_redux_note_explains_the_age_62_recomputation():
    note = S.retired_pay(S.SYS_REDUX, 20, H3).note
    assert "CPI minus one percent" in note
    assert "62" in note


def test_the_brs_note_refuses_to_judge_the_multiplier_alone():
    note = S.retired_pay(S.SYS_BRS, 20, H3).note
    assert "TSP match" in note
    assert "never on the multiplier alone" in note


def test_under_twenty_years_the_legacy_pension_is_zero():
    for s in (S.SYS_HIGH3, S.SYS_REDUX, S.SYS_FINAL_PAY):
        pay = S.retired_pay(s, 19.9, H3)
        assert pay.monthly == 0
        assert "no pension at all" in pay.note


# ==========================================================================
# The 20-year cliff
# ==========================================================================

def test_the_cliff_is_worth_a_large_number_near_twenty_years():
    c = S.value_of_reaching_twenty(S.SYS_HIGH3, 18.0, H3, retirement_age=42)
    assert c.years_remaining == pytest.approx(2.0)
    assert c.present_value > 1_000_000
    assert c.value_per_remaining_year > 400_000


def test_the_legacy_cliff_note_says_there_is_no_partial_credit():
    c = S.value_of_reaching_twenty(S.SYS_HIGH3, 18.0, H3, retirement_age=42)
    assert "no partial credit" in c.note
    assert "19 years and 11 months" in c.note


def test_the_brs_cliff_is_softer_and_says_why():
    c = S.value_of_reaching_twenty(S.SYS_BRS, 18.0, H3, retirement_age=42,
                                   tsp_balance=250_000)
    assert "keep your TSP balance" in c.note
    assert "85%" in c.note


def test_past_twenty_years_the_cliff_is_behind_you():
    c = S.value_of_reaching_twenty(S.SYS_HIGH3, 22.0, H3, retirement_age=46)
    assert c.years_remaining == 0
    assert "already retirement-eligible" in c.note


def test_the_cliff_is_worth_less_the_older_you_retire():
    young = S.value_of_reaching_twenty(S.SYS_HIGH3, 18.0, H3, retirement_age=40)
    old = S.value_of_reaching_twenty(S.SYS_HIGH3, 18.0, H3, retirement_age=55)
    assert young.present_value > old.present_value


# ==========================================================================
# The BRS lump-sum election
# ==========================================================================

def brs_annual() -> float:
    return S.retired_pay(S.SYS_BRS, 20, H3).annual


def test_the_lump_sum_requires_an_implausible_return_to_break_even():
    """The number that settles the argument."""
    l = S.brs_lump_sum(brs_annual(), retirement_age=42, share=0.50)
    assert l.breakeven_real_return > 0.08
    assert l.verdict == "Almost certainly a bad trade"


def test_taking_half_gives_up_more_than_taking_a_quarter():
    half = S.brs_lump_sum(brs_annual(), 42, share=0.50)
    quarter = S.brs_lump_sum(brs_annual(), 42, share=0.25)
    assert half.lump_sum_gross > quarter.lump_sum_gross
    assert half.total_annuity_given_up > quarter.total_annuity_given_up


def test_the_lump_sum_is_reduced_by_a_single_year_of_tax():
    l = S.brs_lump_sum(brs_annual(), 42, share=0.50, marginal_tax_rate=0.32)
    assert l.lump_sum_after_tax == pytest.approx(l.lump_sum_gross * 0.68)


def test_a_higher_tax_rate_worsens_the_breakeven():
    low = S.brs_lump_sum(brs_annual(), 42, marginal_tax_rate=0.12)
    high = S.brs_lump_sum(brs_annual(), 42, marginal_tax_rate=0.37)
    assert high.breakeven_real_return > low.breakeven_real_return


def test_payments_given_up_exceed_the_gross_lump_sum():
    """This is the trade in one line."""
    l = S.brs_lump_sum(brs_annual(), 42, share=0.50)
    assert l.total_annuity_given_up > l.lump_sum_gross


def test_the_reasoning_names_the_discount_rate_problem():
    l = S.brs_lump_sum(brs_annual(), 42)
    joined = " ".join(l.reasoning)
    assert "safest asset you own" in joined
    assert "sequence risk" in joined


def test_the_reasoning_concedes_the_narrow_cases():
    """An analysis that only argues one way is not analysis."""
    joined = " ".join(S.brs_lump_sum(brs_annual(), 42).reasoning)
    assert "shortened life expectancy" in joined
    assert "not one of those cases" in joined


def test_retiring_at_full_retirement_age_makes_the_election_moot():
    l = S.brs_lump_sum(brs_annual(), retirement_age=67)
    assert l.verdict == "Not applicable"


def test_the_breakeven_solver_is_consistent_with_the_annuity_math():
    from engine.networth.balance_sheet import annuity_present_value
    l = S.brs_lump_sum(brs_annual(), 42, share=0.50)
    pv_at_breakeven = annuity_present_value(
        brs_annual() * 0.50, l.years_reduced, l.breakeven_real_return)
    assert pv_at_breakeven == pytest.approx(l.lump_sum_after_tax, rel=0.02)


# ==========================================================================
# Comparing systems
# ==========================================================================

def test_all_four_systems_are_compared():
    rows = S.compare_systems(20, H3, retirement_age=42)
    assert {r["System"] for r in rows} == {
        S.SYS_FINAL_PAY, S.SYS_HIGH3, S.SYS_REDUX, S.SYS_BRS}


def test_redux_present_value_is_penalised_for_its_reduced_cola():
    rows = {r["System"]: r for r in S.compare_systems(20, H3, retirement_age=42)}
    # Same multiplier as BRS at 20 years, but worth less because of CPI-1%.
    assert rows[S.SYS_REDUX]["Multiplier"] == pytest.approx(
        rows[S.SYS_BRS]["Multiplier"])
    assert (rows[S.SYS_REDUX]["Pension present value"]
            < rows[S.SYS_BRS]["Pension present value"])


def test_the_csb_bonus_is_counted_in_the_redux_total():
    rows = {r["System"]: r for r in S.compare_systems(20, H3, retirement_age=42)}
    assert rows[S.SYS_REDUX].get("CSB bonus") == S.CSB_BONUS


def test_brs_total_includes_the_tsp_the_match_built():
    rows = {r["System"]: r for r in
            S.compare_systems(20, H3, retirement_age=42, tsp_balance_brs=300_000)}
    assert rows[S.SYS_BRS]["Total"] > rows[S.SYS_BRS]["Pension present value"]
