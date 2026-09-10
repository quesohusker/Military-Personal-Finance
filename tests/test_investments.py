"""
Tests for the investments engine and the page that renders it.

Three of these are the reason the module exists, and they are checked against
the sample retiree rather than a constructed fixture:

  * the pension-as-a-bond share, which is what makes a military retiree's
    allocation question different from a civilian's;
  * the coverage ratio, which is what removes sequence-of-returns risk;
  * the twenty-year cost of a 1%-of-assets rollover, which is the largest
    avoidable number most retirees will ever be offered.
"""

import sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from engine import storage
from engine import mortality as MORT
from engine.investments import tsp_allocation as TA
from engine.networth import balance_sheet as BS
from engine.profile import Household, Investments, ServiceMember, ACTIVE
from ui.panel import PROFILE_KEY, VERSION_KEY, DIRTY_KEY

SAMPLES = ROOT / "samples"
E5 = SAMPLES / "e5_6yrs_brs.mpfplan.json"
O5 = SAMPLES / "retired_o5_26yrs.mpfplan.json"
PAGE = ROOT / "pages" / "21_Investments.py"


def load(path: pathlib.Path) -> Household:
    return storage.from_upload_bytes(path.read_bytes())


def retiree() -> Household:
    return load(O5)


# ==========================================================================
# The funds themselves
# ==========================================================================

def test_five_funds_with_expense_ratios_in_the_published_range():
    assert TA.FUND_CODES == ("G", "F", "C", "S", "I")
    for code in TA.FUND_CODES:
        f = TA.FUNDS[code]
        assert 0.03 <= f.expense_ratio_pct <= 0.07, code
        assert f.what.strip() and f.note.strip()
    assert [c for c in TA.FUND_CODES if TA.FUNDS[c].is_equity] == ["C", "S", "I"]


def test_the_numbers_that_age_carry_a_verify_note_with_a_year():
    assert TA.EXPENSE_RATIO_YEAR >= 2024
    assert str(TA.EXPENSE_RATIO_YEAR) in TA.VERIFY["expense_ratios"]
    assert str(TA.L_FUND_YEAR) in TA.VERIFY["l_fund_equity"]
    for key in ("expense_ratios", "l_fund_equity", "l_fund_lineup", "ift_rules"):
        note = TA.VERIFY[key]
        assert note.startswith("VERIFY")
        assert "Confidence" in note


def test_the_g_fund_is_described_as_unique_to_the_tsp():
    note = TA.FUNDS["G"].note
    assert "not for sale anywhere" in note
    assert "only inside the TSP" in note


def test_the_i_fund_note_covers_the_2024_index_change():
    note = TA.FUNDS["I"].note
    assert "EAFE" in note and "emerging markets" in note


# ==========================================================================
# The L funds and the glide path
# ==========================================================================

def test_the_glide_path_falls_monotonically_toward_l_income():
    equities = [TA.l_fund_equity_pct(n) for n in TA.L_FUNDS]
    assert equities == sorted(equities), "later target dates hold more equity"
    assert TA.l_fund_equity_pct(TA.L_INCOME) == min(equities)
    assert 20 <= TA.l_fund_equity_pct(TA.L_INCOME) <= 40
    assert max(equities) >= 95, "the far-dated funds are essentially all equity"


def test_the_lineup_runs_in_five_year_steps_to_2075():
    years = TA.L_FUND_TARGET_YEARS
    assert years[0] == 2030 and years[-1] == 2075
    assert all(b - a == 5 for a, b in zip(years, years[1:]))
    assert TA.L_INCOME in TA.L_FUNDS and len(TA.L_FUNDS) == len(years) + 1


def test_an_l_fund_is_picked_by_the_year_the_money_is_needed():
    assert TA.l_fund_for_year(2054) == "L 2055"
    assert TA.l_fund_for_year(2026) == TA.L_INCOME
    assert TA.l_fund_for_year(2090) == "L 2075"
    assert not TA.is_l_fund("L 2100") and TA.is_l_fund("L 2050")


def test_the_suggestion_is_the_withdrawal_year_not_the_separation_year():
    h = retiree()                       # born 1975, already retired at 51
    pick = TA.suggested_l_fund(h, withdrawal_age=62)
    assert pick.withdrawal_year == 2037 and pick.fund == "L 2035"
    assert "not the year you leave the service" in pick.note


