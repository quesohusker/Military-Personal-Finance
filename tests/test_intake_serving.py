"""
The Currently Serving intake set.

Three agents write into one question schema, so the failures worth a test here
are the ones that are invisible on screen: a widget key that collides with
another module's (both widgets then show each other's value and neither page
looks broken), an `attr` that does not exist on the object `path` names, a
label that is not a question, and a conditional that gates the wrong way round.
"""

from dataclasses import fields, replace

import pytest

from engine import intake
from engine.benefits import gi_bill as GI
from engine.benefits import life_insurance as LI
from engine.funnel import (FUNNEL_SERVING, FUNNEL_VETERAN, FUNNEL_RETIRED,
                           KINDS, KIND_PCT, KIND_NUMBER, QUESTIONS as COMMON,
                           ensure_spouse, grouped, prepare, questions_for,
                           set_funnel, validate)
from engine.intake import serving
from engine.intake.serving import QUESTIONS as SRV
from engine.profile import Household, ServiceMember


def serving_household(**member) -> Household:
    """A household in the serving funnel, prepared as the page would."""
    h = Household(member=ServiceMember(**member))
    set_funnel(h, FUNNEL_SERVING)
    prepare(h)
    return h


def q(key: str):
    return next(x for x in SRV if x.key == key)


# ==========================================================================
# The contract every funnel module signs
# ==========================================================================

def test_the_serving_set_validates():
    assert validate(intake.all_questions(FUNNEL_SERVING)) == []


def test_the_whole_pool_across_every_funnel_validates():
    """The duplicate-key check that only works with all three modules loaded."""
    assert validate(intake.pool()) == []


def test_the_module_exposes_exactly_the_one_name_the_contract_asks_for():
    assert isinstance(serving.QUESTIONS, tuple)
    assert SRV, "an empty serving set is the silent failure, not an empty one"
    assert intake.funnel_questions(FUNNEL_SERVING) == SRV


def test_every_key_is_prefixed_srv():
    assert [x.key for x in SRV if not x.key.startswith("srv_")] == []


def test_every_key_is_unique_within_the_set():
    keys = [x.key for x in SRV]
    assert len(keys) == len(set(keys))


def test_no_key_collides_with_the_common_set_or_another_funnel():
    mine = {x.key for x in SRV}
    assert mine & {x.key for x in COMMON} == set()
    for other in (FUNNEL_VETERAN, FUNNEL_RETIRED):
        theirs = {x.key for x in intake.funnel_questions(other)}
        assert mine & theirs == set(), f"collides with the {other} module"


def test_every_label_is_a_second_person_question():
    for x in SRV:
        assert x.label.strip().endswith("?"), x.key
        assert x.label[0].isupper(), x.key


def test_every_question_is_asked_by_the_serving_funnel_alone():
    for x in SRV:
        assert x.funnels == (FUNNEL_SERVING,), x.key
        assert x.asks(FUNNEL_SERVING)
        assert not x.asks(FUNNEL_VETERAN)
        assert not x.asks(FUNNEL_RETIRED)


def test_every_question_has_a_known_kind_and_a_card_to_sit_in():
    for x in SRV:
        assert x.kind in KINDS, x.key
        assert x.group, x.key


def test_orders_leave_gaps_of_ten_within_each_group():
    seen: dict[str, list[int]] = {}
    for x in SRV:
        seen.setdefault(x.group, []).append(x.order)
    for group, orders in seen.items():
        assert len(orders) == len(set(orders)), \
            f"{group} has two questions at the same order"
        assert all(o % 10 == 0 and o > 0 for o in orders), group


# ==========================================================================
# Every attr resolves on the object its path names
# ==========================================================================

def test_every_attr_is_a_real_field_on_the_object_the_path_resolves_to():
    h = Household(has_spouse=True)
    ensure_spouse(h)
    for x in SRV:
        obj = x.target(h)
        assert obj is not None, f"{x.key}: path {x.path!r} does not resolve"
        names = {f.name for f in fields(type(obj))}
        assert x.attr in names, (f"{x.key}: {type(obj).__name__} has no field "
                                 f"{x.attr!r}")


def test_every_answer_round_trips_through_a_saved_plan():
    """A field that is not on the dataclass would be lost by asdict()."""
    h = Household()
    data = h.to_dict()
    for x in SRV:
        node = data
        for part in [p for p in x.path.split(".") if p]:
            node = node[part]
        assert x.attr in node, f"{x.key} would not be saved with the plan"


def test_no_serving_question_writes_into_assumptions_with_the_wrong_kind():
    """
    Assumptions are stored IN PERCENT, so they take KIND_NUMBER, not KIND_PCT.

    The trap is silent: a pct widget would divide a 4.0 inflation assumption by
    a hundred on the way in and show 0.04%.
    """
    for x in SRV:
        if x.path == "assumptions":
            assert x.kind == KIND_NUMBER, x.key


