"""
Tests for the healthcare engine and the page that draws it.

Three things here are worth more than the rest put together:

  * IRMAA is a STEP function. A dollar over a bracket costs the whole step,
    for the whole year, and the model has to reproduce that exactly -- a
    smoothed approximation would give the opposite advice about a conversion.
  * TRICARE For Life REQUIRES Medicare Part B. Declining Part B does not save
    the premium, it forfeits the coverage, and the model must show those years
    as uncovered rather than as cheap.
  * Group A and Group B split on a single DIEMS date, 1 January 2018.

The rest checks the phases, the horizon, the discounting and the page itself,
which is rendered headlessly against both sample plans.
"""

import sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import math
from datetime import date

import pytest

from engine import mortality as MORT
from engine import storage
from engine.benefits import healthcare as HC
from engine.profile import (Household, ServiceMember, Healthcare,
                            ACTIVE, GUARD, RESERVE, RETIRED, VETERAN, CIVILIAN)
from ui.panel import PROFILE_KEY, DIRTY_KEY, VERSION_KEY

YEAR = 2026                      # the year every figure in FIGURES applies to
SAMPLE_E5 = ROOT / "samples" / "e5_6yrs_brs.mpfplan.json"
SAMPLE_O5 = ROOT / "samples" / "retired_o5_26yrs.mpfplan.json"


def load(path: pathlib.Path) -> Household:
    return storage.from_upload_bytes(path.read_bytes())


def household(component=ACTIVE, **member) -> Household:
    m = ServiceMember(component=component, birth_year=1980, **member)
    return Household(member=m, healthcare=Healthcare())


# ==========================================================================
# IRMAA: the step function, and the cliff
# ==========================================================================

def test_irmaa_ceilings_are_inclusive_so_the_cliff_is_one_dollar_wide():
    """$218,000 pays the standard premium. $218,001 pays the surcharge."""
    edge = HC.FIGURES["irmaa_ceilings_joint"][0]
    assert HC.irmaa_for_magi(edge - 1, joint := True).index == 0
    assert HC.irmaa_for_magi(edge, joint).index == 0
    assert HC.irmaa_for_magi(edge + 1, joint).index == 1

    single_edge = HC.FIGURES["irmaa_ceilings_single"][0]
    assert HC.irmaa_for_magi(single_edge, False).index == 0
    assert HC.irmaa_for_magi(single_edge + 1, False).index == 1


def test_one_dollar_over_the_edge_costs_the_whole_step_for_the_year():
    edge = HC.FIGURES["irmaa_ceilings_joint"][0]
    under = HC.irmaa_for_magi(edge - 1, True)
    over = HC.irmaa_for_magi(edge + 1, True)

    assert under.part_b_monthly == HC.FIGURES["part_b_standard_monthly"]
    assert over.part_b_monthly > under.part_b_monthly
    # Two dollars of MAGI buy an entire year of surcharge, per person.
    step = (over.part_b_monthly - under.part_b_monthly) * 12.0
    assert step > 900
    assert HC.irmaa_cost_annual(edge, True, 1, include_part_d=False) == 0.0
    assert HC.irmaa_cost_annual(edge + 1, True, 1,
                                include_part_d=False) == pytest.approx(step)
    # And it is per person, so a couple pays it twice.
    assert HC.irmaa_cost_annual(edge + 1, True, 2,
                                include_part_d=False) == pytest.approx(2 * step)


def test_the_step_is_flat_between_cliffs():
    """Inside a tier, more MAGI costs nothing. That is what a step means."""
    lo, hi = HC.FIGURES["irmaa_ceilings_joint"][0], HC.FIGURES["irmaa_ceilings_joint"][1]
    a = HC.irmaa_cost_annual(lo + 1, True, 2)
    b = HC.irmaa_cost_annual(hi - 1, True, 2)
    assert a == b > 0
    assert HC.irmaa_cost_annual(hi + 1, True, 2) > b


