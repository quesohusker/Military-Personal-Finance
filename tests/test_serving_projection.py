"""
The spine over the serving years — docs/ARCHITECTURE.md §7 step 4.

`Profile` had no concept of being in uniform (§4b): no grade, no DIEMS, no
promotions, no separation. Wages were one figure grown at a real rate, which
is a civilian shape, so the projection either refused or answered a question
nobody asked. These tests pin the three things that changed:

  1. Military pay STEPS. It is read off `engine/career/timeline.py`, never
     modelled a second time here, and every figure below is checked against
     the engine that owns it rather than against a memory of it.
  2. Most of it is not taxable. The E-5 sample is paid $84,815 with $20,550
     in box 1 — 76% never reaches a return — and the tax closure must see
     only the $20,550 while the cash flow sees all of it.
  3. The pension starts LATER, or not at all. Never in the same year as
     military pay, never before twenty years, and never for a Guard or
     Reserve career the tables cannot price.

And the rule that protects everything already built: a household not in
uniform must come out of this unchanged.
"""

import sys
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import storage
from engine.profile import (Household, ServiceMember, ACTIVE, GUARD, RESERVE,
                            VETERAN, RETIRED, SYS_HIGH3 as APP_HIGH3)
from engine.career import timeline as TL
from engine.pay import basepay as BP, bah as BAH, bas as BAS, taxable as TP
from engine.retirement import roth_bridge as RB
from engine.retirement import tsp as TSP
from engine.retirement import systems as SYS
from engine.retirement.projection import run_projection
from engine.roth_profile import Profile, MilitaryService

# Pinned so the figures do not move under the tests when the calendar does.
YEAR = 2026
E5 = "e5_6yrs_brs.mpfplan.json"
O5 = "retired_o5_26yrs.mpfplan.json"


def load(name: str) -> Household:
    return storage.from_upload_bytes((ROOT / "samples" / name).read_bytes())


def profile(name: str, timeline=None) -> Profile:
    h = load(name)
    return RB.to_roth_profile(h, RB.default_inputs(h, YEAR), start_year=YEAR,
                              timeline=timeline)


# ==========================================================================
# The rule that protects what already works
# ==========================================================================

def test_a_retiree_has_no_service_block_at_all():
    p = profile(O5)
    assert p.service.serving is False
    assert p.service.years == []
    assert p.service.not_modelled == ""
    # 0 means "already flowing", which is what leaves the retiree walk alone.
    assert p.military.pension_start_year == 0
    assert p.military.retired_pay_monthly == pytest.approx(8_056.62)


def test_the_retiree_projection_does_not_move():
    """
    Verified row by row against the engine as it stood before step 4: every
    shared field of every year, in both futures, identical. These two totals
    are the summary of that comparison and they are a regression pin -- if one
    moves, the serving work has reached a household it has no business in.
    """
    p = profile(O5)
    base = run_projection(p, convert=False)
    conv = run_projection(p, convert=True)

    assert base.lifetime_total_tax == pytest.approx(2_136_682.63, abs=1.0)
    assert base.heir_value_total == pytest.approx(11_400_863.36, abs=1.0)
    assert conv.lifetime_total_tax == pytest.approx(2_147_058.82, abs=1.0)
    assert conv.heir_value_total == pytest.approx(11_444_034.89, abs=1.0)

    # Nothing in the serving half touches a retiree's rows.
    assert all(r.military_allowances == 0.0 for r in base.rows)
    assert all(r.tsp_service_contribution == 0.0 for r in base.rows)
    assert base.separation_year == 0 and base.pension_start_year == 0


# ==========================================================================
# 1. Pay that steps, read off the engine that already models it
# ==========================================================================

def test_the_schedule_covers_every_year_from_now_to_separation():
    sv = profile(E5).service
    assert sv.serving is True
    assert sv.component == ACTIVE
    assert [r.year for r in sv.years] == list(range(2026, 2041))
    assert sv.years[0].years_of_service == 6.0
    assert sv.separation_year == 2040
    assert sv.separation_years_of_service == 20.0


