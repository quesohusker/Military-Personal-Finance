"""
The two new pages, driven rather than read.

`HANDOFF.md`: "Unit tests do not catch page bugs. Every page-level defect in
this project was found by driving a real browser, never by pytest." That stays
true — this is not a substitute for the Playwright sweep. It covers the three
things about these two pages that a unit test CAN reach and that would be
expensive to find late:

  * the renderer dispatches every question in every funnel's set without
    raising, including the funnel-specific sets it has never seen;
  * choosing a funnel actually writes through to the plan and the dirty flag;
  * the funnel is not a permissions system — no page gates on it.
"""

import pathlib
import re

import pytest

from engine.funnel import FUNNELS, prepare, set_funnel
from engine.profile import Household

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest

ROOT = pathlib.Path(__file__).resolve().parent.parent
START = "pages/00_Start.py"
INTAKE = "pages/01_Intake.py"


def loaded(h: Household) -> "AppTest":
    def go(page):
        at = AppTest.from_file(str(ROOT / page), default_timeout=180)
        at.session_state["household"] = h
        at.session_state["plan_version"] = 0
        return at.run()
    return go


def furnished(funnel: str) -> Household:
    """A household with every conditional question switched on."""
    h = Household(has_spouse=True)
    set_funnel(h, funnel)
    prepare(h)
    h.monthly_expenses = 5_000.0
    m = h.member
    m.is_deployed = True
    m.drawing_hostile_fire_pay = True
    m.va_rating = 100
    m.years_of_service = 22.0
    m.diems_date = "1999-05-15"
    m.date_of_rank = ""
    return h


# ==========================================================================
# The renderer survives every question set
# ==========================================================================

@pytest.mark.parametrize("funnel", list(FUNNELS))
def test_intake_renders_every_question_in_every_funnel(funnel):
    at = loaded(furnished(funnel))(INTAKE)
    assert not at.exception, at.exception
    widgets = (len(at.number_input) + len(at.text_input) + len(at.selectbox)
               + len(at.toggle))
    assert widgets > 15, f"{funnel}: only {widgets} widgets rendered"


@pytest.mark.parametrize("funnel", list(FUNNELS))
def test_the_start_page_renders_for_a_plan_that_has_answered(funnel):
    """
    The door carries no prose, so the only signal that a plan has already
    answered is which button is marked. Exactly one must be.
    """
    h = Household()
    set_funnel(h, funnel)
    at = loaded(h)(START)
    assert not at.exception, at.exception

    marked = {b.key for b in at.button if b.proto.type == "primary"}
    assert marked == {f"door_{funnel}__v0"}, \
        f"an answered plan should mark what it picked, got {marked}"


def test_intake_sends_an_unasked_plan_to_the_front_door_instead_of_guessing():
    at = loaded(Household())(INTAKE)
    assert not at.exception, at.exception
    assert at.warning, "intake should not open before the funnel is chosen"
    assert not at.number_input


def test_the_start_page_offers_all_three_funnels_before_it_is_answered():
    at = loaded(Household())(START)
    assert not at.exception, at.exception
    keys = {b.key for b in at.button}
    for funnel in FUNNELS:
        assert f"door_{funnel}__v0" in keys, funnel


# ==========================================================================
# Choosing one writes through
# ==========================================================================

@pytest.mark.parametrize("funnel", list(FUNNELS))
def test_choosing_a_funnel_records_it_and_marks_the_plan_dirty(funnel):
    h = Household()
    at = loaded(h)(START)
    at.button(key=f"door_{funnel}__v0").click().run()

    after = at.session_state["household"]
    assert after.funnel == funnel
    # set_funnel is a pure engine function; the PAGE owes the dirty flag.
    assert at.session_state["unsaved_changes"] is True


# ==========================================================================
# Not a permissions system (ARCHITECTURE.md §2)
# ==========================================================================

def test_no_page_outside_the_front_door_knows_the_funnel_exists():
    for page in (ROOT / "pages").glob("*.py"):
        if page.name in ("00_Start.py", "01_Intake.py"):
            continue
        assert "funnel" not in page.read_text(encoding="utf-8"), \
            f"{page.name} gates on the funnel — it must not"


def test_the_renderer_names_no_funnel():
    """If 01_Intake knows a funnel by name, it is no longer data-driven."""
    text = (ROOT / INTAKE).read_text(encoding="utf-8")
    for token in ("FUNNEL_SERVING", "FUNNEL_VETERAN", "FUNNEL_RETIRED",
                  "srv_", "vet_", "ret_", '"serving"', '"veteran"', '"retiree"'):
        assert token not in text, f"01_Intake.py mentions {token}"


def test_every_page_is_still_registered_in_the_router():
    src = (ROOT / "Military_Finance.py").read_text(encoding="utf-8")
    registered = set(re.findall(r'_page\("(pages/[^"]+)"', src))
    on_disk = {f"pages/{p.name}" for p in (ROOT / "pages").glob("*.py")}
    assert on_disk - registered == set(), "a page exists but is unreachable"
    assert registered - on_disk == set(), "the router points at a missing page"


# ==========================================================================
# The door stays a door
#
# The front door is four buttons and a crest. Every page in this app has a
# subtitle and help text and findings; this one has none on purpose, because
# the three labels are the question and a door you have to read is a bad
# door. Prose creeps back in one well-meant sentence at a time, so the
# absence is pinned here rather than left to discipline.
# ==========================================================================

def test_the_front_door_carries_nothing_but_the_choice():
    at = loaded(Household())(START)
    assert not at.exception, at.exception

    keys = [b.key for b in at.button]
    assert keys == ["door_serving__v0", "door_veteran__v0",
                    "door_retiree__v0", "door_open__v0"], keys

    # No banners, no expanders, no findings, no metrics, no second heading.
    assert not at.info, "the door explains nothing"
    assert not at.success
    assert not at.error
    assert not at.metric
    assert not at.expander
    assert not at.header
    assert not at.subheader
    assert not at.selectbox
    assert not at.number_input
    assert not at.toggle


def test_the_front_door_offers_exactly_one_way_back_into_a_saved_plan():
    at = loaded(Household())(START)
    assert len(at.file_uploader) == 1
    # Selecting a file must not load it -- there is no way back from the
    # wrong one, so the button stays disabled until something is chosen.
    assert at.button(key="door_open__v0").disabled is True
