"""
The funnel model: inference, persistence, and keeping `component` consistent.

The inference rules are the app's single answer to a question 30+ existing
status gates answer differently (docs/ARCHITECTURE.md §4a), so each ambiguous
case gets its own test with the reasoning in the name.
"""

import json
from pathlib import Path

import pytest

from engine import storage
from engine.funnel import (
    FUNNELS, FUNNEL_SERVING, FUNNEL_VETERAN, FUNNEL_RETIRED, FUNNEL_UNSET,
    FUNNEL_SPECS, SPEC_BY_KEY, DEFAULT_ESSENTIAL_SHARE, Question, QUESTIONS,
    KINDS, KIND_INTEGER, KIND_CHOICE, KIND_MONEY, KIND_TEXT, GROUP_ORDER,
    spec, label_for, is_chosen, infer_funnel, funnel_of, set_funnel,
    ensure_spouse, prepare, essential_monthly, discretionary_monthly,
    has_essential_split, questions_for, visible_questions, grouped, validate,
    has_spouse,
)
from engine import intake
from engine.profile import (Household, ServiceMember, ACTIVE, GUARD, RESERVE,
                            RETIRED, VETERAN, CIVILIAN, SERVING)

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


def hh(**member) -> Household:
    return Household(member=ServiceMember(**member))


# ==========================================================================
# The funnels themselves
# ==========================================================================

def test_there_are_three_funnels_in_the_order_intake_offers_them():
    assert FUNNELS == (FUNNEL_SERVING, FUNNEL_VETERAN, FUNNEL_RETIRED)
    assert tuple(f.key for f in FUNNEL_SPECS) == FUNNELS


def test_unset_is_a_fourth_state_and_is_not_one_of_the_three():
    assert FUNNEL_UNSET == ""
    assert FUNNEL_UNSET not in FUNNELS
    assert not is_chosen(FUNNEL_UNSET)
    assert spec(FUNNEL_UNSET) is None
    assert label_for(FUNNEL_UNSET) == "Not chosen yet"


def test_every_funnel_carries_a_label_a_description_and_what_it_implies():
    for f in FUNNEL_SPECS:
        assert f.label and f.description and f.frame
        assert f.implies and all(s.strip() for s in f.implies)
        assert f.default_component in (ACTIVE, VETERAN, RETIRED)


def test_a_blank_plan_has_not_been_asked():
    assert Household().funnel == FUNNEL_UNSET


# ==========================================================================
# Inference, one component at a time
# ==========================================================================

@pytest.mark.parametrize("component", [ACTIVE, GUARD, RESERVE])
def test_every_serving_component_infers_serving(component):
    assert infer_funnel(hh(component=component)) == FUNNEL_SERVING


def test_the_retiree_component_infers_retired():
    assert infer_funnel(hh(component=RETIRED)) == FUNNEL_RETIRED


def test_the_veteran_component_infers_veteran():
    assert infer_funnel(hh(component=VETERAN)) == FUNNEL_VETERAN


def test_a_plain_civilian_infers_veteran():
    # A civilian problem with whatever military assets exist. It is the set
    # that asks the fewest questions that do not apply.
    assert infer_funnel(hh(component=CIVILIAN, years_of_service=0.0)) \
        == FUNNEL_VETERAN


def test_inference_never_returns_unset():
    for component in (ACTIVE, GUARD, RESERVE, RETIRED, VETERAN, CIVILIAN):
        assert infer_funnel(hh(component=component)) in FUNNELS


# -- the ambiguous cases ---------------------------------------------------

def test_serving_beats_retired_pay_because_the_future_is_still_a_decision():
    # A Guard member drawing a prior retirement, or someone who typed a figure
    # into the retiree card while still in uniform.
    h = hh(component=GUARD, retired_pay_monthly=2_400.0)
    assert infer_funnel(h) == FUNNEL_SERVING


def test_retired_pay_overrides_a_veteran_label():
    # Positive evidence of a pension beats a label that says otherwise.
    h = hh(component=VETERAN, retired_pay_monthly=3_100.0)
    assert infer_funnel(h) == FUNNEL_RETIRED


