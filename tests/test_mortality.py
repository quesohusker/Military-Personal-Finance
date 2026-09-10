import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

from engine import mortality as M


def test_expected_age_at_death_rises_with_age():
    """Survivorship: having reached 70 you are expected to outlive a 30-year-old's expectation."""
    ages = [25, 40, 55, 65, 75, 85]
    deaths = [M.life_expectancy(a) for a in ages]
    assert deaths == sorted(deaths)
    assert M.life_expectancy(85) > M.life_expectancy(30)


def test_remaining_years_fall_with_age():
    t = M.load()
    rem = [t.remaining(a) for a in range(20, 100, 5)]
    assert rem == sorted(rem, reverse=True)


def test_women_outlive_men_at_every_age():
    for a in range(20, 100, 5):
        assert M.life_expectancy(a, M.SEX_FEMALE) >= M.life_expectancy(a, M.SEX_MALE)


def test_unspecified_sex_is_the_midpoint():
    t = M.load()
    for a in (30, 50, 70):
        mid = (t.remaining(a, M.SEX_MALE) + t.remaining(a, M.SEX_FEMALE)) / 2
        assert t.remaining(a) == pytest.approx(mid)


def test_interpolation_between_anchors_is_monotone():
    t = M.load()
    assert t.remaining(50) > t.remaining(52) > t.remaining(55)


def test_ages_outside_the_table_clamp_rather_than_crash():
    t = M.load()
    # Clamp to whatever the loaded table actually covers: the published SSA
    # table runs to 119, the built-in fallback stops at 110.
    lo, hi = min(t.male), max(t.male)
    assert t.remaining(lo - 5) == t.remaining(lo)
    assert t.remaining(hi + 30) == t.remaining(hi)


def test_planning_age_sits_past_the_median():
    """Half of people outlive the median; a plan that ends there fails half the time."""
    assert M.planning_age(50) == M.life_expectancy(50) + M.LONGEVITY_MARGIN_YEARS


def test_builtin_table_passes_its_own_shape_checks():
    M.check(M._BUILTIN_MALE, M._BUILTIN_FEMALE)


def test_shape_check_refuses_an_inverted_table():
    """A column shifted by one parses fine and is wrong for every user."""
    male = {a: v for a, v in M._BUILTIN_MALE.items()}
    inverted = {a: male[110 - a] if (110 - a) in male else v for a, v in male.items()}
    with pytest.raises(M.LifeTableError):
        M.check(inverted, M._BUILTIN_FEMALE)


def test_shape_check_refuses_female_below_male():
    female = {a: v - 10 for a, v in M._BUILTIN_MALE.items()}
    female = {a: max(0.5, v) for a, v in female.items()}
    with pytest.raises(M.LifeTableError):
        M.check(M._BUILTIN_MALE, female)


def test_shape_check_refuses_an_absurd_starting_expectancy():
    male = dict(M._BUILTIN_MALE); male[0] = 40.0
    male = {a: min(v, 40.0) for a, v in male.items()}
    with pytest.raises(M.LifeTableError):
        M.check(male, M._BUILTIN_FEMALE)


def test_builtin_is_flagged_as_not_authoritative():
    """The pages tell the user which table they are looking at."""
    t = M.load()
    if not M.DATA_PATH.exists():
        assert not t.authoritative
        assert "approximate" in t.source.lower()
        assert "import_life_table" in M.explain(40)


def test_explain_names_the_coin_flip():
    assert "half" in M.explain(45, M.SEX_MALE).lower()
