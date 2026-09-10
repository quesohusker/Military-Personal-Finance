import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

from engine.profile import Household, ServiceMember, ACTIVE, RETIRED
from engine.debt.payoff import Debt
from engine.networth import balance_sheet as BS


def retiree() -> Household:
    h = Household()
    h.member = ServiceMember(birth_year=1975, component=RETIRED, grade="O-5",
                             retired_pay_monthly=7276, va_disability_monthly=4000,
                             tsp_traditional_balance=700_000,
                             tsp_roth_balance=100_000)
    h.cash_savings = 60_000
    h.taxable_brokerage = 250_000
    h.home_value = 420_000
    h.mortgage_balance = 280_000
    return h


# ==========================================================================
# Annuity valuation
# ==========================================================================

def test_annuity_pv_is_less_than_the_undiscounted_total():
    pv = BS.annuity_present_value(50_000, 30, 0.03)
    assert 0 < pv < 50_000 * 30


def test_a_zero_discount_rate_gives_the_simple_total():
    assert BS.annuity_present_value(50_000, 30, 0.0) == pytest.approx(1_500_000)


def test_a_higher_discount_rate_lowers_the_value():
    assert (BS.annuity_present_value(50_000, 30, 0.06)
            < BS.annuity_present_value(50_000, 30, 0.02))


def test_deferring_an_annuity_lowers_its_value():
    now = BS.annuity_present_value(50_000, 20, 0.03)
    later = BS.annuity_present_value(50_000, 20, 0.03, deferral_years=10)
    assert later < now


def test_no_payment_or_no_years_is_worth_nothing():
    assert BS.annuity_present_value(0, 30) == 0
    assert BS.annuity_present_value(50_000, 0) == 0


# ==========================================================================
# Balance sheet arithmetic
# ==========================================================================

def test_net_worth_is_assets_less_liabilities():
    bs = BS.from_household(retiree())
    assert bs.net_worth == pytest.approx(bs.total_assets - bs.total_liabilities)


def test_embedded_tax_reduces_net_worth():
    bs = BS.from_household(retiree())
    assert bs.embedded_tax > 0
    assert bs.net_worth_after_tax == pytest.approx(bs.net_worth - bs.embedded_tax)


def test_only_pretax_balances_carry_embedded_tax():
    bs = BS.BalanceSheet(tsp_roth=500_000, ira_roth=100_000)
    assert bs.embedded_tax == 0
    assert bs.net_worth_after_tax == bs.net_worth


def test_investable_assets_exclude_the_house_and_cars():
    bs = BS.from_household(retiree())
    assert bs.home_value > 0
    assert bs.investable_assets < bs.total_assets
    assert bs.investable_assets == pytest.approx(
        bs.liquid_assets + bs.retirement_assets)


def test_liquid_net_worth_ignores_the_mortgage():
    h = retiree()
    bs = BS.from_household(h)
    assert bs.liquid_net_worth == pytest.approx(
        bs.investable_assets - bs.consumer_debt - bs.vehicle_debt)


def test_home_equity():
    bs = BS.from_household(retiree())
    assert bs.home_equity == pytest.approx(420_000 - 280_000)


def test_debts_are_routed_to_the_right_liability_bucket():
    h = retiree()
    h.debts = [Debt("Visa", 5_000, 0.22, 150, "Credit card"),
               Debt("Truck", 22_000, 0.07, 480, "Auto loan"),
               Debt("Student", 12_000, 0.05, 140, "Student loan — federal")]
    bs = BS.from_household(h)
    assert bs.consumer_debt == 5_000
    assert bs.vehicle_debt == 22_000
    assert bs.other_debt == 12_000


# ==========================================================================
# The pension as an asset -- the part civilian tools omit
# ==========================================================================

def test_pension_and_va_are_valued_as_streams():
    bs = BS.from_household(retiree(), life_expectancy=90, current_year=2026)
    labels = [s.label for s in bs.streams]
    assert "Military retired pay" in labels
    assert "VA disability compensation" in labels
    assert bs.streams_present_value > 0


def test_va_compensation_is_marked_tax_free():
    bs = BS.from_household(retiree())
    va = next(s for s in bs.streams if "VA" in s.label)
    assert not va.is_taxable
    pension = next(s for s in bs.streams if "retired pay" in s.label)
    assert pension.is_taxable


def test_streams_can_exceed_the_entire_portfolio():
    """The finding that reframes a military retiree's balance sheet."""
    bs = BS.from_household(retiree())
    assert bs.streams_present_value > bs.investable_assets
    assert bs.net_worth_with_streams > bs.net_worth_after_tax


