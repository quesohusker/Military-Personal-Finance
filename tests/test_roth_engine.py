"""
Tests for the projection engine.

These check arithmetic against hand-computable answers and enforce invariants
that must hold in every projection. A financial model that runs without
crashing is not the same as one that is right.
"""

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import copy
import pytest

from engine.tax import tables as T
from engine.tax import federal as TX
from engine.tax import state as ST
from engine.roth_profile import Profile, Person, ConversionPlan
from engine.retirement.projection import (run_projection, ss_claim_factor,
                               uniform_lifetime_divisor, military_pay_real)
from engine.retirement.roth_analysis import compare
from engine.retirement.montecarlo import run_monte_carlo


# ==========================================================================
# Federal bracket arithmetic
# ==========================================================================

def test_bracket_tax_matches_hand_calculation():
    b = T.FEDERAL_BRACKETS_2026[T.MFJ]
    # $100,000 taxable, MFJ: 10% on the first 24,800, 12% on the rest.
    expected = 24_800 * 0.10 + (100_000 - 24_800) * 0.12
    assert TX.bracket_tax(100_000, b) == pytest.approx(expected)


def test_bracket_tax_zero_and_negative():
    b = T.FEDERAL_BRACKETS_2026[T.MFJ]
    assert TX.bracket_tax(0, b) == 0.0
    assert TX.bracket_tax(-5_000, b) == 0.0


def test_bracket_tax_is_monotonic():
    b = T.FEDERAL_BRACKETS_2026[T.SINGLE]
    prev = -1.0
    for income in range(0, 900_000, 7_000):
        t = TX.bracket_tax(income, b)
        assert t >= prev
        prev = t


def test_marginal_rate_at_boundaries():
    b = T.FEDERAL_BRACKETS_2026[T.MFJ]
    assert TX.marginal_rate(24_800, b) == 0.10       # at the boundary, still 10%
    assert TX.marginal_rate(24_801, b) == 0.12
    assert TX.marginal_rate(10_000_000, b) == 0.37


def test_bracket_headroom():
    b = T.FEDERAL_BRACKETS_2026[T.MFJ]
    # Top of the 22% band is 211,100.
    assert TX.bracket_headroom(150_000, b, 0.22) == pytest.approx(61_100)
    assert TX.bracket_headroom(250_000, b, 0.22) == 0.0
    assert TX.bracket_headroom(0, b, 0.37) == float("inf")


# ==========================================================================
# Social Security taxation
# ==========================================================================

def test_ss_untaxed_below_first_threshold():
    # 20k SS, 10k other -> provisional 20k, below the 32k joint threshold.
    assert TX.taxable_social_security(20_000, 10_000, 0, T.MFJ) == 0.0


def test_ss_caps_at_85_percent():
    got = TX.taxable_social_security(40_000, 300_000, 0, T.MFJ)
    assert got == pytest.approx(0.85 * 40_000)


def test_ss_middle_tier_is_half_the_excess():
    # SS 20k, other 30k -> provisional 40k, between 32k and 44k.
    got = TX.taxable_social_security(20_000, 30_000, 0, T.MFJ)
    assert got == pytest.approx(min(0.5 * (40_000 - 32_000), 0.5 * 20_000))


def test_ss_thresholds_erode_with_the_deflator():
    """Unindexed thresholds must bite harder as the deflator shrinks them."""
    now = TX.taxable_social_security(40_000, 40_000, 0, T.MFJ, deflator=1.0)
    later = TX.taxable_social_security(40_000, 40_000, 0, T.MFJ, deflator=0.5)
    assert later > now


def test_ss_zero_benefit():
    assert TX.taxable_social_security(0, 200_000, 0, T.MFJ) == 0.0


# ==========================================================================
# Capital gains stacking
# ==========================================================================

def test_gains_stack_on_top_of_ordinary_income():
    b = T.LTCG_BRACKETS_2026[T.MFJ]
    # With no ordinary income, 50k of gains sits inside the 0% band (to 98,900).
    assert TX.capital_gains_tax(0, 50_000, b) == 0.0
    # Pushed above the 0% band by ordinary income, the same gains are taxed.
    assert TX.capital_gains_tax(150_000, 50_000, b) == pytest.approx(50_000 * 0.15)


