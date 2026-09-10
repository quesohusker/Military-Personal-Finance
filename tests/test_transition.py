import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from datetime import date

import pytest

from engine import storage
from engine.career import transition as TR
from engine.profile import Household, ServiceMember

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAGE = ROOT / "pages" / "18_Leaving_the_Service.py"
SAMPLES = [ROOT / "samples" / "e5_6yrs_brs.mpfplan.json",
           ROOT / "samples" / "retired_o5_26yrs.mpfplan.json"]

# A representative E-5: $4,110 basic, $1,806 BAH, $476.95 BAS.
BASIC = 4_110.0
BAH = 1_806.0
BAS = 476.95


# ==========================================================================
# Sold leave pays basic pay, and only basic pay
# ==========================================================================

def test_a_sold_leave_day_is_one_thirtieth_of_monthly_basic_pay():
    assert TR.sell_leave_value(1, BASIC) == pytest.approx(BASIC / 30.0)
    assert TR.sell_leave_value(45, BASIC) == pytest.approx(BASIC / 30.0 * 45)
    assert TR.sell_leave_value(45, BASIC) == pytest.approx(6_165.0)


def test_sold_leave_excludes_bah_and_bas():
    """The number people get wrong: they budget the sale at LES gross."""
    with_allowances = TR.compare_leave(30, BASIC, BAH, BAS)
    without = TR.compare_leave(30, BASIC, 0.0, 0.0)
    assert with_allowances.sell.gross == pytest.approx(without.sell.gross)
    assert with_allowances.sell.gross == pytest.approx(TR.sell_leave_value(30, BASIC))
    assert with_allowances.sell.terminal_allowances == 0.0


def test_sold_leave_is_taxable_and_terminal_allowances_are_not():
    c = TR.compare_leave(45, BASIC, BAH, BAS, marginal_rate=0.22)
    assert c.sell.tax == pytest.approx(c.sell.sold_gross * 0.22)
    # Taking it: only the basic-pay part of the day is taxed.
    assert c.take.tax == pytest.approx(c.take.terminal_basic * 0.22)
    assert c.take.tax == pytest.approx(c.sell.tax)


# ==========================================================================
# The 60-day CAREER cap
# ==========================================================================

def test_the_career_cap_is_sixty_days():
    assert TR.SELLBACK_CAREER_CAP_DAYS == 60
    assert TR.sellback_cap_remaining(0) == 60
    assert TR.sellback_cap_remaining(15) == 45
    assert TR.sellback_cap_remaining(60) == 0
    assert TR.sellback_cap_remaining(90) == 0


def test_the_cap_binds_and_caps_what_can_be_sold():
    c = TR.compare_leave(75, BASIC, BAH, BAS)
    assert c.cap_binds
    assert c.days_over_cap == pytest.approx(15)
    assert c.sell.days_sold == pytest.approx(60)
    assert c.sell.days_taken == pytest.approx(15)
    assert c.sell.sold_gross == pytest.approx(TR.sell_leave_value(60, BASIC))


def test_leave_already_sold_eats_the_same_career_cap():
    c = TR.compare_leave(45, BASIC, BAH, BAS, days_already_sold=40)
    assert c.cap_remaining == pytest.approx(20)
    assert c.cap_binds
    assert c.sell.days_sold == pytest.approx(20)
    assert c.sell.days_taken == pytest.approx(25)


def test_the_cap_does_not_bind_below_sixty_days():
    c = TR.compare_leave(45, BASIC, BAH, BAS)
    assert not c.cap_binds
    assert c.sell.days_sold == pytest.approx(45)


# ==========================================================================
# Terminal leave against selling
# ==========================================================================

def test_terminal_leave_beats_selling_whenever_allowances_are_positive():
    for bah, bas in ((BAH, BAS), (0.0, BAS), (BAH, 0.0), (2_500.0, 300.0)):
        c = TR.compare_leave(45, BASIC, bah, bas)
        assert bah + bas > 0
        assert c.take.after_tax > c.sell.after_tax
        assert c.advantage_of_taking > 0
        assert c.best.label == TR.TAKE


def test_the_advantage_of_taking_is_exactly_the_untaxed_allowances():
    c = TR.compare_leave(45, BASIC, BAH, BAS, marginal_rate=0.22)
    assert c.advantage_of_taking == pytest.approx(45 * (BAH + BAS) / 30.0)
    assert c.take.after_tax == pytest.approx(c.sell.after_tax
                                             + c.advantage_of_taking)


