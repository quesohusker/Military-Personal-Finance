"""
The career timeline belongs to the plan, not to the browser tab.

It used to live in `st.session_state["timeline"]`, which meant the separation
year, every promotion and every PCS move were lost on a reload and absent from
every downloaded plan file. Ten minutes of careful answers, returned as
nothing. It also blocked the lifetime projection, which has to read the serving
years from somewhere a projection can reach (ARCHITECTURE.md §4a, §7 step 1).

What these tests hold down:

  * a timeline survives a save and a load, promotions and moves intact;
  * a plan saved before the timeline was part of one still loads;
  * service averages seed a plan that carries nothing, and NEVER a plan that
    carries an answer -- including the answer "no more promotions", which is an
    empty list and would otherwise be re-seeded on every open;
  * editing the timeline marks the plan dirty, so the unsaved-changes warning
    tells the truth.
"""

import sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import json

import pytest

from engine import storage
from engine.career import timeline as TL
from engine.profile import Household, ServiceMember, ACTIVE

CAREER_PAGE = ROOT / "pages" / "3_Career.py"


def member(**kw) -> ServiceMember:
    base = dict(birth_year=1999, component=ACTIVE, grade="E-5",
                years_of_service=6.0, diems_date="2020-06-01",
                duty_zip="28310", has_dependents=True)
    base.update(kw)
    return ServiceMember(**base)


def answered() -> Household:
    """A household whose Career page has been used in anger."""
    h = Household(member=member())
    h.career = TL.CareerTimeline(
        promotions=[TL.Promotion("E-6", 7.5, confirmed=True),
                    TL.Promotion("E-7", 12.0)],
        moves=[TL.PCSMove(8.0, "92134", "San Diego",
                          into_government_housing=True),
               TL.PCSMove(11.0, "73503", "Fort Sill")],
        separation_at_years_of_service=24.0,
        entered=True)
    return h


def reloaded(h: Household) -> Household:
    """Exactly the path the sidebar's download and upload buttons take."""
    return storage.from_upload_bytes(storage.to_download_bytes(h))


# ==========================================================================
# Round trip
# ==========================================================================

def test_the_household_carries_a_timeline_before_anyone_answers():
    assert isinstance(Household().career, TL.CareerTimeline)


def test_promotions_and_moves_survive_a_save_and_a_load():
    back = reloaded(answered()).career

    assert [p.to_grade for p in back.promotions] == ["E-6", "E-7"]
    assert [p.at_years_of_service for p in back.promotions] == [7.5, 12.0]
    assert back.promotions[0].confirmed is True
    assert back.separation_at_years_of_service == 24.0

    assert [m.destination_zip for m in back.moves] == ["92134", "73503"]
    assert back.moves[0].destination_label == "San Diego"
    assert back.moves[0].into_government_housing is True


def test_what_comes_back_is_dataclasses_not_raw_dictionaries():
    """
    asdict() flattens the nested events on the way out, but the generic
    rebuilder cannot see through a plain `list` annotation on the way back --
    it would hand back lists of dicts, and every attribute read downstream
    would raise.
    """
    back = reloaded(answered()).career
    assert isinstance(back, TL.CareerTimeline)
    assert all(isinstance(p, TL.Promotion) for p in back.promotions)
    assert all(isinstance(m, TL.PCSMove) for m in back.moves)
    assert TL.project(answered().member, back, start_year=2026) is not None


def test_the_timeline_is_actually_written_into_the_plan_file():
    """If it is not in the JSON, it is not in the plan."""
    payload = json.loads(storage.to_download_bytes(answered()).decode("utf-8"))
    assert payload["career"]["separation_at_years_of_service"] == 24.0
    assert payload["career"]["promotions"][0]["to_grade"] == "E-6"
    assert payload["career"]["moves"][0]["destination_zip"] == "92134"


def test_a_saved_plan_round_trips_unchanged():
    h = answered()
    assert reloaded(h).to_dict() == h.to_dict()