def test_basic_pay_comes_from_the_pay_table_and_steps_at_longevity():
    """
    Not a second pay model: every figure is `basepay.lookup()` for that grade
    and that year of service. The steps at 8, 10 and 12 years are the whole
    reason a growth rate cannot stand in for this.
    """
    table = BP.load()
    sv = profile(E5).service
    for r in sv.years:
        expect = BP.lookup(r.grade, r.years_of_service, table)
        assert expect.found
        assert r.basic_pay_monthly == pytest.approx(expect.monthly)

    by_yos = {r.years_of_service: r.basic_pay_monthly for r in sv.years}
    assert by_yos[6] == by_yos[7] == pytest.approx(4_110.0)     # same band
    assert by_yos[8] == pytest.approx(4_299.90)                 # a step
    assert by_yos[10] == pytest.approx(4_395.30)
    assert by_yos[12] == pytest.approx(4_421.70)
    assert by_yos[8] > by_yos[7] and by_yos[10] > by_yos[9] and by_yos[12] > by_yos[11]


def test_a_promotion_moves_the_pay_and_the_pension_with_it():
    entered = TL.CareerTimeline(promotions=TL.default_promotions("E-5", 6.0),
                                separation_at_years_of_service=20.0, entered=True)
    flat = profile(E5).service
    promoted = profile(E5, timeline=entered).service

    assert flat.separation_grade == "E-5"
    assert promoted.separation_grade == "E-8"
    assert promoted.high_three_monthly > flat.high_three_monthly
    # The grade on each row is the grade the member holds that year.
    at_2029 = next(r for r in promoted.years if r.year == 2029)
    assert at_2029.grade == "E-6"
    assert at_2029.basic_pay_monthly == pytest.approx(
        BP.lookup("E-6", 9, BP.load()).monthly)


def test_the_high_three_is_the_last_thirty_six_months_of_basic_pay():
    sv = profile(E5).service
    tail = sv.years[-3:]
    assert sv.high_three_monthly == pytest.approx(
        sum(r.basic_pay_monthly for r in tail) / 3.0)


# ==========================================================================
# 2. The taxable / untaxed split — the thing civilian tools get wrong
# ==========================================================================

def test_the_first_year_matches_what_the_e5_is_actually_paid():
    """
    HANDOFF's headline figures for this sample, and the reason the app exists:
    paid $84,815, $20,550 in box 1, 76% never reaching a tax return.
    """
    first = profile(E5).service.years[0]
    assert first.total_pay == pytest.approx(84_815, abs=1)
    assert first.taxable_pay == pytest.approx(20_550, abs=1)
    assert first.nontaxable_pay == pytest.approx(64_265, abs=1)
    assert first.nontaxable_share == pytest.approx(0.76, abs=0.005)


def test_the_pay_reconciles_line_by_line_with_the_engines_that_own_it():
    h = load(E5)
    m = h.member
    first = profile(E5).service.years[0]

    basic = BP.lookup(m.grade, m.years_of_service, BP.load()).monthly * 12.0
    bah = BAH.lookup(m.duty_zip, m.grade, m.has_dependents, BAH.load()).monthly * 12.0
    bas = BAS.bas_monthly(False).monthly * 12.0
    special = m.special_pay_monthly * 12.0

    assert first.total_pay == pytest.approx(basic + bah + bas + special)
    # BAH and BAS are never wages, and this file's special pay is not taxable.
    assert first.taxable_pay == pytest.approx(TP.annual_after_czte(m))
    assert first.nontaxable_pay == pytest.approx(bah + bas + special
                                                 + (basic - TP.annual_after_czte(m)))


def test_a_non_taxable_special_pay_stays_out_of_the_taxable_figure():
    h = load(E5)
    h.member.in_combat_zone = False          # take the exclusion out of it
    h.member.special_pay_taxable = False
    untaxed = RB.build_service(h, start_year=YEAR).years[0]
    assert untaxed.taxable_pay == pytest.approx(TP.compute(h.member).annual)

    h.member.special_pay_taxable = True
    taxed = RB.build_service(h, start_year=YEAR).years[0]
    assert taxed.taxable_pay == pytest.approx(TP.compute(h.member).annual)

    special = h.member.special_pay_monthly * 12.0
    assert taxed.total_pay == pytest.approx(untaxed.total_pay)
    assert taxed.taxable_pay - untaxed.taxable_pay == pytest.approx(special)