def test_with_no_allowances_the_two_paths_are_worth_the_same():
    c = TR.compare_leave(45, BASIC, 0.0, 0.0)
    assert c.take.after_tax == pytest.approx(c.sell.after_tax)
    assert c.advantage_of_taking == pytest.approx(0.0)


def test_only_selling_produces_a_lump_at_the_settlement():
    c = TR.compare_leave(45, BASIC, BAH, BAS, marginal_rate=0.22)
    assert c.take.cash_at_separation == pytest.approx(0.0)
    assert c.sell.cash_at_separation == pytest.approx(6_165.0 * 0.78)


# ==========================================================================
# The hybrid
# ==========================================================================

def test_the_hybrid_never_beats_both():
    for days in (10, 45, 60, 75, 90, 120):
        for already in (0, 20, 55, 60):
            c = TR.compare_leave(days, BASIC, BAH, BAS, days_already_sold=already)
            best = max(c.take.after_tax, c.sell.after_tax)
            worst = min(c.take.after_tax, c.sell.after_tax)
            assert c.hybrid.after_tax <= best + 1e-6
            assert c.hybrid.after_tax >= worst - 1e-6


def test_below_the_cap_the_hybrid_is_just_selling():
    c = TR.compare_leave(45, BASIC, BAH, BAS)
    assert c.hybrid.days_sold == pytest.approx(c.sell.days_sold)
    assert c.hybrid.after_tax == pytest.approx(c.sell.after_tax)


def test_above_the_cap_the_hybrid_carries_the_leftover_days_as_leave():
    c = TR.compare_leave(90, BASIC, BAH, BAS)
    assert c.hybrid.days_sold == pytest.approx(60)
    assert c.hybrid.days_taken == pytest.approx(30)
    assert c.hybrid.after_tax > TR.compare_leave(60, BASIC, BAH, BAS).sell.after_tax


# ==========================================================================
# VA timing: the BDD window and what missing it costs
# ==========================================================================

def test_the_va_gap_cost_scales_with_the_months_unfiled():
    one = TR.va_timing(1_500.0, filed_bdd=False, months_to_decision=2)
    two = TR.va_timing(1_500.0, filed_bdd=False, months_to_decision=3)
    four = TR.va_timing(1_500.0, filed_bdd=False, months_to_decision=5)

    assert one.gap_months == pytest.approx(1)
    assert two.gap_dollars == pytest.approx(2 * 1_500.0)
    assert four.gap_dollars == pytest.approx(4 * one.gap_dollars)
    assert four.gap_dollars > two.gap_dollars > one.gap_dollars


def test_the_gap_scales_with_the_expected_award_too():
    small = TR.va_timing(500.0, filed_bdd=False)
    large = TR.va_timing(2_000.0, filed_bdd=False)
    assert large.gap_dollars == pytest.approx(4 * small.gap_dollars)


def test_filing_bdd_removes_the_gap():
    filed = TR.va_timing(1_500.0, filed_bdd=True)
    not_filed = TR.va_timing(1_500.0, filed_bdd=False)
    assert filed.gap_months == 0
    assert filed.gap_dollars == 0
    assert not_filed.gap_dollars > 0


def test_the_bdd_window_is_a_hundred_and_eighty_to_ninety_days_out():
    assert TR.va_timing(1_000.0, days_until_separation=120).in_window
    assert TR.va_timing(1_000.0, days_until_separation=300).too_early
    assert TR.va_timing(1_000.0, days_until_separation=45).too_late
    assert not TR.va_timing(1_000.0, days_until_separation=45).in_window


def test_the_missed_window_is_a_cash_flow_cost_not_a_forfeiture():
    v = TR.va_timing(1_500.0, filed_bdd=False)
    assert v.back_pay == pytest.approx(v.gap_dollars)
    assert any("back-date" in n or "arrears" in n for n in v.notes)


# ==========================================================================
# The TSP loan, and the rule of 55
# ==========================================================================

