"""
Tests for the Social Security engine and its page.

The arithmetic here is entirely statutory, so it can be checked against
published numbers rather than against itself: a $2,000 PIA is $1,400 at 62 and
$2,480 at 70 for anyone born in 1960 or later, a spousal benefit tops out at
half the worker's PIA, and the taxation thresholds have not moved since 1993.

The fallback estimate is checked against a BAND rather than a figure. It is a
modelled career -- the pay table, the promotion timeline and the bend points
all move it -- and a test that pins it to the cent would fail every time the
pay table is updated, which is exactly when nobody wants to look at it.
"""

import sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from engine.income import social_security as SS
from engine import storage
from engine import mortality as MORT
from engine.pay import basepay as BP
from engine.tax import tables as T
from ui.panel import PROFILE_KEY, VERSION_KEY, DIRTY_KEY

E5 = "e5_6yrs_brs.mpfplan.json"
O5 = "retired_o5_26yrs.mpfplan.json"
SAMPLES = [E5, O5]

FRA_67 = 1975          # anyone born 1960 or later
FRA_66 = 1950          # 1943-1954


def sample(name):
    return storage.from_upload_bytes((ROOT / "samples" / name).read_bytes())


# ==========================================================================
# Full retirement age
# ==========================================================================

def test_full_retirement_age_by_birth_year():
    """65 through 1937, two months a year to 66, a pause, then on to 67."""
    assert SS.full_retirement_age(1930) == (65, 0)
    assert SS.full_retirement_age(1937) == (65, 0)
    assert SS.full_retirement_age(1938) == (65, 2)
    assert SS.full_retirement_age(1940) == (65, 6)
    assert SS.full_retirement_age(1942) == (65, 10)
    assert SS.full_retirement_age(1943) == (66, 0)
    assert SS.full_retirement_age(1954) == (66, 0)
    assert SS.full_retirement_age(1955) == (66, 2)
    assert SS.full_retirement_age(1959) == (66, 10)
    assert SS.full_retirement_age(1960) == (67, 0)
    assert SS.full_retirement_age(1999) == (67, 0)


def test_full_retirement_age_never_goes_backwards():
    months = [SS.full_retirement_age_months(y) for y in range(1930, 2011)]
    assert months == sorted(months)
    assert min(months) == 65 * 12 and max(months) == 67 * 12


def test_full_retirement_age_labels_and_fractions():
    assert SS.fra_years(FRA_67) == pytest.approx(67.0)
    assert SS.fra_years(1957) == pytest.approx(66.5)
    assert SS.fra_label(1960) == "67"
    assert SS.fra_label(1958) == "66 and 8 months"
    assert SS.fra_label(1955) == "66 and 2 months"


# ==========================================================================
# The claim-age factors
# ==========================================================================

def test_a_2000_dollar_pia_pays_1400_at_62_and_2480_at_70():
    """The headline numbers for anyone born in 1960 or later: 70% and 124%."""
    assert SS.benefit_at(2_000, FRA_67, 62) == pytest.approx(1_400.0)
    assert SS.benefit_at(2_000, FRA_67, 67) == pytest.approx(2_000.0)
    assert SS.benefit_at(2_000, FRA_67, 70) == pytest.approx(2_480.0)


def test_the_early_reduction_steepens_after_36_months():
    # 5/9 of 1% a month for the first 36, 5/12 of 1% a month beyond.
    assert SS.claim_factor(FRA_67, 66) == pytest.approx(1 - 12 * (5 / 9) / 100)
    assert SS.claim_factor(FRA_67, 64) == pytest.approx(0.80)
    assert SS.claim_factor(FRA_67, 63) == pytest.approx(0.75)
    assert SS.claim_factor(FRA_67, 62) == pytest.approx(0.70)
    # An FRA of 66 is only 48 months from 62, so 62 costs 25% rather than 30%.
    assert SS.claim_factor(FRA_66, 62) == pytest.approx(0.75)


