"""
Tests for the pay engine.

The BAH parser is tested against synthetic fixtures shaped like the DTMO ASCII
files. The point is not that it parses -- it is that it REFUSES to parse
anything whose shape it does not recognise, because a rate table that is
misaligned by one column produces entirely plausible, entirely wrong numbers.
"""

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import json
import pytest

from engine.pay import grades as G
from engine.pay import bas
from engine.pay import bah


# ==========================================================================
# Grades
# ==========================================================================

def test_every_grade_code_is_unique():
    codes = [g.code for g in G.GRADES]
    assert len(codes) == len(set(codes))


def test_grade_lookup_accepts_the_forms_people_type():
    for form in ("E-5", "e5", "E05", "E5"):
        assert G.get(form).label == "E-5"


def test_prior_enlisted_officer_grades_exist():
    """A mustang paid on the O-1E line is invisible if these are missing."""
    for label in ("O-1E", "O-2E", "O-3E"):
        g = G.get(label)
        assert g.category == G.OFFICER_PRIOR_ENLISTED
    assert G.get("O-3E").code == "O03E"
    assert G.get("O-3").code == "O03"


def test_unknown_grade_raises():
    with pytest.raises(KeyError):
        G.get("E-99")
    with pytest.raises(KeyError):
        G.get("banana")


def test_rank_titles_differ_by_branch():
    assert G.get("E-7").title("Army") == "Sergeant First Class"
    assert G.get("E-7").title("Navy") == "Chief Petty Officer"
    assert G.get("O-4").title("Navy") == "Lieutenant Commander"


def test_yos_column_buckets_downward():
    assert G.yos_column(0) == 0
    assert G.yos_column(1.9) == 0
    assert G.yos_column(2) == 2
    assert G.yos_column(3.9) == 3
    assert G.yos_column(11) == 10
    assert G.yos_column(26) == 26
    assert G.yos_column(99) == 40


# ==========================================================================
# BAS
# ==========================================================================

def test_bas_officer_is_lower_than_enlisted():
    assert bas.bas_monthly(True).monthly < bas.bas_monthly(False).monthly


def test_bas_ii_is_double_the_standard_enlisted_rate():
    assert bas.bas_monthly(False, bas_ii=True).monthly == pytest.approx(
        bas.bas_monthly(False).monthly * 2, rel=0.01)


def test_bas_ii_does_not_apply_to_officers():
    assert bas.bas_monthly(True, bas_ii=True).monthly == bas.bas_monthly(True).monthly


def test_bas_falls_back_and_says_so_for_an_unpublished_year():
    r = bas.bas_monthly(False, year=2099)
    assert r.is_estimate
    assert r.year == bas.latest_year()
    assert "refresh" in r.note.lower()


def test_bas_did_not_track_the_pay_raise():
    """BAS follows the USDA food index, not the military pay raise."""
    growth = bas.BAS_RATES[2026]["enlisted"] / bas.BAS_RATES[2025]["enlisted"] - 1
    assert 0.020 < growth < 0.030      # ~2.4%, not the 3.8% pay raise


# ==========================================================================
# BAH parsing
# ==========================================================================

def _rate_line(mha: str, base: float) -> str:
    """One synthetic rate row, monotonically increasing across the 27 grades."""
    rates = [base + 40 * i for i in range(len(bah.BAH_COLUMN_ORDER))]
    return mha + "," + ",".join(f"{r:.0f}" for r in rates)


FIXTURE_ZIPMHA = "78234 TX290\n22060 VA337\n96818 HI001\n"
FIXTURE_NAMES = "TX290,San Antonio TX\nVA337,Fort Belvoir VA\nHI001,Honolulu HI\n"
FIXTURE_WITH = "\n".join([_rate_line("TX290", 1500), _rate_line("VA337", 2200),
                          _rate_line("HI001", 2800)])
FIXTURE_WITHOUT = "\n".join([_rate_line("TX290", 1200), _rate_line("VA337", 1800),
                             _rate_line("HI001", 2400)])


def test_parse_zip_mha_pads_short_zips():
    parsed = bah.parse_zip_mha("1234 MA100\n78234 TX290\n")
    assert parsed["01234"] == "MA100"
    assert parsed["78234"] == "TX290"


def test_parse_rates_maps_columns_to_grades_in_order():
    rates = bah.parse_rates(FIXTURE_WITH)
    row = rates["TX290"]
    assert row["E01"] == 1500
    assert row["E02"] == 1540
    assert row["O10"] == 1500 + 40 * 26


