import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

from engine.benefits import concurrent_receipt as CR
from engine.benefits import sbp as SBP


# ==========================================================================
# CRDP / CRSC eligibility
# ==========================================================================

def test_crdp_needs_both_twenty_years_and_a_fifty_percent_rating():
    assert CR.eligibility(20, 50, False).crdp
    assert not CR.eligibility(19, 100, False).crdp
    assert not CR.eligibility(26, 40, False).crdp


def test_crsc_has_no_length_of_service_requirement():
    """This is the whole point of CRSC for a Chapter 61 retiree."""
    e = CR.eligibility(8, 60, True, is_chapter_61=True)
    assert e.crsc
    assert not e.crdp


def test_crdp_is_automatic_and_crsc_is_not():
    e = CR.eligibility(26, 100, True)
    assert "automatic" in e.crdp_reason
    assert "must apply" in e.crsc_reason


def test_the_crsc_reason_says_who_makes_the_determination():
    e = CR.eligibility(26, 100, False)
    assert "the service determines" in e.crsc_reason
    assert "instrumentality of war" in e.crsc_reason


def test_a_chapter_61_retiree_is_told_crsc_is_still_open():
    e = CR.eligibility(8, 60, False, is_chapter_61=True)
    assert "Chapter 61" in e.crdp_reason


# ==========================================================================
# The after-tax comparison -- the reason this module exists
# ==========================================================================

def test_crsc_is_tax_free_and_crdp_is_not():
    c = CR.compare(crdp_monthly=3000, crsc_monthly=3000, marginal_tax_rate=0.24)
    assert c.crsc_after_tax == c.crsc_gross_annual
    assert c.crdp_after_tax < c.crdp_gross_annual


def test_a_larger_crdp_can_still_lose_after_tax():
    """The mismatch DFAS cannot see, because it compares gross."""
    c = CR.compare(crdp_monthly=3200, crsc_monthly=2600,
                   marginal_tax_rate=0.24, state_tax_rate=0.05)
    assert c.better_by_gross == CR.CRDP
    assert c.better_by_after_tax == CR.CRSC
    assert c.mismatch
    assert c.after_tax_difference > 0


def test_the_mismatch_note_names_the_default_and_the_fix():
    c = CR.compare(3200, 2600, marginal_tax_rate=0.24, state_tax_rate=0.05)
    note = c.notes[0]
    assert "DFAS would default you to CRDP" in note
    assert "open season" in note


def test_no_mismatch_when_the_default_is_already_right():
    c = CR.compare(crdp_monthly=4000, crsc_monthly=2000, marginal_tax_rate=0.12)
    assert not c.mismatch
    assert "DFAS default is correct" in c.notes[0]


def test_a_higher_tax_rate_makes_crsc_relatively_better():
    low = CR.compare(3200, 2600, marginal_tax_rate=0.10)
    high = CR.compare(3200, 2600, marginal_tax_rate=0.35)
    assert not low.mismatch
    assert high.mismatch


def test_the_breakeven_is_reported():
    c = CR.compare(3200, 2600, marginal_tax_rate=0.24)
    assert any("break-even" in n for n in c.notes)


def test_the_comparison_says_it_is_a_recurring_decision():
    c = CR.compare(3200, 2600)
    assert any("recurring decision" in n for n in c.notes)


def test_findings_warn_about_va_retroactive_recoupment():
    e = CR.eligibility(26, 100, True)
    c = CR.compare(3200, 2600, marginal_tax_rate=0.24, state_tax_rate=0.05)
    detail = " ".join(d for _, _, d in CR.findings(e, c, 100, 26))
    assert "recoupment" in detail


def test_a_dual_eligible_is_told_dfas_compares_gross():
    e = CR.eligibility(26, 100, True)
    out = CR.findings(e, None, 100, 26)
    assert any("GROSS" in d for _, _, d in out)


# ==========================================================================
# SBP
# ==========================================================================

def sbp(**kw) -> SBP.SBPAnalysis:
    base = dict(retired_pay_monthly=7276, retirement_age=47,
                member_life_expectancy=82, survivor_life_expectancy=90,
                survivor_age_at_retirement=45, marginal_tax_rate=0.22)
    base.update(kw)
    return SBP.analyse(**base)