def test_a_loan_before_the_year_you_turn_fifty_five_is_flagged_for_the_penalty():
    t = TR.tsp_at_separation(12_000.0, birth_year=1975, separation_date=date(2029, 6, 30))
    assert t.age_in_separation_year == 54
    assert not t.rule_of_55
    assert t.penalty_applies
    assert t.penalty == pytest.approx(1_200.0)
    assert t.total_cost > t.income_tax


def test_the_rule_of_fifty_five_turns_the_penalty_off():
    t = TR.tsp_at_separation(12_000.0, birth_year=1975, separation_date=date(2030, 6, 30))
    assert t.age_in_separation_year == 55
    assert t.rule_of_55
    assert not t.penalty_applies
    assert t.penalty == 0.0
    assert t.total_cost == pytest.approx(t.income_tax)


def test_the_rule_of_fifty_five_is_the_calendar_year_not_the_birthday():
    """Separate in January of the year you turn 55 and it still applies."""
    january = TR.tsp_at_separation(20_000.0, birth_year=1975,
                                   separation_date=date(2030, 1, 15))
    assert january.age_at_separation < 55
    assert january.rule_of_55
    assert not january.penalty_applies


def test_a_young_member_with_a_loan_pays_tax_and_penalty():
    t = TR.tsp_at_separation(8_000.0, birth_year=1999,
                             separation_date=date(2027, 3, 30),
                             marginal_rate=0.22)
    assert t.penalty_applies
    assert t.income_tax == pytest.approx(8_000.0 * 0.22)
    assert t.penalty == pytest.approx(800.0)
    assert t.total_cost == pytest.approx(8_000.0 * 0.32)


def test_no_loan_costs_nothing_and_still_warns():
    t = TR.tsp_at_separation(0.0, birth_year=1999, separation_date=date(2027, 3, 30))
    assert t.total_cost == 0.0
    assert not t.penalty_applies
    assert t.notes


def test_past_fifty_nine_and_a_half_there_is_no_penalty():
    t = TR.tsp_at_separation(10_000.0, birth_year=1960,
                             separation_date=date(2027, 3, 30))
    assert t.age_at_separation > 59.5
    assert not t.penalty_applies


# ==========================================================================
# TAMP, CHCBP and the final move: a retiree and a separatee differ
# ==========================================================================

def test_a_retiree_and_a_separatee_get_different_health_paths():
    retiree = TR.health_cover(is_retiring=True)
    separatee = TR.health_cover(is_retiring=False)

    assert retiree.path == TR.PATH_RETIREE_TRICARE
    assert separatee.path == TR.PATH_CHCBP
    assert retiree.path != separatee.path
    assert not retiree.tamp_applies and not separatee.tamp_applies
    assert not retiree.chcbp_available
    assert separatee.chcbp_available


def test_tamp_belongs_to_the_involuntary_separatee_only():
    involuntary = TR.health_cover(is_retiring=False, involuntary=True)
    voluntary = TR.health_cover(is_retiring=False, involuntary=False)
    retiree = TR.health_cover(is_retiring=True, involuntary=True)

    assert involuntary.tamp_applies
    assert involuntary.free_days == 180
    assert not voluntary.tamp_applies
    assert voluntary.free_days == 0
    assert not retiree.tamp_applies      # a retiree needs no bridge


def test_the_chcbp_election_window_is_sixty_days():
    c = TR.health_cover(is_retiring=False)
    assert c.chcbp_enroll_days == 60
    assert c.chcbp_max_months == 18


def test_a_retiree_and_a_separatee_get_different_final_moves():
    retiree = TR.final_move(is_retiring=True)
    separatee = TR.final_move(is_retiring=False)

    assert retiree.deadline_days > separatee.deadline_days
    assert retiree.deadline_days == 3 * 365
    assert separatee.deadline_days == 180
    assert retiree.home_of_selection
    assert not separatee.home_of_selection


def test_ucx_refuses_to_guess_a_weekly_amount():
    sep = TR.unemployment(is_retiring=False, state="Texas")
    ret = TR.unemployment(is_retiring=True, state="Texas")
    assert sep.likely_eligible and ret.likely_eligible
    assert not sep.retired_pay_offset_risk
    assert ret.retired_pay_offset_risk        # state-dependent offset
    assert "state" in ret.note.lower()
    assert "$" not in sep.note and "$" not in ret.note


# ==========================================================================
# The cash-flow gap
# ==========================================================================