def test_delayed_credits_are_eight_percent_a_year_and_stop_at_70():
    assert SS.claim_factor(FRA_67, 68) == pytest.approx(1.08)
    assert SS.claim_factor(FRA_67, 69) == pytest.approx(1.16)
    assert SS.claim_factor(FRA_67, 70) == pytest.approx(1.24)
    assert SS.claim_factor(FRA_67, 75) == SS.claim_factor(FRA_67, 70)
    # An FRA of 66 gets four years of credits rather than three.
    assert SS.claim_factor(FRA_66, 70) == pytest.approx(1.32)
    # Nothing happens below 62 either.
    assert SS.claim_factor(FRA_67, 55) == SS.claim_factor(FRA_67, 62)


# ==========================================================================
# Breakeven
# ==========================================================================

def test_the_breakeven_between_62_and_70_lands_in_the_high_seventies():
    be = SS.breakeven_age(1_400, 62, 2_480, 70)
    assert 77.0 <= be <= 81.0
    assert be == pytest.approx(80.37, abs=0.05)
    # The same question for an FRA of 66 lands in the same place.
    be66 = SS.breakeven_age(SS.benefit_at(2_000, FRA_66, 62), 62,
                            SS.benefit_at(2_000, FRA_66, 70), 70)
    assert 77.0 <= be66 <= 81.0


def test_the_breakeven_against_full_retirement_age_comes_earlier():
    be_fra = SS.breakeven_age(1_400, 62, 2_000, 67)
    assert 76.0 <= be_fra <= 79.0
    assert be_fra < SS.breakeven_age(1_400, 62, 2_480, 70)


def test_discounting_pushes_the_breakeven_later_and_a_smaller_benefit_never_catches_up():
    plain = SS.breakeven_age(1_400, 62, 2_480, 70)
    discounted = SS.breakeven_age(1_400, 62, 2_480, 70, real_rate=0.03)
    assert discounted > plain
    assert SS.breakeven_age(1_400, 62, 1_400, 70) is None


def test_cumulative_and_present_value_of_a_level_real_benefit():
    assert SS.cumulative_benefit(1_000, 62, 82) == pytest.approx(240_000)
    assert SS.cumulative_benefit(1_000, 70, 62) == 0.0
    # Undiscounted, the present value is just the total.
    assert SS.present_value_of_benefit(1_000, 62, 82, 0.0) == pytest.approx(240_000)
    # Discounted, waiting costs: the same monthly amount deferred is worth less.
    now = SS.present_value_of_benefit(1_000, 62, 82, 0.03)
    later = SS.present_value_of_benefit(1_000, 70, 90, 0.03)
    assert later < now


# ==========================================================================
# Spousal and survivor
# ==========================================================================

def test_the_spousal_benefit_is_capped_at_half_the_workers_pia():
    at_fra = SS.spousal_benefit(2_000, 0, FRA_67, 67)
    assert at_fra.total == pytest.approx(1_000)
    assert at_fra.share_of_worker_pia == pytest.approx(0.50)
    # There are no delayed credits on a spousal benefit: it peaks at FRA.
    assert SS.spousal_benefit(2_000, 0, FRA_67, 70).total == pytest.approx(1_000)
    # Claiming at 62 with an FRA of 67 pays 65% of it -- 32.5% of the PIA.
    early = SS.spousal_benefit(2_000, 0, FRA_67, 62)
    assert early.total == pytest.approx(650)
    assert early.share_of_worker_pia == pytest.approx(0.325)


def test_a_spouse_with_their_own_larger_record_gets_no_top_up():
    r = SS.spousal_benefit(2_000, 1_200, FRA_67, 67)
    assert r.spousal_excess_full == 0.0
    assert r.total == pytest.approx(1_200)
    assert "own benefit is already at least half" in r.note
    # Below half, they are topped up to exactly half.
    r2 = SS.spousal_benefit(2_000, 400, FRA_67, 67)
    assert r2.spousal_excess_full == pytest.approx(600)
    assert r2.total == pytest.approx(1_000)


def test_a_spouse_on_ssdi_keeps_their_full_pia_at_any_claim_age():
    fixed = SS.spousal_benefit(2_000, 900, FRA_67, 62, own_is_fixed=True)
    assert fixed.own_benefit == pytest.approx(900)
    reduced = SS.spousal_benefit(2_000, 900, FRA_67, 62)
    assert reduced.own_benefit == pytest.approx(630)     # 70% of 900


