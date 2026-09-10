"""
Tests for the VA loan, the PCS-horizon rent-versus-buy comparison, and the
disabled-veteran property tax table.

Directions, not dollars, wherever the answer depends on an assumption: the
funding fee schedule is statutory and is asserted exactly, but "buying wins at
ten years" is asserted as a sign, because the size of the win moves with every
input on the page.
"""

import sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from engine.housing import va_loan as VL
from engine.housing import rent_vs_buy as RB
from engine import storage
from ui.panel import PROFILE_KEY, VERSION_KEY, DIRTY_KEY

PAGE = ROOT / "pages" / "19_Home_and_VA_Loan.py"
SAMPLES = [ROOT / "samples" / "e5_6yrs_brs.mpfplan.json",
           ROOT / "samples" / "retired_o5_26yrs.mpfplan.json"]


# ==========================================================================
# The funding fee
# ==========================================================================

def test_first_use_fee_tiers_by_down_payment():
    """2.15% under 5% down, 1.50% at 5-10%, 1.25% at 10% or more."""
    assert VL.funding_fee_rate(0.0) == pytest.approx(0.0215)
    assert VL.funding_fee_rate(4.99) == pytest.approx(0.0215)
    assert VL.funding_fee_rate(5.0) == pytest.approx(0.0150)
    assert VL.funding_fee_rate(9.99) == pytest.approx(0.0150)
    assert VL.funding_fee_rate(10.0) == pytest.approx(0.0125)
    assert VL.funding_fee_rate(25.0) == pytest.approx(0.0125)


def test_subsequent_use_costs_more_but_only_under_five_percent_down():
    assert VL.funding_fee_rate(0.0, subsequent_use=True) == pytest.approx(0.0330)
    assert VL.funding_fee_rate(0.0, subsequent_use=True) > VL.funding_fee_rate(0.0)
    # At 5% and 10% down the two schedules converge -- the part people miss.
    assert VL.funding_fee_rate(5.0, subsequent_use=True) == VL.funding_fee_rate(5.0)
    assert VL.funding_fee_rate(10.0, subsequent_use=True) == VL.funding_fee_rate(10.0)


def test_the_four_hundred_thousand_dollar_case():
    """The headline range: $8,600 first use, $13,200 subsequent, on $400,000."""
    first = VL.funding_fee(400_000, 0.0, subsequent_use=False)
    later = VL.funding_fee(400_000, 0.0, subsequent_use=True)
    assert first.amount == pytest.approx(8_600.0)
    assert later.amount == pytest.approx(13_200.0)
    assert later.amount > first.amount


@pytest.mark.parametrize("rating", [10, 30, 50, 70, 100])
def test_a_service_connected_rating_of_ten_percent_zeroes_the_fee(rating):
    f = VL.funding_fee(400_000, 0.0, subsequent_use=True, va_rating=rating)
    assert f.exempt is True
    assert f.rate == 0.0
    assert f.amount == 0.0
    # And the page can say what the waiver was worth.
    assert f.exemption_worth == pytest.approx(13_200.0)
    assert f.exempt_reason == VL.EXEMPT_RATED


def test_a_rating_below_ten_percent_does_not_exempt():
    f = VL.funding_fee(400_000, 0.0, va_rating=0)
    assert f.exempt is False and f.amount == pytest.approx(8_600.0)
    assert VL.funding_fee(400_000, 0.0, va_rating=5).exempt is False


def test_surviving_spouse_and_purple_heart_are_exempt_too():
    assert VL.funding_fee(400_000, 0.0, is_surviving_spouse=True).exempt
    assert VL.funding_fee(400_000, 0.0,
                          purple_heart_on_active_duty=True).exempt
    assert VL.exemption(0, is_surviving_spouse=True).reason == VL.EXEMPT_SURVIVING_SPOUSE
    assert VL.exemption(0, purple_heart_on_active_duty=True).reason == VL.EXEMPT_PURPLE_HEART
    # "Entitled to receive" covers compensation offset by retired pay.
    assert VL.exemption(0, receives_va_compensation=True).exempt