def test_parse_rates_refuses_a_wrong_column_count():
    """The whole point: never silently accept a shifted table."""
    short = "TX290," + ",".join("1500" for _ in range(20))
    with pytest.raises(bah.BAHFormatError) as e:
        bah.parse_rates(short)
    assert "20 rate columns" in str(e.value)
    assert "27" in str(e.value)

    long = "TX290," + ",".join("1500" for _ in range(30))
    with pytest.raises(bah.BAHFormatError):
        bah.parse_rates(long)


def test_parse_rates_rejects_an_empty_file():
    with pytest.raises(bah.BAHFormatError):
        bah.parse_rates("\n\n")


def test_parse_zip_mha_rejects_an_empty_file():
    with pytest.raises(bah.BAHFormatError):
        bah.parse_zip_mha("")


def test_column_order_covers_every_real_grade_exactly_once():
    assert len(bah.BAH_COLUMN_ORDER) == len(set(bah.BAH_COLUMN_ORDER))
    assert set(bah.BAH_COLUMN_ORDER) == {g.code for g in G.GRADES}


# ==========================================================================
# BAH lookup
# ==========================================================================

@pytest.fixture
def data(tmp_path):
    d = bah.BAHData(
        year=2026,
        zip_to_mha=bah.parse_zip_mha(FIXTURE_ZIPMHA),
        mha_names=bah.parse_mha_names(FIXTURE_NAMES),
        with_dependents=bah.parse_rates(FIXTURE_WITH),
        without_dependents=bah.parse_rates(FIXTURE_WITHOUT),
        source="fixture", retrieved="2026-01-01",
    )
    return d


def test_lookup_resolves_zip_to_mha_and_rate(data):
    r = bah.lookup("78234", "E-5", True, data)
    assert r.found
    assert r.mha == "TX290"
    assert r.mha_name == "San Antonio TX"
    assert r.monthly == 1500 + 40 * 4      # E05 is the 5th column
    assert r.annual == r.monthly * 12


def test_lookup_distinguishes_dependency_status(data):
    with_deps = bah.lookup("78234", "E-5", True, data)
    without = bah.lookup("78234", "E-5", False, data)
    assert with_deps.monthly > without.monthly


def test_lookup_handles_messy_zip_input(data):
    for form in ("78234", "78234-1234", " 78234 "):
        assert bah.lookup(form, "E-5", True, data).found


def test_lookup_without_data_explains_how_to_fix_it():
    r = bah.lookup("78234", "E-5", True, None)
    assert not r.found
    assert "refresh_bah" in r.note


def test_lookup_of_an_overseas_zip_points_at_oha(data):
    r = bah.lookup("09045", "E-5", True, data)
    assert not r.found
    assert "OHA" in r.note


def test_lookup_of_a_bad_grade_is_reported_not_raised(data):
    r = bah.lookup("78234", "E-99", True, data)
    assert not r.found
    assert "grade" in r.note.lower()


def test_save_and_load_roundtrip(tmp_path, data):
    bah.save(data, tmp_path)
    loaded = bah.load(2026, tmp_path)
    assert loaded.n_zips == data.n_zips
    assert loaded.with_dependents == data.with_dependents
    assert bah.lookup("22060", "O-3", False, loaded).found


def test_load_returns_none_when_nothing_is_installed(tmp_path):
    assert bah.load(2026, tmp_path) is None
    assert bah.available_years(tmp_path) == []


def test_load_picks_the_newest_year_by_default(tmp_path, data):
    bah.save(data, tmp_path)
    older = bah.BAHData(**{**data.__dict__, "year": 2024})
    bah.save(older, tmp_path)
    assert bah.available_years(tmp_path) == [2026, 2024]
    assert bah.load(None, tmp_path).year == 2026


# ==========================================================================
# Refresh-script sanity checks
# ==========================================================================

def test_sanity_check_catches_a_shifted_rate_table():
    """
    The failure this is all built to prevent: a table that parses fine but has
    junior grades out-earning senior ones.
    """
    from scripts.refresh_bah import sanity_check

    reversed_order = list(reversed(bah.BAH_COLUMN_ORDER))
    good = bah.parse_rates(FIXTURE_WITH)
    bad = bah.parse_rates(FIXTURE_WITH, column_order=reversed_order)

    d = bah.BAHData(year=2026, zip_to_mha={str(i).zfill(5): "TX290" for i in range(40000)},
                    with_dependents={f"M{i:03d}": bad["TX290"] for i in range(300)},
                    without_dependents={f"M{i:03d}": bad["TX290"] for i in range(300)})
    problems = sanity_check(d)
    assert any("out-earns" in p for p in problems)