def test_gains_split_across_two_bands():
    b = T.LTCG_BRACKETS_2026[T.MFJ]
    # Ordinary 88,900 leaves 10,000 of the 0% band, then 15% applies.
    got = TX.capital_gains_tax(88_900, 30_000, b)
    assert got == pytest.approx(20_000 * 0.15)


# ==========================================================================
# IRMAA
# ==========================================================================

def test_irmaa_is_zero_below_the_first_threshold():
    assert TX.irmaa_annual(100_000, T.MFJ, 2, count_base_premium=False) == 0.0


def test_irmaa_is_a_cliff():
    """One dollar over a threshold costs a full year of surcharge."""
    under = TX.irmaa_annual(218_000, T.MFJ, 2, count_base_premium=False)
    over = TX.irmaa_annual(218_001, T.MFJ, 2, count_base_premium=False)
    assert under == 0.0
    assert over > 1_000


def test_irmaa_scales_with_enrolled_people():
    one = TX.irmaa_annual(300_000, T.MFJ, 1)
    two = TX.irmaa_annual(300_000, T.MFJ, 2)
    assert two == pytest.approx(2 * one)


# ==========================================================================
# Social Security claiming
# ==========================================================================

def test_claim_at_fra_is_exactly_pia():
    assert ss_claim_factor(1975, 67) == pytest.approx(1.0)


def test_claim_at_62_cuts_thirty_percent_for_fra_67():
    # 60 months early: 36 at 5/9 of 1%, then 24 at 5/12 of 1% = 30%.
    assert ss_claim_factor(1975, 62) == pytest.approx(0.70, abs=1e-6)


def test_claim_at_70_adds_24_percent_for_fra_67():
    assert ss_claim_factor(1975, 70) == pytest.approx(1.24, abs=1e-6)


def test_fra_varies_by_birth_year():
    assert T.full_retirement_age(1954) == 66.0
    assert T.full_retirement_age(1960) == 67.0
    assert T.full_retirement_age(1957) == pytest.approx(66 + 6 / 12)


# ==========================================================================
# RMDs
# ==========================================================================

def test_rmd_age_follows_secure_2_0():
    assert T.rmd_age_for_birth_year(1949) == 72
    assert T.rmd_age_for_birth_year(1955) == 73
    assert T.rmd_age_for_birth_year(1960) == 75
    assert T.rmd_age_for_birth_year(1975) == 75


def test_uniform_lifetime_divisor_shrinks_with_age():
    ages = sorted(T.UNIFORM_LIFETIME_TABLE)
    for a, b in zip(ages, ages[1:]):
        assert uniform_lifetime_divisor(a) > uniform_lifetime_divisor(b)


def test_divisor_clamps_outside_the_table():
    assert uniform_lifetime_divisor(50) == uniform_lifetime_divisor(min(T.UNIFORM_LIFETIME_TABLE))
    assert uniform_lifetime_divisor(130) == uniform_lifetime_divisor(max(T.UNIFORM_LIFETIME_TABLE))


# ==========================================================================
# Military retired pay
# ==========================================================================

def test_full_cola_holds_real_value():
    from engine.roth_profile import MilitaryRetirement, SYS_HIGH3
    m = MilitaryRetirement(system=SYS_HIGH3, retired_pay_monthly=7_000,
                           retirement_year=2025, cola_real_drift=0.0)
    assert military_pay_real(m, 2045, 70) == pytest.approx(84_000)


def test_redux_drift_erodes_real_value_then_restores_at_62():
    from engine.roth_profile import MilitaryRetirement, SYS_REDUX
    m = MilitaryRetirement(system=SYS_REDUX, retired_pay_monthly=7_000,
                           retirement_year=2025, cola_real_drift=-0.01,
                           redux_recompute_age=62, redux_catchup_applies=True)
    before = military_pay_real(m, 2050, 61)
    at_62 = military_pay_real(m, 2051, 62)
    assert before < 84_000            # eroded by CPI-minus-1
    assert at_62 == pytest.approx(84_000)   # restored at the recomputation


# ==========================================================================
# State tax
# ==========================================================================

def test_no_tax_state_returns_zero():
    assert ST.state_tax(ST.get_rule("Texas"), 60, 90_000, 40_000, 20_000,
                        50_000, 0) == 0.0