# ==========================================================================
# Equity share -- with and without an L fund
# ==========================================================================

def test_equity_share_without_an_l_fund_is_just_c_plus_s_plus_i():
    inv = Investments(tsp_g_pct=20, tsp_f_pct=10, tsp_c_pct=50, tsp_s_pct=10,
                      tsp_i_pct=10, tsp_lifecycle_fund="", tsp_lifecycle_pct=0)
    es = TA.equity_share(inv)
    assert es.equity_pct == pytest.approx(70.0)
    assert es.fixed_pct == pytest.approx(30.0)
    assert es.allocation_total_pct == pytest.approx(100.0)
    assert es.sums_to_100 and not es.problems


def test_a_lifecycle_percentage_is_ignored_when_no_l_fund_is_chosen():
    """The default profile carries lifecycle_pct=100 and no fund named."""
    inv = Investments(tsp_c_pct=100.0, tsp_lifecycle_fund="",
                      tsp_lifecycle_pct=100.0)
    es = TA.equity_share(inv)
    assert es.allocation_total_pct == pytest.approx(100.0)
    assert es.equity_pct == pytest.approx(100.0)


def test_equity_share_counts_the_shares_held_inside_the_l_fund():
    inv = Investments(tsp_lifecycle_fund="L 2055", tsp_lifecycle_pct=100.0)
    es = TA.equity_share(inv)
    assert es.equity_pct == pytest.approx(TA.l_fund_equity_pct("L 2055"))
    assert es.lifecycle_equity_pct == pytest.approx(es.equity_pct)
    assert es.direct_equity_pct == 0.0
    assert es.sums_to_100


def test_an_l_fund_next_to_individual_funds_is_the_arithmetic_people_miss():
    """50% L 2050 + 50% C is not 50% equity. It is 90%."""
    inv = Investments(tsp_c_pct=50.0, tsp_lifecycle_fund="L 2050",
                      tsp_lifecycle_pct=50.0)
    es = TA.equity_share(inv)
    expected = 50.0 + 50.0 * TA.l_fund_equity_pct("L 2050") / 100.0
    assert es.equity_pct == pytest.approx(expected)
    assert es.equity_pct > 85
    assert any("alongside individual funds" in p for p in es.problems)


def test_equity_plus_fixed_is_always_the_whole_allocation():
    for inv in (Investments(tsp_g_pct=60, tsp_c_pct=40),
                Investments(tsp_lifecycle_fund="L 2040", tsp_lifecycle_pct=100),
                Investments(tsp_f_pct=25, tsp_i_pct=25,
                            tsp_lifecycle_fund="L Income",
                            tsp_lifecycle_pct=50)):
        es = TA.equity_share(inv)
        assert es.equity_pct + es.fixed_pct == pytest.approx(
            es.allocation_total_pct)


# ==========================================================================
# An allocation that does not sum to 100 is flagged
# ==========================================================================

def test_an_allocation_short_of_100_is_flagged():
    inv = Investments(tsp_g_pct=50.0, tsp_c_pct=40.0)     # 90%
    es = TA.equity_share(inv)
    assert es.allocation_total_pct == pytest.approx(90.0)
    assert not es.sums_to_100
    assert es.unassigned_pct == pytest.approx(10.0)
    assert any(TA.MIS_SUM_MARK in p for p in es.problems)


def test_an_allocation_over_100_is_flagged_as_rejected_by_the_tsp():
    inv = Investments(tsp_g_pct=50.0, tsp_c_pct=60.0)     # 110%
    es = TA.equity_share(inv)
    assert not es.sums_to_100
    assert any("would reject" in p for p in es.problems)


def test_the_l_fund_counts_toward_the_same_100():
    short = Investments(tsp_c_pct=50.0, tsp_lifecycle_fund="L 2050",
                        tsp_lifecycle_pct=40.0)
    assert not TA.equity_share(short).sums_to_100
    exact = Investments(tsp_c_pct=50.0, tsp_lifecycle_fund="L 2050",
                        tsp_lifecycle_pct=50.0)
    assert TA.equity_share(exact).sums_to_100


def test_an_empty_allocation_says_so_rather_than_claiming_zero_equity():
    es = TA.equity_share(Investments())
    assert es.is_empty
    assert any("No allocation entered" in p for p in es.problems)
    assert not any(TA.MIS_SUM_MARK in p for p in es.problems)


