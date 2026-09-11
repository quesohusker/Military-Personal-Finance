"""
State of legal residence: written through the plan, and asked in ONE place.

Two properties, and they used to belong to one page.

THE WRITE-THROUGH. The Residency page assigned `h.state_of_legal_residence`
directly instead of going through `choice()`, so changing it called neither
`mark_dirty()` nor `invalidate()`: the plan looked saved when it was not, and
every cached result stayed on the old state (ARCHITECTURE.md §4a). Of all the
fields in the app this is close to the worst one to write silently -- SCRA
means it decides who taxes a whole career's pay and then the retired pay after
it, routinely a six-figure call.

THE ONE HOME. The same field was asked twice -- free text on Profile, a
dropdown on Residency -- which is the R3 defect. It is now asked once, on
Intake, and both pages read it. So the write-through property is tested where
the field is now written, and the Residency page is tested for the two things
it still does: canonicalise a spelling the state table recognises, and say so
when it cannot.

The canonicalisation is not decoration. `get_rule()` answers a no-income-tax
rule for anything it does not recognise, so "TX" left unresolved would turn a
typo into a tax-free conversion.
"""

import sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from engine import intake, storage
from engine.profile import Household, ServiceMember, ACTIVE

PAGE = ROOT / "pages" / "10_Residency_and_Education.py"
INTAKE = ROOT / "pages" / "01_Intake.py"
SOURCE = PAGE.read_text(encoding="utf-8")

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest

SLR_KEY = "q_slr__v0"          # the common question's stem, through wkey()


def household(state: str = "Texas") -> Household:
    h = Household(member=ServiceMember(birth_year=1990, component=ACTIVE,
                                       grade="E-6", years_of_service=10.0,
                                       diems_date="2016-06-01",
                                       duty_zip="28310", has_dependents=True))
    h.state_of_legal_residence = state
    h.current_state = "North Carolina"
    intake.set_funnel(h, intake.FUNNEL_SERVING)
    return h


def clean(at: "AppTest") -> bool:
    """The plan has no unsaved changes. session_state here has no .get()."""
    return ("unsaved_changes" not in at.session_state
            or at.session_state["unsaved_changes"] is False)


def run(h: Household, page: pathlib.Path = PAGE) -> "AppTest":
    at = AppTest.from_file(str(page), default_timeout=180)
    at.session_state["household"] = h
    at.session_state["plan_version"] = 0
    at.run()
    assert not at.exception, at.exception
    return at


# ==========================================================================
# The write-through, at the field's one home
# ==========================================================================

def test_intake_asks_for_the_state_and_writes_it_through():
    h = household("Texas")
    at = run(h, INTAKE)
    assert clean(at), "opening the page is not an edit"

    at.text_input(key=SLR_KEY).set_value("California").run()
    assert not at.exception, at.exception
    assert h.state_of_legal_residence == "California"
    assert at.session_state["unsaved_changes"] is True


def test_changing_the_state_throws_away_results_computed_under_the_old_one():
    """A tax figure cached under Texas is not an answer about California."""
    h = household("Texas")
    at = run(h, INTAKE)
    at.session_state["projection"] = "stale"
    at.text_input(key=SLR_KEY).set_value("California").run()
    assert not at.exception, at.exception
    assert "projection" not in at.session_state


def test_the_new_state_survives_a_save_and_a_load():
    h = household("Texas")
    at = run(h, INTAKE)
    at.text_input(key=SLR_KEY).set_value("Michigan").run()
    back = storage.from_upload_bytes(
        storage.to_download_bytes(at.session_state["household"]))
    assert back.state_of_legal_residence == "Michigan"


def test_exactly_one_question_in_the_whole_app_writes_this_field():
    """R3, asserted against the assembled set rather than against one page."""
    for key in intake.FUNNELS:
        writers = [q.key for q in intake.all_questions(key)
                   if (q.path, q.attr) == ("", "state_of_legal_residence")]
        assert writers == ["q_slr"], f"{key}: {writers}"


# ==========================================================================
# What the Residency page still does with it
# ==========================================================================

@pytest.mark.parametrize("typed, expected", [
    ("TX", "Texas"),                 # a plan may carry any of these
    ("texas", "Texas"),
    ("  Texas  ", "Texas"),
    ("Michigan", "Michigan"),
])
def test_a_spelling_the_state_table_knows_is_canonicalised_here(typed, expected):
    """
    The bug this guards: an unresolved spelling falls through `get_rule()` to a
    no-income-tax rule, which is a wrong answer that looks like a right one.
    """
    h = household(typed)
    at = run(h)
    assert h.state_of_legal_residence == expected
    assert any(expected in e.value for e in at.markdown)


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
    # And it no longer offers a second widget for the field at all.
    assert 'choice("Which state is your legal residence?"' not in SOURCE
    assert '"state_of_legal_residence", D.STATE_NAMES' not in SOURCE


def test_the_comparison_dropdown_is_a_what_if_and_says_so():
    """R3: a page-local knob has to be visibly labelled as one."""
    h = household("Texas")
    at = run(h)
    box = at.selectbox(key="altstate__v0")
    assert "compare" in box.label.lower()
    assert "does not change your plan" in (box.help or "")


@pytest.mark.parametrize("sample", ["e5_6yrs_brs.mpfplan.json",
                                    "retired_o5_26yrs.mpfplan.json"])
def test_the_page_renders_for_both_sample_plans(sample):
    h = storage.from_upload_bytes((ROOT / "samples" / sample).read_bytes())
    at = run(h)
    assert any(h.state_of_legal_residence in e.value for e in at.markdown)