def test_headroom_is_the_conversion_that_still_fits():
    edge = HC.FIGURES["irmaa_ceilings_joint"][0]
    magi = edge - 20_000
    room = HC.irmaa_headroom(magi, True)
    assert room == 20_000
    # Convert exactly the headroom and nothing is triggered...
    assert HC.conversion_irmaa_cost(magi, room, True, 2) == 0.0
    # ...one dollar more and the whole step is bought.
    assert HC.conversion_irmaa_cost(magi, room + 1, True, 2) > 0.0


def test_the_top_tier_has_no_cliff_above_it():
    top = HC.irmaa_tiers(True)[-1]
    assert top.is_top
    assert math.isinf(HC.irmaa_headroom(top.floor + 1, True))
    assert HC.conversion_irmaa_cost(top.floor + 1, 500_000, True, 2) == 0.0


def test_tiers_are_monotonic_and_aligned():
    for joint in (True, False):
        tiers = HC.irmaa_tiers(joint)
        assert len(tiers) == len(HC.FIGURES["irmaa_part_b_monthly"])
        assert [t.index for t in tiers] == list(range(len(tiers)))
        for a, b in zip(tiers, tiers[1:]):
            assert a.ceiling == b.floor
            assert a.part_b_monthly < b.part_b_monthly
            assert a.part_d_surcharge_monthly < b.part_d_surcharge_monthly
        assert tiers[0].part_b_surcharge_monthly == 0.0


def test_joint_brackets_are_twice_the_single_ones_until_the_top():
    single = HC.FIGURES["irmaa_ceilings_single"]
    joint = HC.FIGURES["irmaa_ceilings_joint"]
    assert len(single) == len(joint)
    for s, j in zip(single[:-1], joint[:-1]):
        assert j == pytest.approx(2 * s)
    # The top threshold is the exception -- it is not doubled.
    assert joint[-1] < 2 * single[-1]


# ==========================================================================
# A conversion that crosses a bracket
# ==========================================================================

def test_a_conversion_that_crosses_a_bracket_costs_the_whole_step():
    edge = HC.FIGURES["irmaa_ceilings_joint"][0]
    base = edge - 1_000
    p = HC.probe_conversion(base, 1_001, joint=True, n_enrolled=2,
                            include_part_d=False, conversion_year=YEAR,
                            age_in_conversion_year=64)
    assert p.tiers_crossed == 1
    assert p.headroom_before == 1_000
    assert p.overshoot == 1                      # one dollar past the line
    assert p.applies                             # 64 + 2 lookback years >= 65

    tier1 = HC.irmaa_tiers(True)[1]
    step = (tier1.part_b_monthly - HC.FIGURES["part_b_standard_monthly"]) * 12 * 2
    assert p.extra_annual_cost == pytest.approx(step)

    # The last dollar bought the entire step: the effective rate on the
    # conversion is absurd, which is the whole point of showing it.
    assert p.effective_rate > 1.0
    # Stopping at the headroom costs nothing at all.
    fits = HC.probe_conversion(base, 1_000, joint=True, n_enrolled=2,
                               include_part_d=False, conversion_year=YEAR,
                               age_in_conversion_year=64)
    assert fits.tiers_crossed == 0
    assert fits.extra_annual_cost == 0.0


def test_headroom_plus_overshoot_is_the_conversion():
    edge = HC.FIGURES["irmaa_ceilings_joint"][0]
    p = HC.probe_conversion(edge - 5_000, 30_000, joint=True, n_enrolled=1)
    assert p.tiers_crossed == 1
    assert p.headroom_before + p.overshoot == pytest.approx(p.conversion)


def test_a_conversion_can_cross_more_than_one_cliff():
    p = HC.probe_conversion(200_000, 200_000, joint=True, n_enrolled=2)
    assert p.tiers_crossed >= 2
    assert p.extra_annual_cost > 0


def test_part_d_is_only_charged_when_a_part_d_plan_is_held():
    edge = HC.FIGURES["irmaa_ceilings_joint"][0]
    with_d = HC.conversion_irmaa_cost(edge, 1, True, 1, include_part_d=True)
    without = HC.conversion_irmaa_cost(edge, 1, True, 1, include_part_d=False)
    assert with_d > without > 0