def test_a_mis_summed_allocation_reaches_the_findings_with_a_dollar_figure():
    h = retiree()
    h.investments = Investments(tsp_g_pct=50.0, tsp_c_pct=40.0,
                                target_equity_pct=40.0)
    heads = [head for _, head, _ in TA.findings(h)]
    assert any("add to 90%, not 100%" in head for head in heads)


# ==========================================================================
# Drift and the rebalance direction
# ==========================================================================

def test_no_drift_inside_the_band_is_left_alone():
    inv = Investments(tsp_g_pct=22, tsp_c_pct=62, tsp_s_pct=16,
                      target_equity_pct=80.0)
    d = TA.versus_target(inv)
    assert d.equity_pct == pytest.approx(78.0)
    assert d.drift_pts == pytest.approx(-2.0)
    assert d.direction == "hold" and d.in_band and not d.moves


def test_too_much_equity_moves_money_into_the_g_fund():
    inv = Investments(tsp_g_pct=10, tsp_c_pct=60, tsp_s_pct=20, tsp_i_pct=10,
                      target_equity_pct=70.0)
    d = TA.versus_target(inv, tsp_balance=200_000)
    assert d.drift_pts == pytest.approx(20.0)
    assert d.direction == "reduce"
    assert d.moves and all(dst == "G" for _, dst, _ in d.moves)
    assert all(src in TA.EQUITY_CODES for src, _, _ in d.moves)
    assert sum(pts for _, _, pts in d.moves) == pytest.approx(20.0, abs=0.2)
    assert d.dollars == pytest.approx(40_000)
    assert "always allows" in d.note


def test_too_little_equity_moves_money_out_of_the_g_fund():
    inv = Investments(tsp_g_pct=60, tsp_c_pct=30, tsp_s_pct=10,
                      target_equity_pct=80.0)
    d = TA.versus_target(inv, tsp_balance=100_000)
    assert d.drift_pts == pytest.approx(-40.0)
    assert d.direction == "add"
    assert d.moves and all(src in TA.FIXED_CODES for src, _, _ in d.moves)
    assert all(dst in TA.EQUITY_CODES for _, dst, _ in d.moves)
    assert d.dollars == pytest.approx(40_000)
    assert "unrestricted" in d.note


def test_the_direction_reverses_with_the_target():
    inv = Investments(tsp_g_pct=40, tsp_c_pct=60)
    inv.target_equity_pct = 20.0
    assert TA.versus_target(inv).direction == "reduce"
    inv.target_equity_pct = 90.0
    assert TA.versus_target(inv).direction == "add"


def test_drift_inside_an_l_fund_suggests_switching_l_funds():
    inv = Investments(tsp_lifecycle_fund="L 2055", tsp_lifecycle_pct=100.0,
                      target_equity_pct=80.0)
    d = TA.versus_target(inv, tsp_balance=800_000)
    assert d.direction == "reduce"
    assert d.l_fund_switch == "L 2050"
    assert d.moves and d.moves[0][0] == "L 2055" and d.moves[0][1] == "G"
    # Moving a point out of a 99%-equity fund sheds 0.99 points of equity, so
    # the transfer has to be grossed up to close a 19-point gap.
    assert d.moves[0][2] > 19.0
    assert "rebalances itself" in d.note
    assert TA.describe_moves(d.moves) == "19.2 points from L 2055 to G"


def test_the_suggested_transfers_add_up_to_the_drift_they_close():
    """Legs rounded independently would not total the gap, which reads as an error."""
    inv = Investments(tsp_g_pct=20, tsp_c_pct=50, tsp_s_pct=10, tsp_i_pct=20,
                      target_equity_pct=70.0)
    d = TA.versus_target(inv, tsp_balance=800_000)
    assert len(d.moves) == 3
    assert sum(pts for _, _, pts in d.moves) == pytest.approx(abs(d.drift_pts))


def test_a_single_point_transfer_is_described_in_the_singular():
    inv = Investments(tsp_g_pct=24, tsp_c_pct=76, target_equity_pct=75.0)
    d = TA.versus_target(inv, band_pts=0.5)
    assert TA.describe_moves(d.moves) == "1 point from C to G"