def test_the_pct_questions_are_the_decimal_fields_and_are_bounded_in_percent():
    """
    `pct()` divides by 100 on the way in, so its bounds are 0-100 while the
    stored field is 0.0-1.0. Both of these are stored as decimals.
    """
    pcts = [x for x in SRV if x.kind == KIND_PCT]
    assert {x.attr for x in pcts} == {"tsp_contribution_pct", "tsp_roth_share"}
    m = ServiceMember()
    for x in pcts:
        assert 0.0 <= getattr(m, x.attr) <= 1.0, x.key
        assert x.min_value == 0.0 and 0 < x.max_value <= 100.0, x.key


# ==========================================================================
# DIEMS comes first, and says why
# ==========================================================================

def test_diems_is_the_first_question_of_the_first_serving_card():
    h = serving_household()
    cards = [(title, qs) for title, qs in grouped(intake.questions_to_ask(h))
             if any(x.key.startswith("srv_") for x in qs)]
    first_title, first_card = cards[0]
    assert first_title == serving.GROUP_SERVICE
    assert first_card[0].key == "srv_diems"


def test_diems_says_what_it_decides():
    help_text = q("srv_diems").help.lower()
    assert "date of initial entry" in help_text
    assert "retirement system" in help_text
    assert "match" in help_text


def test_the_serving_cards_render_in_the_order_the_module_declares():
    """
    Card order is declared in `group_rank`, not smuggled through the titles.

    This test was written when `Question` had no `group_rank` and `grouped()`
    fell back to sorting card titles alphabetically -- so the titles had to be
    chosen to come out right and renaming one silently moved the page. The
    order is now stated, the titles are free prose, and "Leaving the service"
    has moved to the end where the story puts it.
    """
    h = serving_household(years_of_service=12.0)
    titles = [t for t, qs in grouped(intake.questions_to_ask(h))
              if any(x.key.startswith("srv_") for x in qs)]
    assert titles == [serving.GROUP_SERVICE, serving.GROUP_STATION,
                      serving.GROUP_TSP, serving.GROUP_DEPLOYMENT,
                      serving.GROUP_INSURANCE, serving.GROUP_GI_BILL,
                      serving.GROUP_SEPARATION]


def test_renaming_a_serving_card_does_not_reorder_the_page():
    """The property the ranks buy. Titles are prose; prose gets rewritten."""
    renamed = tuple(
        replace(q, group="ZZZ last alphabetically") if q.group == serving.GROUP_SERVICE
        else q
        for q in serving.QUESTIONS)
    titles = [t for t, _ in grouped(renamed)]
    assert titles[0] == "ZZZ last alphabetically"


# ==========================================================================
# What is asked, and what is deliberately not
# ==========================================================================

@pytest.mark.parametrize("path,attr", [
    ("member", "diems_date"),
    ("member", "grade"),
    ("member", "years_of_service"),
    ("member", "date_of_rank"),
    ("member", "duty_zip"),
    ("member", "has_dependents"),
    ("member", "lives_in_government_housing"),
    ("member", "tsp_contribution_pct"),
    ("member", "tsp_roth_share"),
    ("member", "is_deployed"),
    ("member", "months_deployed_this_year"),
    ("member", "in_combat_zone"),
    ("member", "drawing_hostile_fire_pay"),
    ("member", "sdp_balance"),
    ("member", "sgli_coverage"),
    ("member", "planned_separation_date"),
])
def test_the_architecture_serving_row_is_covered(path, attr):
    assert any(x.path == path and x.attr == attr for x in SRV), \
        f"{path}.{attr} is in ARCHITECTURE.md §5 and is not asked"


def test_nothing_the_common_set_already_asks_is_asked_again():
    common = {(x.path, x.attr) for x in COMMON}
    for x in SRV:
        assert (x.path, x.attr) not in common, f"{x.key} duplicates the common set"


def test_no_two_serving_questions_write_into_the_same_field():
    """Two widgets on one field fight over its value."""
    targets = [(x.path, x.attr) for x in SRV]
    assert len(targets) == len(set(targets))


def test_the_common_set_is_untouched_by_this_module():
    assert questions_for(FUNNEL_SERVING) == questions_for(FUNNEL_VETERAN)


# ==========================================================================
# The conditionals
# ==========================================================================

def test_the_brs_opt_in_is_asked_only_of_a_pre_2018_diems():
    assert q("srv_brs_optin").applies(serving_household(diems_date="2011-08-15"))
    assert not q("srv_brs_optin").applies(serving_household(diems_date="2018-01-01"))
    assert not q("srv_brs_optin").applies(serving_household(diems_date="2021-06-01"))


