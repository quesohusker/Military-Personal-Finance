import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

from engine.pay import taxable as TX
from engine.pay import basepay as BP
from engine.profile import ServiceMember, ACTIVE, RETIRED


def _e5():
    return ServiceMember(component=ACTIVE, grade="E-5", years_of_service=6.0)


def test_basic_pay_comes_from_the_table_when_no_les_override():
    t = TX.compute(_e5())
    assert t.basic_source == TX.SOURCE_TABLE
    assert t.basic_monthly == pytest.approx(4_110.0)
    assert t.annual == pytest.approx(4_110.0 * 12)


def test_les_override_beats_the_table():
    m = _e5(); m.basic_pay_monthly_override = 5_000.0
    t = TX.compute(m)
    assert t.basic_source == TX.SOURCE_LES
    assert t.basic_monthly == 5_000.0


def test_taxable_special_pay_is_monthly_times_twelve():
    m = _e5(); m.special_pay_monthly = 675.0; m.special_pay_taxable = True
    assert TX.compute(m).annual == pytest.approx((4_110.0 + 675.0) * 12)


def test_nontaxable_special_pay_is_excluded_and_noted():
    m = _e5(); m.special_pay_monthly = 675.0; m.special_pay_taxable = False
    t = TX.compute(m)
    assert t.annual == pytest.approx(4_110.0 * 12)
    assert any("non-taxable" in n for n in t.notes)


def test_bonus_is_annual_not_monthly():
    """A $20,000 re-enlistment bonus adds $20,000, not $240,000."""
    m = _e5(); m.bonus_annual_taxable = 20_000.0
    assert TX.compute(m).annual == pytest.approx(4_110.0 * 12 + 20_000.0)


def test_bah_and_bas_never_enter_the_figure():
    m = _e5(); m.bah_monthly_override = 2_000.0; m.bas_monthly_override = 465.0
    assert TX.compute(m).annual == pytest.approx(4_110.0 * 12)


def test_a_retiree_has_no_military_pay_but_has_retired_pay():
    m = ServiceMember(component=RETIRED, grade="O-5", years_of_service=26.0,
                      retired_pay_monthly=8_056.62)
    t = TX.compute(m)
    assert t.basic_monthly == 0.0
    assert t.basic_source == TX.SOURCE_NOT_SERVING
    assert TX.annual_retired_pay(m) == pytest.approx(8_056.62 * 12)


def test_unknown_grade_is_reported_not_guessed():
    m = _e5(); m.grade = "E-5"; m.years_of_service = 6.0
    m.basic_pay_monthly_override = 0.0
    r = BP.lookup("Z-9", 6.0, BP.load())
    assert not r.found
    m.grade = "Z-9"
    t = TX.compute(m)
    assert t.basic_monthly == 0.0
    assert any("could not be looked up" in n for n in t.notes)


def test_describe_lists_every_component():
    m = _e5(); m.special_pay_monthly = 100.0; m.bonus_annual_taxable = 5_000.0
    d = TX.compute(m).describe()
    assert "Basic pay" in d and "special pays" in d and "Bonuses" in d
    assert "BAH and BAS are not in it" in d


def test_a_retiree_gets_a_sentence_not_a_zero_sum():
    m = ServiceMember(component=RETIRED, grade="O-5", years_of_service=26.0,
                      retired_pay_monthly=8_056.62)
    t = TX.compute(m)
    assert not t.serving
    assert t.lines() == []
    assert "not serving" in t.describe()
    assert "x 12" not in t.describe()