def test_interfund_transfers_are_free_and_capped_at_two_a_month():
    assert TA.IFT_COST == 0.0
    assert TA.IFT_UNRESTRICTED_PER_MONTH == 2
    assert "INTO the G Fund" in TA.VERIFY["ift_rules"]


# ==========================================================================
# THE MILITARY INSIGHT: the pension is the bond holding
# ==========================================================================

def test_the_retirees_pension_is_more_than_half_of_everything_they_own():
    """The finding the whole page is built around, on the sample retiree."""
    h = retiree()
    pb = TA.pension_as_bond(h, real_discount_rate=0.03)
    assert pb.real_discount_rate == 0.03
    assert pb.bond_like_pct > 50.0
    assert pb.replacement_cost > pb.portfolio > 0


def test_the_replacement_cost_is_the_balance_sheets_own_figure():
    """Two pages quoting different values for the same pension is not an option."""
    h = retiree()
    le = MORT.life_expectancy(h.member.age(2026), h.member.sex)
    bs = BS.from_household(h, life_expectancy=le, real_discount_rate=0.03,
                           current_year=2026)
    pb = TA.pension_as_bond(h, real_discount_rate=0.03, current_year=2026)
    assert pb.replacement_cost == pytest.approx(bs.streams_present_value)
    assert pb.portfolio == pytest.approx(bs.investable_assets)
    assert pb.bond_like_pct == pytest.approx(
        bs.streams_present_value
        / (bs.streams_present_value + bs.investable_assets) * 100.0)


def test_the_discount_rate_defaults_to_the_plans_assumption():
    h = retiree()
    h.assumptions.real_discount_rate_pct = 5.0
    assert TA.pension_as_bond(h).real_discount_rate == pytest.approx(0.05)
    # A higher discount rate values the pension lower, so the bond-like share
    # falls. If a conclusion flips between plausible rates it was never strong.
    assert (TA.pension_as_bond(h, real_discount_rate=0.05).bond_like_pct
            < TA.pension_as_bond(h, real_discount_rate=0.02).bond_like_pct)


def test_an_all_equity_tsp_is_not_an_all_equity_household():
    h = retiree()
    pb = TA.pension_as_bond(h, real_discount_rate=0.03)
    assert pb.household_equity_pct(100.0) < 50.0
    assert pb.household_equity_pct(60.0) < pb.household_equity_pct(100.0)
    # No portfolio allocation reaches an 80% household equity share.
    assert pb.portfolio_equity_for(80.0) > 100.0


def test_an_active_duty_member_has_no_pension_bond_yet():
    pb = TA.pension_as_bond(load(E5))
    assert not pb.applies
    assert pb.replacement_cost == 0.0 and pb.bond_like_pct == 0.0


def test_the_pension_finding_leads_because_it_is_the_biggest_number():
    out = TA.findings(retiree())
    assert out, "the retiree has findings"
    sev, head, detail = out[0]
    assert "already about" in head and "in bonds" in head
    assert "more equity than a civilian's at the same age" in detail
    assert "not a cash value" in detail       # the caveat travels with it


# ==========================================================================
# Sequence-of-returns risk and the coverage ratio
# ==========================================================================

def test_the_retirees_guaranteed_income_covers_more_than_they_spend():
    c = TA.expenses_covered(retiree())
    assert c.ratio > 1.0
    assert c.fully_covered
    assert c.surplus_monthly > 0 and c.gap_monthly == 0
    assert "do not have to sell anything in a bad year" in c.detail


def test_a_coverage_ratio_below_one_sizes_the_gap_not_the_spending():
    h = retiree()
    h.monthly_expenses = 20_000.0
    c = TA.expenses_covered(h)
    assert c.ratio < 1.0 and not c.fully_covered
    assert c.gap_monthly == pytest.approx(20_000 - c.guaranteed_monthly)
    assert c.gap_annual == pytest.approx(c.gap_monthly * 12)
    assert "not of total" in c.detail and "G Fund" in c.detail
    assert c.years_of_gap_covered > 0


def test_a_serving_member_with_no_pension_has_no_floor_yet():
    c = TA.expenses_covered(load(E5))
    assert c.guaranteed_monthly == 0.0
    assert c.ratio == 0.0 and not c.fully_covered


def test_coverage_is_quiet_when_spending_is_unknown():
    h = retiree()
    h.monthly_expenses = 0.0
    c = TA.expenses_covered(h)
    assert c.ratio == 0.0
    assert "Enter what you spend" in c.headline