def test_military_exemption_removes_pension_from_the_base():
    mi = ST.get_rule("Michigan")
    assert mi.military_pension_exempt == 1.0
    only_pension = ST.state_tax(mi, 50, 90_000, 0, 0, 0, 0)
    assert only_pension == 0.0


def test_california_taxes_military_pay():
    ca = ST.get_rule("California")
    assert ST.state_tax(ca, 50, 90_000, 0, 0, 0, 0) > 0


def test_retirement_exclusion_is_age_gated():
    mi = ST.get_rule("Michigan")
    young = ST.state_tax(mi, 50, 0, 0, 0, 60_000, 0)
    old = ST.state_tax(mi, 70, 0, 0, 0, 60_000, 0)
    assert young > 0
    assert old == 0.0


# ==========================================================================
# Tax policy scenarios
# ==========================================================================

def test_surcharge_raises_tax_only_after_the_change_year():
    pol = TX.TaxPolicy(scenario=TX.SCENARIO_SURCHARGE, change_year=2035,
                       surcharge_points=5.0)
    before = TX.regime_for_year(pol, 2034, T.MFJ, 0, 2)
    after = TX.regime_for_year(pol, 2035, T.MFJ, 0, 2)
    assert TX.bracket_tax(200_000, before.ordinary_brackets) < \
           TX.bracket_tax(200_000, after.ordinary_brackets)
    assert before.ordinary_brackets == T.FEDERAL_BRACKETS_2026[T.MFJ]


def test_pre_tcja_raises_tax_and_cuts_the_standard_deduction():
    pol = TX.TaxPolicy(scenario=TX.SCENARIO_PRE_TCJA, change_year=2030)
    now = TX.regime_for_year(TX.TaxPolicy(), 2030, T.MFJ, 0, 2)
    later = TX.regime_for_year(pol, 2030, T.MFJ, 0, 2)
    assert TX.bracket_tax(150_000, later.ordinary_brackets) > \
           TX.bracket_tax(150_000, now.ordinary_brackets)
    assert later.standard_deduction < now.standard_deduction
    assert later.personal_exemption > 0


def test_bracket_width_factor_narrows_bands():
    pol = TX.TaxPolicy(scenario=TX.SCENARIO_SURCHARGE, change_year=2030,
                       surcharge_points=0.0, bracket_width_factor=0.9)
    r = TX.regime_for_year(pol, 2030, T.MFJ, 0, 2)
    assert r.ordinary_brackets[0][0] == pytest.approx(24_800 * 0.9)


def test_real_bracket_drag_compounds():
    pol = TX.TaxPolicy(real_bracket_drag=0.01)
    r0 = TX.regime_for_year(pol, 2026, T.MFJ, 0, 2)
    r10 = TX.regime_for_year(pol, 2036, T.MFJ, 0, 2)
    assert r10.ordinary_brackets[0][0] == pytest.approx(
        r0.ordinary_brackets[0][0] * 0.99 ** 10)


# ==========================================================================
# Profile serialisation
# ==========================================================================

def test_profile_roundtrips_through_json():
    p = _demo_profile()
    assert Profile.from_json(p.to_json()).to_dict() == p.to_dict()


def test_profile_ignores_unknown_keys():
    """An old saved file must still load after the schema grows."""
    d = _demo_profile().to_dict()
    d["some_future_field"] = 42
    d["primary"]["removed_field"] = "x"
    loaded = Profile.from_dict(d)
    assert loaded.primary.birth_year == 1975


def test_profile_fills_defaults_for_missing_keys():
    loaded = Profile.from_dict({"profile_name": "sparse"})
    assert loaded.profile_name == "sparse"
    assert loaded.assumptions.inflation == 0.025


# ==========================================================================
# Projection invariants
# ==========================================================================