def test_the_combat_zone_exclusion_applies_once_and_not_to_the_career():
    """
    The §2 decision from docs/STATUS.md, now inside the schedule: a deployment
    is a this-year event. Reducing every year would model a seven-month tour
    as a fourteen-year pay cut.
    """
    sv = profile(E5).service
    assert sv.years[0].taxable_pay == pytest.approx(20_550, abs=1)
    assert sv.years[1].taxable_pay == pytest.approx(49_320, abs=1)
    assert sv.years[0].total_pay == pytest.approx(sv.years[1].total_pay)


def test_a_member_who_is_not_deployed_has_a_fully_taxable_first_year():
    h = load(E5)
    h.member.in_combat_zone = False
    h.member.months_deployed_this_year = 0
    sv = RB.build_service(h, RB.default_inputs(h, YEAR), start_year=YEAR)
    assert sv.years[0].taxable_pay == pytest.approx(49_320, abs=1)


# ==========================================================================
# 3. TSP: the match is basic pay only, BRS only, and always traditional
# ==========================================================================

def test_the_member_contributes_a_share_of_basic_pay_and_the_service_matches():
    sv = profile(E5).service
    first = sv.years[0]
    basic = first.basic_pay_monthly * 12.0

    # 3% elected, all Roth on this file.
    assert first.tsp_member_roth == pytest.approx(basic * 0.03)
    assert first.tsp_member_traditional == 0.0
    # 1% automatic + 3% matching, and the service's money is never Roth.
    expected = TSP.service_match(basic, 0.03, True, first.years_of_service)
    assert first.tsp_service == pytest.approx(expected.total_service)
    assert first.tsp_service == pytest.approx(basic * 0.04)
    assert first.traditional_in == pytest.approx(first.tsp_service)


def test_there_is_no_match_without_brs():
    h = load(E5)
    h.member.diems_date = "2015-06-01"          # High-3, not BRS
    assert h.member.retirement_system == APP_HIGH3
    sv = RB.build_service(h, start_year=YEAR)
    assert all(r.tsp_service == 0.0 for r in sv.years)
    assert sv.years[0].tsp_member_roth > 0      # their own money is unaffected


def test_the_members_own_contribution_is_capped_by_the_deferral_limit():
    h = load(E5)
    h.member.tsp_contribution_pct = 0.90        # a bonus year, or an error
    first = RB.build_service(h, start_year=YEAR).years[0]
    assert first.member_contribution == pytest.approx(
        TSP.elective_limit(YEAR - h.member.birth_year))
    # The match follows the percentage, not the capped dollars: 1% automatic
    # plus a matching contribution that tops out at 4%, so 5% of basic pay and
    # not a cent more however much the member puts in.
    assert first.tsp_service == pytest.approx(first.basic_pay_monthly * 12.0 * 0.05)


# ==========================================================================
# The projection: what the serving years do to the walk
# ==========================================================================

def test_allowances_are_spendable_and_invisible_to_the_tax_return():
    p = profile(E5)
    rows = run_projection(p, convert=False).rows
    first = rows[0]

    assert first.military_taxable_pay == pytest.approx(20_550, abs=1)
    assert first.military_allowances == pytest.approx(64_265, abs=1)
    # Wages are the taxable half plus the spouse's job; AGI never sees the rest.
    assert first.wages == pytest.approx(20_550 + 38_000, abs=1)
    assert first.agi < first.wages + first.military_allowances
    assert first.agi == pytest.approx(first.wages + first.dividends, abs=1)


def test_the_deployed_first_year_is_taxed_exactly_as_it_was_before_step_4():
    """
    The CZTE fix (docs/STATUS.md §2) still holds, to the dollar: the E-5's
    first year was $2,666 of tax on $26,350 of taxable income, and reading the
    year off a schedule instead of a wage figure must not move it.
    """
    rows = run_projection(profile(E5), convert=False).rows
    assert rows[0].total_tax == pytest.approx(2_666, abs=1)


