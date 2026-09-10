"""
Tests for the priority waterfall and the career timeline.

The waterfall tests exist mainly to pin down the five places where military
rules diverge from the civilian flowchart. Those are the parts that are easy to
regress into generic advice, and generic advice here is wrong advice.
"""

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

from engine.profile import (Household, ServiceMember, ACTIVE, GUARD, RESERVE,
                            RETIRED, VETERAN, SYS_BRS, SYS_HIGH3,
                            retirement_system_for_diems, has_tsp_match)
from engine.debt.payoff import Debt
from engine.coach import prime_directive as PD
from engine.career import timeline as TL
from engine.pay import grades as G, bah as BAH


def brs_member(**kw) -> ServiceMember:
    base = dict(birth_year=1999, component=ACTIVE, grade="E-5",
                years_of_service=6.0, diems_date="2020-06-01",
                duty_zip="28310", has_dependents=True,
                basic_pay_monthly_override=3706.20, tsp_contribution_pct=0.05)
    base.update(kw)
    return ServiceMember(**base)


def legacy_member(**kw) -> ServiceMember:
    base = dict(birth_year=1985, component=ACTIVE, grade="O-4",
                years_of_service=16.0, diems_date="2010-05-15",
                basic_pay_monthly_override=9500.0, tsp_contribution_pct=0.05)
    base.update(kw)
    return ServiceMember(**base)


def household(member, **kw) -> Household:
    h = Household(member=member)
    h.monthly_expenses = kw.pop("monthly_expenses", 4200.0)
    h.cash_savings = kw.pop("cash_savings", 5000.0)
    for k, v in kw.items():
        setattr(h, k, v)
    return h


# ==========================================================================
# The five military divergences
# ==========================================================================

def test_tsp_match_step_does_not_apply_under_a_legacy_system():
    """'Always get the match' is wrong advice for a High-3 member."""
    r = PD.evaluate(household(legacy_member()))
    step = r.by_key("tsp_match")
    assert step.status == PD.NOT_APPLICABLE
    assert "no TSP match" in step.action
    assert "High-3" in step.action


def test_tsp_match_step_applies_under_brs():
    r = PD.evaluate(household(brs_member(tsp_contribution_pct=0.03)))
    step = r.by_key("tsp_match")
    assert step.applies
    assert step.status == PD.IN_PROGRESS
    assert "5%" in step.action


def test_tsp_match_says_it_is_computed_on_basic_pay_only():
    r = PD.evaluate(household(brs_member(tsp_contribution_pct=0.03)))
    assert "BASIC PAY ONLY" in r.by_key("tsp_match").military_note


def test_tsp_match_quantifies_the_money_being_left_behind():
    r = PD.evaluate(household(brs_member(tsp_contribution_pct=0.03)))
    step = r.by_key("tsp_match")
    # 2 percentage points of $3,706.20/mo for a year.
    assert step.amount_needed == pytest.approx(3706.20 * 0.02 * 12, rel=0.01)


def test_hsa_is_not_applicable_to_active_duty():
    """TRICARE is not a high-deductible plan, so the step cannot be taken."""
    r = PD.evaluate(household(brs_member()))
    step = r.by_key("hsa")
    assert step.status == PD.NOT_APPLICABLE
    assert "TRICARE is not one" in step.action


def test_hsa_is_available_after_separation():
    r = PD.evaluate(household(brs_member(component=VETERAN)))
    assert r.by_key("hsa").status != PD.NOT_APPLICABLE


def test_sdp_outranks_the_tsp_match_when_deployed():
    m = brs_member(is_deployed=True, drawing_hostile_fire_pay=True, sdp_balance=0)
    r = PD.evaluate(household(m))
    sdp, match = r.by_key("sdp"), r.by_key("tsp_match")
    assert sdp.applies
    assert sdp.order < match.order
    assert sdp.weight >= match.weight


def test_sdp_does_not_apply_when_not_deployed():
    r = PD.evaluate(household(brs_member()))
    assert r.by_key("sdp").status == PD.NOT_APPLICABLE