def _member(**kw) -> Household:
    h = Household()
    for k, v in kw.items():
        if hasattr(h, k):
            setattr(h, k, v)
        else:
            setattr(h.member, k, v)
    return h


def test_the_cash_flow_gap_is_sized_from_monthly_expenses():
    va = TR.va_timing(0.0, filed_bdd=False)
    flow = TR.cash_flow(date(2027, 3, 31), BASIC, BAH, BAS, 4_200.0,
                        is_retiring=False, va=va)
    assert flow.months_short > 0
    assert flow.reserve_needed == pytest.approx(flow.total_shortfall)
    doubled = TR.cash_flow(date(2027, 3, 31), BASIC, BAH, BAS, 8_400.0,
                           is_retiring=False, va=va)
    assert doubled.total_shortfall > flow.total_shortfall


def test_pay_stops_on_the_separation_date_not_at_the_end_of_the_month():
    early = TR.cash_flow(date(2027, 3, 10), BASIC, BAH, BAS, 4_200.0)
    late = TR.cash_flow(date(2027, 3, 31), BASIC, BAH, BAS, 4_200.0)
    e0 = next(r for r in early.rows if r.offset == 0)
    l0 = next(r for r in late.rows if r.offset == 0)
    assert e0.military_pay < l0.military_pay
    assert l0.military_pay == pytest.approx(BASIC + BAH + BAS)


def test_retired_pay_arrives_after_a_gap_and_the_va_after_the_rating():
    filed = TR.cash_flow(date(2027, 3, 31), BASIC, BAH, BAS, 6_000.0,
                         is_retiring=True, retired_pay_monthly=5_000.0,
                         va_monthly=1_500.0,
                         va=TR.va_timing(1_500.0, filed_bdd=True))
    unfiled = TR.cash_flow(date(2027, 3, 31), BASIC, BAH, BAS, 6_000.0,
                           is_retiring=True, retired_pay_monthly=5_000.0,
                           va_monthly=1_500.0,
                           va=TR.va_timing(1_500.0, filed_bdd=False))
    assert filed.va_offset < unfiled.va_offset
    assert filed.total_shortfall < unfiled.total_shortfall
    first = next(r for r in filed.rows if r.offset == 1)
    assert first.retired_pay == 0.0          # 30 to 60 days to establish
    second = next(r for r in filed.rows if r.offset == 2)
    assert second.retired_pay == pytest.approx(5_000.0)


def test_the_timeline_runs_three_months_before_to_six_after():
    flow = TR.cash_flow(date(2027, 3, 31), BASIC, BAH, BAS, 4_200.0)
    assert [r.offset for r in flow.rows] == list(range(-3, 7))
    assert flow.rows[0].label == "Dec 2026"
    assert flow.rows[-1].label == "Sep 2027"


# ==========================================================================
# analyze() and findings()
# ==========================================================================

def test_analyze_reads_the_member_and_orders_findings_by_dollars():
    h = _member(monthly_expenses=4_200.0, grade="E-5", years_of_service=6.0,
                birth_year=1999, duty_zip="28310", has_dependents=True,
                leave_balance_days=45.0, planned_separation_date="2027-03-31")
    t = TR.analyze(h, is_retiring=False, today=date(2026, 9, 10))

    assert t.basic_monthly > 0
    assert t.leave.days == 45
    assert t.leave.take.after_tax > t.leave.sell.after_tax

    out = TR.findings(t)
    assert out and all(len(f) == 3 for f in out)
    assert all(f[0] in ("good", "warn", "bad", "info") for f in out)
    heads = [f[1] for f in out]
    assert len(heads) == len(set(heads))


def test_findings_lead_with_a_dollar_figure_and_end_with_the_unpriced_ones():
    h = _member(monthly_expenses=4_200.0, leave_balance_days=45.0,
                duty_zip="28310", has_dependents=True,
                planned_separation_date="2027-03-31")
    out = TR.findings(TR.analyze(h, is_retiring=False, today=date(2026, 9, 10)))
    assert "$" in out[0][1]
    assert any("UCX" in f[1] for f in out)


def test_an_empty_household_still_produces_findings_without_dividing_by_zero():
    t = TR.analyze(Household(), is_retiring=False)
    assert TR.findings(t)
    assert TR.countdown(t)
    assert t.leave.take.after_tax == 0.0