def test_financing_the_fee_raises_the_payment_and_the_interest():
    f = VL.funding_fee(400_000, 0.0, rate_pct=6.5, years=30.0, finance_it=True)
    assert f.financed_loan_amount == pytest.approx(408_600.0)
    assert f.extra_payment_monthly > 0
    # Borrowed at the mortgage rate for thirty years, the interest on the fee
    # exceeds the fee itself.
    assert f.extra_interest_over_term > f.amount
    cash = VL.funding_fee(400_000, 0.0, rate_pct=6.5, finance_it=False)
    assert cash.financed_loan_amount == pytest.approx(400_000.0)
    assert cash.extra_interest_over_term == 0.0


def test_no_pmi_is_worth_more_than_the_fee_at_zero_down():
    fee = VL.funding_fee(400_000, 0.0)
    pmi = VL.pmi_saving(400_000, 400_000, 6.5, 30.0)
    assert pmi.monthly > 0
    assert 0 < pmi.months_until_78_ltv < 30 * 12
    assert pmi.total_paid > fee.amount
    # A conventional loan at 80% LTV carries no PMI, so nothing is saved.
    assert VL.pmi_saving(320_000, 400_000, 6.5).total_paid == 0.0


# ==========================================================================
# Entitlement
# ==========================================================================

def test_full_entitlement_has_no_loan_limit():
    e = VL.entitlement()
    assert e.full is True
    assert e.max_zero_down_loan is None
    assert e.basic == 36_000.0
    assert e.bonus > 0
    assert e.total == pytest.approx(VL.FIGURES["conforming_limit_2026"] * 0.25)


def test_partial_entitlement_caps_the_next_zero_down_purchase():
    e = VL.entitlement(prior_loan_balance=250_000)
    assert e.full is False
    assert e.used == pytest.approx(62_500.0)
    assert e.max_zero_down_loan is not None
    assert e.max_zero_down_loan == pytest.approx((e.total - 62_500.0) * 4.0)
    assert e.max_zero_down_loan < VL.FIGURES["conforming_limit_2026"]


# ==========================================================================
# Assumability
# ==========================================================================

def test_assumability_is_worth_nothing_when_rates_match():
    a = VL.assumability_value(280_000, 25, 6.5, 6.5)
    assert abs(a.value) < 1.0
    assert abs(a.monthly_saving) < 0.01


def test_assumability_value_rises_with_the_rate_gap():
    values = [VL.assumability_value(280_000, 25, 2.125, mkt).value
              for mkt in (2.125, 3.5, 5.0, 6.5, 8.0)]
    assert values == sorted(values)
    assert values[0] < 1.0
    assert values[-1] > values[1] > 0


def test_assumability_value_rises_with_the_remaining_term():
    values = [VL.assumability_value(280_000, yrs, 2.125, 6.5).value
              for yrs in (2, 5, 10, 20, 25, 28)]
    assert values == sorted(values)
    assert values[-1] > values[0] * 5


def test_a_low_rate_loan_is_a_six_figure_asset():
    """$280,000 at 2.125% with 25 years left, in a 6.5% market."""
    a = VL.assumability_value(280_000, 25, 2.125, 6.5, home_value=420_000)
    assert a.monthly_saving > 600
    assert 80_000 < a.value < 130_000
    assert a.value_pct_of_balance > 0.30
    # The seller's entitlement stays tied up, and the page must say so.
    assert a.entitlement_at_risk == pytest.approx(70_000.0)
    joined = " ".join(a.notes).lower()
    assert "entitlement" in joined and "substitut" in joined
    assert a.buyer_cash_needed == pytest.approx(140_000.0)


# ==========================================================================
# Never prepay a cheap loan
# ==========================================================================

