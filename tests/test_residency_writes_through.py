"""
The Residency page must write through the plan, not around it.

It assigned `h.state_of_legal_residence` directly instead of going through
`choice()`, so changing it called neither `mark_dirty()` nor `invalidate()`:
the plan looked saved when it was not, and every cached result stayed on the
old state (ARCHITECTURE.md §4a). Of all the fields in the app this is close to
the worst one to write silently — SCRA means it decides who taxes a whole
career's pay and then the retired pay after it, routinely a six-figure call.

The same field is asked twice: free text on Profile, a dropdown here. So the
page has to accept what Profile allows — "TX", "texas" — rather than failing to
find it and quietly selecting the first state in the list.
"""

import sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from engine import storage
from engine.profile import Household, ServiceMember, ACTIVE

PAGE = ROOT / "pages" / "10_Residency_and_Education.py"
SOURCE = PAGE.read_text(encoding="utf-8")

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest


def household(state: str = "Texas") -> Household:
    h = Household(member=ServiceMember(birth_year=1990, component=ACTIVE,
                                       grade="E-6", years_of_service=10.0,
                                       diems_date="2016-06-01",
                                       duty_zip="28310", has_dependents=True))
    h.state_of_legal_residence = state
    h.current_state = "North Carolina"
    return h


def clean(at: "AppTest") -> bool:
    """The plan has no unsaved changes. session_state here has no .get()."""
    return ("unsaved_changes" not in at.session_state
            or at.session_state["unsaved_changes"] is False)


def run(h: Household) -> "AppTest":
    at = AppTest.from_file(str(PAGE), default_timeout=180)
    at.session_state["household"] = h
    at.session_state["plan_version"] = 0
    at.run()
    assert not at.exception, at.exception
    return at


def test_choosing_a_state_writes_it_to_the_plan_and_marks_it_dirty():
    h = household("Texas")
    at = run(h)
    assert clean(at), "opening the page is not an edit"

    at.selectbox(key="slr2__v0").select("California").run()
    assert not at.exception, at.exception
    assert h.state_of_legal_residence == "California"
    assert at.session_state["unsaved_changes"] is True


def test_changing_the_state_throws_away_results_computed_under_the_old_one():
    """A tax figure cached under Texas is not an answer about California."""
    h = household("Texas")
    at = run(h)
    at.session_state["projection"] = "stale"
    at.selectbox(key="slr2__v0").select("California").run()
    assert not at.exception, at.exception
    assert "projection" not in at.session_state


def test_the_new_state_survives_a_save_and_a_load():
    h = household("Texas")
    at = run(h)
    at.selectbox(key="slr2__v0").select("Michigan").run()
    back = storage.from_upload_bytes(
        storage.to_download_bytes(at.session_state["household"]))
    assert back.state_of_legal_residence == "Michigan"


@pytest.mark.parametrize("typed, expected", [
    ("TX", "Texas"),                 # Profile takes free text, and people type this
    ("texas", "Texas"),
    ("  Texas  ", "Texas"),
    ("Michigan", "Michigan"),
])
def test_what_profile_accepts_as_text_is_understood_here(typed, expected):
    """
    The bug this guards: the dropdown could not find "TX" in the state list,
    so it fell to index 0 and moved the member's residence to Alabama.
    """
    h = household(typed)
    at = run(h)
    assert h.state_of_legal_residence == expected
    assert at.selectbox(key="slr2__v0").value == expected


def test_re_spelling_the_same_answer_does_not_claim_unsaved_changes():
    h = household("TX")
    at = run(h)
    assert clean(at)


def test_a_state_the_table_does_not_know_is_flagged_rather_than_swapped_silently():
    h = household("Freedonia")
    at = run(h)
    assert at.warning, "the member must be told their residence was not understood"
    assert any("Freedonia" in w.value for w in at.warning)


def test_the_page_does_not_assign_the_field_behind_the_helper_s_back():
    """The defect, asserted in the source: any bare write is a silent write."""
    assert "h.state_of_legal_residence = slr" not in SOURCE
    assert 'choice("Which state is your legal residence?"' in SOURCE


@pytest.mark.parametrize("sample", ["e5_6yrs_brs.mpfplan.json",
                                    "retired_o5_26yrs.mpfplan.json"])
def test_the_page_renders_for_both_sample_plans(sample):
    h = storage.from_upload_bytes((ROOT / "samples" / sample).read_bytes())
    at = run(h)
    assert at.selectbox(key="slr2__v0").value == h.state_of_legal_residence
