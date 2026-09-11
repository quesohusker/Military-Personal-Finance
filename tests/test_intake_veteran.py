"""
The Veteran funnel's question set.

Two failures these tests exist to catch, both of which look fine on screen:

  * A DUPLICATE WIDGET KEY between this module and another agent's. Two widgets
    sharing a key show each other's value and neither page looks broken, which
    is why `validate()` is run over the ASSEMBLED set and not just this one.
  * A RETIREE QUESTION LEAKING IN. A veteran who did not retire has no pension
    and no TRICARE, so asking about SBP, CRDP, CRSC or retired pay does not
    merely waste a row -- it tells them something untrue about their own
    situation.
"""

import inspect

import pytest

from engine import intake
from engine.funnel import (FUNNEL_SERVING, FUNNEL_VETERAN, FUNNEL_RETIRED,
                           KINDS, KIND_PCT, KIND_NUMBER, QUESTIONS as COMMON,
                           prepare, validate, visible_questions)
from engine.intake import veteran as V
from engine.profile import Household, ServiceMember, VETERAN

PREFIX = "vet_"


def vet_household(**member) -> Household:
    """A separated veteran, prepared the way the renderer prepares one."""
    h = Household(member=ServiceMember(component=VETERAN, **member))
    intake.prepare(h)          # the page's prepare: it sees V.DERIVED too
    return h


def keys_on_screen(h: Household) -> set[str]:
    return {q.key for q in visible_questions(h, V.QUESTIONS)}


# ==========================================================================
# The contract: §6 of docs/FUNNEL_CONTRACT.md is one line
# ==========================================================================

def test_the_module_registers_a_tuple_of_questions_and_nothing_else():
    assert isinstance(V.QUESTIONS, tuple)
    assert V.QUESTIONS, "an empty funnel is the failure the contract warns about"
    assert all(isinstance(q, intake.Question) for q in V.QUESTIONS)


def test_intake_finds_them_without_a_registration_call():
    assert intake.funnel_questions(FUNNEL_VETERAN) == V.QUESTIONS


def test_the_module_never_imports_streamlit_or_the_package_that_imports_it():
    src = inspect.getsource(V)
    assert "import streamlit" not in src
    assert "ui.panel" not in src.replace("`ui.panel`", "")
    assert "from engine.intake" not in src


# ==========================================================================
# Keys
# ==========================================================================

def test_every_key_is_prefixed_and_unique_within_the_module():
    keys = [q.key for q in V.QUESTIONS]
    assert all(k.startswith(PREFIX) for k in keys), keys
    assert len(keys) == len(set(keys))


def test_no_key_collides_with_the_common_set():
    assert not ({q.key for q in V.QUESTIONS} & {q.key for q in COMMON})


def test_the_assembled_veteran_set_validates():
    assert validate(intake.all_questions(FUNNEL_VETERAN)) == []


def test_the_whole_app_pool_still_validates_with_this_module_in_it():
    # Catches a key this module shares with serving.py or retiree.py, whichever
    # of them exists by the time this runs.
    assert validate(intake.pool()) == []


# ==========================================================================
# Labels, kinds and widget arguments
# ==========================================================================

def test_every_label_is_a_second_person_question():
    starters = ("What", "When", "How", "Which", "Is", "Are", "Do", "Does", "At")
    for q in V.QUESTIONS:
        assert q.label.strip().endswith("?"), q.key
        assert q.label.split()[0] in starters, q.label
        assert " you" in q.label or q.label.startswith("Is your"), q.label


def test_every_kind_is_one_of_the_seven_and_every_choice_has_options():
    for q in V.QUESTIONS:
        assert q.kind in KINDS, q.key
        if q.kind == "choice":
            assert q.options, q.key


def test_widget_kwargs_are_arguments_the_real_helper_accepts():
    import ui.panel as panel
    for q in V.QUESTIONS:
        helper = getattr(panel, q.kind)
        sig = inspect.signature(helper)
        sig.bind("label", object(), q.attr, key="k", **q.widget_kwargs())