def test_prepay_verdict_flips_on_the_rate_against_the_expected_return():
    # 4% real and 2.5% inflation is 6.6% nominal, not 6.5%.
    cheap = VL.prepay_verdict(2.75, real_return_pct=4.0, inflation_pct=2.5)
    dear = VL.prepay_verdict(9.0, real_return_pct=4.0, inflation_pct=2.5)
    assert cheap.prepay_wins is False
    assert dear.prepay_wins is True
    assert cheap.expected_nominal_return_pct == pytest.approx(6.6, abs=0.01)
    assert "Do not prepay" in cheap.verdict
    assert cheap.spread_pct > 0 and dear.spread_pct < 0


def test_prepay_verdict_is_decided_against_the_nominal_return_not_the_real_one():
    """A 5% mortgage beats a 4% REAL return only if you forget inflation."""
    v = VL.prepay_verdict(5.0, real_return_pct=4.0, inflation_pct=2.5)
    assert v.expected_nominal_return_pct > 5.0
    assert v.prepay_wins is False


def test_prepay_puts_numbers_on_the_loss():
    v = VL.prepay_verdict(2.75, 4.0, 2.5, balance=280_000, years_left=25,
                          extra_monthly=500.0)
    assert v.value_if_invested > v.value_if_prepaid > 0
    assert v.difference > 0
    assert any("$" in n for n in v.notes)


# ==========================================================================
# IRRRL
# ==========================================================================

def test_irrrl_fee_is_half_a_point_and_is_waived_when_rated():
    plain = VL.irrrl(300_000, 25, 6.5, 5.0, va_rating=0, other_closing_costs=0.0)
    assert plain.funding_fee_rate == pytest.approx(0.005)
    assert plain.funding_fee_amount == pytest.approx(1_500.0)

    rated = VL.irrrl(300_000, 25, 6.5, 5.0, va_rating=10, other_closing_costs=0.0)
    assert rated.exempt is True
    assert rated.funding_fee_amount == 0.0
    assert rated.monthly_saving > plain.monthly_saving


def test_irrrl_break_even_exists_only_when_the_rate_actually_falls():
    up = VL.irrrl(300_000, 25, 5.0, 6.5, va_rating=0)
    assert up.break_even_months is None and up.worth_it is False
    down = VL.irrrl(300_000, 25, 6.5, 4.5, va_rating=0)
    assert down.break_even_months is not None and down.break_even_months > 0


# ==========================================================================
# Rent versus buy
# ==========================================================================

def test_rent_is_capped_at_one_hundred_and_five_percent_of_bah():
    rent, capped = RB.effective_rent(2_600.0, 2_000.0)
    assert rent == pytest.approx(2_100.0) and capped is True
    rent, capped = RB.effective_rent(1_500.0, 2_000.0)
    assert rent == pytest.approx(1_500.0) and capped is False
    # No rent entered: fall back to the allowance.
    rent, capped = RB.effective_rent(0.0, 2_000.0)
    assert rent == pytest.approx(2_100.0)


def _pcs_case(**kw):
    """A representative purchase near a base in a 6.5% market."""
    args = dict(price=320_000, mortgage_rate_pct=6.5, monthly_rent=2_000.0,
                bah_monthly=2_500.0, appreciation_pct=3.0, inflation_pct=2.5,
                real_return_pct=4.0, horizon_years=3.0, max_years=20)
    args.update(kw)
    price = args.pop("price")
    rate = args.pop("mortgage_rate_pct")
    return RB.compare(price, rate, **args)


def test_three_years_favours_renting_and_ten_years_favours_buying():
    r = _pcs_case()
    assert RB.advantage_at(r, 3) < 0, "a three-year tour does not break even"
    assert RB.advantage_at(r, 10) > 0, "a decade does"
    assert r.break_even_years is not None
    assert 3 < r.break_even_years < 10


def test_the_verdict_follows_the_horizon():
    short = _pcs_case(horizon_years=3.0)
    assert short.buy_wins_at_horizon is False
    assert "Rent" in short.verdict

    long = _pcs_case(horizon_years=10.0)
    assert long.buy_wins_at_horizon is True
    assert "Buy" in long.verdict
    # Same house, same market: only the horizon changed.
    assert short.break_even_years == pytest.approx(long.break_even_years)