def test_a_diems_date_that_does_not_parse_hides_the_opt_in_rather_than_guessing():
    h = serving_household(diems_date="not a date")
    assert h.member.diems is None
    assert not q("srv_brs_optin").applies(h)
    assert not q("srv_csb_redux").applies(h)


def test_csb_redux_is_asked_only_inside_the_window_it_could_be_elected_in():
    assert q("srv_csb_redux").applies(serving_household(diems_date="1995-04-01"))
    # Before 1 Aug 1986 the election never existed; the answer changes nothing.
    assert not q("srv_csb_redux").applies(serving_household(diems_date="1984-02-01"))
    # And no new election has been possible since the end of 2017.
    assert not q("srv_csb_redux").applies(serving_household(diems_date="2019-09-01"))


def test_time_in_grade_is_asked_only_when_there_is_no_date_of_rank():
    assert q("srv_time_in_grade").applies(serving_household(date_of_rank=""))
    assert not q("srv_time_in_grade").applies(
        serving_household(date_of_rank="2023-06-01"))
    # A DOR that does not parse is no DOR at all, so the fallback comes back.
    assert q("srv_time_in_grade").applies(serving_household(date_of_rank="June 2023"))


@pytest.mark.parametrize("key", ["srv_deployed_months", "srv_combat_zone",
                                 "srv_hostile_fire"])
def test_the_deployment_detail_is_asked_only_of_someone_deployed(key):
    assert q(key).applies(serving_household(is_deployed=True))
    assert not q(key).applies(serving_household(is_deployed=False))


def test_the_sdp_is_gated_on_hostile_fire_pay_not_on_deployment():
    """Hostile fire or imminent danger pay is what opens the SDP."""
    assert not q("srv_sdp_balance").applies(
        serving_household(is_deployed=True, drawing_hostile_fire_pay=False))
    assert q("srv_sdp_balance").applies(
        serving_household(is_deployed=True, drawing_hostile_fire_pay=True))


def test_an_sdp_balance_stays_on_screen_after_the_deployment_ends():
    """Interest runs for 90 days after redeployment and the money is still there."""
    assert q("srv_sdp_balance").applies(
        serving_household(is_deployed=False, drawing_hostile_fire_pay=False,
                          sdp_balance=9_500.0))


def test_the_gi_bill_question_waits_for_the_six_year_transfer_mark():
    below = GI.TRANSFER_SERVICE_REQUIRED - 1
    assert not q("srv_gi_bill_children").applies(
        serving_household(years_of_service=float(below)))
    assert q("srv_gi_bill_children").applies(
        serving_household(years_of_service=float(GI.TRANSFER_SERVICE_REQUIRED)))
    assert q("srv_gi_bill_children").applies(
        serving_household(years_of_service=14.0))


def test_the_gi_bill_help_states_what_the_transfer_costs():
    help_text = q("srv_gi_bill_children").help.lower()
    assert "four more" in help_text            # the obligation, not a gift
    assert "still" in help_text and "serving" in help_text


def test_every_predicate_is_a_named_function_so_a_failure_names_something():
    for x in SRV:
        if x.when is not None:
            assert getattr(x.when, "__name__", "<lambda>") != "<lambda>", x.key


def test_the_predicates_are_pure():
    """A `when` must not write to the household it is handed."""
    h = serving_household(diems_date="2011-08-15", is_deployed=True,
                          date_of_rank="", years_of_service=8.0)
    before = h.to_dict()
    for x in SRV:
        x.applies(h)
    assert h.to_dict() == before


# ==========================================================================
# Widget extras that would be silently dropped or silently wrong
# ==========================================================================

def test_sgli_cannot_be_set_above_what_sgli_sells():
    assert q("srv_sgli").max_value == LI.SGLI_MAX


def test_the_choice_question_offers_the_real_pay_grades():
    grade = q("srv_grade")
    assert grade.options, "a choice question with no options renders empty"
    assert "E-5" in grade.options and "O-3E" in grade.options
    assert ServiceMember().grade in grade.options


def test_widget_extras_are_ones_the_kind_actually_honours():
    """`widget_kwargs()` drops anything else silently, so check it survives."""
    for x in SRV:
        kwargs = x.widget_kwargs()
        if x.help:
            assert kwargs["help"] == x.help, x.key
        if x.min_value is not None and x.kind != "toggle":
            assert "min_value" in kwargs, x.key
        if x.placeholder:
            assert kwargs.get("placeholder") == x.placeholder, x.key


def test_a_serving_plan_can_be_answered_end_to_end_without_a_none_target():
    h = serving_household(diems_date="2011-08-15", is_deployed=True,
                          drawing_hostile_fire_pay=True, years_of_service=12.0)
    asked = intake.questions_to_ask(h)
    assert all(x.target(h) is not None for x in asked)
    assert {x.key for x in SRV if x.when is None} <= {x.key for x in asked}