def test_an_assumptions_percentage_would_have_to_be_a_number_not_a_pct():
    # `Assumptions` stores percent (4.0 means 4%); `pct` stores a decimal and
    # displays a percent. Mixing them is a silent factor of a hundred.
    for q in V.QUESTIONS:
        if q.path == "assumptions":
            assert q.kind == KIND_NUMBER, q.key
        if q.kind == KIND_PCT:
            assert q.path != "assumptions", q.key


# ==========================================================================
# Funnels
# ==========================================================================

def test_only_the_veteran_funnel_asks_any_of_them():
    for q in V.QUESTIONS:
        assert q.funnels == (FUNNEL_VETERAN,), q.key
        assert q.asks(FUNNEL_VETERAN)
        assert not q.asks(FUNNEL_SERVING)
        assert not q.asks(FUNNEL_RETIRED)


def test_none_of_them_reach_a_serving_or_retired_household():
    for funnel in (FUNNEL_SERVING, FUNNEL_RETIRED):
        assert not ({q.key for q in intake.all_questions(funnel)}
                    & {q.key for q in V.QUESTIONS})


# ==========================================================================
# Targets -- every attr resolves on the object its path names
# ==========================================================================

def test_every_attr_exists_on_the_object_the_path_resolves_to():
    h = vet_household()
    for q in V.QUESTIONS:
        target = q.target(h)
        assert target is not None, f"{q.key}: path {q.path!r} does not resolve"
        assert hasattr(target, q.attr), (
            f"{q.key}: {type(target).__name__} has no attribute {q.attr!r}")


def test_every_answer_round_trips_through_a_saved_plan():
    h = vet_household()
    h.member.va_rating = 70
    h.member.va_disability_monthly = 1_716.28
    h.member.planned_separation_date = "2019-06-30"
    h.healthcare.out_of_pocket_annual = 9_400.0
    back = Household.from_dict(h.to_dict())
    for q in V.QUESTIONS:
        assert getattr(q.target(back), q.attr) == getattr(q.target(h), q.attr)


# ==========================================================================
# What a veteran must NOT be asked
# ==========================================================================

RETIREE_ONLY_ATTRS = {
    "retired_pay_monthly",      # there is no pension
    "sbp_elected",              # SBP is an election against retired pay
    "crdp_applies",             # concurrent receipt needs retired pay to offset
    "crsc_monthly",
    "tricare_plan",             # no military retirement, no TRICARE at any price
    "took_csb_redux",           # a retirement-system election, never reached
    "opted_into_brs",
}

SERVING_ONLY_ATTRS = {
    "is_deployed", "months_deployed_this_year", "in_combat_zone",
    "drawing_hostile_fire_pay", "duty_zip", "lives_in_government_housing",
    "tsp_contribution_pct", "tsp_roth_share", "leave_balance_days",
    "basic_pay_monthly_override", "bah_monthly_override", "date_of_rank",
}


def test_no_retiree_only_field_is_asked_of_a_veteran():
    asked = {q.attr for q in V.QUESTIONS}
    assert not (asked & RETIREE_ONLY_ATTRS)


def test_no_still_serving_field_is_asked_of_a_veteran():
    asked = {q.attr for q in V.QUESTIONS}
    assert not (asked & SERVING_ONLY_ATTRS)


def test_no_label_mentions_a_benefit_this_person_does_not_have():
    for q in V.QUESTIONS:
        low = q.label.lower()
        for word in ("retired pay", "pension", "sbp", "survivor benefit plan",
                     "tricare", "crdp", "crsc"):
            assert word not in low, f"{q.key} asks about {word}"


def test_nothing_the_common_set_already_asks_is_asked_again():
    common_targets = {(q.path, q.attr) for q in COMMON}
    for q in V.QUESTIONS:
        assert (q.path, q.attr) not in common_targets, q.key


# ==========================================================================
# The questions that matter most, by name
# ==========================================================================

def test_the_va_rating_is_asked_in_the_ten_point_steps_the_va_awards():
    q = next(q for q in V.QUESTIONS if q.attr == "va_rating")
    assert q.options == tuple(range(0, 101, 10))
    assert q.format_func(10) == "10%"
    # The rating is an integer percent on the profile, NOT a pct-kind decimal.
    assert q.kind == "choice"


def test_the_va_rating_and_its_monthly_amount_are_both_asked():
    attrs = {q.attr for q in V.QUESTIONS}
    assert {"va_rating", "va_disability_monthly"} <= attrs