def test_selling_costs_are_what_kill_the_short_horizon():
    dear = _pcs_case(selling_cost_pct=8.0)
    cheap = _pcs_case(selling_cost_pct=0.0)
    assert cheap.break_even_years < dear.break_even_years
    assert RB.advantage_at(cheap, 3) > RB.advantage_at(dear, 3)


def test_appreciation_moves_the_break_even_the_way_you_expect():
    flat = _pcs_case(appreciation_pct=0.0)
    hot = _pcs_case(appreciation_pct=6.0)
    assert hot.break_even_years is not None
    assert flat.break_even_years is None or flat.break_even_years > hot.break_even_years


def test_the_horizon_table_is_one_row_a_year_and_builds_equity():
    r = _pcs_case(max_years=15)
    assert [row.year for row in r.rows] == list(range(1, 16))
    assert r.rows[-1].mortgage_balance < r.rows[0].mortgage_balance
    assert r.rows[-1].equity > r.rows[0].equity
    assert r.upfront_cash > 0
    assert r.monthly_all_in > r.monthly_piti > r.monthly_pi


def test_the_military_traps_are_all_stated():
    joined = " ".join(_pcs_case().notes).lower()
    assert "three-year tour" in joined
    assert "landlord" in joined
    assert "section 121" in joined and "suspend" in joined
    assert "verify" in joined


def test_a_zero_price_does_not_blow_up():
    r = RB.compare(0.0, 6.5, monthly_rent=1_500.0, bah_monthly=2_000.0)
    assert r.rows == [] and r.break_even_years is None
    assert RB.advantage_at(r, 3) == 0.0
    assert r.notes


# ==========================================================================
# Disabled-veteran property tax exemptions
# ==========================================================================

def test_texas_at_one_hundred_percent_is_a_full_homestead_exemption():
    e = RB.lookup("Texas", 100)
    assert e is not None
    assert e.qualifies is True and e.full_exemption is True
    assert e.kind == "full"
    assert e.saving(6_000.0, 400_000.0) == pytest.approx(6_000.0)
    assert "11.131" in e.citation


def test_texas_below_one_hundred_percent_is_a_small_flat_amount():
    schedule = {10: 5_000.0, 30: 7_500.0, 50: 10_000.0, 70: 12_000.0}
    for rating, amount in schedule.items():
        e = RB.lookup("Texas", rating)
        assert e.qualifies and not e.full_exemption
        assert e.exempt_value == pytest.approx(amount)
    # And it is worth very little: $12,000 off a $400,000 house.
    partial = RB.lookup("TX", 70)
    assert partial.saving(6_000.0, 400_000.0) == pytest.approx(180.0)


def test_a_rating_below_the_schedule_does_not_qualify():
    e = RB.lookup("Texas", 0)
    assert e is not None and e.qualifies is False
    assert e.saving(6_000.0, 400_000.0) == 0.0


def test_an_unknown_state_returns_none_rather_than_a_guess():
    assert RB.lookup("Freedonia", 100) is None
    assert RB.lookup("", 100) is None
    assert RB.lookup("Wyoming", 100) is None      # not in the table yet
    assert RB.normalise_state("Freedonia") is None


def test_state_names_and_codes_both_resolve():
    for name in ("TX", "tx", "Texas", "TEXAS", " texas "):
        e = RB.lookup(name, 100)
        assert e is not None and e.state_code == "TX"
    assert "Texas" in RB.states_covered()


def test_every_entry_in_the_table_carries_a_citation_and_a_confidence():
    for code, entry in RB.STATE_EXEMPTIONS.items():
        assert entry["citation"].strip(), code
        assert entry["confidence"].strip(), code
        assert entry["schedule"], code
        for lo, hi, kind, amount, description in entry["schedule"]:
            assert 0 <= lo <= hi <= 100, code
            assert kind in ("full", "amount", "percent"), code
            assert description.strip(), code
    # And every lookup carries the incompleteness warning with it.
    assert "INCOMPLETE" in RB.lookup("Texas", 100).verify