def test_a_retiree_with_no_pay_entered_is_still_a_retiree():
    # 9_Survivor gates on retired_pay_monthly > 0. The funnel does not: a
    # Chapter 61 retiree fully offset by VA, and a retiree who has not typed
    # the figure yet, are both retirees. Absent evidence overrides nothing.
    h = hh(component=RETIRED, retired_pay_monthly=0.0)
    assert infer_funnel(h) == FUNNEL_RETIRED


def test_va_compensation_alone_does_not_make_someone_a_retiree():
    # 1_Profile shows its retiree card when va_disability_monthly > 0, which is
    # right for that card and wrong for the funnel. A rated veteran with no
    # pension is squarely the Veteran funnel.
    h = hh(component=VETERAN, va_disability_monthly=3_800.0, va_rating=100,
           va_rating_permanent_total=True)
    assert infer_funnel(h) == FUNNEL_VETERAN


def test_a_veteran_with_twenty_years_is_taken_at_their_word():
    # The component is spelled "Veteran (not retired)". With no retired pay to
    # contradict it, the label wins.
    h = hh(component=VETERAN, years_of_service=22.0)
    assert infer_funnel(h) == FUNNEL_VETERAN


def test_a_civilian_with_twenty_years_is_a_grey_area_retiree():
    # CIVILIAN claims nothing either way, so service history speaks: 20 good
    # years and no pay showing is a Guard or Reserve retiree waiting on 60.
    h = hh(component=CIVILIAN, years_of_service=20.0)
    assert infer_funnel(h) == FUNNEL_RETIRED


def test_a_civilian_with_short_service_is_a_veteran():
    assert infer_funnel(hh(component=CIVILIAN, years_of_service=6.0)) \
        == FUNNEL_VETERAN


def test_the_diems_date_is_not_evidence_of_anything():
    a = hh(component=VETERAN, diems_date="1994-05-01")
    b = hh(component=VETERAN, diems_date="")
    assert infer_funnel(a) == infer_funnel(b) == FUNNEL_VETERAN


# ==========================================================================
# funnel_of: an answer beats an inference
# ==========================================================================

def test_funnel_of_falls_back_to_inference_when_never_asked():
    h = hh(component=RETIRED)
    assert h.funnel == FUNNEL_UNSET
    assert funnel_of(h) == FUNNEL_RETIRED


def test_a_stored_answer_wins_over_what_the_plan_looks_like():
    h = hh(component=RETIRED, retired_pay_monthly=4_000.0)
    h.funnel = FUNNEL_VETERAN                 # set by hand, not via set_funnel
    assert infer_funnel(h) == FUNNEL_RETIRED
    assert funnel_of(h) == FUNNEL_VETERAN


def test_a_junk_value_falls_back_to_inference_rather_than_breaking():
    h = hh(component=ACTIVE)
    h.funnel = "sailor"
    assert funnel_of(h) == FUNNEL_SERVING


# ==========================================================================
# set_funnel keeps member.component consistent -- the integration point
# ==========================================================================

def test_choosing_retired_sets_the_component_the_existing_gates_read():
    h = hh(component=ACTIVE)
    set_funnel(h, FUNNEL_RETIRED)
    assert h.funnel == FUNNEL_RETIRED
    assert h.member.component == RETIRED
    assert not h.member.is_serving


def test_choosing_veteran_sets_the_component():
    h = hh(component=ACTIVE)
    set_funnel(h, FUNNEL_VETERAN)
    assert h.member.component == VETERAN


def test_choosing_serving_from_outside_lands_on_active_duty():
    h = hh(component=CIVILIAN)
    set_funnel(h, FUNNEL_SERVING)
    assert h.member.component == ACTIVE
    assert h.member.is_serving


@pytest.mark.parametrize("component", [GUARD, RESERVE])
def test_choosing_serving_does_not_narrow_a_guard_or_reserve_member(component):
    h = hh(component=component)
    set_funnel(h, FUNNEL_SERVING)
    assert h.member.component == component


def test_set_funnel_never_invents_or_erases_money():
    h = hh(component=VETERAN, retired_pay_monthly=0.0, va_disability_monthly=900.0)
    set_funnel(h, FUNNEL_RETIRED)
    assert h.member.retired_pay_monthly == 0.0      # the page still asks
    assert h.member.va_disability_monthly == 900.0  # nothing destroyed