def test_sdp_requires_hostile_fire_pay_not_merely_deployment():
    m = brs_member(is_deployed=True, drawing_hostile_fire_pay=False)
    assert PD.evaluate(household(m)).by_key("sdp").status == PD.NOT_APPLICABLE


def test_scra_step_comes_before_the_debt_step():
    """Capping pre-service debt at 6% can reorder the payoff queue."""
    m = brs_member()
    h = household(m, debts=[Debt("Visa", 6800, 0.2249, 180,
                                 incurred_before_service=True)])
    r = PD.evaluate(h)
    assert r.by_key("scra").order < r.by_key("high_interest_debt").order


def test_scra_quantifies_the_annual_interest_saved():
    h = household(brs_member(),
                  debts=[Debt("Visa", 10_000, 0.24, 250, incurred_before_service=True)])
    step = PD.evaluate(h).by_key("scra")
    assert step.status == PD.NOT_STARTED
    assert step.amount_needed == pytest.approx(10_000 * (0.24 - 0.06), rel=0.01)
    assert "orders" in step.action


def test_scra_does_not_apply_to_debt_incurred_during_service():
    h = household(brs_member(),
                  debts=[Debt("Visa", 10_000, 0.24, 250, incurred_before_service=False)])
    step = PD.evaluate(h).by_key("scra")
    assert step.status == PD.DONE


def test_scra_cap_removes_a_debt_from_the_high_interest_step():
    """A 22% pre-service card becomes a 6% obligation once capped."""
    h = household(brs_member(),
                  debts=[Debt("Visa", 6800, 0.2249, 180, incurred_before_service=True)])
    assert PD.evaluate(h).by_key("high_interest_debt").status == PD.DONE

    h2 = household(brs_member(),
                   debts=[Debt("Visa", 6800, 0.2249, 180, incurred_before_service=False)])
    assert PD.evaluate(h2).by_key("high_interest_debt").status == PD.IN_PROGRESS


# ==========================================================================
# Waterfall mechanics
# ==========================================================================

def test_emergency_fund_target_is_lower_while_serving():
    serving = PD.evaluate(household(brs_member())).by_key("full_ef")
    civilian = PD.evaluate(household(brs_member(component=VETERAN))).by_key("full_ef")
    assert serving.target < civilian.target
    assert "job loss" in serving.military_note


def test_score_is_zero_for_an_empty_profile_and_high_for_a_complete_one():
    empty = Household(member=brs_member(basic_pay_monthly_override=0,
                                        tsp_contribution_pct=0.0))
    empty.monthly_expenses = 0
    empty.cash_savings = 0
    low = PD.evaluate(empty).score

    m = brs_member(tsp_contribution_pct=0.35, ira_contributed_this_year=7500)
    good = household(m, cash_savings=60_000, taxable_brokerage=50_000)
    high = PD.evaluate(good).score
    assert low < 25
    assert high > 80
    assert 0 <= low <= 100 and 0 <= high <= 100


def test_current_step_is_the_first_incomplete_applicable_one():
    r = PD.evaluate(household(brs_member(tsp_contribution_pct=0.0),
                              cash_savings=0, monthly_expenses=4000))
    assert r.current is not None
    assert r.current.applies and not r.current.complete
    earlier = [s for s in r.active_steps if s.order < r.current.order]
    assert all(s.complete for s in earlier)


def test_not_applicable_steps_are_excluded_from_the_score():
    r = PD.evaluate(household(legacy_member()))
    assert r.applicable == len([s for s in r.steps if s.applies])
    assert r.applicable < len(r.steps)


def test_every_step_has_an_action_and_a_reason():
    for member in (brs_member(), legacy_member(),
                   brs_member(is_deployed=True, drawing_hostile_fire_pay=True)):
        for s in PD.evaluate(household(member)).steps:
            assert s.title and s.action and s.why, s.key


def test_combat_zone_surfaces_the_higher_tsp_limit():
    m = brs_member(in_combat_zone=True, is_deployed=True,
                   drawing_hostile_fire_pay=True)
    note = PD.evaluate(household(m)).by_key("roth_tsp").military_note
    assert "72,000" in note and "24,500" in note