def _demo_profile() -> Profile:
    p = Profile(profile_name="Test", state="Michigan")
    p.primary = Person(birth_year=1975, annual_wages=95_000,
                       work_through_year=2040, ss_pia_monthly=3_100,
                       ss_claim_age=67, death_age=90,
                       traditional_balance=700_000, roth_balance=100_000)
    p.spouse = Person(birth_year=1977, annual_wages=45_000,
                      work_through_year=2040, ss_pia_monthly=1_500,
                      ss_claim_age=67, death_age=93,
                      traditional_balance=150_000, roth_balance=40_000)
    p.military.retired_pay_monthly = 7_280
    p.military.retirement_year = 2025
    p.military.va_disability_monthly = 4_000
    p.taxable.balance = 250_000
    p.taxable.cost_basis = 160_000
    p.taxable.cash_balance = 60_000
    p.assumptions.annual_spending = 130_000
    p.assumptions.spending_start_year = 2026
    p.conversion.start_year = 2041
    p.conversion.end_year = 2049
    p.conversion.target_bracket = 0.22
    return p


def test_balances_never_go_negative():
    p = _demo_profile()
    for convert in (False, True):
        r = run_projection(p, convert=convert)
        for row in r.rows:
            assert row.traditional_balance >= -1e-6, row.year
            assert row.roth_balance >= -1e-6, row.year
            assert row.taxable_balance >= -1e-6, row.year
            assert row.cash_balance >= -1e-6, row.year


def test_conversions_only_inside_the_window():
    p = _demo_profile()
    r = run_projection(p, convert=True)
    for row in r.rows:
        if row.conversion > 0:
            assert p.conversion.start_year <= row.year <= p.conversion.end_year


def test_no_conversions_when_disabled():
    p = _demo_profile()
    r = run_projection(p, convert=False)
    assert all(row.conversion == 0 for row in r.rows)
    assert r.lifetime_conversions == 0


def test_bracket_strategy_respects_its_ceiling():
    """The solver must not overshoot the target bracket."""
    p = _demo_profile()
    p.conversion.target_bracket = 0.22
    r = run_projection(p, convert=True)
    ceiling = max(b for b, rate in T.FEDERAL_BRACKETS_2026[T.MFJ]
                  if rate <= 0.22 and b != float("inf"))
    converted_years = [row for row in r.rows
                       if row.conversion > 0 and row.filing_status == T.MFJ]
    assert converted_years, "the fixture should produce conversions"
    for row in converted_years:
        # Ordinary taxable income is what the solver targets; preferential
        # income (dividends and gains) stacks above it and is excluded.
        ordinary_taxable = row.taxable_income - (row.realized_gains
                                                 + row.dividends)
        assert ordinary_taxable <= ceiling + 1.0, (row.year, ordinary_taxable)
        assert row.marginal_rate <= 0.22 + 1e-9, (row.year, row.marginal_rate)


def test_bracket_strategy_fills_the_bracket_it_is_given():
    """A higher target must convert strictly more."""
    low, high = copy.deepcopy(_demo_profile()), copy.deepcopy(_demo_profile())
    low.conversion.target_bracket = 0.12
    high.conversion.target_bracket = 0.24
    assert (run_projection(high, convert=True).lifetime_conversions >
            run_projection(low, convert=True).lifetime_conversions)


def test_annual_cap_is_binding():
    p = _demo_profile()
    p.conversion.annual_cap = 25_000
    r = run_projection(p, convert=True)
    for row in r.rows:
        assert row.conversion <= 25_000 + 1e-6, row.year


def test_conversion_never_exceeds_the_available_balance():
    p = _demo_profile()
    p.conversion.strategy = ConversionPlan.STRATEGY_FIXED
    p.conversion.fixed_amount = 10_000_000
    r = run_projection(p, convert=True)
    assert all(row.traditional_balance >= -1e-6 for row in r.rows)
    assert r.lifetime_conversions <= (p.primary.traditional_balance
                                      + p.spouse.traditional_balance) * 50


def test_converting_moves_money_from_traditional_to_roth():
    p = _demo_profile()
    a = run_projection(p, convert=False)
    b = run_projection(p, convert=True)
    assert b.ending_traditional < a.ending_traditional
    assert b.ending_roth > a.ending_roth
    assert b.lifetime_rmds < a.lifetime_rmds


def test_survivor_files_single_and_stays_single():
    p = _demo_profile()
    r = run_projection(p, convert=False)
    seen_single = False
    for row in r.rows:
        if row.n_alive == 1 and row.year > p.primary.birth_year + p.primary.death_age:
            assert row.filing_status == T.SINGLE, row.year
            seen_single = True
    assert seen_single, "the projection should include survivor years"