def test_military_pay_stops_at_separation_and_the_pension_starts_after_it():
    p = profile(E5)
    rows = {r.year: r for r in run_projection(p, convert=False).rows}

    assert rows[2040].military_taxable_pay > 0        # last year in uniform
    assert rows[2040].military_retired_pay == 0.0     # not paid twice
    assert rows[2041].military_taxable_pay == 0.0
    assert rows[2041].military_allowances == 0.0
    assert rows[2041].military_retired_pay == pytest.approx(1_768.68 * 12, abs=1)


def test_the_pension_is_the_multiplier_on_the_high_three():
    p = profile(E5)
    sv = p.service
    expect = SYS.retired_pay(SYS.SYS_BRS, 20.0, sv.high_three_monthly)
    assert expect.multiplier == pytest.approx(0.40)
    assert p.military.retired_pay_monthly == pytest.approx(expect.monthly)
    assert p.military.retirement_year == 2040
    assert p.military.years_of_service == 20.0


def test_the_tsp_balance_is_built_by_the_schedule_and_stops_at_separation():
    p = profile(E5)
    p.spouse = None
    p.has_spouse = False
    rows = {r.year: r for r in run_projection(p, convert=False).rows}

    first = p.service.years[0]
    assert rows[2026].tsp_member_contribution == pytest.approx(first.member_contribution)
    assert rows[2026].tsp_service_contribution == pytest.approx(first.tsp_service)
    # 9,000 opening + the service's 4% of basic, then a year of growth.
    assert rows[2026].traditional_balance == pytest.approx(
        (9_000.0 + first.tsp_service) * 1.04, abs=1)
    # Nothing is contributed after the uniform comes off: the app does not ask
    # about a civilian employer plan and does not invent one.
    assert rows[2041].tsp_member_contribution == 0.0
    assert rows[2041].tsp_service_contribution == 0.0
    assert rows[2042].traditional_balance == pytest.approx(
        rows[2041].traditional_balance * 1.04, abs=1)


def test_the_members_own_contribution_leaves_the_paycheck():
    """Money contributed cannot also be money spent."""
    p = profile(E5)
    p.spouse = None
    p.has_spouse = False
    base = run_projection(p, convert=False)

    q = profile(E5)
    q.spouse = None
    q.has_spouse = False
    for r in q.service.years:
        r.tsp_member_roth = 0.0
        r.tsp_member_traditional = 0.0
    none_saved = run_projection(q, convert=False)

    assert none_saved.rows[0].taxable_balance > base.rows[0].taxable_balance


# ==========================================================================
# The twenty-year cliff, and the systems.py gap it exposes
# ==========================================================================

def test_leaving_before_twenty_pays_no_pension_under_brs_either():
    """
    Active-duty retirement vests at twenty under every one of the four systems.

    `systems.retired_pay()` used to zero a short career for the legacy systems
    but NOT for BRS, so asked directly it answered with a pension a member
    leaving at twelve will never be paid. That gap was pinned here and has
    since been closed at source; BRS is gentler because the member keeps the
    TSP and the vested match, not because it pays an annuity at twelve years.
    The bridge applies the same cliff, and now agrees with the engine rather
    than working around it.
    """
    leave_at_12 = TL.CareerTimeline(separation_at_years_of_service=12.0,
                                    entered=True)
    p = profile(E5, timeline=leave_at_12)

    # Closed at source: all four systems answer the same way at twelve years.
    for system in (SYS.SYS_FINAL_PAY, SYS.SYS_HIGH3, SYS.SYS_REDUX, SYS.SYS_BRS):
        assert SYS.retired_pay(system, 12.0, 4_400.0).monthly == 0.0, system
    brs_note = SYS.retired_pay(SYS.SYS_BRS, 12.0, 4_400.0).note
    assert "20-year cliff is absolute" in brs_note
    assert "vested match are still yours" in brs_note, \
        "BRS is gentler for a reason, and the note has to say which"

    # And twenty years is untouched.
    assert SYS.retired_pay(SYS.SYS_BRS, 20.0, 4_400.0).monthly > 0
    assert SYS.retired_pay(SYS.SYS_HIGH3, 20.0, 4_400.0).monthly > 0

    assert p.military.retired_pay_monthly == 0.0
    assert p.military.tricare_annual_cost == 0.0
    monthly, note = RB.pension_at_separation(load(E5).member, p.service)
    assert monthly == 0.0
    assert "short of twenty" in note

    rows = {r.year: r for r in run_projection(p, convert=False).rows}
    assert rows[2032].military_taxable_pay > 0
    assert rows[2033].military_taxable_pay == 0.0
    assert all(r.military_retired_pay == 0.0 for r in rows.values())