def test_the_countdown_has_twelve_six_three_and_one_month_milestones():
    h = _member(planned_separation_date="2027-03-31")
    ms = TR.countdown(TR.analyze(h, today=date(2026, 9, 10)))
    assert [x.months_out for x in ms] == [12, 6, 3, 1]
    assert all(x.items for x in ms)
    assert "Mar 2026" in ms[0].label          # twelve months before Mar 2027
    assert "Feb 2027" in ms[-1].label
    assert any("BDD" in i for i in ms[1].items)


def test_a_blank_separation_date_becomes_a_placeholder_not_a_crash():
    d = TR.parse_separation_date("", today=date(2026, 9, 10))
    assert d == date(2027, 3, 9)
    assert TR.parse_separation_date("not a date", today=date(2026, 9, 10)) == d
    assert TR.parse_separation_date("2028-01-31") == date(2028, 1, 31)


# ==========================================================================
# The page renders, headlessly, against both sample plans
# ==========================================================================

@pytest.mark.parametrize("sample", SAMPLES, ids=lambda p: p.stem)
def test_the_page_renders_against_the_sample_plans(sample):
    from streamlit.testing.v1 import AppTest
    from ui.panel import PROFILE_KEY, VERSION_KEY

    h = storage.from_upload_bytes(sample.read_bytes())
    h.member.leave_balance_days = 45.0
    h.member.planned_separation_date = "2027-03-31"

    at = AppTest.from_file(str(PAGE), default_timeout=90)
    at.session_state[PROFILE_KEY] = h
    at.session_state[VERSION_KEY] = 1
    at.run()

    assert not at.exception, at.exception
    assert at.title[0].value.startswith("🚪")


@pytest.mark.parametrize("sample", SAMPLES, ids=lambda p: p.stem)
def test_the_page_survives_the_other_leave_choices(sample):
    from streamlit.testing.v1 import AppTest
    from ui.panel import PROFILE_KEY, VERSION_KEY

    h = storage.from_upload_bytes(sample.read_bytes())
    h.member.leave_balance_days = 75.0        # over the career cap

    at = AppTest.from_file(str(PAGE), default_timeout=90)
    at.session_state[PROFILE_KEY] = h
    at.session_state[VERSION_KEY] = 1
    at.run()
    assert not at.exception, at.exception

    for label in TR.LEAVE_CHOICES:
        at.radio(key=f"tr_choice__v1").set_value(label).run()
        assert not at.exception, at.exception

    at.toggle(key="tr_bdd__v1").set_value(True).run()
    assert not at.exception, at.exception
    at.number_input(key="tr_loan__v1").set_value(15_000.0).run()
    assert not at.exception, at.exception


def test_the_page_binds_the_leave_balance_back_to_the_member():
    from streamlit.testing.v1 import AppTest
    from ui.panel import PROFILE_KEY, VERSION_KEY, DIRTY_KEY

    h = storage.from_upload_bytes(SAMPLES[0].read_bytes())
    at = AppTest.from_file(str(PAGE), default_timeout=90)
    at.session_state[PROFILE_KEY] = h
    at.session_state[VERSION_KEY] = 1
    at.run()
    assert not at.exception, at.exception

    at.number_input(key="tr_days__v1").set_value(52.0).run()
    assert not at.exception, at.exception
    assert at.session_state[PROFILE_KEY].member.leave_balance_days == 52.0
    assert at.session_state[DIRTY_KEY]


def test_the_page_binds_the_separation_date_back_to_the_member():
    from streamlit.testing.v1 import AppTest
    from ui.panel import PROFILE_KEY, VERSION_KEY, DIRTY_KEY

    h = storage.from_upload_bytes(SAMPLES[0].read_bytes())
    h.member.planned_separation_date = "2027-03-31"
    at = AppTest.from_file(str(PAGE), default_timeout=90)
    at.session_state[PROFILE_KEY] = h
    at.session_state[VERSION_KEY] = 1
    at.run()
    assert not at.exception, at.exception
    assert at.session_state[PROFILE_KEY].member.planned_separation_date == "2027-03-31"

    at.date_input(key="tr_date__v1").set_value(date(2027, 6, 30)).run()
    assert not at.exception, at.exception
    assert at.session_state[PROFILE_KEY].member.planned_separation_date == "2027-06-30"
    assert at.session_state[DIRTY_KEY]