def test_the_surcharge_is_paid_two_years_after_the_conversion():
    p = HC.probe_conversion(0, 10_000, joint=False, conversion_year=YEAR)
    assert p.year_paid == YEAR + HC.FIGURES["irmaa_lookback_years"] == YEAR + 2


def test_a_conversion_before_the_window_closes_never_lands():
    """MAGI at 62 sets a premium for 64, when nobody is on Medicare yet."""
    early = HC.probe_conversion(300_000, 100_000, joint=True,
                                age_in_conversion_year=62)
    late = HC.probe_conversion(300_000, 100_000, joint=True,
                               age_in_conversion_year=63)
    assert not early.applies
    assert late.applies
    assert HC.CONVERSION_WINDOW_CLOSES_AT == HC.MEDICARE_AGE - 2 == 63


# ==========================================================================
# TRICARE groups: the 1 January 2018 line
# ==========================================================================

def test_group_a_and_group_b_split_on_the_first_of_january_2018():
    assert HC.GROUP_B_DIEMS_START == date(2018, 1, 1)
    assert HC.tricare_group(date(2017, 12, 31)) == HC.GROUP_A
    assert HC.tricare_group(date(2018, 1, 1)) == HC.GROUP_B
    assert HC.tricare_group(date(2018, 1, 2)) == HC.GROUP_B
    # An unreadable DIEMS falls back to Group A, where nearly every current
    # retiree sits -- guessing Group B would overstate the fees.
    assert HC.tricare_group(None) == HC.GROUP_A


def test_group_b_pays_more_than_group_a_on_every_fee_and_cap():
    for plan in (HC.PLAN_PRIME, HC.PLAN_SELECT):
        for family in (True, False):
            a = HC.enrollment_fee_annual(plan, HC.GROUP_A, family)
            b = HC.enrollment_fee_annual(plan, HC.GROUP_B, family)
            assert b > a > 0
            assert HC.enrollment_fee_annual(plan, HC.GROUP_A, True) == \
                2 * HC.enrollment_fee_annual(plan, HC.GROUP_A, False)
    assert HC.catastrophic_cap(HC.GROUP_B, True) > HC.catastrophic_cap(HC.GROUP_A, True)
    assert HC.catastrophic_cap(HC.GROUP_A, True) == 3_000.0     # fixed in law
    assert HC.catastrophic_cap(HC.GROUP_A, False) == 1_000.0


def test_neither_group_pays_an_enrollment_fee_for_tricare_for_life():
    for group in (HC.GROUP_A, HC.GROUP_B):
        assert HC.enrollment_fee_annual(HC.PLAN_TFL, group, True) == 0.0


def test_the_diems_date_drives_the_group_in_a_lifetime_run():
    early = household(diems_date="2017-12-31", years_of_service=9.0)
    late = household(diems_date="2018-01-01", years_of_service=9.0)
    assert HC.lifetime_cost(early, today_year=YEAR).group == HC.GROUP_A
    assert HC.lifetime_cost(late, today_year=YEAR).group == HC.GROUP_B
    assert (HC.lifetime_cost(late, today_year=YEAR).total_today_dollars >
            HC.lifetime_cost(early, today_year=YEAR).total_today_dollars)


# ==========================================================================
# TRICARE Reserve Select is for the Selected Reserve and nobody else
# ==========================================================================

def test_reserve_select_is_offered_to_guard_and_reserve_only():
    assert HC.trs_eligible(GUARD) and HC.trs_eligible(RESERVE)
    for other in (ACTIVE, RETIRED, VETERAN, CIVILIAN):
        assert not HC.trs_eligible(other)
        assert HC.PLAN_TRS not in HC.plans_for(other)
    for rc in (GUARD, RESERVE):
        assert HC.PLAN_TRS in HC.plans_for(rc)