def test_a_course_of_action_is_the_same_household_with_two_timelines():
    """
    §7 step 6 is not built. This is the shape that keeps it possible: readiness
    for a serving member is one number per branch, and a branch is a timeline.
    """
    h = load(E5)
    i = RB.default_inputs(h, YEAR)
    stay = RB.to_roth_profile(h, i, start_year=YEAR, timeline=TL.CareerTimeline(
        promotions=TL.default_promotions("E-5", 6.0),
        separation_at_years_of_service=20.0, entered=True))
    leave = RB.to_roth_profile(h, i, start_year=YEAR, timeline=TL.CareerTimeline(
        separation_at_years_of_service=12.0, entered=True))

    a = run_projection(stay, convert=False)
    b = run_projection(leave, convert=False)
    assert a.pension_start_year == 2041 and b.pension_start_year == 2033
    assert a.pension_annual_at_start > 0 and b.pension_annual_at_start == 0
    assert a.lifetime_military_taxable_pay > b.lifetime_military_taxable_pay
    # Same household, same plan file, two futures priced side by side.
    assert stay.primary.birth_year == leave.primary.birth_year
    assert h.career.separation_at_years_of_service == 20.0   # neither mutated it


# ==========================================================================
# What still cannot be modelled says so, rather than guessing
# ==========================================================================

@pytest.mark.parametrize("component", [GUARD, RESERVE])
def test_guard_and_reserve_refuse_rather_than_run_on_active_duty_tables(component):
    h = load(E5)
    h.member.component = component
    p = RB.to_roth_profile(h, RB.default_inputs(h, YEAR), start_year=YEAR)

    assert p.service.serving is False
    assert p.service.years == []
    assert "drill pay" in p.service.not_modelled
    assert p.service.component == component
    # No pension is invented for them either: theirs starts at 60, on points.
    assert p.military.retired_pay_monthly == 0.0
    assert p.military.pension_start_year == 0


def test_the_unanswered_career_page_is_named_as_an_assumption():
    sv = profile(E5).service
    said = " ".join(sv.assumptions).lower()
    assert "nobody has answered the career page" in said
    assert "no further promotions" in said or "no pcs moves" in said
    assert "earn after you take the uniform off" in said
    assert sv.civilian_wages_entered is False


def test_an_entered_civilian_wage_is_not_reported_as_an_assumption():
    h = load(E5)
    h.member.civilian_wages_annual = 70_000.0
    sv = RB.build_service(h, RB.default_inputs(h, YEAR), start_year=YEAR)
    assert sv.civilian_wages_entered is True
    assert sv.civilian_wages_annual == 70_000.0
    assert not any("take the uniform off" in a for a in sv.assumptions)


def test_a_veteran_is_paid_va_compensation_without_a_pension():
    """
    A defect found on the way: VA compensation was gated on retired pay being
    greater than zero, so a veteran who never reached twenty was modelled with
    none of it at all -- and for many of them it is the only indexed income
    they have (§4a). Retirees are unaffected: theirs was always paid.
    """
    h = Household(has_spouse=False, monthly_expenses=4_000.0)
    h.member = ServiceMember(component=VETERAN, birth_year=1985,
                             va_disability_monthly=1_500.0, va_rating=70)
    rows = run_projection(RB.to_roth_profile(h, start_year=YEAR),
                          convert=False).rows
    assert rows[0].va_disability == pytest.approx(18_000.0)
    assert rows[0].other_taxfree == pytest.approx(18_000.0)
    assert rows[0].agi == pytest.approx(0.0, abs=1)      # and it is not taxed


# ==========================================================================
# It has to survive a saved plan
# ==========================================================================