def test_an_active_duty_member_has_no_pension_stream_yet():
    h = Household()
    h.member = ServiceMember(component=ACTIVE, grade="E-5", retired_pay_monthly=0)
    bs = BS.from_household(h)
    assert bs.streams == []
    assert bs.streams_present_value == 0


def test_a_longer_life_expectancy_raises_the_pension_value():
    short = BS.from_household(retiree(), life_expectancy=80)
    long = BS.from_household(retiree(), life_expectancy=95)
    assert long.streams_present_value > short.streams_present_value


def test_streams_are_worth_nothing_past_life_expectancy():
    bs = BS.from_household(retiree(), life_expectancy=40, current_year=2026)
    assert bs.streams_present_value == 0


# ==========================================================================
# Findings
# ==========================================================================

def test_negative_net_worth_is_called_out():
    h = Household()
    h.member = ServiceMember(component=ACTIVE, grade="E-4")
    h.debts = [Debt("Truck", 30_000, 0.14, 600, "Auto loan")]
    h.vehicles_value = 18_000
    out = BS.findings(BS.from_household(h), h)
    assert any(s == "bad" and "net worth" in head.lower() for s, head, _ in out)


def test_underwater_vehicle_is_flagged_with_the_mla():
    h = Household()
    h.member = ServiceMember(component=ACTIVE, grade="E-4")
    h.vehicles_value = 15_000
    h.debts = [Debt("Truck", 28_000, 0.18, 620, "Auto loan")]
    out = BS.findings(BS.from_household(h), h)
    detail = " ".join(d for _, _, d in out)
    assert "36%" in detail


def test_underwater_home_warns_about_a_pcs():
    h = retiree()
    h.home_value = 250_000
    h.mortgage_balance = 300_000
    out = BS.findings(BS.from_household(h), h)
    assert any("underwater" in head.lower() for _, head, _ in out)
    assert "PCS" in " ".join(d for _, _, d in out)


def test_pretax_concentration_is_flagged_against_the_pension_floor():
    out = BS.findings(BS.from_household(retiree()), retiree())
    detail = " ".join(d for _, _, d in out)
    assert "pre-tax" in " ".join(h for _, h, _ in out).lower()
    assert "taxable income floor" in detail


def test_consumer_debt_exceeding_savings_is_flagged():
    h = Household()
    h.member = ServiceMember(component=ACTIVE, grade="E-5")
    h.cash_savings = 500
    h.debts = [Debt("Visa", 6_000, 0.24, 180, "Credit card")]
    out = BS.findings(BS.from_household(h), h)
    assert any("liquid savings" in head for _, head, _ in out)


# ==========================================================================
# The valuation caveat
#
# Putting a pension on a balance sheet is a contested practice. These tests
# exist so the caveat cannot quietly disappear in a refactor -- an unqualified
# "your pension is worth $2M" is exactly the overclaim this module must not make.
# ==========================================================================

def test_caveat_states_there_is_no_cash_value():
    c = BS.VALUATION_CAVEAT
    assert "no cash-out value" in c
    assert "cannot sell it" in c
    assert "leave it to an heir" in c


def test_caveat_states_you_could_not_buy_one_either():
    assert "cannot buy one" in BS.VALUATION_CAVEAT
    assert "at any price" in BS.VALUATION_CAVEAT


def test_caveat_concedes_the_practice_is_contested():
    assert "not a universally accepted practice" in BS.VALUATION_CAVEAT
    assert "objections are fair" in BS.VALUATION_CAVEAT


def test_caveat_explains_what_the_number_is_good_for_and_not():
    c = BS.VALUATION_CAVEAT
    assert "what it would cost to buy" in c
    assert "Do not" in c and "withdrawal-rate" in c


def test_short_caveat_travels_with_the_pension_stream():
    """The caveat must reach anyone reading a single stream, not just the page."""
    bs = BS.from_household(retiree())
    pension = next(s for s in bs.streams if "retired pay" in s.label)
    assert "not a cash value" in pension.note
    assert "borrow against" in pension.note


def test_the_headline_finding_says_replacement_cost_not_worth():
    """'Your pension is worth $2M' is the overclaim. 'Replacing it would cost' is not."""
    out = BS.findings(BS.from_household(retiree()), retiree())
    heads = [h for _, h, _ in out]
    assert any("Replacing your guaranteed income would cost" in h for h in heads)
    assert not any("guaranteed income is worth" in h for h in heads)


def test_the_finding_repeats_the_caveat_inline():
    out = BS.findings(BS.from_household(retiree()), retiree())
    detail = " ".join(d for _, _, d in out)
    assert "not a cash value" in detail
    assert "Not every advisor" in detail


def test_replacement_cost_is_an_alias_for_present_value():
    bs = BS.from_household(retiree())
    for s in bs.streams:
        assert s.replacement_cost == s.present_value