def test_the_plan_menu_only_offers_for_life_to_someone_already_retired():
    assert HC.PLAN_TFL in HC.plans_for(RETIRED)
    for other in (ACTIVE, GUARD, RESERVE, VETERAN, CIVILIAN):
        assert HC.PLAN_TFL not in HC.plans_for(other)
    for component in (ACTIVE, GUARD, RESERVE, RETIRED, VETERAN, CIVILIAN):
        assert HC.plans_for(component), "every component gets a usable menu"
        assert set(HC.plans_for(component)) <= set(HC.PLANS)


def test_an_active_duty_family_is_never_charged_a_reserve_select_premium():
    """Even if the stored plan says Reserve Select, which it cannot be."""
    h = household(ACTIVE, years_of_service=9.0)
    h.healthcare.tricare_plan = HC.PLAN_TRS
    lc = HC.lifetime_cost(h, today_year=YEAR)
    assert HC.PH_TRS not in {r.phase for r in lc.rows}
    serving = [r for r in lc.rows if r.phase == HC.PH_ACTIVE]
    assert serving and all(r.premiums == 0.0 for r in serving)


def test_a_drilling_reservist_pays_reserve_select_and_a_gray_area_follows():
    h = household(RESERVE, years_of_service=14.0, diems_date="2010-06-01")
    lc = HC.lifetime_cost(h, leave_service_age=52, today_year=YEAR)
    phases = {r.phase for r in lc.rows}
    assert HC.PH_TRS in phases
    assert HC.PH_GRAY in phases            # retired reservist, under 60
    trs = [r for r in lc.rows if r.phase == HC.PH_TRS]
    gray = [r for r in lc.rows if r.phase == HC.PH_GRAY]
    assert trs[0].premiums == pytest.approx(HC.trs_annual(False))
    # TRICARE Retired Reserve is priced at full cost: an order of magnitude
    # more than Reserve Select, which is the whole warning about the gray area.
    assert gray[0].premiums > 8 * trs[0].premiums
    assert lc.span_of(HC.PH_GRAY) == (52, 59)


# ==========================================================================
# Declining Part B
# ==========================================================================

def test_declining_part_b_forfeits_tricare_for_life():
    h = load(SAMPLE_O5)
    h.healthcare.part_b_when_eligible = False
    lc = HC.lifetime_cost(h, today_year=YEAR)

    assert lc.tfl_covered is False
    assert lc.first_part_b_age is None
    over_65 = [r for r in lc.rows if r.age >= HC.MEDICARE_AGE]
    assert over_65, "the sample lives past 65"
    for r in over_65:
        assert r.phase == HC.PH_NO_TFL
        assert r.covered is False
        assert r.n_part_b == 0
        assert r.premiums == 0.0 and r.irmaa == 0.0


def test_declining_part_b_yields_a_bad_finding_that_names_the_consequence():
    h = load(SAMPLE_O5)
    h.healthcare.part_b_when_eligible = False
    lc = HC.lifetime_cost(h, today_year=YEAR)
    found = HC.findings(h, lc)

    bad = [f for f in found if f[0] == "bad"]
    assert bad, "declining Part B is not a warning, it is a mistake"
    headline, detail = bad[0][1], bad[0][2]
    assert "Part B" in headline and "TRICARE For Life" in headline
    assert "Medigap" in detail and "Advantage" in detail
    assert "10%" in detail                       # the late-enrollment penalty


def test_taking_part_b_pays_the_premium_and_keeps_the_cover():
    h = load(SAMPLE_O5)
    h.healthcare.part_b_when_eligible = True
    lc = HC.lifetime_cost(h, today_year=YEAR)
    assert lc.tfl_covered is True
    assert not any(f[0] == "bad" for f in HC.findings(h, lc))
    at_65 = [r for r in lc.rows if r.age == HC.MEDICARE_AGE][0]
    assert at_65.phase == HC.PH_TFL
    assert at_65.covered is True
    assert at_65.n_part_b == 2                   # the sample is married
    assert at_65.premiums == pytest.approx(
        HC.FIGURES["part_b_standard_monthly"] * 12 * 2)


