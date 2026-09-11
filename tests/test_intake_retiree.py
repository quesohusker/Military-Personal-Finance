"""
The Retired Military intake set: engine/intake/retiree.py.

Three agents write into one question schema, so the tests that matter here are
the ones that catch a collision or a dangling attribute rather than the ones
that restate the questions. `validate()` over the ASSEMBLED pool is the first;
a writable-attribute check is the second, because `hasattr` is satisfied by a
derived property like `ServiceMember.retirement_system` that would raise the
moment a widget tried to write to it.
"""

from engine import intake
from engine.funnel import (FUNNEL_RETIRED, FUNNEL_SERVING, FUNNEL_VETERAN,
                           KIND_CHOICE, prepare, validate)
from engine.intake import retiree as R
from engine.profile import Household, RETIRED, ServiceMember
from engine.benefits import concurrent_receipt as CR
from engine.benefits import healthcare as HC


def retiree(**member) -> Household:
    """A retiree household, prepared, with a spouse record to write into."""
    member.setdefault("component", RETIRED)
    h = Household(member=ServiceMember(**member), has_spouse=True)
    prepare(h)
    return h


def keys_on_screen(h: Household) -> list[str]:
    return [q.key for q in intake.questions_to_ask(h) if q.key.startswith("ret_")]


# ==========================================================================
# The contract
# ==========================================================================

def test_the_retiree_set_validates():
    assert validate(intake.all_questions(FUNNEL_RETIRED)) == []


def test_no_ret_key_collides_with_another_funnel_module():
    # The real failure this guards: two agents choosing the same widget key,
    # which shows each widget the other's value and breaks neither page.
    # Deliberately a KEY check over the assembled pool rather than a full
    # validate() of it -- a problem inside serving.py or veteran.py is theirs
    # to fail on (test_funnel.py already checks each funnel's set), and this
    # file should only go red for something retiree.py did.
    keys = [q.key for q in intake.pool()]
    assert len(keys) == len(set(keys))
    ours = {q.key for q in R.QUESTIONS}
    for funnel in (FUNNEL_SERVING, FUNNEL_VETERAN):
        assert not (ours & {q.key for q in intake.all_questions(funnel)})


def test_the_module_exposes_a_questions_tuple_and_asks_something():
    assert isinstance(R.QUESTIONS, tuple)
    assert len(R.QUESTIONS) > 0
    assert all(isinstance(q, intake.Question) for q in R.QUESTIONS)


def test_every_key_is_prefixed_ret():
    bad = [q.key for q in R.QUESTIONS if not q.key.startswith("ret_")]
    assert bad == []


def test_every_key_is_unique_within_the_module():
    keys = [q.key for q in R.QUESTIONS]
    assert len(keys) == len(set(keys))


def test_no_retiree_key_leaks_into_another_funnel():
    for funnel in (FUNNEL_SERVING, FUNNEL_VETERAN):
        assert [q.key for q in intake.all_questions(funnel)
                if q.key.startswith("ret_")] == []


def test_every_question_is_asked_by_the_retiree_funnel_alone():
    assert all(q.funnels == (FUNNEL_RETIRED,) for q in R.QUESTIONS)


def test_every_label_is_a_second_person_question():
    for q in R.QUESTIONS:
        assert q.label.strip().endswith("?"), q.key
        assert q.label.split()[0] in {"What", "Which", "How", "When", "Did",
                                      "Do", "Does", "Are", "Is", "Will",
                                      "Have", "Has", "At", "If"}, q.label


def test_every_question_has_a_group_and_help():
    for q in R.QUESTIONS:
        assert q.group, q.key
        assert q.help, q.key


def test_orders_leave_gaps_of_ten_within_each_group():
    by_group: dict[str, list[int]] = {}
    for q in R.QUESTIONS:
        by_group.setdefault(q.group, []).append(q.order)
    for group, orders in by_group.items():
        assert len(set(orders)) == len(orders), group
        assert all(o % 10 == 0 and o > 0 for o in orders), group


def test_it_does_not_repeat_anything_the_common_set_already_asks():
    common = {(q.path, q.attr) for q in intake.QUESTIONS}
    assert not [q.key for q in R.QUESTIONS if (q.path, q.attr) in common]


# ==========================================================================
# Every attribute exists -- and can actually be written to
# ==========================================================================

def test_every_attr_resolves_on_the_object_its_path_names():
    h = retiree()
    for q in R.QUESTIONS:
        obj = q.target(h)
        assert obj is not None, f"{q.key}: path {q.path!r} does not resolve"
        assert hasattr(obj, q.attr), f"{q.key}: no {q.attr!r} on {type(obj).__name__}"


def test_every_attr_is_writable_not_a_derived_property():
    # ServiceMember.retirement_system is a READ-ONLY property off the DIEMS
    # date. It passes hasattr and would raise the first time a widget wrote to
    # it, which is why this set asks for the DIEMS date instead.
    h = retiree()
    for q in R.QUESTIONS:
        obj = q.target(h)
        setattr(obj, q.attr, getattr(obj, q.attr))


def test_the_retirement_system_is_asked_for_as_the_diems_date():
    assert "retirement_system" not in {q.attr for q in R.QUESTIONS}
    assert "diems_date" in {q.attr for q in R.QUESTIONS}
    h = retiree(diems_date="1998-06-15")
    assert h.member.retirement_system  # resolves off the answer we collect