def test_a_saved_profile_rebuilds_its_service_years_as_objects():
    """
    A bare `list` annotation carries no element type, so without the hook in
    `_build()` a reloaded plan hands the projection dicts and dies one year
    into a sixty-year walk.
    """
    p = profile(E5)
    back = Profile.from_json(p.to_json())

    assert len(back.service.years) == len(p.service.years)
    assert all(isinstance(r, type(p.service.years[0])) for r in back.service.years)
    assert back.service.years[0].taxable_pay == p.service.years[0].taxable_pay
    assert back.military.pension_start_year == 2041

    original = run_projection(p, convert=False)
    reloaded = run_projection(back, convert=False)
    assert reloaded.lifetime_total_tax == pytest.approx(original.lifetime_total_tax)
    assert reloaded.heir_value_total == pytest.approx(original.heir_value_total)


def test_an_empty_service_block_is_the_default():
    """Every Profile ever written before this still loads, and still means
    'not serving'."""
    p = Profile()
    assert isinstance(p.service, MilitaryService)
    assert p.service.serving is False
    assert p.service.pension_start_year == 0
    assert Profile.from_dict({"profile_name": "old file"}).service.serving is False


def test_a_grade_the_tables_do_not_carry_refuses_instead_of_pricing_zero():
    """
    An unknown grade raises from inside the timeline, and a schedule of zeroes
    would look exactly like a member who is paid nothing.
    """
    h = load(E5)
    h.member.grade = "E-99"
    sv = RB.build_service(h, start_year=YEAR)
    assert sv.serving is False
    assert sv.years == []
    assert "could not be priced" in sv.not_modelled


def test_a_separation_point_already_behind_the_member_is_pulled_forward():
    """
    A plan left alone for two years, or a timeline nobody has opened, would
    otherwise produce a schedule with no years in it at all.
    """
    behind = TL.CareerTimeline(separation_at_years_of_service=4.0, entered=True)
    p = profile(E5, timeline=behind)           # the member has served six
    assert len(p.service.years) == 1
    assert p.service.separation_year == YEAR
    assert p.service.separation_years_of_service == 6.0
    assert p.military.retired_pay_monthly == 0.0      # six years is not twenty
    rows = run_projection(p, convert=False).rows
    assert rows[0].military_taxable_pay > 0
    assert rows[1].military_taxable_pay == 0.0


def test_pay_and_the_tsp_stop_if_the_member_dies_in_service():
    """
    The schedule is a plan, not a fact: a member who dies in uniform is not
    still being paid, and the match cannot keep landing in their account.
    """
    p = profile(E5)
    p.survivorship.first_death = "Primary"
    p.survivorship.first_death_year = 2032
    rows = {r.year: r for r in run_projection(p, convert=False).rows}

    assert rows[2032].military_taxable_pay > 0      # the year of death is paid
    assert rows[2033].military_taxable_pay == 0.0
    assert rows[2033].military_allowances == 0.0
    assert rows[2033].tsp_service_contribution == 0.0
    assert rows[2033].wages == pytest.approx(38_000, abs=1)   # the spouse's job


# ==========================================================================
# The assumptions have to be visible, not merely recorded
# ==========================================================================
# §8: a number with no visible derivation is worse than no number. The service
# schedule writes down every place it had to assume something -- and until
# review nothing rendered any of them. Five carefully worded lines on the
# Profile, shown to nobody, while the figure they produce is a seven-figure
# ending balance.

def test_the_spending_assumption_is_recorded_with_its_saving_rate():
    """
    The assumption that moves the ending balance more than any other, and the
    one that was missing: spending is one figure held flat in REAL terms for
    forty years while pay steps with longevity and promotion, and everything
    not spent compounds in a taxable account.

    For a retiree that is close to true. For someone at six years it implies a
    saving rate they never agreed to. The arithmetic is the plan's own and is
    not second-guessed -- but the rate is stated as a number they can check
    against their own bank statement.
    """
    p = profile(E5)
    spending = [a for a in p.service.assumptions if "saving rate" in a]
    assert len(spending) == 1, "the spending assumption is not recorded"
    note = spending[0]

    h = load(E5)
    annual = h.monthly_expenses * 12.0
    first = p.service.years[0]
    rate = 1.0 - annual / (first.taxable_pay + first.nontaxable_pay)
    assert f"{rate * 100:.0f}%" in note, "the stated rate is not the real one"
    assert f"{annual:,.0f}" in note
    assert "raise your monthly spending figure" in note