def test_a_named_slot_carries_the_timeline_too(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "SAVE_DIR", tmp_path)
    storage.save_slot(answered(), "career test")
    back = storage.load_slot("career test").career
    assert back.separation_at_years_of_service == 24.0
    assert [p.to_grade for p in back.promotions] == ["E-6", "E-7"]


# ==========================================================================
# Every plan saved before this must still load
# ==========================================================================

def test_a_plan_saved_before_the_timeline_existed_still_loads():
    old = Household(member=member()).to_dict()
    old.pop("career")
    h = Household.from_dict(old)
    assert h.career == TL.CareerTimeline()
    assert h.career.promotions == [] and h.career.moves == []
    assert h.career.entered is False


@pytest.mark.parametrize("sample", ["e5_6yrs_brs.mpfplan.json",
                                    "retired_o5_26yrs.mpfplan.json"])
def test_both_sample_plans_still_load(sample):
    h = storage.from_upload_bytes((ROOT / "samples" / sample).read_bytes())
    assert isinstance(h.career, TL.CareerTimeline)
    assert h.career.entered is False


@pytest.mark.parametrize("career", [
    {},                                        # written, but empty
    None,                                      # written as nothing at all
    "20 years",                                # written by something else
    {"separation_at_years_of_service": None},  # a key that lost its value
    {"promotions": None, "moves": None},
    {"promotions": [{"to_grade": "E-6", "at_years_of_service": 8.0,
                     "rank_held": "unknown key"}]},
])
def test_a_damaged_or_unfamiliar_timeline_loads_rather_than_raising(career):
    """
    A plan file outlives the version of the app that wrote it. Refusing to open
    it loses everything else in it too, which is a far worse failure than
    falling back to a default separation year.
    """
    data = Household(member=member()).to_dict()
    data["career"] = career
    h = Household.from_dict(data)
    assert isinstance(h.career, TL.CareerTimeline)
    assert h.career.separation_at_years_of_service == 20.0


def test_an_unfamiliar_key_is_dropped_and_the_rest_of_the_event_kept():
    t = TL.CareerTimeline.from_dict(
        {"promotions": [{"to_grade": "E-7", "at_years_of_service": 13.5,
                         "selected_by_board": True}]})
    assert len(t.promotions) == 1
    assert t.promotions[0].to_grade == "E-7"
    assert t.promotions[0].at_years_of_service == 13.5


def test_the_timeline_still_round_trips_through_its_own_dict():
    t = TL.CareerTimeline(promotions=TL.default_promotions("O-3", 5.0),
                          moves=[TL.PCSMove(8.0, "92134", "San Diego")],
                          separation_at_years_of_service=20.0, entered=True)
    back = TL.CareerTimeline.from_dict(t.to_dict())
    assert back == t


# ==========================================================================
# Defaults seed an empty plan, and only an empty plan
# ==========================================================================
AppTest = pytest.importorskip("streamlit.testing.v1").AppTest


def run_career(h: Household) -> "AppTest":
    at = AppTest.from_file(str(CAREER_PAGE), default_timeout=180)
    at.session_state["household"] = h
    at.session_state["plan_version"] = 0
    at.run()
    assert not at.exception, at.exception
    return at


def test_the_page_seeds_service_averages_for_a_plan_that_carries_nothing():
    h = Household(member=member())
    run_career(h)
    assert [p.to_grade for p in h.career.promotions] == ["E-6", "E-7", "E-8", "E-9"]
    # A default is not an answer, so the plan is not yet "unsaved changes".
    assert h.career.entered is False


def test_the_page_does_not_overwrite_a_real_answer_with_defaults():
    h = answered()
    run_career(h)
    assert [p.to_grade for p in h.career.promotions] == ["E-6", "E-7"]
    assert h.career.separation_at_years_of_service == 24.0
    assert [m.destination_zip for m in h.career.moves] == ["92134", "73503"]