def test_declining_part_b_is_not_the_cheaper_choice_once_care_is_priced():
    """Uncapped out-of-pocket is what an uncovered year actually looks like."""
    h = load(SAMPLE_O5)
    h.healthcare.out_of_pocket_annual = 30_000.0
    h.healthcare.part_b_when_eligible = True
    covered = HC.lifetime_cost(h, today_year=YEAR)
    h.healthcare.part_b_when_eligible = False
    uncovered = HC.lifetime_cost(h, today_year=YEAR)
    assert uncovered.total_today_dollars > covered.total_today_dollars


# ==========================================================================
# The retiree sample
# ==========================================================================

def test_the_retiree_sample_starts_part_b_at_sixty_five():
    h = load(SAMPLE_O5)
    assert h.member.birth_year == 1975 and h.member.component == RETIRED
    lc = HC.lifetime_cost(h, today_year=YEAR)

    assert lc.first_part_b_age == HC.MEDICARE_AGE == 65
    assert lc.phase_of(64) == HC.PH_RETIREE_PRIME
    assert lc.phase_of(65) == HC.PH_TFL
    start, end = lc.span_of(HC.PH_TFL)
    assert start == 65 and end == lc.death_age - 1
    # The year it starts is the year the member turns 65.
    at_65 = [r for r in lc.rows if r.age == 65][0]
    assert at_65.year == 1975 + 65 == 2040
    assert at_65.n_part_b >= 1
    # Nobody pays a Part B premium before then.
    assert all(r.n_part_b == 0 for r in lc.rows if r.age < 65)


def test_the_retiree_sample_costs_more_after_sixty_five_than_before():
    h = load(SAMPLE_O5)
    lc = HC.lifetime_cost(h, today_year=YEAR)
    before = [r for r in lc.rows if r.age < 65][0].total
    after = [r for r in lc.rows if r.age == 65][0].total
    assert after > 5 * before
    # Prime for a family is a few hundred dollars; Part B for two is thousands.
    assert before == pytest.approx(
        HC.enrollment_fee_annual(HC.PLAN_PRIME, HC.GROUP_A, True))


def test_the_retiree_sample_runs_to_life_expectancy_and_is_discounted():
    h = load(SAMPLE_O5)
    lc = HC.lifetime_cost(h, today_year=YEAR)
    age0 = YEAR - h.member.birth_year
    assert lc.start_age == age0 == 51
    assert lc.death_age == MORT.life_expectancy(age0, h.member.sex)
    assert [r.age for r in lc.rows] == list(range(age0, lc.death_age))
    assert lc.rows[0].discount_factor == 1.0

    assert h.assumptions.real_discount_rate_pct > 0
    assert 0 < lc.present_value < lc.total_today_dollars
    assert lc.total_today_dollars == pytest.approx(sum(r.total for r in lc.rows))


def test_a_higher_discount_rate_lowers_the_present_value_only():
    h = load(SAMPLE_O5)
    base = HC.lifetime_cost(h, today_year=YEAR)
    h.assumptions.real_discount_rate_pct = 6.0
    steeper = HC.lifetime_cost(h, today_year=YEAR)
    assert steeper.present_value < base.present_value
    assert steeper.total_today_dollars == pytest.approx(base.total_today_dollars)


def test_the_retiree_samples_lifetime_cost_is_the_number_the_page_shows():
    """A regression peg: if a figure moves, this test says by how much."""
    h = load(SAMPLE_O5)
    lc = HC.lifetime_cost(h, today_year=YEAR)
    # Group A family Prime until 65, then Part B for two. Both phase lengths
    # follow life expectancy, so derive them rather than pinning a year count
    # that a life-table update silently invalidates.
    import engine.mortality as MORT
    age_now = h.member.age(YEAR)
    death_age = MORT.life_expectancy(age_now, h.member.sex)
    pre65 = max(0, 65 - age_now)
    post65 = max(0, death_age - max(age_now, 65))
    fee_years = HC.enrollment_fee_annual(HC.PLAN_PRIME, HC.GROUP_A, True) * pre65
    part_b_years = HC.FIGURES["part_b_standard_monthly"] * 12 * 2 * post65
    assert lc.total_today_dollars == pytest.approx(fee_years + part_b_years)
    assert lc.present_value < lc.total_today_dollars