# ==========================================================================
# Fees -- the rollover pitch
# ==========================================================================

def test_one_percent_of_assets_on_800k_costs_six_figures_over_20_years():
    f = TA.fee_drag(800_000, years=20, real_return_pct=4.0, advisor_pct=1.0)
    assert f.cost >= 100_000, "six figures"
    assert f.cost == pytest.approx(f.tsp_value - f.advisor_value)
    assert f.tsp_value > f.advisor_value
    assert f.first_year_fee == pytest.approx(8_000)
    assert f.cost > 20 * f.first_year_fee, "the fee compounds, it does not add"


def test_the_fee_costs_more_the_longer_it_is_paid():
    args = dict(real_return_pct=4.0, advisor_pct=1.0)
    ten = TA.fee_drag(800_000, years=10, **args).cost
    twenty = TA.fee_drag(800_000, years=20, **args).cost
    thirty = TA.fee_drag(800_000, years=30, **args).cost
    assert ten < twenty < thirty


def test_the_tsp_costs_about_a_twentieth_of_the_advisory_fee():
    f = TA.fee_drag(800_000)
    assert f.multiple_of_tsp_cost == pytest.approx(20.0, rel=0.35)
    assert 0.03 <= f.tsp_expense_pct <= 0.07


def test_no_balance_means_no_fee_and_no_finding():
    f = TA.fee_drag(0.0)
    assert f.cost == 0.0 and f.cost_as_pct_of_balance == 0.0


def test_the_rollover_finding_uses_the_households_own_balances():
    h = retiree()
    f = TA.rollover_pitch(h)
    assert f.balance == pytest.approx(700_000 + 100_000 + 180_000 + 45_000)
    assert f.real_return_pct == h.assumptions.real_return_pct
    assert f.cost > 100_000
    heads = [head for _, head, _ in TA.findings(h)]
    assert any("1%-of-assets IRA" in head for head in heads)


# ==========================================================================
# Asset location
# ==========================================================================

def test_growth_belongs_in_roth_and_bonds_in_traditional():
    h = retiree()
    h.investments = Investments(tsp_g_pct=30, tsp_c_pct=50, tsp_s_pct=10,
                                tsp_i_pct=10, target_equity_pct=70)
    loc = TA.asset_location(h, years=20)
    assert loc.roth == pytest.approx(100_000 + 45_000)
    assert loc.traditional == pytest.approx(700_000 + 180_000)
    assert loc.applies and loc.gain > 0
    body = " ".join(loc.lines)
    assert "C and S in the ROTH" in body and "G and F in the TRADITIONAL" in body
    assert "matching lands in the TRADITIONAL balance" in body


def test_the_placement_gain_is_the_tax_on_the_difference_in_growth():
    h = retiree()
    h.investments = Investments(tsp_g_pct=30, tsp_c_pct=70, target_equity_pct=70)
    loc = TA.asset_location(h, years=20)
    e = (1 + loc.equity_real_pct / 100) ** 20
    b = (1 + loc.bond_real_pct / 100) ** 20
    assert loc.gain == pytest.approx(loc.tax_rate * loc.swappable * (e - b))
    assert loc.swappable <= min(loc.roth, loc.traditional)


def test_nothing_to_relocate_when_one_side_is_empty():
    h = Household()
    h.member = ServiceMember(component=ACTIVE, tsp_roth_balance=20_000)
    h.investments = Investments(tsp_c_pct=100.0)
    loc = TA.asset_location(h)
    assert not loc.applies
    assert any("every future contribution" in line for line in loc.lines)


# ==========================================================================
# Findings
# ==========================================================================

def test_findings_are_ordered_by_dollars_at_stake():
    out = TA.findings(retiree())
    assert len(out) >= 4
    for sev, head, detail in out:
        assert sev in ("good", "info", "warn", "bad")
        assert head.strip() and detail.strip()
    heads = [h for _, h, _ in out]
    # The pension leads; the rollover fee outranks the smaller placement gain.
    assert heads.index(next(h for h in heads if "in bonds" in h)) == 0
    assert (heads.index(next(h for h in heads if "1%-of-assets" in h))
            < heads.index(next(h for h in heads if "Holding the growth" in h)))