def test_clearing_the_funnel_leaves_the_component_alone():
    h = hh(component=RETIRED)
    set_funnel(h, FUNNEL_UNSET)
    assert h.funnel == FUNNEL_UNSET
    assert h.member.component == RETIRED


def test_set_funnel_rejects_anything_that_is_not_a_funnel():
    h = Household()
    with pytest.raises(ValueError):
        set_funnel(h, "Retired Military")
    assert h.funnel == FUNNEL_UNSET


@pytest.mark.parametrize("key", list(FUNNELS))
def test_set_then_infer_agree_for_every_funnel_on_a_clean_plan(key):
    h = Household()
    set_funnel(h, key)
    assert infer_funnel(h) == key
    assert funnel_of(h) == key


def test_a_chosen_funnel_makes_the_existing_status_gates_agree():
    # The gates are not rewritten; the funnel feeds them. Two real ones:
    # 19_Housing's `m.is_serving` and 16_Healthcare's component membership.
    h = Household()
    set_funnel(h, FUNNEL_SERVING)
    assert h.member.is_serving
    assert h.member.component not in (VETERAN, CIVILIAN)

    set_funnel(h, FUNNEL_VETERAN)
    assert not h.member.is_serving
    assert h.member.component in (VETERAN, CIVILIAN)

    set_funnel(h, FUNNEL_RETIRED)
    assert not h.member.is_serving
    assert h.member.component == RETIRED


# ==========================================================================
# Persistence
# ==========================================================================

def test_the_funnel_round_trips_through_json():
    h = Household(profile_name="Round trip")
    set_funnel(h, FUNNEL_RETIRED)
    back = Household.from_json(h.to_json())
    assert back.funnel == FUNNEL_RETIRED
    assert back.member.component == RETIRED


def test_the_spending_split_and_target_age_round_trip():
    h = Household()
    h.monthly_expenses = 9_000.0
    h.essential_monthly_expenses = 5_500.0
    h.target_retirement_age = 62
    back = Household.from_json(h.to_json())
    assert back.essential_monthly_expenses == 5_500.0
    assert back.target_retirement_age == 62


def test_a_plan_saved_before_the_funnel_existed_still_loads():
    old = Household(profile_name="Legacy").to_dict()
    for key in ("funnel", "essential_monthly_expenses", "target_retirement_age"):
        old.pop(key)
    back = Household.from_dict(old)
    assert back.funnel == FUNNEL_UNSET
    assert back.essential_monthly_expenses == 0.0
    assert back.target_retirement_age == 0
    assert funnel_of(back) in FUNNELS          # resolved, not blank


def test_an_old_plan_file_with_no_funnel_key_survives_upload():
    old = Household(profile_name="Legacy", member=ServiceMember(component=RETIRED))
    payload = old.to_dict()
    payload.pop("funnel")
    back = storage.from_upload_bytes(json.dumps(payload).encode("utf-8"))
    assert back.funnel == FUNNEL_UNSET
    assert funnel_of(back) == FUNNEL_RETIRED


def test_the_funnel_survives_a_slot_save_and_load(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "SAVE_DIR", tmp_path)
    h = Household(profile_name="Slot test")
    set_funnel(h, FUNNEL_VETERAN)
    h.essential_monthly_expenses = 3_000.0
    storage.save_slot(h, "Slot test")
    back = storage.load_slot("Slot test")
    assert back.funnel == FUNNEL_VETERAN
    assert back.essential_monthly_expenses == 3_000.0


@pytest.mark.parametrize("name", ["e5_6yrs_brs.mpfplan.json",
                                  "retired_o5_26yrs.mpfplan.json"])
def test_the_sample_plans_still_load_and_infer_a_funnel(name):
    h = Household.from_json((SAMPLES / name).read_text(encoding="utf-8"))
    assert h.funnel == FUNNEL_UNSET            # they predate the field
    assert funnel_of(h) in FUNNELS


def test_the_samples_infer_the_funnel_a_reader_would_expect():
    e5 = Household.from_json(
        (SAMPLES / "e5_6yrs_brs.mpfplan.json").read_text(encoding="utf-8"))
    o5 = Household.from_json(
        (SAMPLES / "retired_o5_26yrs.mpfplan.json").read_text(encoding="utf-8"))
    assert funnel_of(e5) == FUNNEL_SERVING
    assert funnel_of(o5) == FUNNEL_RETIRED