def test_premium_and_annuity_are_the_statutory_rates():
    a = sbp()
    assert a.premium_monthly == pytest.approx(a.base_amount_monthly * 0.065)
    assert a.annuity_monthly == pytest.approx(a.base_amount_monthly * 0.55)


def test_the_premium_is_pre_tax_so_the_real_cost_is_lower():
    a = sbp(marginal_tax_rate=0.24)
    assert a.premium_after_tax_monthly == pytest.approx(a.premium_monthly * 0.76)


def test_premiums_stop_at_the_paid_up_point():
    """Thirty years of premiums AND age 70 -- whichever comes later."""
    early = sbp(retirement_age=42)
    late = sbp(retirement_age=55)
    assert early.years_paying == pytest.approx(30.0)      # 30 years binds
    assert late.years_paying == pytest.approx(27.0)       # age 70 binds


def test_cost_and_benefit_are_valued_at_the_same_date():
    """
    Comparing a discounted benefit against an undiscounted premium sum
    understates SBP by roughly a third. Both sides must be present values.
    """
    a = sbp()
    assert a.premiums_present_value > 0
    assert a.premiums_present_value < a.total_premiums_after_tax


def test_the_value_depends_heavily_on_survivor_longevity():
    """That sensitivity IS the answer -- SBP is insurance against a long life."""
    short = sbp(survivor_life_expectancy=85)
    long = sbp(survivor_life_expectancy=95)
    assert long.annuity_present_value > short.annuity_present_value * 2
    ratio_short = short.annuity_present_value / short.premiums_present_value
    ratio_long = long.annuity_present_value / long.premiums_present_value
    assert ratio_short < 1.2 < ratio_long


def test_the_dic_offset_repeal_is_stated_explicitly():
    """A large body of published advice predates this and is now wrong."""
    a = sbp(dic_applies=True)
    joined = " ".join(a.notes)
    assert "repealed effective 1 January 2023" in joined
    assert "predates the repeal" in joined
    assert a.survivor_total_monthly > a.annuity_monthly


def test_without_dic_the_repeal_is_still_mentioned():
    joined = " ".join(sbp(dic_applies=False).notes)
    assert "both SBP and DIC in full" in joined


def test_the_paid_up_cap_is_called_out_as_the_overlooked_feature():
    joined = " ".join(sbp().notes)
    assert "most overlooked feature" in joined
    assert "buy term instead" in joined


def test_the_equivalent_term_face_is_reported_and_needs_permanent_cover():
    a = sbp()
    assert a.equivalent_term_face > 0
    joined = " ".join(a.notes)
    assert "permanent coverage, not term" in joined


def test_the_notes_name_the_three_risks_transferred():
    joined = " ".join(sbp().notes)
    for risk in ("longevity", "inflation", "sequence"):
        assert risk in joined


def test_the_irrevocability_window_is_stated():
    joined = " ".join(sbp().notes)
    assert "second and third anniversary" in joined
    assert "notarised" in joined


def test_a_reduced_base_amount_scales_everything():
    full = sbp()
    half = sbp(base_amount_monthly=3638)
    assert half.premium_monthly == pytest.approx(full.premium_monthly / 2, rel=0.01)
    assert half.annuity_monthly == pytest.approx(full.annuity_monthly / 2, rel=0.01)


# ==========================================================================
# SBP findings
# ==========================================================================

def test_not_electing_is_flagged_as_a_deliberate_choice_to_make():
    out = SBP.findings(sbp(), elected=False, has_spouse=True)
    assert any(sev == "warn" and "not elected" in head for sev, head, _ in out)
    detail = " ".join(d for _, _, d in out)
    assert "notarised concurrence" in detail


def test_no_spouse_means_nothing_to_elect():
    out = SBP.findings(sbp(), elected=False, has_spouse=False)
    assert any("spouse and dependent benefit" in head for _, head, _ in out)


def test_a_close_ratio_points_at_the_longevity_assumption():
    out = SBP.findings(sbp(survivor_life_expectancy=85), True, True)
    detail = " ".join(d for _, _, d in out)
    assert "longer survivor life expectancy" in detail


def test_the_findings_refuse_to_frame_sbp_as_a_rate_of_return():
    detail = " ".join(d for _, _, d in SBP.findings(sbp(), True, True))
    assert "Not a rate of return" in detail
    assert "cannot be outlived" in detail