def test_the_survivor_gets_the_deceaseds_delayed_credit_amount():
    r = SS.survivor_benefit(2_000, FRA_67, 70, survivor_own_benefit=900)
    assert r.deceased_benefit == pytest.approx(2_480)
    assert r.survivor_benefit == pytest.approx(2_480)    # credits included
    assert r.survivor_receives == pytest.approx(2_480)
    assert r.household_before == pytest.approx(3_380)
    assert r.household_after == pytest.approx(2_480)
    assert r.monthly_drop == pytest.approx(900)          # two checks become one
    assert not r.floor_applied


def test_a_survivor_of_an_early_claimer_is_floored_at_82_and_a_half_percent():
    r = SS.survivor_benefit(2_000, FRA_67, 62, survivor_own_benefit=0)
    assert r.deceased_benefit == pytest.approx(1_400)
    assert r.survivor_benefit == pytest.approx(1_650)    # 82.5% of the PIA
    assert r.floor_applied
    # A bigger benefit of their own simply stays; nothing is inherited.
    own = SS.survivor_benefit(2_000, FRA_67, 67, survivor_own_benefit=2_500)
    assert own.survivor_receives == pytest.approx(2_500)
    assert "own benefit is the larger one" in own.note


# ==========================================================================
# Taxation of the benefit
# ==========================================================================

def test_the_provisional_income_thresholds_are_the_statutory_ones():
    assert SS.PROVISIONAL_TIER1[T.SINGLE] == 25_000
    assert SS.PROVISIONAL_TIER2[T.SINGLE] == 34_000
    assert SS.PROVISIONAL_TIER1[T.MFJ] == 32_000
    assert SS.PROVISIONAL_TIER2[T.MFJ] == 44_000
    assert SS.MAX_TAXABLE_SHARE == 0.85


def test_provisional_income_is_other_income_plus_half_the_benefit():
    r = SS.taxation(30_000, 16_000, married=True)
    assert r.provisional_income == pytest.approx(31_000)
    assert r.taxable_amount == 0.0
    assert r.taxable_share == 0.0
    assert "none of the benefit is taxed" in r.note
    # Tax-exempt interest counts too -- that is the point of putting it there.
    with_muni = SS.taxation(30_000, 16_000, married=True, tax_exempt_interest=5_000)
    assert with_muni.provisional_income == pytest.approx(36_000)
    assert with_muni.taxable_amount > 0


def test_between_the_tiers_each_dollar_drags_fifty_cents_of_benefit_into_tax():
    a = SS.taxation(30_000, 21_000, married=True)     # provisional 36,000
    b = SS.taxation(30_000, 22_000, married=True)     # provisional 37,000
    assert a.taxable_amount == pytest.approx(2_000)
    assert b.taxable_amount - a.taxable_amount == pytest.approx(500)


def test_above_the_second_tier_it_is_eighty_five_cents_up_to_the_ceiling():
    a = SS.taxation(30_000, 40_000, married=True)     # provisional 55,000
    b = SS.taxation(30_000, 41_000, married=True)
    assert b.taxable_amount - a.taxable_amount == pytest.approx(850)
    top = SS.taxation(30_000, 200_000, married=True)
    assert top.taxable_share == pytest.approx(0.85)
    assert top.taxable_amount == pytest.approx(25_500)
    assert "85% ceiling" in top.note


def test_a_single_filer_crosses_the_thresholds_earlier():
    single = SS.taxation(30_000, 20_000, married=False)   # provisional 35,000
    joint = SS.taxation(30_000, 20_000, married=True)     # provisional 35,000
    assert single.status == T.SINGLE and joint.status == T.MFJ
    assert single.taxable_amount > joint.taxable_amount
    assert SS.taxation(30_000, 0, married=False).taxable_amount == 0.0


def test_the_taxation_ramp_never_falls_as_other_income_rises():
    shares = [t.taxable_share for _, t in SS.taxation_ramp(30_000, married=True)]
    assert shares == sorted(shares)
    assert shares[0] == 0.0
    assert shares[-1] == pytest.approx(0.85)