# ==========================================================================
# Essential vs discretionary spending
# ==========================================================================

def test_zero_means_unanswered_not_nothing_is_essential():
    h = Household()
    h.monthly_expenses = 8_000.0
    assert not has_essential_split(h)
    assert essential_monthly(h) == pytest.approx(8_000.0 * DEFAULT_ESSENTIAL_SHARE)


def test_the_answer_is_used_when_there_is_one():
    h = Household()
    h.monthly_expenses = 8_000.0
    h.essential_monthly_expenses = 4_500.0
    assert has_essential_split(h)
    assert essential_monthly(h) == 4_500.0
    assert discretionary_monthly(h) == 3_500.0


def test_nothing_entered_gives_nothing_rather_than_a_guess_on_a_guess():
    assert essential_monthly(Household()) == 0.0
    assert discretionary_monthly(Household()) == 0.0


def test_essential_is_clamped_to_the_total_it_cannot_exceed():
    h = Household()
    h.monthly_expenses = 4_000.0
    h.essential_monthly_expenses = 5_000.0
    assert essential_monthly(h) == 4_000.0
    assert discretionary_monthly(h) == 0.0


def test_an_essential_answer_before_a_total_is_kept():
    h = Household()
    h.essential_monthly_expenses = 3_200.0
    assert essential_monthly(h) == 3_200.0


def test_the_fallback_is_conservative_because_people_understate_the_floor():
    assert 0.5 < DEFAULT_ESSENTIAL_SHARE <= 1.0


# ==========================================================================
# The question schema
# ==========================================================================

def test_the_common_set_validates():
    assert validate() == []


@pytest.mark.parametrize("key", list(FUNNELS))
def test_the_assembled_set_validates_for_every_funnel(key):
    assert validate(intake.all_questions(key)) == []


def test_every_widget_kind_is_a_helper_in_ui_panel():
    import ui.panel as panel
    for kind in KINDS:
        assert callable(getattr(panel, kind, None)), kind


def test_widget_kwargs_only_pass_what_the_helper_accepts():
    import inspect
    import ui.panel as panel
    for q in QUESTIONS:
        params = inspect.signature(getattr(panel, q.kind)).parameters
        for name in q.widget_kwargs():
            assert name in params, f"{q.key}: {q.kind}() has no {name}"


def test_a_question_resolves_its_target_object():
    h = Household()
    by = next(q for q in QUESTIONS if q.key == "q_birth_year")
    spend = next(q for q in QUESTIONS if q.key == "q_spend_total")
    assert by.target(h) is h.member
    assert spend.target(h) is h


def test_a_choice_question_carries_its_options():
    sex = next(q for q in QUESTIONS if q.key == "q_sex")
    assert sex.kind == KIND_CHOICE
    assert sex.widget_kwargs()["options"]


def test_every_common_question_is_asked_by_every_funnel():
    for q in QUESTIONS:
        assert set(q.funnels) == set(FUNNELS), q.key


# House style: labels are questions put to the user, never noun field names.
# "What year were you born?", not "Birth year".
QUESTION_OPENERS = {"what", "which", "how", "are", "do", "does", "did", "when",
                    "where", "at", "if", "have", "has", "is", "will", "would"}


def test_every_label_is_a_question_and_not_a_noun_label():
    for q in QUESTIONS:
        label = q.label.strip()
        assert label.endswith("?"), q.key
        assert label[0].isupper(), q.key
        assert label.split()[0].lower() in QUESTION_OPENERS, \
            f"{q.key}: {label!r} reads as a field name, not a question."


def test_the_spending_split_question_asks_what_could_not_be_cut():
    q = next(q for q in QUESTIONS if q.attr == "essential_monthly_expenses")
    assert q.kind == KIND_MONEY
    assert "budget" not in q.label.lower()
    assert "cut" in q.label.lower() or "still have to pay" in q.label.lower()


def test_the_target_retirement_age_question_exists_and_is_an_integer():
    q = next(q for q in QUESTIONS if q.attr == "target_retirement_age")
    assert q.kind == KIND_INTEGER