def test_no_more_promotions_is_an_answer_and_survives_the_next_open():
    """
    The trap the `entered` flag exists for: an empty promotion list is both
    "nobody has been here" and "I am not getting promoted again", and re-seeding
    the second one throws away a deliberate answer on every reload.
    """
    h = Household(member=member())
    h.career = TL.CareerTimeline(separation_at_years_of_service=12.0,
                                 entered=True)
    run_career(h)
    assert h.career.promotions == []


def test_the_seed_survives_the_round_trip_the_old_page_lost():
    """End to end: answer, download, upload, and still have the answers."""
    h = Household(member=member())
    at = run_career(h)
    at.slider(key="sepslider__v0").set_value(12.0).run()
    assert not at.exception, at.exception

    after = reloaded(at.session_state["household"])
    assert after.career.separation_at_years_of_service == 12.0
    assert after.career.entered is True
    assert [p.to_grade for p in after.career.promotions] == ["E-6", "E-7",
                                                            "E-8", "E-9"]


# ==========================================================================
# Editing marks the plan dirty
# ==========================================================================

def test_moving_the_separation_slider_marks_the_plan_dirty():
    h = Household(member=member())
    at = run_career(h)
    opened_clean = ("unsaved_changes" not in at.session_state
                    or at.session_state["unsaved_changes"] is False)
    assert opened_clean, "merely opening the page is not an edit"

    at.slider(key="sepslider__v0").set_value(14.0).run()
    assert not at.exception, at.exception
    assert at.session_state["unsaved_changes"] is True
    assert h.career.separation_at_years_of_service == 14.0
    assert h.career.entered is True


def test_moving_a_promotion_marks_the_plan_dirty():
    h = Household(member=member())
    at = run_career(h)
    at.slider(key="prom_0__v0").set_value(9.5).run()
    assert not at.exception, at.exception
    assert at.session_state["unsaved_changes"] is True
    assert h.career.promotions[0].at_years_of_service == 9.5


def test_clearing_the_promotions_marks_the_plan_dirty():
    h = Household(member=member())
    at = run_career(h)
    at.button(key="clearp__v0").click().run()
    assert not at.exception, at.exception
    assert at.session_state["unsaved_changes"] is True
    assert h.career.promotions == []
    assert h.career.entered is True


def test_editing_the_timeline_invalidates_cached_results():
    """A stale projection is worse than none: it looks like an answer."""
    h = Household(member=member())
    at = run_career(h)
    at.session_state["projection"] = "stale"
    at.slider(key="sepslider__v0").set_value(16.0).run()
    assert not at.exception, at.exception
    assert "projection" not in at.session_state


def test_a_promotion_after_the_separation_point_is_kept_not_deleted():
    """
    It is not shown -- it falls after the member leaves -- but the timeline is
    saved now, so nudging the separation slider down for a moment must not
    silently delete a grade the member expects to make.
    """
    h = answered()                      # E-7 at 12.0, separating at 24
    at = run_career(h)
    at.slider(key="sepslider__v0").set_value(10.0).run()
    assert not at.exception, at.exception
    assert [p.to_grade for p in h.career.promotions] == ["E-6", "E-7"]
    assert h.career.promotions[1].at_years_of_service == 12.0


@pytest.mark.parametrize("sample", ["e5_6yrs_brs.mpfplan.json",
                                    "retired_o5_26yrs.mpfplan.json"])
def test_the_page_opens_both_samples_without_claiming_unsaved_changes(sample):
    """
    The retiree sample is 26 years in and carries the default separation year
    of 20, which the slider cannot show. Adopting the clamped default is the
    app tidying its own default, not an answer, and must not raise the
    unsaved-changes warning on a plan the member has only looked at.
    """
    h = storage.from_upload_bytes((ROOT / "samples" / sample).read_bytes())
    at = run_career(h)
    opened_clean = ("unsaved_changes" not in at.session_state
                    or at.session_state["unsaved_changes"] is False)
    assert opened_clean
    assert h.career.entered is False


def test_the_page_no_longer_keeps_the_timeline_in_session_state():
    """The whole defect, asserted directly."""
    source = CAREER_PAGE.read_text(encoding="utf-8")
    assert 'session_state["timeline"]' not in source
    assert "h.career" in source