def test_retired_pay_stops_at_death_and_sbp_begins():
    p = _demo_profile()
    p.military.sbp_elected = True
    r = run_projection(p, convert=False)
    death = p.primary.birth_year + p.primary.death_age
    after = [row for row in r.rows if row.year > death]
    assert after, "spouse should outlive the retiree in this fixture"
    for row in after:
        assert row.military_retired_pay == 0.0
        assert row.va_disability == 0.0
        assert row.sbp_annuity > 0


def test_widow_pays_more_tax_on_less_income():
    """The core survivor finding. If this breaks, the model is not useful."""
    p = _demo_profile()
    r = run_projection(p, convert=False)
    death = p.primary.birth_year + p.primary.death_age
    last_joint = [x for x in r.rows if x.year == death][0]
    first_single = [x for x in r.rows if x.year == death + 1][0]
    assert first_single.agi < last_joint.agi
    assert first_single.marginal_rate > last_joint.marginal_rate


def test_rmds_start_at_the_required_age():
    p = _demo_profile()
    p.conversion.enabled = False
    r = run_projection(p, convert=False)
    rmd_age = p.rmd_age(p.primary)
    first_rmd_year = p.primary.birth_year + rmd_age
    for row in r.rows:
        if row.year < first_rmd_year:
            assert row.rmd == 0.0, row.year
    assert any(row.rmd > 0 for row in r.rows if row.year >= first_rmd_year)


def test_surplus_income_is_not_discarded():
    """Excess cash must be reinvested, or the no-conversion future is flattered."""
    p = _demo_profile()
    p.assumptions.annual_spending = 40_000     # far below income
    r = run_projection(p, convert=False)
    early = r.rows[0].taxable_balance
    later = r.rows[10].taxable_balance
    assert later > early


def test_paying_tax_from_the_ira_is_worse_than_paying_from_outside():
    p = _demo_profile()
    outside = copy.deepcopy(p)
    outside.conversion.pay_tax_from_taxable = True
    inside = copy.deepcopy(p)
    inside.conversion.pay_tax_from_taxable = False
    assert (run_projection(outside, convert=True).ending_roth >
            run_projection(inside, convert=True).ending_roth)


def test_zero_traditional_makes_the_futures_identical():
    p = _demo_profile()
    p.primary.traditional_balance = 0
    p.spouse.traditional_balance = 0
    a = run_projection(p, convert=False)
    b = run_projection(p, convert=True)
    assert a.lifetime_total_tax == pytest.approx(b.lifetime_total_tax)


def test_projection_covers_the_expected_years():
    p = _demo_profile()
    r = run_projection(p, convert=False)
    assert r.rows[0].year == p.assumptions.start_year
    assert r.rows[-1].year == p.final_year()


# ==========================================================================
# Heir valuation
# ==========================================================================

def test_roth_is_worth_more_than_traditional_to_heirs():
    p = _demo_profile()
    a = run_projection(p, convert=False)
    b = run_projection(p, convert=True)
    assert b.heir_tax_paid < a.heir_tax_paid


def test_heir_tax_rate_of_zero_removes_the_heir_penalty():
    p = _demo_profile()
    p.heirs.heir_marginal_rate = 0.0
    p.heirs.heir_state_rate = 0.0
    r = run_projection(p, convert=False)
    assert r.heir_tax_paid == pytest.approx(0.0)


# ==========================================================================
# Analysis and Monte Carlo
# ==========================================================================

def test_compare_produces_findings():
    c = compare(_demo_profile())
    assert c.findings
    assert any("RMD" in f.headline or "rmd" in f.headline.lower()
               for f in c.findings)


def test_monte_carlo_is_reproducible_and_paired():
    p = _demo_profile()
    p.monte_carlo.n_paths = 12
    p.monte_carlo.random_seed = 7
    a = run_monte_carlo(p)
    b = run_monte_carlo(p)
    assert list(a.legacy_delta) == list(b.legacy_delta)
    assert a.legacy_delta.size == 12
    # Pairing: the delta must equal the difference of the two arrays exactly.
    assert list(a.legacy_delta) == list(a.legacy_convert - a.legacy_no_convert)