# ==========================================================================
# The fallback: a modelled career -> AIME -> PIA
# ==========================================================================

def test_aime_takes_the_highest_35_years_and_fills_the_rest_with_zeros():
    assert SS.aime_from_earnings([42_000] * 35) == 3_500
    assert SS.aime_from_earnings([42_000] * 20) == 2_000      # 15 zeros
    assert SS.aime_from_earnings([42_000] * 35 + [1_000]) == 3_500
    assert SS.aime_from_earnings([]) == 0


def test_the_bend_point_formula():
    b1, b2 = SS.BEND_POINT_1, SS.BEND_POINT_2
    assert SS.pia_from_aime(1_000) == pytest.approx(900.0)
    assert SS.pia_from_aime(b1) == pytest.approx(0.9 * b1, abs=0.1)
    at_b2 = SS.pia_from_aime(b2)
    assert at_b2 == pytest.approx(0.9 * b1 + 0.32 * (b2 - b1), abs=0.1)
    # 15 cents on the dollar above the second bend point.
    assert SS.pia_from_aime(b2 + 1_000) - at_b2 == pytest.approx(150.0, abs=0.1)
    assert SS.pia_from_aime(0) == 0.0


def test_special_extra_earnings_credits_stop_after_2001():
    assert SS.extra_earnings_credit(1999, 1_500) == pytest.approx(500)
    assert SS.extra_earnings_credit(2001, 30_000) == pytest.approx(1_200)
    assert SS.extra_earnings_credit(2002, 30_000) == 0.0
    assert SS.extra_earnings_credit(1985, 0) == 0.0


def test_the_fallback_pia_for_the_e5_sample_lands_in_a_credible_band():
    """
    The E-5 sample: 27 years old, six years in, no statement. The model runs
    the default enlisted ladder to 20 years and then 21 civilian years at the
    zero wage on that plan, so the PIA is basic pay only with 15 zeros in the
    35-year average. That should land near $1,600 a month.
    """
    h = sample(E5)
    est = SS.estimate_pia_from_career(h.member, current_year=2026)
    assert est.found
    assert est.n_military_years == 20
    assert est.n_civilian_years == 21
    assert est.n_years_counted == 20            # the other 15 are zeros
    assert 2_400 <= est.aime <= 3_100, est.aime
    assert 1_400 <= est.pia <= 1_850, est.pia
    assert est.pia == pytest.approx(SS.pia_from_aime(est.aime))
    assert est.bend_points_year == SS.PARAMETER_YEAR


def test_the_fallback_counts_basic_pay_only():
    """Covered earnings are 12 x basic pay: BAH and BAS carry no FICA."""
    h = sample(E5)
    est = SS.estimate_pia_from_career(h.member, current_year=2026)
    first = est.years[0]
    table = BP.load()
    assert table is not None
    expected = BP.lookup(first.grade, 0.5, table).monthly * 12.0
    assert first.source == "Military"
    assert first.covered == pytest.approx(expected)
    assert first.extra_credit == 0.0            # nothing accrues after 2001
    # This plan has no civilian wage, so those years are the zeros above.
    civ = [y for y in est.years if y.source == "Civilian"]
    assert civ and all(y.covered == 0 for y in civ)
    assert all(y.covered <= SS.TAXABLE_MAXIMUM for y in est.years)


def test_the_o5_sample_earns_pre_2002_extra_credits_and_a_bigger_pia():
    h = sample(O5)
    est = SS.estimate_pia_from_career(h.member, current_year=2026)
    assert est.found
    assert est.n_military_years == 26
    assert est.n_years_counted == 35            # a full record, no zeros
    credited = [y for y in est.years if y.extra_credit > 0]
    assert [y.calendar_year for y in credited] == [1999, 2000, 2001]
    assert all(y.extra_credit == SS.EXTRA_CREDIT_ANNUAL_CAP for y in credited)
    assert est.pia > SS.estimate_pia_from_career(sample(E5).member,
                                                 current_year=2026).pia