# -- conditional questions -------------------------------------------------

def test_the_spouse_question_is_hidden_until_there_is_a_spouse():
    q = next(q for q in QUESTIONS if q.key == "q_spouse_birth_year")
    h = Household()
    assert not q.applies(h)

    h.has_spouse = True
    assert not q.applies(h)          # married, but no record to write into
    prepare(h)
    assert q.applies(h)
    assert q.target(h) is h.spouse


def test_ensure_spouse_is_idempotent_and_respects_has_spouse():
    h = Household()
    assert ensure_spouse(h) is None
    h.has_spouse = True
    first = ensure_spouse(h)
    assert first is not None
    assert ensure_spouse(h) is first
    assert has_spouse(h)


def test_a_question_outside_this_funnel_does_not_apply():
    q = Question(key="serving_only", label="Are you deployed right now?",
                 kind="toggle", path="member", attr="is_deployed",
                 group="Deployment", funnels=(FUNNEL_SERVING,))
    serving = hh(component=ACTIVE)
    retiree = hh(component=RETIRED)
    assert q.applies(serving)
    assert not q.applies(retiree)


# -- assembly --------------------------------------------------------------

def test_visible_questions_come_back_in_group_then_order():
    h = prepare(Household(has_spouse=True))
    qs = visible_questions(h)
    keys = [q.key for q in qs]
    assert keys.index("q_birth_year") < keys.index("q_married")
    assert keys.index("q_married") < keys.index("q_spouse_birth_year")
    assert keys.index("q_spend_total") < keys.index("q_spend_essential")


def test_grouped_bundles_questions_into_input_cards():
    h = prepare(Household(has_spouse=True))
    cards = grouped(visible_questions(h))
    titles = [t for t, _ in cards]
    assert titles[0] == "About you"
    assert len(titles) == len(set(titles))
    assert sum(len(qs) for _, qs in cards) == len(visible_questions(h))


def test_questions_for_does_not_need_a_household():
    for key in FUNNELS:
        assert len(questions_for(key)) == len(QUESTIONS)


# ==========================================================================
# The extension point the three funnel modules plug into
# ==========================================================================

def test_a_funnel_module_that_does_not_exist_yet_contributes_nothing(monkeypatch):
    """
    All three modules exist now, so the absent case is simulated.

    The mechanism still has to hold. It is what let the common set render while
    the three were being written in parallel, and it is what a fourth funnel
    would land on.
    """
    monkeypatch.setitem(intake.MODULES, FUNNEL_VETERAN,
                        "engine.intake.not_written_yet")
    assert intake.funnel_questions(FUNNEL_VETERAN) == ()
    assert intake.all_questions(FUNNEL_VETERAN) == questions_for(FUNNEL_VETERAN)

    # The other two are untouched by one module going missing.
    assert intake.funnel_questions(FUNNEL_SERVING)
    assert intake.funnel_questions(FUNNEL_RETIRED)


def test_a_broken_funnel_module_raises_rather_than_going_quiet(monkeypatch):
    """
    Only the module's OWN absence is swallowed. A silently empty funnel -- a
    bad import inside a module that does exist -- is the worse failure, so it
    surfaces.
    """
    def bad_import_inside(name):
        raise ModuleNotFoundError("No module named 'engine.nope'",
                                  name="engine.nope")

    monkeypatch.setattr(intake.importlib, "import_module", bad_import_inside)
    with pytest.raises(ModuleNotFoundError):
        intake.funnel_questions(FUNNEL_SERVING)


def test_every_funnel_module_has_landed_and_contributes_its_own_questions():
    for key in FUNNELS:
        extra = intake.funnel_questions(key)
        assert extra, f"{key}: {intake.MODULES[key]} contributed nothing"
        for q in extra:
            assert q.funnels == (key,), \
                f"{q.key} is in the {key} module but asked by {q.funnels}"
            assert q.key.startswith(("srv_", "vet_", "ret_")), q.key
        assert len(intake.all_questions(key)) == len(QUESTIONS) + len(extra)


def test_every_funnel_has_a_module_named_for_it():
    assert set(intake.MODULES) == set(FUNNELS)
    for name in intake.MODULES.values():
        assert name.startswith("engine.intake.")