def test_no_assumption_carries_a_pair_of_dollar_signs():
    """
    Two unescaped '$' in one string and Streamlit eats both. These lines are
    rendered through `describe()`, so they are written without any.
    """
    for sample in (E5, O5):
        for note in profile(sample).service.assumptions:
            assert note.count("$") < 2, note[:60]


def test_describe_surfaces_every_assumption_and_the_refusal():
    """
    `describe()` is the one thing a page actually reads. It dropped the whole
    assumptions list, so a serving member's projection rested on five invisible
    inputs.
    """
    rows = RB.describe(profile(E5))
    labels = [k for k, _ in rows]
    stated = [v for k, v in rows if k.startswith("Assumption")]
    assert len(stated) == len(profile(E5).service.assumptions) > 0
    # Numbered, so a reader can tell there are several rather than one.
    assert any(k.startswith("Assumption 1 of ") for k in labels)

    # A retiree assumed nothing, so there is nothing to show.
    assert not [k for k, _ in RB.describe(profile(O5)) if k.startswith("Assumption")]


def test_a_refusal_reaches_the_page_rather_than_stopping_at_the_profile():
    """Guard and Reserve are not modelled; `describe()` has to say so."""
    from engine.profile import GUARD
    h = load(E5)
    h.member.component = GUARD
    rows = RB.describe(RB.to_roth_profile(h, RB.default_inputs(h)))
    said = [v for k, v in rows if k == "Not modelled"]
    assert said and "Guard and Reserve" in said[0]


# ==========================================================================
# A career reaches its own separation point
# ==========================================================================
# Found at review, and it only exists because two rounds met: intake derives
# years of service from the DIEMS date (so it is a FRACTION now, not a whole
# number typed by hand), and the career walk steps a whole year at a time from
# wherever the member is today. From 6.3 the steps run 6.3, 7.3 ... 19.3, and a
# member who said "I separate at twenty" was modelled as separating at 19.3 --
# the wrong side of the twenty-year cliff. `pension_at_separation()` then
# correctly priced no pension, and a lifetime annuity vanished in silence.

@pytest.mark.parametrize("start", [6.0, 6.3, 6.9, 12.5, 19.8])
def test_the_career_walk_lands_on_the_separation_point_from_any_fraction(start):
    m = ServiceMember(grade="E-5", years_of_service=start, duty_zip="28310")
    rows = TL.project(m, TL.CareerTimeline(separation_at_years_of_service=20.0),
                      start_year=2026)
    assert rows[-1].years_of_service == pytest.approx(20.0), \
        f"a career starting at {start} stopped at {rows[-1].years_of_service}"


@pytest.mark.parametrize("target", [8.0, 12.0, 19.0])
def test_a_short_career_still_stops_where_the_member_said(target):
    """The clamp must not carry anyone PAST their own answer."""
    m = ServiceMember(grade="E-5", years_of_service=6.3, duty_zip="28310")
    rows = TL.project(m, TL.CareerTimeline(separation_at_years_of_service=target),
                      start_year=2026)
    assert rows[-1].years_of_service == pytest.approx(target)
    assert all(r.years_of_service <= target + 1e-9 for r in rows)


def test_a_derived_year_count_does_not_cost_the_member_their_pension():
    """
    The whole defect, end to end and through the path the app actually walks:
    load the sample, choose the funnel, run `intake.prepare()` exactly as every
    page does, and the twenty-year pension must still be there.
    """
    from engine import intake
    from engine.funnel import set_funnel

    h = load(E5)
    set_funnel(h, "serving")
    intake.prepare(h)                      # derives years of service from DIEMS
    assert h.member.years_of_service % 1 != 0, "the derivation makes it fractional"
    assert h.career.separation_at_years_of_service == 20.0

    p = RB.to_roth_profile(h, RB.default_inputs(h))
    assert p.service.separation_years_of_service == pytest.approx(20.0)
    assert p.military.retired_pay_monthly == pytest.approx(1_768.68, abs=0.01)
    assert p.military.pension_start_year == p.service.separation_year + 1