def test_monte_carlo_mean_is_near_the_deterministic_result():
    p = _demo_profile()
    p.monte_carlo.n_paths = 60
    p.monte_carlo.return_stdev = 0.02
    p.monte_carlo.inflation_stdev = 0.0
    p.monte_carlo.random_seed = 3
    mc = run_monte_carlo(p)
    det = run_projection(p, convert=False)
    import numpy as np
    assert float(np.median(mc.legacy_no_convert)) == pytest.approx(
        det.heir_value_total, rel=0.35)


# ==========================================================================
# LLM briefing export
# ==========================================================================

from engine.briefing import (build_briefing, briefing_filename,  # noqa: E402
                             BriefingOptions, TABLE_MODES)
from engine.retirement.roth_analysis import sweep_target_brackets, sweep_tax_scenarios  # noqa: E402
from engine.tax.federal import TaxPolicy, SCENARIO_SURCHARGE  # noqa: E402


def test_briefing_contains_the_sections_a_reviewer_needs():
    p = _demo_profile()
    md = build_briefing(p, compare(p))
    for heading in ("## What I want from you", "## Household",
                    "## Military retirement", "## Income and accounts",
                    "## Assumptions", "## The conversion strategy being tested",
                    "## Results", "## Year by year",
                    "## Known limitations", "## Questions worth asking"):
        assert heading in md, heading


def test_briefing_states_the_engines_omissions():
    """A briefing that only lists strengths produces agreement, not review."""
    md = build_briefing(_demo_profile(), compare(_demo_profile()))
    assert "NOT modelled" in md
    for omission in ("medical-expense deduction", "Qualified charitable",
                     "Alternative Minimum Tax", "estate tax"):
        assert omission in md, omission


def test_briefing_anonymises_names_when_asked():
    p = _demo_profile()
    p.primary.name = "Jane Veteran"
    p.spouse.name = "Pat Spouse"
    anon = build_briefing(p, compare(p), BriefingOptions(anonymize=True))
    assert "Jane Veteran" not in anon
    assert "Pat Spouse" not in anon

    named = build_briefing(p, compare(p), BriefingOptions(anonymize=False))
    assert "Jane Veteran" in named


def test_briefing_rounding_blurs_exact_balances():
    p = _demo_profile()
    p.primary.traditional_balance = 703_412
    exact = build_briefing(p, compare(p), BriefingOptions(round_to=0))
    rounded = build_briefing(p, compare(p), BriefingOptions(round_to=10_000))
    assert "$703,412" in exact
    assert "$703,412" not in rounded
    assert "$700,000" in rounded


def test_briefing_table_modes_change_length():
    p = _demo_profile()
    c = compare(p)
    none_ = build_briefing(p, c, BriefingOptions(table_mode="None"))
    milestone = build_briefing(p, c, BriefingOptions(table_mode="Milestone years"))
    every = build_briefing(p, c, BriefingOptions(table_mode="Every year"))
    assert "## Year by year" not in none_
    assert len(none_) < len(milestone) < len(every)


def test_briefing_milestone_table_covers_the_structural_years():
    """The reviewer must be able to see RMD onset and the survivor transition."""
    p = _demo_profile()
    c = compare(p)
    md = build_briefing(p, c, BriefingOptions(table_mode="Milestone years"))
    rmd_year = p.primary.birth_year + p.rmd_age(p.primary)
    first_ss = p.primary.birth_year + p.primary.ss_claim_age
    widow_year = p.primary.birth_year + p.primary.death_age + 1
    for y in (rmd_year, first_ss, widow_year, p.assumptions.start_year):
        assert f"| {y} |" in md, y
    # Both filing statuses must appear, or the widow's penalty is invisible.
    assert "| Joint |" in md and "| Single |" in md


def test_briefing_includes_every_conversion_year():
    p = _demo_profile()
    c = compare(p)
    md = build_briefing(p, c, BriefingOptions(table_mode="Milestone years"))
    for row in c.conv.rows:
        if row.conversion > 0:
            assert f"| {row.year} |" in md, row.year