# ==========================================================================
# Career timeline
# ==========================================================================

def test_default_promotions_only_go_upward():
    for grade in ("E-4", "E-7", "O-2", "O-4", "W-2"):
        ups = TL.default_promotions(grade, 5)
        cur = G.get(grade).sort
        assert all(G.get(p.to_grade).sort > cur for p in ups), grade


def test_default_promotions_never_schedule_one_in_the_past():
    for p in TL.default_promotions("E-5", 12.0):
        assert p.at_years_of_service > 12.0


def test_officer_and_enlisted_use_different_tables():
    assert [p.to_grade for p in TL.default_promotions("O-3", 5)][0] == "O-4"
    assert [p.to_grade for p in TL.default_promotions("E-5", 5)][0] == "E-6"
    assert [p.to_grade for p in TL.default_promotions("W-2", 3)][0] == "W-3"


def test_promotion_note_warns_that_enlisted_timing_varies():
    assert "varies more" in TL.promotion_note("E-5")
    assert "DOPMA" in TL.promotion_note("O-3")


def test_timeline_roundtrips_through_a_dict():
    t = TL.CareerTimeline(promotions=TL.default_promotions("E-5", 6),
                          moves=[TL.PCSMove(8.0, "92134", "San Diego")],
                          separation_at_years_of_service=20.0)
    back = TL.CareerTimeline.from_dict(t.to_dict())
    assert len(back.promotions) == len(t.promotions)
    assert back.moves[0].destination_zip == "92134"
    assert back.separation_at_years_of_service == 20.0


needs_bah = pytest.mark.skipif(BAH.load() is None, reason="No BAH data installed")


@needs_bah
def test_move_comparison_prices_the_bah_change():
    m = TL.compare_locations("73503", "92134", "E-5", True)
    assert m.found
    assert m.monthly_change > 2_000          # Fort Sill -> San Diego
    assert m.annual_change == pytest.approx(m.monthly_change * 12)
    assert "tax-free" in m.note


@needs_bah
def test_move_comparison_handles_a_pay_cut_move():
    m = TL.compare_locations("92134", "73503", "E-5", True)
    assert m.found and m.monthly_change < 0
    assert "mortgage" in m.note


@needs_bah
def test_move_comparison_reports_an_unknown_zip_rather_than_failing():
    m = TL.compare_locations("73503", "09045", "E-5", True)
    assert not m.found and m.note


@needs_bah
def test_projection_applies_promotions_and_moves():
    m = brs_member(grade="E-5", years_of_service=6.0, duty_zip="73503")
    t = TL.CareerTimeline(
        promotions=[TL.Promotion("E-6", 8.5), TL.Promotion("E-7", 13.5)],
        moves=[TL.PCSMove(9.0, "92134", "San Diego")],
        separation_at_years_of_service=20.0)
    rows = TL.project(m, t, start_year=2026)

    assert rows[0].grade == "E-5"
    assert rows[-1].years_of_service >= 19
    assert any(r.grade == "E-6" for r in rows)
    assert any(r.grade == "E-7" for r in rows)
    # BAH must jump on the move, not drift.
    before = [r for r in rows if r.years_of_service < 9][-1]
    after = [r for r in rows if r.years_of_service >= 9][0]
    assert after.bah_monthly > before.bah_monthly * 1.5


@needs_bah
def test_projection_reports_the_nontaxable_share():
    m = brs_member(duty_zip="92134")
    rows = TL.project(m, TL.CareerTimeline(separation_at_years_of_service=8.0),
                      start_year=2026)
    r = rows[0]
    assert r.nontaxable_monthly > 0
    assert 0 < r.nontaxable_share < 1
    assert r.total_monthly == pytest.approx(r.taxable_monthly + r.nontaxable_monthly)


@needs_bah
def test_government_quarters_pay_no_bah():
    m = brs_member(duty_zip="92134", lives_in_government_housing=True)
    rows = TL.project(m, TL.CareerTimeline(separation_at_years_of_service=8.0),
                      start_year=2026)
    assert all(r.bah_monthly == 0 for r in rows)