def test_the_active_duty_sample_pays_nothing_until_it_retires():
    h = load(SAMPLE_E5)
    lc = HC.lifetime_cost(h, today_year=YEAR)
    assert lc.will_retire is True
    assert lc.group == HC.GROUP_B              # DIEMS 2020
    serving = [r for r in lc.rows if r.phase == HC.PH_ACTIVE]
    assert serving and all(r.total == 0.0 for r in serving)
    assert lc.phase_of(lc.leave_service_age) == HC.PH_RETIREE_PRIME


# ==========================================================================
# MAGI, and the findings that hang off it
# ==========================================================================

def test_serving_pay_is_in_this_years_magi_and_allowances_are_not():
    h = load(SAMPLE_E5)
    magi = HC.estimate_current_magi(h)
    spouse_only = h.spouse_income.annual_income
    assert magi > spouse_only, "the member's own basic pay counts"


def test_combat_zone_pay_is_left_out_of_magi():
    h = load(SAMPLE_E5)
    assert h.member.in_combat_zone
    with_czte = HC.estimate_current_magi(h)
    h.member.in_combat_zone = False
    without = HC.estimate_current_magi(h)
    assert with_czte < without


def test_retirement_magi_counts_the_rmd_a_traditional_balance_forces_out():
    h = load(SAMPLE_O5)
    with_rmd = HC.estimate_retirement_magi(h)
    without = HC.estimate_retirement_magi(h, include_rmd=False)
    assert with_rmd > without
    assert without == pytest.approx(h.member.retired_pay_monthly * 12)
    assert HC.estimate_rmd_annual(h) == pytest.approx(with_rmd - without)
    # VA compensation is not in MAGI, however large it is.
    h.member.va_disability_monthly = 9_000.0
    assert HC.estimate_retirement_magi(h) == pytest.approx(with_rmd)


def test_an_unknown_retirement_income_is_reported_as_unknown():
    h = household(RETIRED, years_of_service=22.0, diems_date="2004-01-01")
    lc = HC.lifetime_cost(h, retirement_magi=0.0, today_year=YEAR)
    text = " ".join(f"{f[1]} {f[2]}" for f in HC.findings(h, lc))
    assert "nothing to estimate" in text
    assert "$0 sits" not in text


def test_a_high_magi_puts_a_surcharge_into_every_medicare_year():
    h = load(SAMPLE_O5)
    standard = HC.lifetime_cost(h, retirement_magi=100_000, filing_joint=True,
                                today_year=YEAR)
    surcharged = HC.lifetime_cost(h, retirement_magi=300_000, filing_joint=True,
                                  today_year=YEAR)
    assert standard.irmaa_tier.index == 0
    assert surcharged.irmaa_tier.index > 0
    assert all(r.irmaa == 0 for r in standard.rows)
    assert all(r.irmaa > 0 for r in surcharged.rows if r.age >= 65)
    assert surcharged.total_today_dollars > standard.total_today_dollars


def test_the_cliff_finding_names_the_first_cliff_and_not_the_second():
    """
    The standard tier's CEILING is the first cliff. The first surcharge
    tier's ceiling is the second one, roughly $56,000 further up -- naming it
    here would tell a retiree they have headroom they do not have.
    """
    h = load(SAMPLE_O5)
    lc = HC.lifetime_cost(h, retirement_magi=100_000, filing_joint=True,
                          today_year=YEAR)
    text = " ".join(f[2] for f in HC.findings(h, lc))
    first, second = HC.FIGURES["irmaa_ceilings_joint"][:2]
    assert f"${first:,.0f} pays the standard premium" in text
    assert f"${first + 1:,.0f} — one dollar more" in text
    assert f"${second:,.0f} pays the standard premium" not in text