def test_briefing_reports_the_verdict_both_ways():
    p = _demo_profile()
    assert "**wins**" in build_briefing(p, compare(p))

    # Force a losing plan: convert at the top rate, paying tax from the IRA.
    bad = copy.deepcopy(p)
    bad.conversion.target_bracket = 0.37
    bad.conversion.pay_tax_from_taxable = False
    bad.taxable.balance = 0
    bad.taxable.cash_balance = 0
    c = compare(bad)
    md = build_briefing(bad, c)
    assert ("**loses**" in md) == (not c.converting_wins)


def test_briefing_flags_a_zero_discount_rate():
    p = _demo_profile()
    p.assumptions.discount_rate = 0.0
    assert "Treat the undiscounted advantage with suspicion" in build_briefing(p, compare(p))
    p.assumptions.discount_rate = 0.04
    assert "Treat the undiscounted advantage with suspicion" not in build_briefing(p, compare(p))


def test_briefing_includes_sweeps_only_when_supplied():
    p = _demo_profile()
    c = compare(p)
    assert "## Which target bracket is best" not in build_briefing(p, c)

    bs = sweep_target_brackets(p, brackets=(0.12, 0.22))
    ss = sweep_tax_scenarios(p, [("Current law", TaxPolicy()),
                                 ("+3 points", TaxPolicy(
                                     scenario=SCENARIO_SURCHARGE,
                                     change_year=2035, surcharge_points=3.0))])
    md = build_briefing(p, c, bracket_sweep=bs, scenario_sweep=ss)
    assert "## Which target bracket is best" in md
    assert "## Sensitivity to future tax law" in md
    assert "Converting wins in **" in md


def test_briefing_appends_reloadable_json():
    p = _demo_profile()
    md = build_briefing(p, compare(p), BriefingOptions(include_json=True))
    assert "## Appendix" in md
    payload = md.split("```json")[1].split("```")[0]
    assert Profile.from_json(payload).to_dict() == p.to_dict()


def test_briefing_filename_is_safe_and_dated():
    p = _demo_profile()
    p.profile_name = "Paul & Kim's plan / v2"
    name = briefing_filename(p)
    assert name.endswith(".md")
    for ch in "&/'":
        assert ch not in name
    from datetime import date
    assert date.today().isoformat() in name


def test_briefing_works_without_a_spouse():
    p = _demo_profile()
    p.has_spouse = False
    md = build_briefing(p, compare(p))
    assert "## Results" in md
    assert "Single" in md


def test_monte_carlo_summary_records_its_own_settings():
    """A summary that cannot state its assumptions produces misleading reports."""
    p = _demo_profile()
    p.monte_carlo.n_paths = 8
    p.monte_carlo.return_stdev = 0.17
    p.monte_carlo.inflation_stdev = 0.009
    mc = run_monte_carlo(p)
    assert mc.return_stdev == pytest.approx(0.17)
    assert mc.inflation_stdev == pytest.approx(0.009)


def test_briefing_reports_the_actual_volatility_assumption():
    p = _demo_profile()
    p.monte_carlo.n_paths = 8
    p.monte_carlo.return_stdev = 0.17
    mc = run_monte_carlo(p)
    md = build_briefing(p, compare(p), monte_carlo=mc)
    assert "## Monte Carlo" in md
    assert "17.0%" in md
    assert "Real return standard deviation: 0.0%" not in md


# ==========================================================================
# The Combat Zone Tax Exclusion, and the first projected year
#
# The Roth engine used to model a deployed member at their full nominal wage.
# Pay excluded under the CZTE never reaches a return, so that overstated
# income in the one year it matters most: the deployed year is the cheapest
# conversion window most members will ever get, and an overstated wage hides
# it. The fix is a first-year-only figure -- a deployment ends, so carrying
# the reduction forward for thirty years would be the opposite error.
# ==========================================================================

import sys as _sys, pathlib as _pathlib                                # noqa: E402
_ROOT = _pathlib.Path(__file__).resolve().parent.parent
_sys.path.insert(0, str(_ROOT))

from engine import storage as _storage                                 # noqa: E402
from engine.pay import taxable as _TP                                  # noqa: E402
from engine.retirement import roth_bridge as _RB                       # noqa: E402

_SAMPLE_E5 = _ROOT / "samples" / "e5_6yrs_brs.mpfplan.json"
_SAMPLE_O5 = _ROOT / "samples" / "retired_o5_26yrs.mpfplan.json"