def test_the_separation_date_and_the_life_cover_are_both_asked():
    # The VGLI-versus-term decision needs both, and it is on a deadline.
    attrs = {q.attr for q in V.QUESTIONS}
    assert {"planned_separation_date", "sgli_coverage"} <= attrs


def test_the_social_security_earnings_history_has_everything_it_needs():
    """
    engine/income/social_security.py::estimate_pia_from_career reads all four,
    and the veteran funnel still puts all four on the plan — but no longer by
    asking for all four. Years of service is worked out from the two DD-214
    dates, and civilian wages moved into the common set because a Guard
    member's day job and a retiree's second career are the same fact (R3).
    """
    from engine.funnel import QUESTIONS as COMMON_SET
    attrs = ({q.attr for q in V.QUESTIONS}
             | {q.attr for q in COMMON_SET})
    assert {"diems_date", "years_of_service", "grade",
            "civilian_wages_annual"} <= attrs
    assert not any(q.attr == "civilian_wages_annual" for q in V.QUESTIONS), \
        "civilian wages belong to the common set now, and to one place only"


def test_the_final_grade_offers_only_grades_the_pay_tables_know():
    from engine.pay import grades as G
    q = next(q for q in V.QUESTIONS if q.attr == "grade")
    assert list(q.options) == G.GRADE_LABELS
    assert ServiceMember().grade in q.options


# ==========================================================================
# Conditionals
# ==========================================================================

def test_an_unrated_veteran_is_not_asked_what_the_va_pays_them():
    on_screen = keys_on_screen(vet_household(va_rating=0))
    assert "vet_va_monthly" not in on_screen
    assert "vet_va_permanent_total" not in on_screen
    assert "vet_va_rating" in on_screen


def test_a_rated_veteran_is_asked_the_monthly_amount():
    assert "vet_va_monthly" in keys_on_screen(vet_household(va_rating=10))


@pytest.mark.parametrize("rating", [10, 20, 30, 40])
def test_permanent_and_total_is_not_asked_where_it_cannot_arise(rating):
    assert "vet_va_permanent_total" not in keys_on_screen(
        vet_household(va_rating=rating))


@pytest.mark.parametrize("rating", [50, 70, 100])
def test_permanent_and_total_is_asked_once_it_could_apply(rating):
    # 50 is under every route to total, including individual unemployability,
    # which needs one condition at 60% or a combined 70%.
    assert "vet_va_permanent_total" in keys_on_screen(
        vet_household(va_rating=rating))


def test_the_unconditional_questions_are_on_screen_for_a_blank_plan():
    h = vet_household()
    on_screen = keys_on_screen(h)
    reviewed = {q.key for q in intake.figures_to_check(h)}
    for q in V.QUESTIONS:
        if q.when is None:
            # Asked, or worked out and offered back for correction. Never
            # missing, and never both (R1).
            assert (q.key in on_screen) != (q.key in reviewed), q.key
            assert (q.key in reviewed) == q.is_derived, q.key


def test_every_predicate_is_a_named_function_not_a_lambda():
    for q in V.QUESTIONS:
        if q.when is not None:
            assert q.when.__name__ != "<lambda>", q.key


# ==========================================================================
# Cards
# ==========================================================================

def test_every_question_sits_in_one_of_this_module_s_cards():
    cards = {V.GROUP_SEPARATION, V.GROUP_VA, intake.GROUP_REVIEW}
    assert {q.group for q in V.QUESTIONS} == cards


def test_the_cards_come_out_after_the_common_ones_in_the_order_the_story_runs():
    titles = [t for t, _ in intake.grouped(intake.all_questions(FUNNEL_VETERAN))]
    # The story, then the review card, which is always last of all.
    assert titles[-3:] == [V.GROUP_SEPARATION, V.GROUP_VA, intake.GROUP_REVIEW]


def test_order_leaves_gaps_of_ten_so_an_insert_does_not_renumber():
    for q in V.QUESTIONS:
        assert q.order % 10 == 0 and q.order > 0, q.key
    for card in {q.group for q in V.QUESTIONS}:
        orders = [q.order for q in V.QUESTIONS if q.group == card]
        assert len(orders) == len(set(orders)), card
