"""
R1: ask the minimum, work out the rest.

`ARCHITECTURE.md` §5a: "A question earns its place only if the answer CANNOT be
derived. The test is not 'is this useful?' -- it is 'can the app work it out?'"
This file is the standing defence of that, in three parts:

  1. THE SHAPE. A question is asked or derived, never both; every derived
     question says what it came from and sits on the review card; nothing the
     app can work out is a blank field in the main flow.
  2. THE ARITHMETIC. Each derivation agrees with the engine that consumes it,
     so the figure shown on the review card is the figure the app will use.
  3. THE STOMP. A derivation may only write into a field still at its declared
     default. A typed correction survives every later render pass, which is
     the whole reason a settled fact gets no widget and a correctable one does.

The counts at the bottom are the point of the exercise and are asserted as
ceilings. Raising one means adding a question, and a question needs the
one-line justification the funnel modules all carry.
"""

import sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from engine import intake
from engine.benefits import concurrent_receipt as CR
from engine.benefits import life_insurance as LI
from engine.funnel import (FUNNEL_SERVING, FUNNEL_VETERAN, FUNNEL_RETIRED,
                           GROUP_REVIEW, is_untouched, state_of_duty_zip)
from engine.intake import pay_check as PC
from engine.intake import serving as SRV
from engine.pay import bah as BAH
from engine.pay import bas as BAS
from engine.pay import basepay as BP
from engine.pay import taxable as TX
from engine.profile import Household, ServiceMember, RETIRED, VETERAN


def plan(funnel: str, **member) -> Household:
    h = Household(member=ServiceMember(**member))
    intake.set_funnel(h, funnel)
    intake.prepare(h)
    return h


# ==========================================================================
# 1. The shape
# ==========================================================================

@pytest.mark.parametrize("funnel", list(intake.FUNNELS))
def test_a_field_is_asked_or_worked_out_and_never_both(funnel):
    asked = {(q.path, q.attr) for q in intake.all_questions(funnel)
             if not q.is_derived}
    derived = {(q.path, q.attr) for q in intake.all_questions(funnel)
               if q.is_derived}
    derived |= {(d.path, d.attr) for d in intake.all_derived(funnel)}
    assert not (asked & derived), sorted(asked & derived)


@pytest.mark.parametrize("funnel", list(intake.FUNNELS))
def test_every_worked_out_figure_says_where_it_came_from(funnel):
    """§8: a number with no visible derivation is worse than no number."""
    for q in intake.all_questions(funnel):
        if q.is_derived:
            assert q.derived_from.strip(), q.key
            assert q.group == GROUP_REVIEW, q.key
    for d in intake.all_derived(funnel):
        assert d.because.strip(), d.key


@pytest.mark.parametrize("funnel", list(intake.FUNNELS))
def test_the_asked_set_and_the_review_card_partition_the_questions(funnel):
    h = plan(funnel)
    asked = {q.key for q in intake.questions_to_ask(h)}
    review = {q.key for q in intake.figures_to_check(h)}
    assert not (asked & review)
    everything = {q.key for q in intake.all_questions(funnel) if q.applies(h)
                  and q.target(h) is not None}
    assert asked | review == everything


def test_validate_rejects_a_derived_question_that_hides_its_source():
    from dataclasses import replace
    q = next(q for q in SRV.QUESTIONS if q.key == "srv_yos")
    problems = intake.validate((replace(q, derived_from=""),))
    assert any("does not say what from" in p for p in problems)


def test_validate_rejects_a_derived_question_left_in_the_main_flow():
    from dataclasses import replace
    q = next(q for q in SRV.QUESTIONS if q.key == "srv_yos")
    problems = intake.validate((replace(q, group=SRV.GROUP_SERVICE,
                                        group_rank=SRV.RANK_SERVICE),))
    assert any("belongs on the" in p for p in problems)


def test_validate_catches_a_settled_fact_fighting_a_question():
    """A field both worked out and asked would have the two overwrite in turn."""
    from engine.funnel import Derived
    clash = Derived(key="x_d_grade", label="Grade", path="member", attr="grade",
                    compute=lambda h: "E-5", because="testing",
                    funnels=(FUNNEL_SERVING,))
    problems = intake.validate(intake.all_questions(FUNNEL_SERVING),
                               derived=(clash,))
    assert any("asked or derived, never both" in p for p in problems)


# ==========================================================================
# 2. The arithmetic — every figure agrees with the engine that consumes it
# ==========================================================================