def test_widget_kwargs_splat_cleanly_for_every_question():
    for q in R.QUESTIONS:
        kwargs = q.widget_kwargs()
        assert "help" in kwargs
        if q.kind == KIND_CHOICE:
            assert kwargs["options"]


# ==========================================================================
# What is asked
# ==========================================================================

def test_it_asks_the_architecture_section_5_retired_only_fields():
    asked = {(q.path, q.attr) for q in R.QUESTIONS}
    for path, attr in (("member", "retired_pay_monthly"),
                       ("member", "diems_date"),          # = retirement system
                       ("member", "years_of_service"),
                       ("member", "sbp_elected"),
                       ("member", "va_disability_monthly"),
                       ("member", "va_rating"),
                       ("member", "va_rating_permanent_total"),
                       ("member", "crdp_applies"),
                       ("member", "crsc_monthly"),
                       ("healthcare", "tricare_plan"),
                       ("healthcare", "part_b_when_eligible")):
        assert (path, attr) in asked, f"{path}.{attr} is not asked"


def test_the_tricare_menu_is_the_one_a_retiree_can_actually_hold():
    # The list is component-dependent and Question.options is fixed at import,
    # so it is resolved once for RETIRED -- which is what this funnel
    # guarantees. Reserve Select is sold to the Selected Reserve and must not
    # appear here.
    q = next(q for q in R.QUESTIONS if q.attr == "tricare_plan")
    assert list(q.options) == HC.plans_for(RETIRED)
    assert HC.PLAN_TRS not in q.options
    assert HC.PLAN_TFL in q.options


# ==========================================================================
# The conditionals
# ==========================================================================

def test_the_redux_and_brs_elections_are_hidden_for_a_post_2018_diems():
    h = retiree(diems_date="2019-06-01")
    on = keys_on_screen(h)
    assert "ret_csb_redux" not in on
    assert "ret_brs_optin" not in on


def test_the_redux_and_brs_elections_are_shown_for_a_pre_2018_diems():
    h = retiree(diems_date="1998-06-15")
    on = keys_on_screen(h)
    assert "ret_csb_redux" in on
    assert "ret_brs_optin" in on


def test_an_unparseable_diems_hides_the_elections_rather_than_crashing():
    for text in ("", "not a date", "1998-13-45"):
        h = retiree(diems_date=text)
        assert R.diems_predates_brs(h) is False
        assert "ret_csb_redux" not in keys_on_screen(h)


def test_the_va_follow_ups_wait_for_a_rating():
    h = retiree(va_rating=0)
    on = keys_on_screen(h)
    assert "ret_va_rating" in on                    # always asked
    assert "ret_va_permanent_total" not in on
    assert "ret_crsc" not in on

    h = retiree(va_rating=100)
    on = keys_on_screen(h)
    assert "ret_va_permanent_total" in on
    assert "ret_crsc" in on


def test_crdp_is_asked_only_when_both_statutory_conditions_are_met():
    both = retiree(va_rating=CR.CRDP_MIN_RATING, years_of_service=CR.CRDP_MIN_YEARS)
    assert "ret_crdp" in keys_on_screen(both)

    short = retiree(va_rating=100, years_of_service=CR.CRDP_MIN_YEARS - 8)
    assert "ret_crdp" not in keys_on_screen(short)
    assert "ret_crsc" in keys_on_screen(short)      # no length-of-service floor

    low = retiree(va_rating=CR.CRDP_MIN_RATING - 10, years_of_service=26)
    assert "ret_crdp" not in keys_on_screen(low)


def test_the_owners_own_case_gets_every_question():
    # A retired LTC: 26 years, 100% P&T, pre-2018 DIEMS. Nothing is hidden
    # from him, and the traditional TSP balance the common set asks for is
    # what the RMD finding is built on.
    h = retiree(diems_date="1998-06-15", years_of_service=26.0, va_rating=100,
                retired_pay_monthly=6_200.0, va_disability_monthly=4_000.0,
                tsp_traditional_balance=1_100_000.0)
    assert set(keys_on_screen(h)) == {q.key for q in R.QUESTIONS}


# ==========================================================================
# Rendering shape
# ==========================================================================

def test_the_questions_land_in_three_cards_after_the_common_ones():
    h = retiree(diems_date="1998-06-15", va_rating=100, years_of_service=26.0)
    titles = [t for t, _ in intake.grouped(intake.questions_to_ask(h))]
    ours = [t for t in titles if t in (R.GROUP_PAY, R.GROUP_VA, R.GROUP_HEALTH)]
    assert ours == [R.GROUP_PAY, R.GROUP_VA, R.GROUP_HEALTH]
    assert titles.index(R.GROUP_PAY) > titles.index(intake.GROUP_ORDER[-1])


def test_a_plan_that_only_infers_as_a_retiree_still_gets_the_questions():
    # Retired pay on the plan overrides a Veteran label (FUNNEL_CONTRACT §2).
    h = Household(member=ServiceMember(component="Veteran (not retired)",
                                       retired_pay_monthly=5_000.0))
    prepare(h)
    assert intake.funnel_of(h) == FUNNEL_RETIRED
    assert "ret_retired_pay" in keys_on_screen(h)


def test_the_predicates_are_pure_and_leave_the_household_alone():
    h = retiree(diems_date="1998-06-15", va_rating=70, years_of_service=22.0)
    before = h.to_dict()
    for predicate in (R.diems_predates_brs, R.is_va_rated, R.crdp_eligible):
        predicate(h)
    assert h.to_dict() == before