def test_more_civilian_years_at_a_real_wage_raise_the_estimate():
    h = sample(E5)
    h.member.civilian_wages_annual = 60_000.0
    few = SS.estimate_pia_from_career(h.member, civilian_years=5, current_year=2026)
    many = SS.estimate_pia_from_career(h.member, civilian_years=15, current_year=2026)
    assert many.pia > few.pia
    assert many.n_years_counted > few.n_years_counted


# ==========================================================================
# The household analysis
# ==========================================================================

@pytest.mark.parametrize("name", SAMPLES)
def test_analyse_runs_on_both_samples_and_is_internally_consistent(name):
    a = SS.analyse(sample(name), current_year=2026)
    assert a.pia > 0
    assert [r.age for r in a.rows] == list(range(62, 71))
    assert a.rows[0].monthly == pytest.approx(a.benefit_at_62)
    assert a.rows[-1].monthly == pytest.approx(a.benefit_at_70)
    assert a.benefit_at_62 < a.benefit_at_fra < a.benefit_at_70
    assert a.rows[-1].annual == pytest.approx(a.rows[-1].monthly * 12)
    assert 62 <= a.best_age_by_life_expectancy <= 70
    assert a.taxation is not None and a.findings


def test_the_statement_figure_wins_over_the_modelled_estimate():
    h = sample(E5)
    h.social_security.estimated_monthly_at_fra = 2_000.0
    a = SS.analyse(h, current_year=2026)
    assert a.pia == pytest.approx(2_000.0)
    assert a.pia_source == SS.SOURCE_STATEMENT
    assert a.benefit_at_62 == pytest.approx(1_400.0)
    assert a.benefit_at_70 == pytest.approx(2_480.0)
    # The estimate is still computed, as a check on the order of magnitude.
    assert a.estimate is not None and a.estimate.found


def test_the_breakeven_framing_uses_the_mortality_table_from_age_62():
    h = sample(E5)
    h.social_security.estimated_monthly_at_fra = 2_000.0
    a = SS.analyse(h, current_year=2026)
    # You only face this decision if you reach 62, so that is what conditions it.
    assert a.conditioning_age == 62
    assert a.life_expectancy == MORT.life_expectancy(62, h.member.sex)
    assert a.planning_age == MORT.planning_age(62, h.member.sex)
    assert a.planning_age > a.life_expectancy
    assert 77.0 <= a.breakeven_62_vs_70 <= 81.0
    assert a.breakeven_62_vs_70_discounted > a.breakeven_62_vs_70
    headline = [f for f in a.findings if "life expectancy" in f[1]]
    assert headline, [f[1] for f in a.findings]
    assert f"life expectancy of {a.life_expectancy}" in headline[0][1]
    assert ("claiming at 70 beats 62" in headline[0][1]
            or "claiming at 62 beats 70" in headline[0][1])


def test_a_spouse_with_no_record_of_their_own_gets_half_of_yours():
    h = sample(E5)
    h.social_security.estimated_monthly_at_fra = 2_000.0
    h.social_security.spouse_estimated_monthly_at_fra = 0.0
    a = SS.analyse(h, current_year=2026)
    assert a.has_spouse
    assert a.spouse_benefit_at_claim == pytest.approx(1_000.0)
    assert a.household_ss_annual == pytest.approx((2_000 + 1_000) * 12)
    # The survivor keeps the larger benefit; the spousal benefit stops.
    assert a.survivor.survivor_receives == pytest.approx(2_000.0)
    assert a.survivor_if_higher_claims_70 == pytest.approx(2_480.0)
    assert a.survivor_if_higher_claims_62 == pytest.approx(1_650.0)   # 82.5% floor


def test_your_own_benefit_can_be_topped_up_on_your_spouses_record():
    h = sample(E5)
    h.social_security.estimated_monthly_at_fra = 1_000.0
    h.social_security.spouse_estimated_monthly_at_fra = 3_000.0
    a = SS.analyse(h, current_year=2026)
    assert a.higher_earner == "your spouse"
    assert a.spousal_for_you.spousal_excess_paid == pytest.approx(500)   # 1,500 - 1,000
    assert a.spousal_for_spouse.spousal_excess_paid == 0.0
    assert a.household_ss_annual == pytest.approx((1_500 + 3_000) * 12)
    # The survivor keeps the larger record, whichever of you it belongs to.
    assert a.survivor.survivor_receives == pytest.approx(3_000)