def test_years_of_service_is_the_diems_date_counted_to_today():
    h = plan(FUNNEL_SERVING, diems_date="2016-05-28")
    from datetime import date
    expected = round((date.today() - date(2016, 5, 28)).days / 365.25, 1)
    assert h.member.years_of_service == expected


def test_a_diems_date_that_does_not_parse_leaves_years_of_service_alone():
    h = plan(FUNNEL_SERVING, diems_date="not a date")
    assert h.member.years_of_service == ServiceMember().years_of_service


@pytest.mark.parametrize("attr", ["basic_pay_monthly_override",
                                  "bah_monthly_override",
                                  "bas_monthly_override"])
def test_basic_pay_bah_and_bas_are_not_questions_in_any_form(attr):
    """
    Paul's rule, in his words: "Base pay, BAS, and BAH is a known quantity."
    Not asked, and not demoted to an override field sitting blank in the flow
    either — removed. They are shown back on the confirmation step instead.
    """
    for funnel in intake.FUNNELS:
        assert not any(q.attr == attr for q in intake.all_questions(funnel)), \
            f"{attr} is a known quantity and is being asked for in {funnel}"


def test_the_pay_packet_shows_the_figures_the_engines_will_use():
    h = plan(FUNNEL_SERVING, grade="E-6", diems_date="2016-06-01",
             duty_zip="28310")
    h.n_dependents = 2
    intake.prepare(h)
    assert h.member.has_dependents is True          # settled, not asked

    p = PC.compute(h)
    used, source = TX.resolve_basic_monthly(h.member)
    assert p.basic == used and source == TX.SOURCE_TABLE
    assert p.bah == BAH.lookup_or_average("28310", "E-6", True,
                                          BAH.load()).monthly
    assert p.bas == BAS.bas_monthly(False).monthly
    assert p.gross_computed == p.taxable + p.untaxed

    rows = dict(SRV.statement(h))
    assert rows["Basic pay"] == f"{p.basic:,.2f}"
    assert rows["Gross"] == f"{p.gross_computed:,.2f}"
    assert "Net, estimated" in rows


def test_bas_still_splits_officer_from_enlisted_and_nothing_else():
    assert (PC.compute(plan(FUNNEL_SERVING, grade="E-6")).bas
            == BAS.bas_monthly(False).monthly)
    assert (PC.compute(plan(FUNNEL_SERVING, grade="O-4")).bas
            == BAS.bas_monthly(True).monthly)


def test_the_taxable_toggle_waits_until_there_is_a_special_pay_to_tax():
    """One question fewer for the member who draws none, which is most of them."""
    q = next(q for q in SRV.QUESTIONS if q.key == "srv_special_pay_taxable")
    assert not q.applies(plan(FUNNEL_SERVING))
    assert q.applies(plan(FUNNEL_SERVING, special_pay_monthly=250.0))


def test_special_pays_stay_a_question_because_no_table_produces_them():
    """Paul: "Ask about special pays." An assignment is not a pay grade."""
    asked = {q.attr for q in intake.all_questions(FUNNEL_SERVING)
             if not q.is_derived}
    assert {"special_pay_monthly", "special_pay_taxable",
            "bonus_annual_taxable"} <= asked
    # And in the main flow, not tucked onto the review card.
    for q in intake.all_questions(FUNNEL_SERVING):
        if q.attr in ("special_pay_monthly", "special_pay_taxable",
                      "bonus_annual_taxable"):
            assert q.group == SRV.GROUP_SPECIAL


def test_a_confirmed_gross_or_net_wins_over_the_app_s_own_arithmetic():
    """
    The same rule `resolve_basic_monthly()` already applies to basic pay, now
    applied to the whole packet: the member's figure wins, and the app says so
    rather than dropping either side.
    """
    h = plan(FUNNEL_SERVING, grade="E-6", diems_date="2016-06-01",
             duty_zip="28310")
    computed_gross, source = PC.resolve_gross_monthly(h)
    assert source == PC.SOURCE_COMPUTED
    assert computed_gross == PC.compute(h).gross_computed

    h.member.gross_pay_monthly_confirmed = computed_gross - 600.0
    used, source = PC.resolve_gross_monthly(h)
    assert used == computed_gross - 600.0
    assert source == PC.SOURCE_CONFIRMED