# ==========================================================================
# Findings
# ==========================================================================

def test_findings_lead_with_the_waived_fee():
    fee = VL.funding_fee(400_000, 0.0, subsequent_use=True, va_rating=100)
    out = VL.findings(fee=fee, va_rating=100)
    assert out[0][0] == "good"
    assert "waived" in out[0][1].lower()
    assert "13,200" in out[0][2]


def test_findings_warn_when_a_short_tour_will_not_break_even():
    r = _pcs_case(horizon_years=3.0)
    out = RB.findings(r, 3.0)
    assert any(sev == "warn" for sev, _, _ in out)
    assert any("121" in detail for _, _, detail in out)


# ==========================================================================
# The page
# ==========================================================================

def _render(sample: pathlib.Path | None = None):
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(PAGE), default_timeout=120)
    if sample is not None:
        h = storage.from_upload_bytes(sample.read_bytes())
        at.session_state[PROFILE_KEY] = h
        at.session_state[VERSION_KEY] = 0
        at.session_state[DIRTY_KEY] = False
    at.run()
    assert not at.exception, at.exception
    return at


def _body(at) -> str:
    """Everything the page actually printed: prose, alerts, captions, metrics."""
    parts = [e.value for e in at.markdown]
    parts += [e.value for e in at.caption]
    for kind in (at.success, at.info, at.warning, at.error):
        parts += [e.value for e in kind]
    for e in at.metric:
        parts += [e.label, e.value]
    return " ".join(str(p) for p in parts)


def test_page_renders_from_an_empty_plan():
    at = _render()
    assert "Buy, rent, or keep the house?" in at.title[0].value
    body = _body(at)
    assert "funding fee" in body.lower()


@pytest.mark.parametrize("sample", SAMPLES, ids=lambda p: p.stem)
def test_page_renders_against_both_sample_plans(sample):
    at = _render(sample)
    body = _body(at)
    assert "entitlement" in body.lower()
    assert "landlord" in body.lower()


def test_page_prices_the_o5_low_rate_loan_as_an_asset():
    """The retired O-5 sample: $280,000 outstanding, 2.125%, 25 years left."""
    at = _render(SAMPLES[1])
    h = at.session_state[PROFILE_KEY]
    h.housing.owns_home = True
    h.housing.is_va_loan = True
    h.housing.mortgage_rate_pct = 2.125
    h.housing.mortgage_years_left = 25.0
    at.run()
    assert not at.exception, at.exception

    body = _body(at)
    assert "assume" in body.lower()
    # 100% rated, so no funding fee anywhere on the page.
    assert "waived" in body.lower() or "no funding fee" in body.lower()
    # And Michigan at 100% is a full homestead exemption.
    assert "homestead" in body.lower()


def test_page_writes_its_inputs_back_into_the_plan():
    at = _render(SAMPLES[0])
    at.number_input(key="hs_rate__v0").set_value(2.75).run()
    assert not at.exception, at.exception
    h = at.session_state[PROFILE_KEY]
    assert h.housing.mortgage_rate_pct == pytest.approx(2.75)
    assert at.session_state[DIRTY_KEY] is True

    at.number_input(key="hs_value__v0").set_value(350_000.0).run()
    assert not at.exception, at.exception
    assert at.session_state[PROFILE_KEY].home_value == pytest.approx(350_000.0)


def test_page_shows_the_exemption_for_a_rated_member():
    at = _render(SAMPLES[0])
    h = at.session_state[PROFILE_KEY]
    h.member.va_rating = 0
    at.run()
    unrated = _body(at)

    h = at.session_state[PROFILE_KEY]
    h.member.va_rating = 10
    at.run()
    assert not at.exception, at.exception
    rated = _body(at)

    assert "no funding fee" in rated.lower()
    assert rated != unrated