def test_sanity_check_catches_swapped_dependency_files():
    from scripts.refresh_bah import sanity_check
    with_deps = bah.parse_rates(FIXTURE_WITH)
    without = bah.parse_rates(FIXTURE_WITHOUT)
    d = bah.BAHData(year=2026,
                    zip_to_mha={str(i).zfill(5): "TX290" for i in range(40000)},
                    with_dependents={f"M{i:03d}": without["TX290"] for i in range(300)},
                    without_dependents={f"M{i:03d}": with_deps["TX290"] for i in range(300)})
    assert any("swapped" in p for p in sanity_check(d))


def test_sanity_check_passes_a_well_formed_table():
    from scripts.refresh_bah import sanity_check
    good = bah.parse_rates(FIXTURE_WITH)
    lower = bah.parse_rates(FIXTURE_WITHOUT)
    d = bah.BAHData(year=2026,
                    zip_to_mha={str(i).zfill(5): "TX290" for i in range(40000)},
                    with_dependents={f"M{i:03d}": good["TX290"] for i in range(300)},
                    without_dependents={f"M{i:03d}": lower["TX290"] for i in range(300)})
    assert sanity_check(d) == []


# ==========================================================================
# Regression tests against the real installed BAH dataset
#
# These skip cleanly when no data is installed, so a fresh clone still passes.
# When data IS present they check structural invariants across every MHA, not
# a handful of samples -- a column misalignment shows up as a violation
# somewhere even when the sampled rows look fine.
# ==========================================================================

real = pytest.mark.skipif(bah.load() is None,
                          reason="No BAH data installed; run scripts/refresh_bah.py")


@real
def test_real_data_has_the_expected_scale():
    d = bah.load()
    assert 30_000 < d.n_zips < 50_000
    assert 250 < d.n_mhas < 500


@real
def test_real_data_senior_grades_outearn_junior_everywhere():
    """A shifted rate column shows up here even when spot checks look fine."""
    d = bah.load()
    for mha, row in d.with_dependents.items():
        assert row["E01"] <= row["E09"], mha
        assert row["E09"] <= row["O06"], mha
        assert row["O03"] <= row["O06"], mha


@real
def test_real_data_prior_enlisted_officers_are_paid_more():
    """O-1E above O-1 is the sharpest confirmation the columns are aligned."""
    d = bah.load()
    for mha, row in d.with_dependents.items():
        assert row["O01E"] >= row["O01"], mha
        assert row["O02E"] >= row["O02"], mha
        assert row["O03E"] >= row["O03"], mha


@real
def test_real_data_dependents_never_reduce_the_rate():
    d = bah.load()
    for mha, row in d.with_dependents.items():
        without = d.without_dependents[mha]
        for code, rate in row.items():
            assert without[code] <= rate + 0.01, f"{mha} {code}"


@real
def test_real_data_junior_enlisted_share_one_rate():
    """BAH pays E-1 through E-4 the same in every MHA."""
    d = bah.load()
    for mha, row in d.with_dependents.items():
        assert len({row["E01"], row["E02"], row["E03"], row["E04"]}) == 1, mha


@real
def test_real_data_rates_are_in_a_plausible_range():
    d = bah.load()
    rates = [v for row in d.with_dependents.values() for v in row.values()]
    assert 500 < min(rates) < 2_000
    assert 5_000 < max(rates) < 15_000


@real
def test_real_data_high_cost_areas_beat_low_cost_areas():
    """Sanity against the actual housing market, not just internal consistency."""
    d = bah.load()
    san_diego = bah.lookup("92134", "E-5", True, d)
    fort_sill = bah.lookup("73503", "E-5", True, d)
    assert san_diego.found and fort_sill.found
    assert san_diego.monthly > fort_sill.monthly * 1.5


@real
def test_real_data_mha_names_survived_the_comma_in_them():
    """
    Names are semicolon-delimited because they contain commas ("KETCHIKAN, AK").
    A comma-first parser truncates every one of them.
    """
    d = bah.load()
    named = [n for n in d.mha_names.values() if n]
    assert len(named) > 300
    assert any("," in n for n in named), "state suffixes were stripped"
    r = bah.lookup("78234", "E-5", True, d)
    assert "SAN ANTONIO" in r.mha_name.upper()
    assert "TX" in r.mha_name.upper()


@real
def test_real_data_every_mha_carries_all_27_grades():
    d = bah.load()
    expected = set(bah.BAH_COLUMN_ORDER)
    for mha, row in d.with_dependents.items():
        assert set(row) == expected, mha