def test_an_all_g_portfolio_is_called_out():
    h = retiree()
    h.investments = Investments(tsp_g_pct=100.0, target_equity_pct=100.0)
    heads = [head for _, head, _ in TA.findings(h)]
    assert any("entire TSP is in fixed income" in head for head in heads)


def test_no_finding_names_a_security_outside_the_tsp():
    """The module must never turn into a recommendation engine."""
    banned = ("VTI", "VOO", "VTSAX", "SPY", "Vanguard", "Fidelity", "Schwab",
              "ETF", "annuity contract")
    for h in (retiree(), load(E5)):
        body = " ".join(head + " " + detail for _, head, detail in TA.findings(h))
        for word in banned:
            assert word not in body, word


def test_a_household_with_nothing_entered_still_produces_findings_safely():
    out = TA.findings(Household())
    assert isinstance(out, list)
    for sev, head, detail in out:
        assert sev in ("good", "info", "warn", "bad")


# ==========================================================================
# The page
# ==========================================================================

def _render(plan: pathlib.Path | None = None):
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(PAGE), default_timeout=120)
    if plan is not None:
        at.session_state[PROFILE_KEY] = load(plan)
        at.session_state[VERSION_KEY] = 0
    at.run()
    assert not at.exception, at.exception
    return at


def test_page_renders_from_an_empty_plan():
    at = _render()
    assert "How is my money invested" in at.title[0].value


@pytest.mark.parametrize("plan", [E5, O5], ids=["e5_brs", "retired_o5"])
def test_page_renders_against_both_sample_plans(plan):
    at = _render(plan)
    body = " ".join(md.value for md in at.markdown)
    assert "Running total" in body
    assert at.session_state[PROFILE_KEY].profile_name.startswith("Sample")


def test_the_page_leads_with_the_pension_for_the_retiree():
    at = _render(O5)
    body = " ".join(md.value for md in at.markdown)
    assert "already own a very large bond" in body or "in bonds" in body
    assert "1%" in body                      # the rollover pitch is priced
    assert "sell anything in a bad year" in body


def test_the_page_offers_no_pension_card_to_a_serving_member():
    at = _render(E5)
    info = " ".join(i.value for i in at.info)
    assert "no retired pay or VA compensation entered" in info


def test_page_inputs_write_straight_into_the_plan():
    at = _render(O5)
    at.number_input(key="iv_c__v0").set_value(60.0).run()
    assert not at.exception, at.exception
    h = at.session_state[PROFILE_KEY]
    assert h.investments.tsp_c_pct == 60.0
    assert at.session_state[DIRTY_KEY] is True


def test_choosing_an_l_fund_writes_it_back_and_moves_the_equity_share():
    at = _render(O5)
    at.selectbox(key="iv_lfund__v0").select("L 2040").run()
    assert not at.exception, at.exception
    h = at.session_state[PROFILE_KEY]
    assert h.investments.tsp_lifecycle_fund == "L 2040"
    assert TA.equity_share(h.investments).equity_pct == pytest.approx(
        h.investments.tsp_lifecycle_pct * TA.l_fund_equity_pct("L 2040") / 100.0)
    assert at.session_state[DIRTY_KEY] is True


def test_the_allocation_charts_render_once_there_is_an_allocation():
    """The sample plans carry no allocation, so the chart path needs its own run."""
    h = load(O5)
    h.investments = Investments(tsp_g_pct=20, tsp_c_pct=50, tsp_s_pct=10,
                                tsp_i_pct=20, target_equity_pct=70,
                                taxable_equity_pct=90)
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(PAGE), default_timeout=120)
    at.session_state[PROFILE_KEY] = h
    at.session_state[VERSION_KEY] = 0
    at.run()
    assert not at.exception, at.exception
    assert len(at.get("vega_lite_chart")) == 2   # allocation, and against target
    body = " ".join(md.value for md in at.markdown)
    assert "Running total: 100%" in body
    assert "80% stocks against a 70% target" in body
    assert "Suggested interfund transfer" in body


def test_the_running_total_reports_a_short_allocation():
    at = _render(O5)
    at.number_input(key="iv_g__v0").set_value(50.0).run()
    at.number_input(key="iv_c__v0").set_value(40.0).run()
    assert not at.exception, at.exception
    body = " ".join(md.value for md in at.markdown)
    assert "Running total: 90%" in body
    caps = " ".join(c.value for c in at.caption)
    assert "unaccounted for" in caps