def test_questions_to_ask_reads_the_household_funnel():
    h = Household()

    set_funnel(h, FUNNEL_RETIRED)
    retiree = intake.questions_to_ask(h)
    assert retiree == visible_questions(
        h, tuple(QUESTIONS) + intake.funnel_questions(FUNNEL_RETIRED))

    set_funnel(h, FUNNEL_SERVING)
    serving = intake.questions_to_ask(h)

    # It read the household rather than a default: the two sets differ, each
    # carries the whole common set, and neither carries a question belonging to
    # the other funnel. The conditional common questions are excluded -- this
    # household is unmarried, so the spouse question is rightly absent -- and
    # so are the DERIVED ones, which are not asked at all (R1). They come back
    # in `figures_to_check()` and are covered by their own tests below.
    unconditional = {q.key for q in QUESTIONS
                     if q.when is None and not q.is_derived}
    assert {q.key for q in retiree} != {q.key for q in serving}
    for asked, key in ((retiree, FUNNEL_RETIRED), (serving, FUNNEL_SERVING)):
        assert unconditional <= {q.key for q in asked}
        assert all(q.asks(key) for q in asked)
    assert not any(q.key.startswith("srv_") for q in retiree)
    assert not any(q.key.startswith("ret_") for q in serving)


def test_the_import_surface_other_agents_build_against_is_present():
    for name in ("FUNNELS", "FUNNEL_SERVING", "FUNNEL_VETERAN",
                 "FUNNEL_RETIRED", "FUNNEL_UNSET", "Question", "QUESTIONS",
                 "infer_funnel", "funnel_of", "set_funnel", "prepare",
                 "essential_monthly", "validate"):
        assert hasattr(intake, name), name


# ==========================================================================
# Nothing downstream had to change
# ==========================================================================

def test_the_waterfall_still_runs_for_every_funnel():
    from engine.coach import prime_directive as PD
    for key in FUNNELS:
        h = Household()
        h.monthly_expenses = 4_200.0
        set_funnel(h, key)
        result = PD.evaluate(h)
        assert result.applicable > 0
        assert 0.0 <= result.score <= 100.0


def test_validate_catches_a_duplicate_widget_key():
    a = Question(key="dupe", label="What do you spend in a month?",
                 kind=KIND_MONEY, attr="monthly_expenses", group="x")
    problems = validate((a, a))
    assert any("Duplicate" in p for p in problems)


def test_validate_catches_an_unknown_kind_and_a_bad_attribute():
    bad = Question(key="bad", label="What is this?", kind="slider",
                   attr="not_a_field", group="x")
    problems = validate((bad,))
    assert any("unknown widget kind" in p for p in problems)
    assert any("no attribute" in p for p in problems)


# ==========================================================================
# The rules validate() enforces on everybody's questions
# ==========================================================================
# These three were added at review, after all four question sets had been
# written. Each one caught something real in the set that landed.

def test_validate_rejects_a_noun_label_with_a_question_mark_stapled_on():
    bad = Question(key="noun", label="Birth year?", kind=KIND_INTEGER,
                   path="member", attr="birth_year", group="x")
    assert any("question word" in p for p in validate((bad,)))


def test_validate_rejects_a_pair_of_dollar_signs_in_help():
    # Streamlit parses the text between two unescaped '$' as LaTeX and eats
    # both signs. `help` is passed straight to the widget, so it cannot be
    # escaped at render time -- it has to not need escaping.
    bad = Question(key="latex", label="How much cover do you carry?",
                   kind=KIND_MONEY, attr="cash_savings", group="x",
                   help="Sold in $50,000 steps to a maximum of $500,000.")
    assert any("LaTeX" in p for p in validate((bad,)))


def test_no_question_anywhere_in_the_app_carries_a_dollar_pair():
    for q in intake.pool():
        for text in (q.label, q.help, q.placeholder):
            assert (text or "").count("$") < 2, q.key