def test_the_findings_state_that_tfl_requires_part_b_and_the_va_does_not_cover_the_family():
    h = load(SAMPLE_O5)
    lc = HC.lifetime_cost(h, today_year=YEAR)
    text = " ".join(f"{f[1]} {f[2]}" for f in HC.findings(h, lc))
    assert "TRICARE For Life has no enrollment fee" in text
    assert "not VA patients" in text
    assert "CHAMPVA" in text
    assert "not a substitute for family coverage" in text


def test_the_gray_area_and_reserve_select_findings_reach_a_reservist():
    h = household(RESERVE, years_of_service=14.0, diems_date="2010-06-01")
    lc = HC.lifetime_cost(h, leave_service_age=52, today_year=YEAR)
    text = " ".join(f"{f[1]} {f[2]}" for f in HC.findings(h, lc))
    assert "Reserve Select" in text
    assert "gray area" in text
    assert "TRR" in text


def test_va_priority_group_falls_out_of_the_rating():
    assert HC.va_priority_group(100, True)[0] == 1
    assert HC.va_priority_group(50)[0] == 1
    assert HC.va_priority_group(30)[0] == 2
    assert HC.va_priority_group(10)[0] == 3
    group, label = HC.va_priority_group(0)
    assert group is None and "income" in label
    assert "CHAMPVA" in HC.va_priority_group(100, True)[1]


# ==========================================================================
# Provenance: every figure says where it came from, and re-derives
# ==========================================================================

def test_every_figure_carries_a_verify_note():
    assert set(HC.FIGURES) - {"year"} == set(HC.VERIFY)
    for key, note in HC.VERIFY.items():
        assert note.strip().endswith(".")
        assert ("VERIFY at" in note or "Statutory" in note
                or "ESTIMATE" in note), f"{key}: says where it came from"


def test_the_part_b_tiers_re_derive_from_the_statutory_cost_shares():
    """A typed digit in a premium is caught here, not by a user at 65."""
    shares = HC.FIGURES["irmaa_share_of_cost"]
    premiums = HC.FIGURES["irmaa_part_b_monthly"]
    total_cost = HC.FIGURES["part_b_standard_monthly"] / shares[0]
    assert total_cost == pytest.approx(811.60, abs=0.05)
    for share, premium in zip(shares, premiums):
        assert premium == pytest.approx(share * total_cost, abs=0.25)


def test_the_part_d_surcharges_re_derive_from_the_base_beneficiary_premium():
    shares = HC.FIGURES["irmaa_share_of_cost"]
    base = HC.FIGURES["part_d_base_beneficiary_monthly"]
    for share, surcharge in zip(shares, HC.FIGURES["irmaa_part_d_monthly"]):
        expected = max(0.0, (share - 0.255) / 0.255 * base)
        assert surcharge == pytest.approx(expected, abs=0.10)


def test_the_figures_are_all_for_the_same_year():
    assert HC.FIGURES["year"] == YEAR
    assert HC.FIGURES["irmaa_lookback_years"] == 2
    assert HC.FIGURES["part_b_late_penalty_per_year"] == 0.10


# ==========================================================================
# The page
# ==========================================================================

PAGE = ROOT / "pages" / "16_Healthcare.py"


def render(sample: pathlib.Path | None = None):
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(PAGE), default_timeout=120)
    if sample is not None:
        at.session_state[PROFILE_KEY] = load(sample)
        at.session_state[VERSION_KEY] = 0
    at.run()
    assert not at.exception, at.exception
    return at


def body(at) -> str:
    return " ".join(md.value for md in at.markdown)


@pytest.mark.parametrize("sample", [None, SAMPLE_E5, SAMPLE_O5],
                         ids=["blank", "e5", "retired_o5"])
def test_the_page_renders(sample):
    at = render(sample)
    assert at.title[0].value == "🏥 What will healthcare cost me?"
    assert at.metric, "the page shows what it costs"
    labels = [m.label for m in at.metric]
    assert "Lifetime cost, today's dollars" in labels
    assert "Your IRMAA tier" in labels
    assert "Headroom to the next cliff" in labels