def _load(path):
    return _storage.from_upload_bytes(path.read_bytes())


def test_an_enlisted_member_excludes_all_pay_for_every_month_in_the_zone():
    """
    Enlisted members and warrant officers have no cap: a qualifying month
    excludes ALL military pay. Seven of twelve months leaves five twelfths.
    """
    h = _load(_SAMPLE_E5)
    m = h.member
    assert m.in_combat_zone and m.months_deployed_this_year == 7

    before = _TP.compute(m).annual
    after = _TP.annual_after_czte(m)

    assert before == pytest.approx(49_320, abs=1)
    assert after == pytest.approx(before * 5 / 12, abs=1)
    assert after == pytest.approx(20_550, abs=1)


def test_czte_wages_are_never_higher_than_the_wage_before_the_exclusion():
    for path in (_SAMPLE_E5, _SAMPLE_O5):
        m = _load(path).member
        assert _TP.annual_after_czte(m) <= _TP.compute(m).annual + 1e-6


def test_a_member_who_is_not_deployed_is_unaffected():
    """The exclusion must not touch anyone it does not apply to."""
    h = _load(_SAMPLE_E5)
    m = h.member
    m.in_combat_zone = False
    assert _TP.czte_months(m) == 0
    assert _TP.annual_after_czte(m) == pytest.approx(_TP.compute(m).annual)
    assert _RB.default_inputs(h).wages_this_year == 0.0


def test_the_bridge_carries_the_deployed_year_but_not_the_deployed_wage():
    """
    The reduction applies once. Later years must use the full wage, or a
    seven-month deployment would model a thirty-year pay cut.
    """
    h = _load(_SAMPLE_E5)
    i = _RB.default_inputs(h)
    assert i.wages_this_year == pytest.approx(20_550, abs=1)
    assert i.wages_annual == pytest.approx(49_320, abs=1)

    p = _RB.to_roth_profile(h, i)
    assert p.primary.wages_first_year == pytest.approx(20_550, abs=1)
    assert p.primary.annual_wages == pytest.approx(49_320, abs=1)


def test_the_projection_uses_the_reduced_wage_only_in_the_first_year():
    h = _load(_SAMPLE_E5)
    i = _RB.default_inputs(h)
    p = _RB.to_roth_profile(h, i)
    p.spouse = None
    p.has_spouse = False
    p.primary.wage_real_growth = 0.0

    rows = run_projection(p, convert=False).rows
    assert rows[0].wages == pytest.approx(20_550, abs=1)
    assert rows[1].wages == pytest.approx(49_320, abs=1)
    assert rows[2].wages == pytest.approx(49_320, abs=1)


def test_the_deployed_year_is_taxed_less_than_it_used_to_be():
    """
    The regression this whole block exists for. Modelling the full wage made
    the member pay tax on income that was never taxable.
    """
    h = _load(_SAMPLE_E5)
    i = _RB.default_inputs(h)

    fixed = run_projection(_RB.to_roth_profile(h, i), convert=False).rows[0]

    i.wages_this_year = 0.0                       # what the old code did
    buggy = run_projection(_RB.to_roth_profile(h, i), convert=False).rows[0]

    assert fixed.wages < buggy.wages
    assert fixed.total_tax < buggy.total_tax
    # The whole exclusion, not a rounding difference.
    assert buggy.wages - fixed.wages == pytest.approx(28_770, abs=1)


def test_an_officer_in_the_zone_is_capped_and_an_enlisted_member_is_not():
    """
    Only commissioned officers are capped, at the highest enlisted basic pay
    plus hostile fire pay. The cap is the difference between the two branches
    of czte_monthly_exclusion, and it is easy to lose in a refactor.
    """
    h = _load(_SAMPLE_E5)
    m = h.member
    m.months_deployed_this_year = 12
    m.in_combat_zone = True

    m.grade = "E-7"
    assert _TP.annual_after_czte(m) == pytest.approx(0.0, abs=1)

    m.grade = "O-8"
    m.basic_pay_monthly_override = 15_000.0
    capped = _TP.annual_after_czte(m)
    assert capped > 0, "an O-8 above the cap keeps taxable pay"
    assert capped == pytest.approx((15_000.0 - 11_391.90) * 12, abs=1)