def test_the_earnings_test_bites_only_when_claiming_early_while_working():
    """$1 withheld for every $2 over the exempt amount, capped at the benefit."""
    h = sample(O5)
    h.social_security.estimated_monthly_at_fra = 3_000.0
    h.social_security.claim_age = 62
    h.member.civilian_wages_annual = 40_000.0
    modest = SS.analyse(h, current_year=2026)
    assert modest.earnings_test_exposed
    assert modest.earnings_test_withheld_annual == pytest.approx(
        (40_000 - SS.EARNINGS_TEST_EXEMPT) * 0.5)

    # More than twice the benefit in excess wages withholds all of it, no more.
    h.member.civilian_wages_annual = 95_000.0
    heavy = SS.analyse(h, current_year=2026)
    assert heavy.earnings_test_withheld_annual == pytest.approx(
        heavy.benefit_at_claim * 12.0)
    assert heavy.earnings_test_withheld_annual < (95_000 - SS.EARNINGS_TEST_EXEMPT) * 0.5

    # At full retirement age there is no test at all.
    h.social_security.claim_age = 67
    assert not SS.analyse(h, current_year=2026).earnings_test_exposed
    # Nor is there one for someone who is not working.
    h.social_security.claim_age = 62
    h.member.civilian_wages_annual = 0.0
    assert not SS.analyse(h, current_year=2026).earnings_test_exposed


def test_the_military_points_are_stated_in_plain_words():
    facts = " ".join(SS.MILITARY_FACTS)
    assert "fully covered" in facts
    assert "WEP and GPO do not apply to military retired pay" in facts
    assert "BAH and BAS are not wages for FICA" in facts
    assert "Roth CONVERSION" in SS.ROTH_NOTE
    assert "provisional income" in SS.ROTH_NOTE
    assert "WITHDRAWAL" in SS.ROTH_NOTE
    a = SS.analyse(sample(E5), current_year=2026)
    assert a.facts == SS.MILITARY_FACTS
    closing = [f for f in a.findings if "Nothing about your service" in f[1]]
    assert closing and "WEP and GPO" in closing[0][2]


def test_the_parameters_carry_their_year_and_a_verification_note():
    assert SS.PARAMETER_YEAR == 2026
    assert "2026" in SS.PARAMETER_NOTE
    assert "ssa.gov" in SS.PARAMETER_NOTE
    assert f"${SS.BEND_POINT_1:,.0f}" in SS.PARAMETER_NOTE
    assert SS.BEND_POINT_1 < SS.BEND_POINT_2 < SS.TAXABLE_MAXIMUM


# ==========================================================================
# The page
# ==========================================================================

PAGE = ROOT / "pages" / "15_Social_Security.py"


def _render(name=None, prepare=None):
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(PAGE), default_timeout=120)
    if name is not None:
        h = sample(name)
        if prepare is not None:
            prepare(h)
        at.session_state[PROFILE_KEY] = h
        at.session_state[VERSION_KEY] = 0
    at.run()
    assert not at.exception, at.exception
    return at


def _prose(at) -> list:
    """Every element on the page that renders markdown, and so needs escaping."""
    return [e for group in (at.markdown, at.caption, at.warning, at.info,
                            at.success, at.error)
            for e in group]


def _body(at) -> str:
    return " ".join(e.value for e in _prose(at))


def test_the_page_renders_with_an_empty_plan():
    at = _render()
    assert at.title[0].value == "🧓 When do I claim Social Security?"
    assert "ssa.gov" in _body(at)