@pytest.mark.parametrize("sample", [None, SAMPLE_E5, SAMPLE_O5],
                         ids=["blank", "e5", "retired_o5"])
def test_the_page_states_the_two_things_that_are_not_optional(sample):
    text = body(render(sample))
    assert "TRICARE For Life requires Medicare Part B" in text
    assert "forfeit TFL" in text
    assert "VA care is a parallel system, not family coverage" in text
    assert "not VA patients" in text


def test_the_page_asks_every_healthcare_question_and_writes_the_answers_back():
    at = render(SAMPLE_O5)
    keys = {"hc_plan__v0", "hc_dental__v0", "hc_oop__v0", "hc_ltc__v0",
            "hc_partb__v0", "hc_magi__v0", "hc_conv__v0"}
    assert keys <= set(at.session_state.filtered_state)

    at.number_input(key="hc_dental__v0").set_value(64.0).run()
    at.number_input(key="hc_ltc__v0").set_value(250.0).run()
    at.selectbox(key="hc_plan__v0").select(HC.PLAN_SELECT).run()
    assert not at.exception, at.exception

    hc = at.session_state[PROFILE_KEY].healthcare
    assert hc.fedvip_dental_monthly == 64.0
    assert hc.ltc_premium_monthly == 250.0
    assert hc.tricare_plan == HC.PLAN_SELECT
    assert at.session_state[DIRTY_KEY] is True


def test_the_page_only_offers_plans_the_component_can_hold():
    assert render(SAMPLE_O5).selectbox(key="hc_plan__v0").options == \
        HC.plans_for(RETIRED)
    assert render(SAMPLE_E5).selectbox(key="hc_plan__v0").options == \
        HC.plans_for(ACTIVE)
    assert HC.PLAN_TRS not in render(SAMPLE_E5).selectbox(key="hc_plan__v0").options


def test_declining_part_b_on_the_page_raises_the_alarm():
    at = render(SAMPLE_O5)
    at.toggle(key="hc_partb__v0").set_value(False).run()
    assert not at.exception, at.exception
    assert at.session_state[PROFILE_KEY].healthcare.part_b_when_eligible is False
    text = body(at)
    assert "🚨" in text
    assert "Declining Medicare Part B forfeits TRICARE For Life" in text
    assert [m for m in at.metric
            if m.label == "Covered at 65" and m.value == "Nothing"]


def test_the_page_prices_a_conversion_that_crosses_a_cliff():
    at = render(SAMPLE_O5)
    edge = HC.FIGURES["irmaa_ceilings_joint"][0]
    at.number_input(key="hc_basemagi__v0").set_value(edge - 1_000).run()
    at.number_input(key="hc_conv__v0").set_value(50_000.0).run()
    assert not at.exception, at.exception

    tier = [m.value for m in at.metric if m.label == "Tier"]
    assert tier and "→" in tier[0] and tier[0] != "Standard → Standard"
    text = body(at)
    assert "cliff" in text
    # It names the conversion that would have fitted under the line.
    assert "instead and the surcharge is zero" in text


def test_the_page_shows_the_irmaa_table_with_the_users_own_row_marked():
    at = render(SAMPLE_O5)
    frames = [df.value for df in at.dataframe]
    irmaa = [f for f in frames if "Tier" in f.columns]
    assert irmaa, "the IRMAA table is on the page"
    table = irmaa[0]
    assert len(table) == len(HC.irmaa_tiers(True))
    marked = [v for v in table[table.columns[0]] if v]
    assert len(marked) == 1, "exactly one row is the user's"


def test_the_page_shows_where_every_figure_came_from():
    at = render(SAMPLE_O5)
    frames = [df.value for df in at.dataframe]
    prov = [f for f in frames if "Figure" in f.columns]
    assert prov, "the provenance table is on the page"
    assert len(prov[0]) == len(HC.VERIFY)
    assert "cms.gov" in " ".join(prov[0].iloc[:, -1])