def test_a_difference_inside_rounding_is_not_worth_remarking_on():
    h = plan(FUNNEL_SERVING, grade="E-6", diems_date="2016-06-01")
    p = PC.compute(h)
    h.member.net_pay_monthly_confirmed = p.net_computed + 5.0
    sev = [f[0] for f in PC.findings(h)]
    assert sev == ["good"], PC.findings(h)


def test_a_difference_worth_naming_names_the_deduction():
    h = plan(FUNNEL_SERVING, grade="E-6", diems_date="2016-06-01")
    p = PC.compute(h)
    h.member.net_pay_monthly_confirmed = p.net_computed - 900.0
    found = PC.findings(h)
    assert [f[0] for f in found] == ["warn"]
    detail = found[0][2]
    assert "garnishment" in detail and "allotment" in detail
    assert "using your figure" in detail


def test_a_plan_with_no_military_pay_has_no_pay_packet_to_confirm():
    h = plan(FUNNEL_VETERAN, component=VETERAN)
    assert PC.statement(h) == []
    assert PC.findings(h) == []
    assert intake.review_statement(h) == ()


def test_sgli_starts_at_the_maximum_because_enrolment_is_automatic():
    h = plan(FUNNEL_SERVING)
    assert h.member.sgli_coverage == LI.SGLI_MAX


def test_a_veterans_cover_starts_at_nothing_because_sgli_ended():
    h = plan(FUNNEL_VETERAN, component=VETERAN)
    assert h.member.sgli_coverage == 0.0


def test_a_veterans_years_served_are_the_two_dates_on_the_dd214():
    h = plan(FUNNEL_VETERAN, component=VETERAN, diems_date="2003-08-11",
             planned_separation_date="2011-08-11")
    assert h.member.years_of_service == 8.0


def test_a_veteran_with_no_separation_date_keeps_what_the_plan_carries():
    h = plan(FUNNEL_VETERAN, component=VETERAN, diems_date="2003-08-11",
             years_of_service=7.5)
    assert h.member.years_of_service == 7.5


def test_hostile_fire_pay_is_asked_and_never_follows_the_combat_zone():
    """
    Two different designations: a combat zone is named by Executive Order for
    the tax exclusion, hostile fire and imminent danger pay by DoD under
    37 U.S.C. 310. They overlap and they are not the same list.

    Deriving one from the other could not be corrected — it derives True, and
    a derivation may only write into a field still at its declared default, so
    a member answering "no" had it flipped back on the next render pass. And it
    is load-bearing: `prime_directive._step_sdp` gates the Savings Deposit
    Program on this flag at weight 2.0, so a false positive tells someone to
    deposit ten thousand dollars into an account they cannot open.
    """
    h = plan(FUNNEL_SERVING, is_deployed=True, in_combat_zone=True)
    assert h.member.drawing_hostile_fire_pay is False, "not assumed from the zone"

    # It is asked instead, of deployed members and of nobody else.
    asked = {q.key for q in intake.questions_to_ask(h)}
    assert "srv_hostile_fire" in asked
    not_deployed = plan(FUNNEL_SERVING, is_deployed=False)
    assert "srv_hostile_fire" not in {q.key for q in intake.questions_to_ask(not_deployed)}


def test_the_sdp_step_stays_shut_until_hostile_fire_pay_is_confirmed():
    from engine.coach import prime_directive as PD
    h = plan(FUNNEL_SERVING, is_deployed=True, in_combat_zone=True)
    h.monthly_expenses = 4_000.0
    assert PD.evaluate(h).by_key("sdp").status == PD.NOT_APPLICABLE

    h.member.drawing_hostile_fire_pay = True
    assert PD.evaluate(h).by_key("sdp").status != PD.NOT_APPLICABLE


def test_crdp_is_worked_out_from_the_two_conditions_the_statute_names():
    both = plan(FUNNEL_RETIRED, component=RETIRED,
                years_of_service=CR.CRDP_MIN_YEARS, va_rating=CR.CRDP_MIN_RATING)
    assert both.member.crdp_applies is True
    assert plan(FUNNEL_RETIRED, component=RETIRED, years_of_service=12.0,
                va_rating=100).member.crdp_applies is False


def test_part_b_is_assumed_taken_because_tricare_for_life_needs_it():
    h = plan(FUNNEL_RETIRED, component=RETIRED)
    assert h.healthcare.part_b_when_eligible is True
    q = next(q for q in intake.figures_to_check(h) if q.key == "ret_part_b")
    assert q.derive(h) is True