@pytest.mark.parametrize("name", SAMPLES)
def test_the_page_renders_against_both_sample_plans(name):
    at = _render(name)
    body = _body(at)
    assert at.title[0].value == "🧓 When do I claim Social Security?"
    # It tells the user where the real number comes from.
    assert "ssa.gov/myaccount" in body
    # The 62-to-70 table and the cumulative chart.
    assert len(at.dataframe) >= 2
    labels = [mm.label for mm in at.metric]
    assert any(lab.startswith("At 62") for lab in labels)
    assert any(lab.startswith("At 70") for lab in labels)
    assert "Breakeven, 62 vs 70" in labels
    # Both military points, in plain words.
    assert "WEP and GPO do not apply to military retired pay" in body
    assert "BAH and BAS are not wages for FICA" in body
    # The Roth interaction.
    assert "Roth conversions and this benefit" in body
    assert "raises provisional income" in body
    # Dollar figures in prose are escaped for markdown, never raw.
    for element in _prose(at):
        assert "$" not in element.value.replace(r"\$", ""), element.value[:120]


@pytest.mark.parametrize("name", SAMPLES)
def test_the_page_binds_its_inputs_to_the_plan(name):
    at = _render(name)
    at.number_input(key="ss_fra__v0").set_value(2_000.0).run()
    assert not at.exception, at.exception
    at.number_input(key="ss_claim__v0").set_value(70).run()
    assert not at.exception, at.exception

    h = at.session_state[PROFILE_KEY]
    assert h.social_security.estimated_monthly_at_fra == pytest.approx(2_000.0)
    assert h.social_security.claim_age == 70
    assert at.session_state[DIRTY_KEY] is True

    values = {mm.label: mm.value for mm in at.metric}
    assert values["At 62"] == "$1,400/mo"
    assert values["At 70"] == "$2,480/mo"
    assert values["At 70, as planned"] == "$2,480/mo"


def test_the_page_swaps_in_the_ssdi_question_for_a_disabled_spouse():
    at = _render(E5)
    labels = [w.label for w in at.number_input]
    assert any("spouse's statement" in lab for lab in labels)
    at.toggle(key="ss_spssdi__v0").set_value(True).run()
    assert not at.exception, at.exception
    labels = [w.label for w in at.number_input]
    assert any("receive from SSDI" in lab for lab in labels)
    at.number_input(key="ss_spssdiamt__v0").set_value(1_500.0).run()
    assert not at.exception, at.exception
    h = at.session_state[PROFILE_KEY]
    assert h.social_security.spouse_on_ssdi is True
    assert h.social_security.spouse_ssdi_monthly == pytest.approx(1_500.0)
    assert "SSDI simply becomes their retirement benefit" in _body(at)


def test_the_page_warns_when_it_is_running_off_a_modelled_career():
    at = _render(E5)
    warnings = " ".join(w.value for w in at.warning)
    assert "No statement figure yet" in warnings
    assert "modelled career" in warnings
    # The fallback shows its working.
    assert "Estimated PIA" in _body(at)
    at.number_input(key="ss_fra__v0").set_value(2_500.0).run()
    assert not at.exception, at.exception
    assert "No statement figure yet" not in " ".join(w.value for w in at.warning)


def test_the_page_flags_an_early_claim_and_the_earnings_test():
    at = _render(O5)
    at.number_input(key="ss_fra__v0").set_value(3_000.0).run()
    at.number_input(key="ss_claim__v0").set_value(62).run()
    assert not at.exception, at.exception
    body = _body(at)
    assert "locks in a 30% cut for life" in body
    assert "earnings test" in body


def test_the_page_shows_the_top_up_running_the_other_way():
    def prepare(h):
        h.social_security.estimated_monthly_at_fra = 1_200.0
        h.social_security.spouse_estimated_monthly_at_fra = 3_000.0
    at = _render(E5, prepare)
    body = _body(at)
    assert "your spouse out-earns you here" in body
    assert "topped up by" in body


def test_the_page_survives_a_missing_pay_table(monkeypatch):
    """No statement, no pay table: the page asks for the statement figure."""
    monkeypatch.setattr(BP, "load", lambda *a, **k: None)
    at = _render(E5)
    body = _body(at)
    assert "There is nothing to work from yet" in body
    assert "ssa.gov" in body
    assert "Enter a statement figure for at least one of you" in body

    # A spouse figure on its own is still enough to draw the spousal picture.
    with_spouse = _render(E5, lambda h: setattr(
        h.social_security, "spouse_estimated_monthly_at_fra", 1_800.0))
    assert "nothing for them to be topped up from" in _body(with_spouse)
