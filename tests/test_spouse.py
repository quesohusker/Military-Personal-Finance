"""
Tests for spouse income under PCS interruption.

The point of this module is that a military spouse's earnings are NOT a
continuous career. These tests pin that: a move must cost something, career
type must change how much, and dual-military must cost nothing.
"""

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

from engine.income import spouse as SP
from engine.career.timeline import PCSMove

MOVES = [PCSMove(9, "92134"), PCSMove(12, "22060"), PCSMove(15, "28310")]


def employed(**kw) -> SP.SpouseIncome:
    base = dict(employed=True, career_type=SP.CAREER_LOCAL, annual_income=52_000,
                retirement_contribution_pct=0.06, employer_match_pct=0.03)
    base.update(kw)
    return SP.SpouseIncome(**base)


def project(s, moves=MOVES, start=6, end=20):
    return SP.project_spouse_income(s, moves, 2026, start, end)


# ==========================================================================
# The core claim: moves cost money
# ==========================================================================

def test_moves_cost_the_spouse_earnings():
    p = project(employed())
    assert p.total_lost > 0
    assert p.total_earned < p.total_uninterrupted
    assert p.n_moves == 3


def test_more_moves_cost_more():
    few = project(employed(), moves=[PCSMove(9, "x")])
    many = project(employed(), moves=MOVES)
    assert many.total_lost > few.total_lost


def test_no_moves_costs_nothing():
    p = project(employed(), moves=[])
    assert p.total_lost == pytest.approx(0.0, abs=1.0)
    assert p.n_moves == 0


def test_an_unemployed_spouse_projects_nothing():
    p = project(SP.SpouseIncome(employed=False))
    assert p.years == []
    assert p.total_earned == 0


def test_zero_income_projects_nothing():
    p = project(employed(annual_income=0))
    assert p.years == []


# ==========================================================================
# Career type changes the answer, which is the actionable part
# ==========================================================================

def test_portable_work_costs_far_less_than_local_employment():
    portable = project(employed(career_type=SP.CAREER_PORTABLE))
    local = project(employed(career_type=SP.CAREER_LOCAL))
    assert portable.total_lost < local.total_lost / 2


def test_a_licensed_profession_is_the_worst_case():
    licensed = project(employed(career_type=SP.CAREER_LICENSED))
    local = project(employed(career_type=SP.CAREER_LOCAL))
    assert licensed.total_lost > local.total_lost


def test_federal_employment_sits_between_portable_and_local():
    fed = project(employed(career_type=SP.CAREER_FEDERAL)).total_lost
    port = project(employed(career_type=SP.CAREER_PORTABLE)).total_lost
    local = project(employed(career_type=SP.CAREER_LOCAL)).total_lost
    assert port < fed < local


def test_every_career_type_has_an_interruption_factor():
    assert set(SP.INTERRUPTION_FACTOR) == set(SP.CAREER_TYPES)


# ==========================================================================
# Dual military
# ==========================================================================

def test_dual_military_loses_nothing_to_a_pcs():
    """Both are on orders, so neither income stops."""
    p = project(employed(is_dual_military=True))
    assert p.total_lost == pytest.approx(0.0, abs=1.0)


def test_dual_military_finding_names_the_real_risk():
    s = employed(is_dual_military=True)
    out = SP.findings(s, project(s))
    detail = " ".join(d for _, _, d in out)
    assert "joint-spouse" in detail
    assert "two households" in detail


# ==========================================================================
# Lost retirement saving
# ==========================================================================

def test_lost_income_also_costs_retirement_saving():
    p = project(employed())
    assert p.total_retirement_lost > 0


def test_no_retirement_contribution_means_no_retirement_loss():
    p = project(employed(retirement_contribution_pct=0.0, employer_match_pct=0.0))
    assert p.total_retirement_lost == 0


def test_the_retirement_loss_compounds():
    """Earlier losses have longer to compound, so they cost more."""
    early = project(employed(), moves=[PCSMove(7, "x")])
    late = project(employed(), moves=[PCSMove(19, "x")])
    assert early.total_retirement_lost > late.total_retirement_lost


# ==========================================================================
# Mechanics
# ==========================================================================

def test_a_move_year_shows_months_out_of_work():
    p = project(employed())
    moved = [r for r in p.years if r.moved]
    assert moved
    assert all(r.months_worked < 12 for r in moved)


def test_pay_rebuilds_between_moves():
    p = project(employed(), moves=[PCSMove(9, "x")])
    after = [r for r in p.years if r.years_of_service > 9]
    rates = [r.wage_rate_annual for r in after]
    assert rates == sorted(rates), "wage rate should recover after a move"


def test_earnings_never_exceed_the_uninterrupted_counterfactual():
    p = project(employed())
    for r in p.years:
        assert r.earned <= r.uninterrupted + 0.01


def test_lost_share_is_a_fraction():
    p = project(employed())
    assert 0 < p.lost_share < 1


# ==========================================================================
# Findings
# ==========================================================================

def test_the_headline_finding_quantifies_the_cost():
    s = employed()
    out = SP.findings(s, project(s))
    assert any(sev == "bad" and "cost your spouse" in head for sev, head, _ in out)


def test_findings_say_this_is_not_an_argument_against_serving():
    s = employed()
    detail = " ".join(d for _, _, d in SP.findings(s, project(s)))
    assert "not a reason not to serve" in detail


def test_a_licensed_spouse_is_told_about_the_reimbursement():
    s = employed(career_type=SP.CAREER_LICENSED)
    detail = " ".join(d for _, _, d in SP.findings(s, project(s)))
    assert "reimburses" in detail
    assert "per PCS" in detail or "per move" in detail


def test_a_local_employee_is_pointed_at_portable_work():
    s = employed(career_type=SP.CAREER_LOCAL)
    heads = [h for _, h, _ in SP.findings(s, project(s))]
    assert any("Portable work" in h for h in heads)


def test_no_spouse_income_still_gives_useful_guidance():
    out = SP.findings(SP.SpouseIncome(employed=False), SP.SpouseProjection())
    assert out
    assert "legitimate choice" in " ".join(d for _, _, d in out)