def test_where_you_live_comes_off_the_duty_zip_while_you_are_serving():
    assert state_of_duty_zip("28310") == "North Carolina"
    h = plan(FUNNEL_SERVING, duty_zip="28310")
    assert h.current_state == "North Carolina"


def test_out_of_uniform_where_you_live_follows_your_legal_residence():
    h = Household(member=ServiceMember(component=VETERAN))
    h.state_of_legal_residence = "Michigan"
    intake.set_funnel(h, FUNNEL_VETERAN)
    intake.prepare(h)
    assert h.current_state == "Michigan"


def test_a_zip_the_bah_archive_does_not_know_says_nothing_rather_than_guessing():
    assert state_of_duty_zip("") == ""
    assert state_of_duty_zip("not a zip") == ""
    assert state_of_duty_zip("99999") == ""


def test_the_child_count_is_left_alone_because_dependants_are_not_heirs():
    """`n_dependents` includes a spouse. The Estate page is the one home."""
    h = Household(n_dependents=3, has_spouse=True)
    intake.set_funnel(h, FUNNEL_RETIRED)
    intake.prepare(h)
    assert h.estate.n_children == 0


# ==========================================================================
# 3. The stomp — a typed answer is never overwritten
# ==========================================================================

def test_a_correction_survives_every_later_render_pass():
    h = plan(FUNNEL_SERVING, diems_date="2010-01-01")
    derived = h.member.years_of_service
    assert derived > 15                       # the app worked something out

    h.member.years_of_service = 11.5          # broken service, corrected
    for _ in range(3):
        intake.prepare(h)
    assert h.member.years_of_service == 11.5


def test_a_pure_override_slot_is_never_filled_in_behind_the_users_back():
    """
    `fills_in=False` means the engine has its own fallback and blank means
    "use it". Writing the computed figure into the slot would turn the app's
    guess into the user's answer, and the LES would then lose to the table.
    """
    h = plan(FUNNEL_SERVING, grade="E-6", diems_date="2016-06-01")
    for key in ("srv_dor", "srv_gross", "srv_net"):
        q = next(q for q in SRV.QUESTIONS if q.key == key)
        assert not q.fills_in
        assert is_untouched(q.target(h), q.attr), key


def test_a_settled_fact_has_no_widget_anywhere():
    """
    The reason the two mechanisms are separate. A derivation may only write
    into a field at its declared default, so for a boolean that derives True
    the contrary answer IS the default and cannot be held. Rather than ship a
    toggle that silently flips back, a fact like that gets no toggle.
    """
    for funnel in intake.FUNNELS:
        settled = {(d.path, d.attr) for d in intake.all_derived(funnel)}
        for q in intake.all_questions(funnel):
            assert (q.path, q.attr) not in settled, q.key


def test_preparing_a_household_twice_writes_nothing_the_second_time():
    h = plan(FUNNEL_SERVING, diems_date="2016-05-28", duty_zip="28310")
    before = h.to_dict()
    intake.prepare(h)
    assert h.to_dict() == before


def test_a_derivation_does_not_mark_the_plan_dirty_or_claim_to_be_an_answer():
    """
    It writes directly rather than through the `ui.panel` helpers, on purpose:
    working out a figure the user never typed is not an edit the user made.
    """
    h = Household(member=ServiceMember(diems_date="2016-05-28"))
    intake.set_funnel(h, FUNNEL_SERVING)
    written = intake.apply_derivations(
        h, intake.all_questions(FUNNEL_SERVING),
        intake.all_derived(FUNNEL_SERVING))
    assert "srv_yos" in written
    assert h.member.years_of_service != ServiceMember().years_of_service


# ==========================================================================
# The counts, which are the whole point
# ==========================================================================

@pytest.mark.parametrize("funnel, ceiling", [
    (FUNNEL_SERVING, 24),          # was 29 before R1, and 2 of these are the
                                   # special pays Paul asked to keep
    (FUNNEL_VETERAN, 19),          # was 23
    (FUNNEL_RETIRED, 21),          # was 23
])
def test_a_blank_plan_is_asked_no_more_than_this(funnel, ceiling):
    """
    R1 is a ceiling, not a target to creep past. Raising one of these numbers
    means a question was added, and every question in the three funnel modules
    carries a one-line comment saying why the app cannot work it out. Write
    that line, or work it out.
    """
    h = plan(funnel)
    asked = intake.questions_to_ask(h)
    assert len(asked) <= ceiling, [q.key for q in asked]