def test_validate_rejects_a_card_that_carries_two_ranks():
    a = Question(key="a", label="What do you spend in a month?",
                 kind=KIND_MONEY, attr="monthly_expenses",
                 group="Money", group_rank=10)
    b = Question(key="b", label="How much cash do you keep on hand?",
                 kind=KIND_MONEY, attr="cash_savings",
                 group="Money", group_rank=20)
    assert any("more than one group_rank" in p for p in validate((a, b)))


def test_two_funnels_may_reuse_a_card_title_and_rank_it_differently():
    # "Leaving the service" is a date not yet picked for someone serving and
    # the DD-214 for a veteran. Only questions that render together must agree.
    a = Question(key="a2", label="When do you plan to separate?",
                 kind=KIND_TEXT, path="member", attr="planned_separation_date",
                 group="Leaving", group_rank=70, funnels=(FUNNEL_SERVING,))
    b = Question(key="b2", label="When did you leave?",
                 kind=KIND_TEXT, path="member", attr="planned_separation_date",
                 group="Leaving", group_rank=10, funnels=(FUNNEL_VETERAN,))
    assert validate((a, b)) == []


def test_group_rank_orders_the_cards_and_beats_the_title():
    zulu = Question(key="z", label="What do you spend in a month?",
                    kind=KIND_MONEY, attr="monthly_expenses",
                    group="Zulu", group_rank=10)
    alpha = Question(key="a3", label="How much cash do you keep on hand?",
                     kind=KIND_MONEY, attr="cash_savings",
                     group="Alpha", group_rank=20)
    assert [t for t, _ in grouped((alpha, zulu))] == ["Zulu", "Alpha"]


def test_the_common_cards_still_come_before_every_funnel_card():
    for key in FUNNELS:
        titles = [t for t, _ in grouped(intake.all_questions(key))]
        assert titles[:len(GROUP_ORDER)] == list(GROUP_ORDER)


def test_every_funnel_card_declares_a_rank():
    # A card left at the default 0 falls back to alphabetical ordering by
    # title, which is the trap group_rank exists to remove.
    for key in FUNNELS:
        for q in intake.funnel_questions(key):
            assert q.group_rank > 0, f"{q.key}: card {q.group!r} has no rank"


# ==========================================================================
# What the whole assembled app asks, as one set
# ==========================================================================

def test_the_whole_pool_validates():
    assert validate(intake.pool()) == []


def test_no_funnel_asks_for_the_same_field_twice():
    # The §4a defect intake exists to end: one field, asked in three places.
    for key in FUNNELS:
        seen = {}
        for q in intake.all_questions(key):
            where = (q.path, q.attr)
            assert where not in seen, \
                f"{key}: {q.key} and {seen[where]} both write {q.path}.{q.attr}"
            seen[where] = q.key


def test_no_funnel_module_repeats_a_common_question():
    common = {(q.path, q.attr) for q in QUESTIONS}
    for key in FUNNELS:
        for q in intake.funnel_questions(key):
            assert (q.path, q.attr) not in common, \
                f"{q.key} re-asks what the common set already asks"


def test_the_child_count_is_never_derived_from_dependants_claimed_for_pay():
    """
    R3 gives `estate.n_children` one home — the Estate page — and R1 does not
    override that with a derivation that answers a different question.

    `n_dependents` is the military pay and tax sense of the word: it INCLUDES A
    SPOUSE, which is what BAH's with-dependants rate turns on, and intake asks
    it two lines below "Are you married?". Deriving a child count from it made
    `scorecard.components.legacy()` — scored only when the user says a legacy
    is a goal (§3) — rate every married member with dependants on a goal they
    never stated. See the note above DERIVED in engine/funnel.py.
    """
    for key in FUNNELS:
        assert not any((d.path, d.attr) == ("estate", "n_children")
                       for d in intake.all_derived(key)), \
            f"{key} derives a child count from a pay concept"

    h = Household(n_dependents=3, has_spouse=True)
    set_funnel(h, FUNNEL_RETIRED)
    intake.prepare(h)
    assert h.estate.n_children == 0, "dependants claimed for pay are not heirs"


def test_percent_questions_only_ever_write_decimal_fields():
    # pct() stores value/100. Assumptions fields are stored IN PERCENT already
    # and must never use this kind, or every rate on the plan drops 100-fold.
    for q in intake.pool():
        if q.kind == "pct":
            assert not q.path.startswith("assumptions"), q.key
